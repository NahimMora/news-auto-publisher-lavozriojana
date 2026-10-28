"""Cliente de la API privada de Instagram (``instagrapi``) sólo para historias
nativas con stickers (``utils/native_story.py``).

La API Graph no admite stickers en historias; la app sí. Reglas:

* sesión persistente (``INSTAGRAPI_SESSION_PATH``, por defecto
  ``data/secrets/instagrapi_session.json``, fuera del repo): se reutiliza y se
  valida; con contraseña sólo se inicia sesión si la guardada dejó de servir;
* sin flujo de challenge automático: un challenge, un "feedback required" o
  un pedido de espera detienen todo y se registran (nunca se intenta evadir
  un control de la plataforma). Para crear o renovar la sesión a mano:
  ``python cli.py native-stories login``;
* credenciales sólo por entorno (``INSTAGRAPI_USERNAME`` /
  ``INSTAGRAPI_PASSWORD``); nunca se loguean.

``instagrapi`` se importa recién al usarlo: con la función apagada el
pipeline no lo necesita.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from utils.logging_setup import setup_logger
from utils.paths import data_dir

logger = setup_logger("instagrapi_client", "native_stories.log")

# Tipos de error: qué hace la etapa con cada uno.
BLOCKED = "blocked"  # challenge, feedback, espera, rate limit: frenar todo
CREDENTIAL = "credential"  # sesión/contraseña inválida o 2FA: frenar y avisar
UNVERIFIED = "unverified"  # pudo haber salido: reconciliar antes de reintentar
REJECTED = "rejected"  # no salió: reintentable con backoff
UNAVAILABLE = "unavailable"  # instagrapi no instalado o sin configurar


class NativeStoryError(Exception):
    def __init__(self, kind: str, code: str, message: str = ""):
        super().__init__(f"{kind}:{code}")
        self.kind = kind
        self.code = code
        self.message = message[:200]


def session_path() -> str:
    raw = str(os.getenv("INSTAGRAPI_SESSION_PATH") or "").strip()
    return raw or str(data_dir() / "secrets" / "instagrapi_session.json")


def _classify(exc: Exception, *, published_phase: bool) -> NativeStoryError:
    """Traduce una excepción de instagrapi sin exponer su contenido crudo."""
    from instagrapi import exceptions as ex

    name = type(exc).__name__
    blocked = tuple(
        getattr(ex, n) for n in (
            "ChallengeRequired", "ChallengeError", "FeedbackRequired", "PleaseWaitFewMinutes", "RateLimitError",
            "SentryBlock", "ClientThrottledError", "ProxyAddressIsBlocked", "SelectContactPointRecoveryForm",
            "RecaptchaChallengeForm",
        ) if hasattr(ex, n)
    )
    credential = tuple(
        getattr(ex, n) for n in (
            "LoginRequired", "BadPassword", "BadCredentials", "TwoFactorRequired", "ReloginAttemptExceeded",
            "ClientLoginRequired",
        ) if hasattr(ex, n)
    )
    if isinstance(exc, blocked):
        return NativeStoryError(BLOCKED, name)
    if isinstance(exc, credential):
        return NativeStoryError(CREDENTIAL, name)
    if isinstance(exc, getattr(ex, "MediaNotFound", ())):
        return NativeStoryError(REJECTED, name)
    # Después de mandar la configuración cualquier otro error es ambiguo.
    return NativeStoryError(UNVERIFIED if published_phase else REJECTED, name)


def _client_class():
    from instagrapi import Client

    class _LVRClient(Client):
        def location_complete(self, location):
            # El sticker usa ``external_id`` (facebook_places_id) tal cual
            # (``location_story_sticker_id``). Con el ID ya cargado no hace
            # falta ir a buscar lat/lng ni el pk interno: menos pedidos y sin
            # ``LocationNotFound`` si el pk no coincide con el ID de Facebook.
            if getattr(location, "external_id", None):
                return location
            return super().location_complete(location)

    return _LVRClient


class NativeStoryClient:
    """Sesión de la app para la cuenta del medio. Uno por etapa."""

    def __init__(self, *, interactive: bool = False):
        self.username = str(os.getenv("INSTAGRAPI_USERNAME") or "").strip()
        self.password = str(os.getenv("INSTAGRAPI_PASSWORD") or "")
        self.path = session_path()
        self.interactive = interactive
        self._client = None

    # ── Sesión ───────────────────────────────────────────────────────────
    def _new_client(self):
        try:
            cls = _client_class()
        except ImportError as exc:
            raise NativeStoryError(UNAVAILABLE, "instagrapi_not_installed") from exc
        client = cls(
            delay_range=[1, 3],
            # Sin challenge interactivo en el pipeline: se detiene y avisa.
            with_challenge_flow=self.interactive,
        )
        client.read_timeout = int(os.getenv("INSTAGRAPI_READ_TIMEOUT_SECONDS", "25"))
        return client

    def _save(self, client) -> None:
        target = Path(self.path)
        target.parent.mkdir(parents=True, exist_ok=True)
        handle, tmp = tempfile.mkstemp(dir=str(target.parent), prefix=".session_", suffix=".json")
        os.close(handle)
        try:
            client.dump_settings(tmp)
            try:
                os.chmod(tmp, 0o600)
            except OSError:
                pass
            os.replace(tmp, target)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    def connect(self):
        """Devuelve un cliente con sesión válida o lanza ``NativeStoryError``."""
        if self._client is not None:
            return self._client
        if not self.username:
            raise NativeStoryError(UNAVAILABLE, "missing_username")
        client = self._new_client()
        has_session = os.path.exists(self.path)
        try:
            if has_session:
                try:
                    with open(self.path, encoding="utf-8") as fh:
                        client.set_settings(json.load(fh))
                except (OSError, ValueError) as exc:
                    # Un archivo de sesión roto no se pisa en silencio.
                    raise NativeStoryError(CREDENTIAL, "session_file_unreadable") from exc
            if not has_session and not self.password:
                raise NativeStoryError(CREDENTIAL, "missing_session")
            # Con sesión cargada, ``login`` la valida y sólo usa la contraseña
            # si Instagram la rechaza.
            client.login(self.username, self.password)
        except NativeStoryError:
            raise
        except ImportError as exc:
            raise NativeStoryError(UNAVAILABLE, "instagrapi_not_installed") from exc
        except Exception as exc:  # noqa: BLE001 — se clasifica sin propagar datos crudos
            err = _classify(exc, published_phase=False)
            logger.error("Sesión de Instagram (app) no disponible: %s/%s", err.kind, err.code)
            raise err from None
        self._save(client)
        self._client = client
        return client

    # ── Publicación ──────────────────────────────────────────────────────
    def publish(self, payload: dict, background_path: str) -> dict:
        """Publica la historia con los tres stickers. Devuelve
        ``{"story_pk", "story_id", "story_url"}``."""
        from instagrapi.types import Location, StoryLink, StoryLocation, StoryMedia

        client = self.connect()
        media = payload["media"]
        medias = [StoryMedia(
            media_pk=int(media["media_pk"]), user_id=int(client.user_id),
            x=media["x"], y=media["y"], width=media["width"], height=media["height"],
        )]
        link = payload["link"]
        links = [StoryLink(webUri=link["url"], x=link["x"], y=link["y"], width=link["width"], height=link["height"])]
        locations = []
        if payload.get("location"):
            loc = payload["location"]
            place = int(loc["external_id"])
            locations = [StoryLocation(
                location=Location(name=loc["name"], external_id=place, external_id_source="facebook_places"),
                x=loc["x"], y=loc["y"], width=loc["width"], height=loc["height"],
            )]
        try:
            story = client.photo_upload_to_story(
                Path(background_path), medias=medias, links=links, locations=locations, resize_mode="fit",
            )
        except Exception as exc:  # noqa: BLE001 — se clasifica sin propagar datos crudos
            err = _classify(exc, published_phase=True)
            logger.error("Historia nativa no confirmada (%s): %s/%s", payload.get("graph_media_id"), err.kind, err.code)
            raise err from None
        pk = str(getattr(story, "pk", "") or "")
        if not pk:
            raise NativeStoryError(UNVERIFIED, "story_without_pk")
        return {
            "story_pk": pk,
            "story_id": str(getattr(story, "id", "") or ""),
            "story_url": f"https://www.instagram.com/stories/{client.username or self.username}/{pk}/",
        }

    def inspect(self, story_pk: str) -> dict:
        """Stickers que Instagram devuelve para una historia ya publicada.

        Se leen del feed de historias de la cuenta: ``media/<pk>/info/`` (lo
        que usa ``story_info``) no trae ``story_link_stickers``.
        """
        client = self.connect()
        try:
            found = [s for s in client.user_stories(client.user_id) if str(s.pk) == str(story_pk)]
            story = found[0] if found else client.story_info(story_pk, use_cache=False)
        except Exception as exc:  # noqa: BLE001
            err = _classify(exc, published_phase=False)
            raise err from None
        return {
            "links": [unwrap_link(str(link.webUri)) for link in (story.links or [])],
            "locations": [str(getattr(sl.location, "external_id", "") or getattr(sl.location, "pk", "") or "") for sl in (story.locations or [])],
            "medias": [int(m.media_pk) for m in (story.medias or [])],
        }

    def find_story_for_media(self, media_pk: int) -> str:
        """pk de una historia vigente de la cuenta que comparte ``media_pk`` (o "")."""
        client = self.connect()
        try:
            stories = client.user_stories(client.user_id)
        except Exception as exc:  # noqa: BLE001
            raise _classify(exc, published_phase=False) from None
        for story in stories:
            if any(int(m.media_pk) == int(media_pk) for m in (story.medias or [])):
                return str(story.pk)
        return ""

    def delete_story(self, story_pk: str) -> bool:
        client = self.connect()
        try:
            return bool(client.story_delete(story_pk))
        except Exception as exc:  # noqa: BLE001
            raise _classify(exc, published_phase=False) from None


def unwrap_link(url: str) -> str:
    """Destino real de un enlace de historia: Instagram lo devuelve envuelto en
    ``l.instagram.com/?u=<destino>`` y le agrega ``fbclid``."""
    from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

    parts = urlsplit(url)
    if parts.hostname == "l.instagram.com":
        inner = dict(parse_qsl(parts.query)).get("u")
        if inner:
            parts = urlsplit(inner)
    query = urlencode([(k, v) for k, v in parse_qsl(parts.query) if k != "fbclid"])
    return urlunsplit((parts.scheme, parts.netloc, parts.path, query, parts.fragment))


def verify(expected: dict, found: dict) -> list[str]:
    """Stickers pedidos que no aparecen en la historia publicada."""
    missing = []
    if expected["link"]["url"].rstrip("/") not in {u.rstrip("/") for u in found.get("links") or []}:
        missing.append("link")
    if int(expected["media"]["media_pk"]) not in set(found.get("medias") or []):
        missing.append("media")
    if expected.get("location") and not found.get("locations"):
        missing.append("location")
    return missing
