"""Datos para la web en R2 (utils/web_feed.py): armado puro, contrato de la web
(lib/feed-types.ts del sitio), fallas por fuente y subida."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import date, datetime
from types import SimpleNamespace
from unittest import mock

from utils.operation_result import OperationResult
from utils.social_time import AR_TZ
from utils.stage_result import StageStatus

NOW = 1_792_780_000.0
SITE = "https://lavozriojana.com/noticias/"
WEB = [
    {"titulo": "MURIÓ EL JOVEN QUE VOLCÓ EN SANAGASTA", "canonical_url": "https://nr/2", "web_url": SITE + "murio-el-joven", "published_at_ts": NOW - 3600,
     "titulo_original_scrapeado": "Murió el joven que volcó en la ruta de Sanagasta",
     "event_update": {"of_canonical_url": "https://nr/1", "of_title": "Muerte cerebral", "novedad": "Murió en el hospital"}},
    {"titulo": "MUERTE CEREBRAL PARA EL JOVEN DE SANAGASTA", "canonical_url": "https://nr/1", "web_url": SITE + "muerte-cerebral", "published_at_ts": NOW - 20 * 3600},
    {"titulo": "VIEJA", "canonical_url": "https://nr/3", "web_url": SITE + "vieja", "published_at_ts": NOW - 5 * 86400},
]
IG_POSTED = {
    "a": {"external_id": "m1", "canonical_url": "https://nr/1", "titulo": "Muerte cerebral", "posted_at": NOW - 20 * 3600},
    "b": {"external_id": "m2", "canonical_url": "https://nr/2", "titulo": "Murió el joven", "posted_at": NOW - 3600},
    "c": {"external_id": "m3", "canonical_url": "https://nr/3", "titulo": "Vieja", "posted_at": NOW - 5 * 86400},
    "d": {"external_id": "m4", "canonical_url": "https://sin-web/4", "titulo": "Sin web", "posted_at": NOW - 3600},
}
INSIGHTS = {
    "m1": {"posted_at": NOW - 20 * 3600, "seccion": "Policiales", "reach": 900, "interactions": 10},
    "m2": {"posted_at": NOW - 3600, "seccion": "Policiales", "reach": 1500, "interactions": 30},
    "m3": {"posted_at": NOW - 5 * 86400, "seccion": "Sociedad", "reach": 9000, "interactions": 100},
    "m4": {"posted_at": NOW - 3600, "seccion": "Policiales", "reach": 99999, "interactions": 1},
}
MOMENT = datetime.fromtimestamp(NOW, tz=AR_TZ)


class TitleTests(unittest.TestCase):
    def test_uppercase_title_gets_sentence_case_with_names_from_the_note(self):
        from utils.web_feed import clean_title

        self.assertEqual(
            clean_title("🚨 FEDERICO WALS PIDIÓ RECIBIR AL PAPA EN LA RIOJA SIN ESPECULACIONES",
                        "El senador Federico Wals pidió que la visita del Papa no se use políticamente."),
            # "Papa" con mayúscula porque así lo escribe la nota.
            "Federico Wals pidió recibir al Papa en La Rioja sin especulaciones",
        )
        # Siglas tal como las escribe la nota; sin referencias, sólo la primera letra.
        self.assertEqual(clean_title("CORTE DE LUZ DE EDELAR EN CHILECITO", "Según informó EDELaR, el corte afectará a Chilecito."),
                         "Corte de luz de EDELaR en Chilecito")
        self.assertEqual(clean_title("NUEVA LEY DE TRÁNSITO"), "Nueva ley de tránsito")
        # Departamentos, localidades y provincias conocidos, aunque la nota no los traiga.
        self.assertEqual(clean_title("CORTES DE LUZ EN ARAUCO, CASTRO BARROS Y SAN BLAS DE LOS SAUCES"),
                         "Cortes de luz en Arauco, Castro Barros y San Blas de los Sauces")
        self.assertEqual(clean_title("BUSCAN A UNA MUJER EN CORRIENTES Y EN PATQUIA"), "Buscan a una mujer en Corrientes y en Patquía")
        # "capital" e "independencia" siguen siendo palabras comunes.
        self.assertEqual(clean_title("ACTO POR LA INDEPENDENCIA EN LA CAPITAL"), "Acto por la independencia en la capital")

    def test_mixed_case_title_is_kept_but_cleaned(self):
        from utils.web_feed import clean_title

        self.assertEqual(clean_title("<b>Encontraron</b> sano y salvo a un niño 👇"), "Encontraron sano y salvo a un niño")


class MostViewedTests(unittest.TestCase):
    def test_windows_rank_by_reach_and_need_a_web_url(self):
        from utils.web_feed import build_most_viewed

        doc = build_most_viewed(INSIGHTS, IG_POSTED, WEB, {"m2": {"permalink": "https://www.instagram.com/p/XXXXX/"}}, now=NOW)
        self.assertEqual([r["url"] for r in doc["ventanas"]["24h"]], [SITE + "murio-el-joven", SITE + "muerte-cerebral"])
        self.assertEqual([r["url"] for r in doc["ventanas"]["7d"]], [SITE + "vieja", SITE + "murio-el-joven", SITE + "muerte-cerebral"])
        top = doc["ventanas"]["24h"][0]
        self.assertEqual(top["instagram"], {"url": "https://www.instagram.com/p/XXXXX/", "alcance": 1500, "interacciones": 30})
        self.assertEqual((top["seccion"], top["titulo"]), ("policiales", "Murió el joven que volcó en Sanagasta"))
        # Sin enlace leído todavía: null, no "".
        self.assertIsNone(doc["ventanas"]["24h"][1]["instagram"]["url"])
        self.assertNotIn("Sin web", json.dumps(doc))
        self.assertEqual(sorted(doc["por_seccion_7d"]), ["policiales", "sociedad"])

    def test_unknown_reach_is_not_zero(self):
        from utils.web_feed import build_most_viewed

        insights = {"m2": {"posted_at": NOW - 3600, "seccion": "Policiales"}}
        self.assertEqual(build_most_viewed(insights, IG_POSTED, WEB, {}, now=NOW)["ventanas"]["24h"], [])


class UpdatesAndVideosTests(unittest.TestCase):
    def test_update_pair_goes_from_the_original_to_the_new_note(self):
        from utils.web_feed import build_updates

        [item] = build_updates(WEB, now=NOW)["items"]
        self.assertEqual(item["nota"]["url"], SITE + "muerte-cerebral")
        self.assertTrue(item["nota"]["publicada"].endswith("-03:00"))
        self.assertEqual(item["actualiza"], {"titulo": "Murió el joven que volcó en Sanagasta", "url": SITE + "murio-el-joven"})
        self.assertEqual(item["novedad"], "Murió en el hospital")

    def test_a_note_never_updates_itself(self):
        from utils.web_feed import build_updates

        selfish = [{**WEB[0], "event_update": {"of_web_url": SITE + "murio-el-joven", "novedad": "x"}}]
        self.assertEqual(build_updates(selfish, now=NOW)["items"], [])

    def test_videos_only_with_verified_link_and_nulls(self):
        from utils.web_feed import build_videos, reel_records

        x = {"r1": {"status": "completed", "instagram_id": "v1", "titulo": "CHOQUE EN LA RUTA 38", "url": "https://x.com/a/status/1", "completed_at": NOW - 60},
             "r2": {"status": "pending", "instagram_id": "v2"},
             "r3": {"status": "completed", "instagram_id": "v4", "titulo": "Programado", "completed_at": NOW + 3600}}
        jobs = {"jobs": {"j1": {"status": "completed", "instagram_id": "v3", "completed_at": NOW - 30,
                                "noticia": {"titulo_instagram": "Nota con video", "canonical_url": "https://nr/2"}}}}
        reels = reel_records(x, jobs, WEB)
        self.assertEqual([r["media_id"] for r in reels], ["v4", "v3", "v1"])
        self.assertEqual(reels[1]["url_nota"], SITE + "murio-el-joven")
        links = {m: {"permalink": f"https://www.instagram.com/reel/{m}AAAA/", "media_type": "VIDEO"} for m in ("v1", "v4")}
        doc = build_videos(reels, links, now=NOW)
        [item] = doc["items"]
        self.assertEqual(item["instagram"], {"url": "https://www.instagram.com/reel/v1AAAA/", "miniatura": None, "video": None,
                                             "video_vence": None, "tipo": "VIDEO"})
        self.assertEqual((item["titulo"], item["url_nota"], item["fuente_video"]), ("Choque en la ruta 38", None, "https://x.com/a/status/1"))

    def test_video_source_comes_from_the_instagram_cdn_with_its_expiry(self):
        from utils.web_feed import build_videos, video_source

        oe = format(int(NOW) + 30 * 3600, "X")
        mp4 = f"https://instagram.fsla2-1.fna.fbcdn.net/o1/v/t16/f2/m86/AQN.mp4?_nc_ht=x&oe={oe}&_nc_sid=1"
        url, expires = video_source(mp4, now=NOW)
        self.assertEqual(url, mp4)
        self.assertEqual(expires, datetime.fromtimestamp(int(NOW) + 30 * 3600, tz=AR_TZ).isoformat(timespec="seconds"))
        # Por vencer, sin firma o fuera del CDN de Instagram: no se ofrece.
        soon = mp4.replace(oe, format(int(NOW) + 3600, "X"))
        for bad in (soon, mp4.split("?")[0], "https://evil.com/a.mp4?oe=" + oe, ""):
            self.assertEqual(video_source(bad, now=NOW), (None, None))
        reels = [{"media_id": "v1", "titulo": "Choque", "origen": "nota", "fuente_video": None, "url_nota": None, "at": NOW - 60}]
        links = {"v1": {"permalink": "https://www.instagram.com/reel/AAAAA/", "media_type": "VIDEO", "media_url": mp4}}
        [item] = build_videos(reels, links, now=NOW)["items"]
        self.assertEqual((item["instagram"]["video"], item["instagram"]["video_vence"]), (mp4, expires))

    def test_permalinks_are_read_once_but_video_thumbnails_every_run(self):
        from utils.web_feed import fetch_permalinks

        getter = mock.Mock(side_effect=lambda m: {"permalink": f"https://www.instagram.com/reel/{m}/"} if m != "bad" else {"permalink": "https://evil/"})
        new = fetch_permalinks(["a", "known", "bad", "a"], {"known": {}, "video": {}}, refresh=["video"], getter=getter)
        self.assertEqual(sorted(new), ["a", "video"])
        self.assertEqual(getter.call_count, 3)


class StoriesAndBreakingTests(unittest.TestCase):
    def test_stories_come_only_from_verified_update_chains_with_event_key(self):
        from utils.web_feed import build_stories

        third = {"titulo": "DETUVIERON AL CONDUCTOR", "canonical_url": "https://nr/9", "web_url": SITE + "detenido", "published_at_ts": NOW - 60,
                 "event_update": {"of_canonical_url": "https://nr/2", "novedad": "Detuvieron al conductor"}}
        doc = build_stories(WEB + [third], now=NOW, story_key_for=lambda url: "event:abc" if url == SITE + "murio-el-joven" else "")
        [story] = doc["items"]
        self.assertEqual([n["url"] for n in story["notas"]], [SITE + "muerte-cerebral", SITE + "murio-el-joven", SITE + "detenido"])
        self.assertEqual((story["storyKey"], story["titulo"]), ("event:abc", "Detuvieron al conductor"))
        self.assertEqual(story["notas"][2]["novedad"], "Detuvieron al conductor")
        # Sin clave event: (cadenas anteriores al arreglo) no sale.
        self.assertEqual(build_stories(WEB + [third], now=NOW, story_key_for=lambda url: "story:viejo")["items"], [])
        self.assertEqual(build_stories([WEB[2]], now=NOW)["items"], [])

    def test_breaking_note_and_alert(self):
        from utils.web_feed import build_breaking

        flags = {"breaking": {"post_id": "6321", "activated_at": "2026-10-23T19:02:41.369091Z"}}
        lookup = lambda pid: {"titulo": "Detuvieron a dos ladrones", "url": SITE + "robo", "seccion": "policiales"} if pid == "6321" else None  # noqa: E731
        activated = datetime.fromisoformat("2026-10-23T19:02:41+00:00").timestamp()
        alert = {"estado": "activa", "nivel": "amarilla", "vence": "2026-10-24T02:59:59-03:00"}
        doc = build_breaking(flags, alert=alert, now=activated + 3600, lookup=lookup)
        self.assertEqual((doc["nota"]["url"], doc["nota"]["vigente"], doc["nota"]["activado"]), (SITE + "robo", True, "2026-10-23T16:02:41-03:00"))
        self.assertEqual(doc["alerta"]["nivel"], "amarilla")
        late = build_breaking(flags, alert={"estado": "sin_alerta"}, now=activated + 7 * 3600, lookup=lookup)
        self.assertFalse(late["nota"]["vigente"])
        self.assertIsNone(late["alerta"])
        # Una alerta vencida no sale aunque el último dato bueno diga "activa".
        self.assertIsNone(build_breaking({}, alert=alert, now=datetime(2026, 10, 24, 4, tzinfo=AR_TZ).timestamp())["alerta"])
        self.assertEqual(build_breaking({"breaking": None}, alert=None, now=NOW), {"nota": None, "alerta": None})


class ServicesTests(unittest.TestCase):
    def test_each_source_fails_alone_and_keeps_last_good(self):
        from utils.web_feed import build_services

        def boom():
            raise RuntimeError("smn caído")

        previous = {"clima": {"temperatura": 20, "actualizado": "2026-10-23T09:00:00-03:00"}}
        fetchers = {name: (lambda: {"ok": True}) for name in ("dolar", "feriados", "pagos", "sismos", "cortes")}
        fetchers["alerta"] = lambda: {"estado": "activa", "actualizado": "2026-10-23T08:00:00-03:00"}
        doc, failed = build_services(previous, now=datetime(2026, 10, 23, 12, 0, tzinfo=AR_TZ), fetchers={**fetchers, "clima": boom})
        self.assertEqual(failed, ["clima"])
        self.assertEqual(doc["clima"], previous["clima"])
        self.assertTrue(doc["dolar"]["actualizado"].startswith("2026-10-23T12:00"))
        # La hora de emisión de la fuente no se pisa con la de la consulta.
        self.assertEqual(doc["alerta"]["actualizado"], "2026-10-23T08:00:00-03:00")

    def test_weather_block(self):
        from utils.web_feed import weather_block

        weather = SimpleNamespace(station="La Rioja", observed_date="23-octubre-2026", observed_at="12:00", temp=23.8, sky="Cubierto",
                                  humidity=45, wind="Norte  13 km/h",
                                  days=[{"date": "2026-10-22", "min": 1, "max": 2, "rain": 0.0},
                                        {"date": "2026-10-24", "min": 14, "max": 27, "rain": 2.5}])
        block = weather_block(weather, today=date(2026, 10, 23))
        self.assertEqual((block["observado"], block["cielo"], block["viento"]), ("2026-10-23T12:00:00-03:00", "cubierto", "Norte 13 km/h"))
        self.assertEqual(weather_block(SimpleNamespace(**{**weather.__dict__, "wind": "Calma"}), today=date(2026, 10, 23))["viento"], "Calma")
        self.assertEqual(block["pronostico"], [{"fecha": "2026-10-24", "dia": "sábado", "min": 14, "max": 27, "lluvia": "2,5 mm"}])

    def test_blocks(self):
        from utils.web_feed import alert_block, cuts_block, dollar_block, payments_block, quakes_block

        self.assertEqual(alert_block({"status": "none"})["estado"], "sin_alerta")
        alert = alert_block({"status": "active", "kind": "aviso", "level": "naranja", "phenomenon": "tormentas", "zones": ["Capital"],
                             "expires": "2026-10-24T02:59:59-03:00", "sent": "2026-10-23T10:00:00-03:00", "description": "Tormentas\nfuertes."})
        self.assertEqual((alert["tipo"], alert["nivel"], alert["zonas"], alert["actualizado"], alert["descripcion"]),
                         ("aviso a muy corto plazo", "naranja", ["Capital"], "2026-10-23T10:00:00-03:00", "Tormentas fuertes."))
        dollar = dollar_block([{"house": "oficial", "name": "Oficial", "buy": 1500, "sell": 1550, "updated_at": "2026-10-23T15:50:00.000Z"},
                               {"house": "blue", "name": "Blue", "buy": None, "sell": 1565, "updated_at": ""}])
        self.assertEqual(dollar["brecha_blue_pct"], 0.97)
        self.assertEqual(dollar["cotizaciones"], [{"casa": "oficial", "nombre": "Oficial", "compra": 1500, "venta": 1550, "actualizado": "2026-10-23T12:50:00-03:00"}])
        pays = payments_block([{"date": "2026-10-23", "concept": "Quincena", "groups": [{"title": "Banco Rioja", "items": ["Salud"]}], "url": ""},
                               {"date": "2026-10-20", "concept": "Vieja"}], date(2026, 10, 23))
        self.assertEqual([p["concepto"] for p in pays["hoy"]], ["Quincena"])
        self.assertEqual((pays["proximos"][0]["dia"], pays["proximos"][0]["url"]), ("viernes", None))
        quakes = quakes_block([
            {"id": "1", "at": "2026-10-23T13:25:57+00:00", "magnitude": 2.7, "depth_km": 130, "province": "LA RIOJA", "status": "revised"},
            {"id": "3", "at": "2026-10-23T11:00:00+00:00", "magnitude": 2.1, "depth_km": 100, "province": "LA RIOJA", "status": "automatic"},
            {"id": "2", "at": "2026-10-23T13:00:00+00:00", "magnitude": 4.0, "depth_km": 10, "province": "SAN JUAN", "status": "revised"},
        ], {"1": {"places": ["35 km al O de Cerro Bonete"]}}, now=datetime(2026, 10, 23, 12, 0, tzinfo=AR_TZ))
        self.assertEqual([(q["id"], q["lugar"], q["estado"]) for q in quakes["ultimos_7_dias"]],
                         [("1", "35 km al O de Cerro Bonete", "revisado"), ("3", "La Rioja", "automático")])
        with mock.patch("utils.service_data.notice_zone", return_value=""):
            cuts = cuts_block([{"service": "luz", "title": "CORTE DE LUZ PROGRAMADO", "url": SITE + "corte", "published_at": "2026-10-23T14:00:00.5Z"}])
        self.assertEqual(cuts["avisos"], [{"servicio": "luz", "titulo": "Corte de luz programado", "zona": None, "url": SITE + "corte",
                                           "publicado": "2026-10-23T11:00:00-03:00"}])

    def test_cap_sent_is_read(self):
        from utils.service_data import parse_cap

        xml = ('<alert xmlns="urn:oasis:names:tc:emergency:cap:1.2"><sent>2026-10-23T10:00:00-03:00</sent><status>Actual</status>'
               '<msgType>Alert</msgType><info><event>Viento</event><severity>Moderate</severity><headline>Alerta amarilla por viento</headline>'
               '<expires>2026-10-24T02:59:59-03:00</expires><area><areaDesc>LA RIOJA: VINCHINA</areaDesc></area></info></alert>')
        self.assertEqual(parse_cap(xml)["sent"], "2026-10-23T10:00:00-03:00")


class ValidationTests(unittest.TestCase):
    def test_built_documents_pass_the_web_rules(self):
        from utils import web_feed

        third = {"titulo": "DETUVIERON AL CONDUCTOR", "canonical_url": "https://nr/9", "web_url": SITE + "detenido", "published_at_ts": NOW - 60,
                 "event_update": {"of_canonical_url": "https://nr/2", "novedad": "Detuvieron al conductor"}}
        web = WEB + [third]
        docs = {
            "mas-visto": web_feed.build_most_viewed(INSIGHTS, IG_POSTED, web, {"m2": {"permalink": "https://www.instagram.com/p/XXXXX/"}}, now=NOW),
            "actualizaciones": web_feed.build_updates(web, now=NOW),
            "historias": web_feed.build_stories(web, now=NOW, story_key_for=lambda url: "event:abc"),
        }
        for name, doc in docs.items():
            with self.subTest(name=name):
                self.assertEqual(web_feed.validate(name, {"version": 1, "actualizado": "2026-10-23T12:00:00-03:00", **doc}, now=MOMENT), ([], []))

    def test_rejections(self):
        from utils.web_feed import validate

        self.assertIn("actualizado sin zona", validate("videos", {"version": 1, "actualizado": "2026-10-23T12:00:00"}, now=MOMENT)[0])
        self.assertIn("version", validate("videos", {"version": 2, "actualizado": "2026-10-23T12:00:00-03:00"}, now=MOMENT)[0])
        future = MOMENT.replace(year=2027).isoformat()
        self.assertIn("actualizado en el futuro", validate("videos", {"version": 1, "actualizado": future}, now=MOMENT)[0])
        _, dropped = validate("actualizaciones", {"version": 1, "actualizado": MOMENT.isoformat(), "items": [
            {"nota": {"titulo": "MAYÚSCULAS", "url": SITE + "a"}, "actualiza": {"titulo": "Nueva", "url": SITE + "b"}},
            {"nota": {"titulo": "Vieja", "url": "https://otro.com/a"}, "actualiza": {"titulo": "Nueva", "url": SITE + "b"}},
        ]}, now=MOMENT)
        self.assertEqual(len(dropped), 2)


class PublishTests(unittest.TestCase):
    def test_uploads_each_valid_document_and_index(self):
        from utils import web_feed

        seen = {}

        def uploader(path, key, content_type, *, cache_control):
            with open(path, encoding="utf-8") as handle:
                seen[key] = json.load(handle)
            self.assertEqual((content_type, cache_control), ("application/json; charset=utf-8", "public, max-age=300"))
            return OperationResult(StageStatus.SUCCESS if key != "feed/v1/videos.json" else StageStatus.DEGRADED)

        stamp = MOMENT.isoformat()
        docs = {"mas-visto": {"version": 1, "actualizado": stamp}, "videos": {"version": 1, "actualizado": stamp},
                "historias": {"version": 1, "actualizado": "sin zona"}}
        with mock.patch.dict(os.environ, {"R2_PUBLIC_URL": "https://media.lavozriojana.com"}):
            ok, bad = web_feed.publish(docs, uploader=uploader, now=MOMENT)
        self.assertEqual((ok, bad), (["mas-visto"], ["videos", "historias"]))
        # El inválido no se sube: queda el anterior en R2.
        self.assertNotIn("feed/v1/historias.json", seen)
        self.assertEqual(seen["feed/v1/index.json"]["feeds"]["mas-visto"], "https://media.lavozriojana.com/feed/v1/mas-visto.json")

    def test_stage_disabled_by_default(self):
        from meta import run_web_feed

        with mock.patch.dict(os.environ, {"WEB_FEED_ENABLED": "false"}):
            self.assertEqual(run_web_feed.main().status, StageStatus.NO_WORK)

    def test_collect_writes_only_its_own_state(self):
        from utils import web_feed

        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"LVR_DATA_DIR": tmp}), \
                mock.patch.object(web_feed, "STATE_PATH", os.path.join(tmp, "web_feed_state.json")), \
                mock.patch.object(web_feed, "build_services", return_value=({"dolar": {"ok": True}, "alerta": {"estado": "sin_alerta"}}, [])):
            for name, value in (("ig_media_insights.json", {"media": INSIGHTS}), ("ig_posted.json", {"posted": IG_POSTED}),
                                ("noticias_web_publicadas.json", WEB)):
                with open(os.path.join(tmp, name), "w", encoding="utf-8") as handle:
                    json.dump(value, handle)
            docs, failed = web_feed.collect(now=MOMENT, fetch_links=False)
            self.assertEqual(sorted(docs), ["actualizaciones", "historias", "mas-visto", "servicios", "ultimo-momento", "videos"])
            self.assertEqual(docs["servicios"]["dolar"], {"ok": True})
            self.assertIsNone(docs["servicios"]["alerta"])
            with open(os.path.join(tmp, "web_feed_state.json"), encoding="utf-8") as handle:
                self.assertEqual(json.load(handle)["servicios"]["dolar"], {"ok": True})


if __name__ == "__main__":
    unittest.main()
