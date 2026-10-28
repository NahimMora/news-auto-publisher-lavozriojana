"""Historias nativas de Instagram con stickers (instagrapi): fondo, IDs, URL,
ubicación, stickers, idempotencia y recuperación. Todo con mocks: sin red ni
publicación. La prueba real está en ``cli.py native-stories live-test``."""
from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image

from utils import native_story as ns
from utils.stage_result import StageStatus

try:
    import instagrapi  # noqa: F401

    HAS_INSTAGRAPI = True
except ImportError:  # CI sin la dependencia opcional
    HAS_INSTAGRAPI = False

WEB_URL = "https://lavozriojana.com/noticias/corte-de-agua-en-chilecito"
PERMALINK = "https://www.instagram.com/p/B1LbfVPlwIA/"
PK = 2110901750722920960


def _post_jpeg(color=(200, 30, 30), size=(800, 1000)) -> bytes:
    import io

    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "JPEG")
    return buf.getvalue()


class _Env(unittest.TestCase):
    """Directorios temporales para data/output y flags limpios."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.data = root / "data"
        self.data.mkdir()
        self.env = mock.patch.dict(os.environ, {
            "LVR_DATA_DIR": str(self.data), "LVR_OUTPUT_DIR": str(root / "output"),
            "IG_NATIVE_STORIES_ENABLED": "true", "IG_NATIVE_STORIES_DRY_RUN": "false",
            "IG_LOCATION_ENABLED": "true", "IG_NATIVE_STORY_INCLUDE_REELS": "false",
            "IG_NATIVE_STORY_MIN_AGE_SECONDS": "120", "IG_NATIVE_STORY_MAX_ATTEMPTS": "3",
            "INSTAGRAPI_SESSION_PATH": str(root / "session.json"),
        })
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def write(self, name, payload):
        (self.data / name).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    def seed(self, *, age=600, media_id="17900000000000001", web_url=WEB_URL, locality="Chilecito", media_type=None,
             location_id="347961018633223", titulo="Corte de agua en Chilecito", seccion="Interior"):
        record = {"external_id": media_id, "posted_at": str(int(time.time() - age)), "meta_queue_key": f"k{media_id}",
                  "titulo": titulo, "seccion": seccion}
        if media_type:
            record["media_type"] = media_type
        if location_id:
            record["ig_location_id"] = location_id
        self.write("ig_posted.json", {"posted": {f"k{media_id}": record}})
        self.write("noticias_meta.json", [{"meta_queue_key": f"k{media_id}", "web_url": web_url, "locality": locality}])
        return media_id


# 1. Fondo ───────────────────────────────────────────────────────────────
class BackgroundTests(_Env):
    def test_dark_background_is_9_16_and_charcoal(self):
        path = ns.write_background(str(self.data / "bg.jpg"))
        with Image.open(path) as image:
            self.assertEqual((1080, 1920), image.size)
            r, g, b = image.convert("RGB").getpixel((540, 960))
        for got, want in zip((r, g, b), (0x11, 0x13, 0x18)):
            self.assertLessEqual(abs(got - want), 2)

    def test_story_image_draws_post_and_pills_under_each_sticker(self):
        # Los stickers de la API son invisibles: la imagen tiene que mostrar
        # la publicación y las pastillas justo debajo de cada zona tocable.
        payload = ns.build_payload(media_id="1", media_pk=PK, web_url=WEB_URL, aspect=0.8,
                                   location={"external_id": "347961018633223", "name": "Chilecito, La Rioja"}, reel=False)
        path = ns.write_story_image(payload, _post_jpeg(), str(self.data / "story.jpg"))
        with Image.open(path) as image:
            image = image.convert("RGB")
            self.assertEqual((1080, 1920), image.size)

            def at(box, dx=0.0):
                return image.getpixel((round((box["x"] + dx) * 1080), round(box["y"] * 1920)))

            red = at(payload["media"])
            self.assertGreater(red[0], 150)
            self.assertLess(red[1], 80)
            for name in ("link", "location"):
                left_edge = payload[name]["width"] / 2 - 0.02
                self.assertGreater(min(at(payload[name], -left_edge)), 240, name)  # pastilla blanca
            self.assertLess(max(image.getpixel((540, 60))), 40)  # fondo oscuro fuera de las cajas

    def test_story_image_requires_post_image(self):
        payload = ns.build_payload(media_id="1", media_pk=PK, web_url=WEB_URL, aspect=0.8, location=None, reel=False)
        with self.assertRaises(ValueError):
            ns.compose_story(payload, b"")

    def test_preview_marks_boxes_and_writes_payload(self):
        payload = ns.build_payload(media_id="1", media_pk=PK, web_url=WEB_URL, aspect=0.8,
                                   location={"external_id": "347961018633223", "name": "Chilecito"}, reel=False)
        out = ns.render_preview(payload, str(self.data / "p" / "x.png"))
        self.assertTrue(os.path.exists(out))
        self.assertEqual(PK, json.loads(Path(out).with_suffix(".json").read_text(encoding="utf-8"))["media"]["media_pk"])


# 2. Media ID ────────────────────────────────────────────────────────────
class MediaIdTests(unittest.TestCase):
    def test_known_shortcodes(self):
        self.assertEqual(2110901750722920960, ns.media_pk_from_shortcode("B1LbfVPlwIA"))
        self.assertEqual(2278584739065882267, ns.media_pk_from_shortcode("B-fKL9qpeab"))

    def test_permalink_forms(self):
        for url in (PERMALINK, "https://www.instagram.com/reel/B1LbfVPlwIA/", "https://instagram.com/lavozriojana.ok/p/B1LbfVPlwIA/?igsh=x"):
            with self.subTest(url=url):
                self.assertEqual(PK, ns.media_pk_from_permalink(url))

    def test_invalid_permalink(self):
        for url in ("", "https://www.instagram.com/stories/x/1/", "https://evil.com/p/B1LbfVPlwIA/", "https://www.instagram.com/p/<>/"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                ns.media_pk_from_permalink(url)

    def test_graph_id_is_not_the_pk(self):
        # El ID de Graph nunca se usa como pk: sólo el shortcode del permalink.
        self.assertNotEqual(17900000000000001, ns.media_pk_from_permalink(PERMALINK))

    @unittest.skipUnless(HAS_INSTAGRAPI, "instagrapi no instalado")
    def test_matches_instagrapi_codec(self):
        from instagrapi.utils import InstagramIdCodec

        for code in ("B1LbfVPlwIA", "CCQQsCXjOaB", "DQx-_9abcde"):
            self.assertEqual(int(InstagramIdCodec.decode(code)), ns.media_pk_from_shortcode(code))


# 3. URL web ─────────────────────────────────────────────────────────────
class WebUrlTests(_Env):
    def test_valid(self):
        self.assertEqual(WEB_URL, ns.validate_web_url(WEB_URL))
        self.assertTrue(ns.validate_web_url("https://www.lavozriojana.com/noticias/x-y-z"))

    def test_rejected(self):
        for url in ("", "http://lavozriojana.com/noticias/x", "https://lavozriojana.com/", "https://infobae.com/noticias/x",
                    "https://lavozriojana.com.evil.net/noticias/x", "https://user:pw@lavozriojana.com/noticias/x", "javascript:alert(1)"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                ns.validate_web_url(url)

    def test_web_url_comes_from_queue_item(self):
        media_id = self.seed()
        candidate = ns.candidates({"jobs": {}})[0]
        self.assertEqual(media_id, candidate["media_id"])
        self.assertEqual(WEB_URL, candidate["web_url"])
        self.assertTrue(candidate["ready"])


# 4. Ubicación ───────────────────────────────────────────────────────────
class LocationTests(_Env):
    def test_reuses_only_location_of_the_original_post(self):
        location, reason = ns.location_for({"locality": "Chilecito · Capital", "ig_location_id": "347961018633223"})
        self.assertEqual("", reason)
        self.assertEqual({"external_id": "347961018633223", "name": "Chilecito"}, location)

    def test_never_adds_location_the_post_did_not_have(self):
        # La nota nombra una localidad con ID cargado, pero el post salió sin
        # ubicación: la historia tampoco la lleva.
        self.assertEqual((None, "post_without_location"), ns.location_for({"locality": "Chilecito"}))
        self.assertEqual((None, "post_without_location"), ns.location_for({"web_editorial": {"locality": "Chamical"}}))

    def test_post_publisher_persists_locality_and_applied_location(self):
        from meta import ig_client

        path = str(self.data / "ig_posted.json")
        with mock.patch.object(ig_client, "IG_STATE_PATH", path):
            ig_client._mark_posted("k1", {"titulo": "t", "locality": "Chilecito", "ig_location_id": "347961018633223",
                                          "web_url": WEB_URL}, "1790")
            ig_client._mark_posted("k2", {"titulo": "t", "ig_location_id": ""}, "1791")
        posted = json.loads(Path(path).read_text(encoding="utf-8"))["posted"]
        self.assertEqual(("Chilecito", "347961018633223", WEB_URL),
                         (posted["k1"]["locality"], posted["k1"]["ig_location_id"], posted["k1"]["web_url"]))
        self.assertNotIn("ig_location_id", posted["k2"])

    def test_missing_cases_give_reason(self):
        self.assertEqual((None, "post_without_location"), ns.location_for({}))
        self.assertEqual((None, "invalid_post_location_id"), ns.location_for({"ig_location_id": "abc"}))
        with mock.patch.dict(os.environ, {"IG_LOCATION_ENABLED": "false"}):
            self.assertEqual((None, "location_disabled"), ns.location_for({"locality": "Chilecito"}))


# 5. Stickers ────────────────────────────────────────────────────────────
class StickerLayoutTests(_Env):
    def test_three_boxes_inside_safe_area_without_overlap(self):
        for aspect in (0.8, 1.0, 1.91, 9 / 16):
            with self.subTest(aspect=aspect):
                payload = ns.build_payload(media_id="1", media_pk=PK, web_url=WEB_URL, aspect=aspect,
                                           location={"external_id": "347961018633223", "name": "Chilecito"}, reel=aspect < 0.6)
                self.assertEqual([], ns.validate_payload(payload))
                media = payload["media"]
                self.assertLessEqual(media["width"], 0.88)
                # Conserva la proporción del post.
                self.assertAlmostEqual(aspect, media["width"] * 1080 / (media["height"] * 1920), places=3)
                self.assertGreater(media["y"] - media["height"] / 2, payload["location"]["y"] + payload["location"]["height"] / 2)

    def test_reference_positions(self):
        payload = ns.build_payload(media_id="1", media_pk=PK, web_url=WEB_URL, aspect=1.0,
                                   location={"external_id": "347961018633223", "name": "Chilecito"}, reel=False)
        self.assertEqual((0.5, 0.17), (payload["link"]["x"], payload["link"]["y"]))
        self.assertEqual((0.5, 0.25), (payload["location"]["x"], payload["location"]["y"]))
        self.assertEqual(0.57, payload["media"]["y"])
        self.assertEqual(0.88, payload["media"]["width"])

    def test_without_location_two_stickers(self):
        payload = ns.build_payload(media_id="1", media_pk=PK, web_url=WEB_URL, aspect=0.8, location=None, reel=False)
        self.assertIsNone(payload["location"])
        self.assertEqual([], ns.validate_payload(payload))

    def test_never_without_link(self):
        with self.assertRaises(ValueError):
            ns.build_payload(media_id="1", media_pk=PK, web_url="", aspect=0.8, location=None, reel=False)
        payload = ns.build_payload(media_id="1", media_pk=PK, web_url=WEB_URL, aspect=0.8, location=None, reel=False)
        payload.pop("link")
        self.assertIn("falta el sticker de enlace", ns.validate_payload(payload))

    def test_overlap_detected(self):
        payload = ns.build_payload(media_id="1", media_pk=PK, web_url=WEB_URL, aspect=0.8, location=None, reel=False)
        payload["link"]["y"] = payload["media"]["y"]
        self.assertTrue(any("superpone" in e for e in ns.validate_payload(payload)))

    @unittest.skipUnless(HAS_INSTAGRAPI, "instagrapi no instalado")
    def test_instagrapi_builds_three_native_stickers(self):
        """El configure real de instagrapi (sin red) arma los tres tap models."""
        from meta import instagrapi_client as igc

        payload = ns.build_payload(media_id="1", media_pk=PK, web_url=WEB_URL, aspect=0.8,
                                   location={"external_id": "347961018633223", "name": "Chilecito"}, reel=False)
        client = igc._client_class()()
        client.authorization_data = {"ds_user_id": "4242"}
        sent = []
        client.private_request = lambda endpoint, data=None, **kw: sent.append((endpoint, data)) or {"status": "ok"}
        client.location_info = mock.Mock(side_effect=AssertionError("no debe pedir la ubicación a la red"))
        client.photo_rupload = mock.Mock(return_value=("up1", 1080, 1920))
        client._current_story_ids = mock.Mock(return_value=set())
        client._extract_configured_story_or_recent = mock.Mock(return_value=mock.Mock(pk="555", id="555_4242"))
        wrapper = igc.NativeStoryClient()
        wrapper._client = client
        with mock.patch("instagrapi.mixins.photo.time.sleep"):
            result = wrapper.publish(payload, ns.write_background(str(self.data / "bg.jpg")))
        self.assertEqual("555", result["story_pk"])
        endpoint, data = sent[-1]
        self.assertEqual("media/configure_to_story/", endpoint)
        taps = json.loads(data["tap_models"])
        by_type = {t["type"]: t for t in taps}
        self.assertEqual(str(PK), by_type["feed_media"]["media_id"])
        self.assertEqual("4242", by_type["feed_media"]["media_owner_id"])
        self.assertEqual(WEB_URL, by_type["story_link"]["url"])
        self.assertEqual("347961018633223", by_type["location"]["location_id"])
        self.assertEqual(str(PK), data["reshared_media_id"])
        self.assertIn("location_sticker", data["story_sticker_ids"])
        self.assertIn("link_sticker_default", data["story_sticker_ids"])
        # Sólo reutilización: ninguna mención, hashtag ni texto agregado.
        self.assertEqual({"feed_media", "story_link", "location"}, set(by_type))
        for key in ("reel_mentions", "story_hashtags", "caption"):
            self.assertFalse(data.get(key), key)
        self.assertEqual(("media/validate_reel_url/", WEB_URL), (sent[0][0], sent[0][1]["url"]))

    def test_verify_reports_missing_stickers(self):
        from meta import instagrapi_client as igc

        payload = ns.build_payload(media_id="1", media_pk=PK, web_url=WEB_URL, aspect=0.8,
                                   location={"external_id": "347961018633223", "name": "Chilecito"}, reel=False)
        self.assertEqual([], igc.verify(payload, {"links": [WEB_URL + "/"], "medias": [PK], "locations": ["347961018633223"]}))
        self.assertEqual(["link", "location"], igc.verify(payload, {"links": [], "medias": [PK], "locations": []}))

    def test_link_sticker_is_read_through_instagram_redirect(self):
        # Forma real devuelta por Instagram en la prueba del 2026-10-28.
        from urllib.parse import quote

        from meta import instagrapi_client as igc

        wrapped = f"https://l.instagram.com/?u={quote(WEB_URL + '?fbclid=PAZX', safe='')}&e=AUCS"
        self.assertEqual(WEB_URL, igc.unwrap_link(wrapped))
        self.assertEqual(WEB_URL + "?a=1", igc.unwrap_link(WEB_URL + "?a=1&fbclid=x"))


# 6. Etapa: idempotencia y recuperación ──────────────────────────────────
class FakeClient:
    def __init__(self, *, publish=None, found=""):
        self.publish_calls = 0
        self._publish = publish
        self.found = found
        self.connected = 0

    def connect(self):
        self.connected += 1

    def publish(self, payload, background):
        self.publish_calls += 1
        self.background_existed = os.path.exists(background)
        self.last_background = background
        if self._publish:
            raise self._publish
        return {"story_pk": "3500", "story_id": "3500_1", "story_url": "https://www.instagram.com/stories/x/3500/"}

    def inspect(self, pk):
        return {"links": [WEB_URL], "medias": [PK], "locations": ["347961018633223"]}

    def find_story_for_media(self, media_pk):
        return self.found


class StageTests(_Env):
    def run_stage(self, client=None, image=None, **kw):
        from meta import ig_client
        from meta import instagrapi_client as igc
        from meta import run_native_stories as rns

        plan = mock.Mock()
        plan.channel_enabled.return_value = True
        info = {"id": "x", "permalink": PERMALINK, "media_type": "IMAGE", "media_url": "https://cdn/x.jpg"}
        with mock.patch.object(rns, "deployment_plan", return_value=plan), mock.patch.object(rns, "quiet_hours", return_value=False), \
                mock.patch.object(ig_client, "media_info", return_value=info) as media_info, \
                mock.patch.object(ns, "measure_aspect", return_value=(0.8, _post_jpeg()) if image is None else image), \
                mock.patch.object(igc, "NativeStoryClient", return_value=client or FakeClient()) as factory:
            result = rns.main(**kw)
        return result, media_info, factory

    def entry(self, media_id):
        return ns.load_state()["jobs"][media_id]

    def test_disabled_is_no_work(self):
        with mock.patch.dict(os.environ, {"IG_NATIVE_STORIES_ENABLED": "false"}):
            result, _, factory = self.run_stage()
        self.assertEqual(StageStatus.NO_WORK, result.status)
        factory.assert_not_called()

    def test_success_records_story_id_and_is_idempotent(self):
        media_id = self.seed()
        client = FakeClient()
        result, _, _ = self.run_stage(client)
        self.assertEqual(StageStatus.SUCCESS, result.status)
        entry = self.entry(media_id)
        self.assertEqual("completed", entry["status"])
        self.assertEqual("3500", entry["story_pk"])
        self.assertEqual("347961018633223", entry["location_id"])
        self.assertEqual([], entry["missing_stickers"])
        self.assertTrue(client.background_existed)
        self.assertFalse(os.path.exists(client.last_background))  # temporal borrado
        again, _, factory = self.run_stage(client)
        self.assertEqual(StageStatus.NO_WORK, again.status)
        self.assertEqual(1, client.publish_calls)

    def test_waits_until_post_is_old_enough(self):
        self.seed(age=30)
        result, media_info, _ = self.run_stage()
        self.assertEqual(StageStatus.NO_WORK, result.status)
        media_info.assert_not_called()

    def test_reels_off_by_default(self):
        self.seed(media_type="reel")
        result, _, _ = self.run_stage()
        self.assertEqual(StageStatus.NO_WORK, result.status)

    def test_without_web_url_never_publishes(self):
        media_id = self.seed(web_url="")
        client = FakeClient()
        self.run_stage(client)
        self.assertEqual(0, client.publish_calls)
        self.assertEqual("skipped", self.entry(media_id)["status"])

    def test_missing_location_still_publishes_with_reason(self):
        media_id = self.seed(location_id="")
        client = FakeClient()
        self.run_stage(client)
        self.assertEqual("completed", self.entry(media_id)["status"])
        self.assertEqual("post_without_location", self.entry(media_id)["location_skipped_reason"])
        self.assertEqual("", self.entry(media_id)["location_id"])

    def test_without_post_image_retries_later_and_never_publishes_blank(self):
        media_id = self.seed()
        client = FakeClient()
        self.run_stage(client, image=(0.0, b""))
        self.assertEqual(0, client.publish_calls)
        self.assertEqual(("failed", "post_image_unavailable"), (self.entry(media_id)["status"], self.entry(media_id)["error"]))

    def test_only_riojan_or_policiales_get_a_story(self):
        media_id = self.seed(titulo="Inflación de septiembre en todo el país", seccion="Economia", location_id="")
        client = FakeClient()
        result, media_info, _ = self.run_stage(client)
        self.assertEqual(StageStatus.NO_WORK, result.status)
        self.assertEqual(0, client.publish_calls)
        media_info.assert_not_called()
        self.assertNotIn(media_id, ns.load_state().get("jobs") or {})  # no consume cupo ni deja estado

    def test_policiales_in_scope_without_riojan_term(self):
        self.seed(titulo="Detuvieron a un hombre tras una persecución", seccion="Policiales", location_id="")
        client = FakeClient()
        self.run_stage(client)
        self.assertEqual(1, client.publish_calls)

    def test_graph_story_is_not_duplicated(self):
        media_id = self.seed()
        self.write("stories_state.json", {"posted": {f"post:{media_id}": {"ig_id": "99"}}})
        client = FakeClient()
        with mock.patch("utils.story_publisher.STATE_PATH", str(self.data / "stories_state.json")):
            self.run_stage(client)
        self.assertEqual(0, client.publish_calls)
        self.assertEqual("graph_story_exists", self.entry(media_id)["error"])

    def test_rejected_backs_off_then_dead_letter(self):
        from meta import instagrapi_client as igc

        media_id = self.seed()
        client = FakeClient(publish=igc.NativeStoryError(igc.REJECTED, "ClientError"))
        result, _, _ = self.run_stage(client)
        self.assertEqual(StageStatus.FAILED, result.status)
        entry = self.entry(media_id)
        self.assertEqual(("failed", 1), (entry["status"], entry["attempts"]))
        self.assertGreater(entry["next_attempt_at"], time.time() + 800)
        self.run_stage(client)  # en backoff: no se intenta
        self.assertEqual(1, client.publish_calls)
        for attempt in (2, 3):
            ns.mark(media_id, next_attempt_at=0)
            self.run_stage(client)
        self.assertEqual(("dead_letter", 3), (self.entry(media_id)["status"], self.entry(media_id)["attempts"]))
        ns.mark(media_id, next_attempt_at=0)
        self.run_stage(client)
        self.assertEqual(3, client.publish_calls)

    def test_ambiguous_is_reconciled_not_republished(self):
        from meta import instagrapi_client as igc

        media_id = self.seed()
        self.run_stage(FakeClient(publish=igc.NativeStoryError(igc.UNVERIFIED, "PhotoConfigureStoryError")))
        self.assertEqual("unverified", self.entry(media_id)["status"])
        # Antes de la ventana de reconciliación no se toca.
        client = FakeClient(found="3600")
        self.run_stage(client)
        self.assertEqual("unverified", self.entry(media_id)["status"])
        # Después: aparece entre las vigentes → completada sin volver a publicar.
        with mock.patch.object(ns.time, "time", return_value=time.time()):
            ns.mark(media_id, status="unverified")
        state_path = ns.state_path()
        state = json.loads(Path(state_path).read_text(encoding="utf-8"))
        state["jobs"][media_id]["updated_at"] -= 3600
        Path(state_path).write_text(json.dumps(state), encoding="utf-8")
        self.run_stage(client)
        self.assertEqual(("completed", "3600", True), (self.entry(media_id)["status"], self.entry(media_id)["story_pk"], self.entry(media_id)["reconciled"]))
        self.assertEqual(0, client.publish_calls)

    def test_ambiguous_not_found_becomes_retryable(self):
        media_id = self.seed()
        ns.mark(media_id, status="unverified", media_pk=PK, attempts=1)
        state = json.loads(Path(ns.state_path()).read_text(encoding="utf-8"))
        state["jobs"][media_id]["updated_at"] -= 3600
        Path(ns.state_path()).write_text(json.dumps(state), encoding="utf-8")
        client = FakeClient(found="")
        self.run_stage(client)
        self.assertEqual("failed", self.entry(media_id)["status"])
        self.assertEqual(0, client.publish_calls)

    def test_challenge_blocks_and_stops(self):
        from meta import instagrapi_client as igc

        media_id = self.seed()
        client = FakeClient(publish=igc.NativeStoryError(igc.BLOCKED, "ChallengeRequired"))
        result, _, _ = self.run_stage(client)
        self.assertEqual("instagram_blocked", result.error_type)
        state = ns.load_state()
        self.assertEqual("ChallengeRequired", state["block_reason"])
        self.assertGreater(state["blocked_until"], time.time() + 23 * 3600)
        # El intento no se gasta y no se reintenta mientras dure el bloqueo.
        self.assertEqual(0, self.entry(media_id)["attempts"])
        result, _, factory = self.run_stage(client)
        self.assertEqual(StageStatus.DEGRADED, result.status)
        factory.assert_not_called()

    def test_invalid_session_is_failed_credential(self):
        from meta import instagrapi_client as igc

        self.seed()
        client = FakeClient()
        client.connect = mock.Mock(side_effect=igc.NativeStoryError(igc.CREDENTIAL, "LoginRequired"))
        result, _, _ = self.run_stage(client)
        self.assertEqual((StageStatus.FAILED, "invalid_credential"), (result.status, result.error_type))

    def test_dry_run_writes_preview_without_connecting(self):
        media_id = self.seed()
        with mock.patch.dict(os.environ, {"IG_NATIVE_STORIES_DRY_RUN": "true"}):
            result, _, factory = self.run_stage()
        factory.assert_not_called()
        self.assertEqual("dry_run", result.details["outcomes"][media_id]["status"])
        self.assertTrue(os.path.exists(result.details["outcomes"][media_id]["preview"]))
        self.assertNotIn(media_id, ns.load_state().get("jobs") or {})

    def test_corrupt_state_fails_instead_of_resetting(self):
        self.seed()
        Path(ns.state_path()).write_text("{roto", encoding="utf-8")
        result, _, factory = self.run_stage()
        self.assertEqual((StageStatus.FAILED, "state_read_error"), (result.status, result.error_type))
        factory.assert_not_called()

    def test_daily_cap(self):
        self.seed()
        with mock.patch.dict(os.environ, {"IG_NATIVE_STORY_MAX_PER_DAY": "0"}):
            result, _, factory = self.run_stage()
        self.assertEqual(StageStatus.NO_WORK, result.status)


@unittest.skipUnless(HAS_INSTAGRAPI, "instagrapi no instalado")
class ClientClassificationTests(unittest.TestCase):
    def test_platform_controls_stop_everything(self):
        from instagrapi import exceptions as ex

        from meta import instagrapi_client as igc

        cases = {
            ex.ChallengeRequired(): igc.BLOCKED, ex.FeedbackRequired(): igc.BLOCKED, ex.PleaseWaitFewMinutes(): igc.BLOCKED,
            ex.LoginRequired(): igc.CREDENTIAL, ex.BadPassword(): igc.CREDENTIAL, ex.TwoFactorRequired(): igc.CREDENTIAL,
            ex.MediaNotFound(): igc.REJECTED, ex.ClientConnectionError(): igc.UNVERIFIED,
        }
        for exc, kind in cases.items():
            with self.subTest(exc=type(exc).__name__):
                self.assertEqual(kind, igc._classify(exc, published_phase=True).kind)
        self.assertEqual(igc.REJECTED, igc._classify(ex.ClientConnectionError(), published_phase=False).kind)

    def test_no_username_never_logs_in(self):
        from meta import instagrapi_client as igc

        with mock.patch.dict(os.environ, {"INSTAGRAPI_USERNAME": ""}), self.assertRaises(igc.NativeStoryError) as ctx:
            igc.NativeStoryClient().connect()
        self.assertEqual("missing_username", ctx.exception.code)

    def test_no_session_and_no_password(self):
        from meta import instagrapi_client as igc

        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {
            "INSTAGRAPI_USERNAME": "lavozriojana.ok", "INSTAGRAPI_PASSWORD": "", "INSTAGRAPI_SESSION_PATH": os.path.join(tmp, "s.json"),
        }), self.assertRaises(igc.NativeStoryError) as ctx:
            igc.NativeStoryClient().connect()
        self.assertEqual((igc.CREDENTIAL, "missing_session"), (ctx.exception.kind, ctx.exception.code))


if __name__ == "__main__":
    unittest.main()
