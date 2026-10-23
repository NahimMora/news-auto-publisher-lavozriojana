"""Formatos sociales (2026-10-18): datos de servicio, historias, carrusel de
la mañana, resumen semanal, seguimiento, respuestas a comentarios, reporte
por correo y fuentes oficiales JSON. Todo con mocks: sin red ni publicación."""
from __future__ import annotations

import io
import json
import os
import tempfile
import time
import unittest
import zipfile
from datetime import date, datetime
from unittest import mock

from utils.operation_result import OperationResult
from utils.social_time import AR_TZ
from utils.stage_result import StageStatus


def _cap(event: str, severity: str, headline: str, polygon: str, description: str = "", *, area: str = "", expires: str = "2026-10-24T02:59:59-03:00") -> str:
    """XML CAP mínimo con la forma del feed del SMN."""
    return (
        '<alert xmlns="urn:oasis:names:tc:emergency:cap:1.2"><status>Actual</status><msgType>Alert</msgType><info>'
        f"<event>{event}</event><severity>{severity}</severity><headline>{headline}</headline><expires>{expires}</expires>"
        f"<description>{description}</description><area><areaDesc>{area}</areaDesc><polygon>{polygon}</polygon></area></info></alert>"
    )

TIEPRE = (
    " Chamical;18-octubre-2026;12:00;Cubierto;20 km;16.8;No se calcula; 66;Noreste  9;965.7 / \n"
    " La Rioja;18-octubre-2026;12:00;Nublado;20 km;17.8;No se calcula; 68;Noreste  1;967.4 / \n"
)
PRON5D = """ LA_RIOJA_AERO
 ================================================================================================
      FECHA *          TEMPERATURA      VIENTO      PRECIPITACION(mm)
                                     (DIR | KM/H)
 ================================================================================================
  18/OCT/2026 06Hs.        12.8       205 |  10         0.0
  18/OCT/2026 15Hs.        21.6        74 |   7         0.0
  19/OCT/2026 06Hs.        14.6       229 |   7         0.2
  19/OCT/2026 15Hs.        24.0        86 |  26         0.3
 ================================================================================================
 MENDOZA_AERO
 ================================================================================================
  18/OCT/2026 06Hs.         5.0       205 |  10         0.0
"""


def _zip(text: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("datos.txt", text.encode("latin-1"))
    return buffer.getvalue()


class ServiceDataTests(unittest.TestCase):
    def test_present_weather_and_forecast(self):
        from utils import service_data as sd

        present = sd.parse_present_weather(TIEPRE, "La Rioja")
        self.assertEqual((present["temp"], present["sky"], present["humidity"], present["observed_at"]), (17.8, "Nublado", 68, "12:00"))
        days = sd.parse_forecast(PRON5D, "LA_RIOJA_AERO")
        self.assertEqual([(d["label"], d["min"], d["max"], d["rain"]) for d in days], [("Dom", 12.8, 21.6, 0.0), ("Lun", 14.6, 24.0, 0.5)])

    def test_fetch_weather_reads_open_data_zips(self):
        from utils import service_data as sd

        def fetcher(url):
            text = TIEPRE if "tiepre" in url else PRON5D
            return mock.Mock(status_code=200, content=_zip(text))

        weather = sd.fetch_weather(fetcher=fetcher)
        self.assertEqual(weather.temp, 17.8)
        self.assertEqual(len(weather.days), 2)

    def test_alerts_from_cap_feed(self):
        from utils import service_data as sd

        base = "https://ssl.smn.gob.ar/feeds/CAP/xml_generados/"
        index = f"<rss><item><link>{base}cordillera.xml</link></item><item><link>{base}misiones.xml</link></item><item><link>{base}vencida.xml</link></item></rss>"
        docs = {
            # Polígono sobre la cordillera de Vinchina (como "Viento_Cordillera" del SMN).
            "cordillera.xml": _cap("Viento", "Moderate", "Viento", "-28.68,-69.6 -27.7,-69.6 -27.7,-68.3 -28.68,-68.3 -28.68,-69.6",
                                   "El área será afectada por vientos del sector oeste con ráfagas que pueden superar los 100 km/h. Otra oración."),
            "misiones.xml": _cap("TORMENTAS FUERTES", "Severe", "AVISO NARANJA POR TORMENTAS FUERTES", "-26.9,-54.4 -27.1,-53.8 -25.6,-53.8 -26.9,-54.4",
                                 area="MISIONES: GUARANI - SAN PEDRO. "),
            "vencida.xml": _cap("Tormentas", "Severe", "Tormentas", "-28,-70 -32,-70 -32,-65 -28,-65 -28,-70", expires="2026-10-20T00:00:00-03:00"),
        }
        calls = []

        def fetcher(url):
            calls.append(url)
            body = index if url == sd.SMN_CAP_INDEX else docs[url.rsplit("/", 1)[-1]]
            return mock.Mock(status_code=200, content=body.encode("utf-8"))

        cache: dict = {}
        when = datetime(2026, 10, 23, 12, 0, tzinfo=AR_TZ)
        alerts = sd.fetch_alerts(fetcher=fetcher, cache=cache, now=when)
        self.assertEqual((alerts["status"], alerts["level"], alerts["phenomenon"], alerts["kind"]), ("active", "amarilla", "viento", "alerta"))
        self.assertEqual(alerts["zones"], ["Vinchina"])
        # Segunda pasada: sólo el índice, los XML salen de la caché.
        calls.clear()
        sd.fetch_alerts(fetcher=fetcher, cache=cache, now=when)
        self.assertEqual(calls, [sd.SMN_CAP_INDEX])
        # Sin nada para La Rioja (o ya vencido): none.
        cache.clear()
        self.assertEqual(sd.fetch_alerts(fetcher=fetcher, cache=cache, now=datetime(2026, 10, 25, 12, 0, tzinfo=AR_TZ))["status"], "none")

    def test_cap_departments_from_text_and_cancel(self):
        from utils import service_data as sd

        aviso = sd.parse_cap(_cap("VIENTO ZONDA", "Severe", "AVISO NARANJA POR VIENTO ZONDA", "-26,-54 -27,-53 -25,-53 -26,-54",
                                  area="CATAMARCA: TINOGASTA. LA RIOJA: CAPITAL - GRAL ANGEL V. PENALOZA - CNEL FELIPE VARELA. "))
        self.assertEqual((aviso["kind"], aviso["level"]), ("aviso", "naranja"))
        self.assertEqual(aviso["departments"], ["Capital", "General Ángel Vicente Peñaloza", "Felipe Varela"])
        cancel = sd.parse_cap(_cap("Tormentas", "Moderate", "Tormentas", "-28,-70 -32,-70 -32,-65 -28,-70").replace("<msgType>Alert", "<msgType>Cancel"))
        self.assertTrue(cancel["cancel"])
        self.assertIsNone(sd.parse_cap("<html>no es CAP"))

    def test_alert_story_uses_smn_text_and_zones(self):
        from utils.social_formats import alert_story

        props = alert_story({"status": "active", "level": "amarilla", "phenomenon": "viento", "kind": "alerta", "zones": ["Vinchina"],
                             "expires": "2026-10-24T02:59:59-03:00", "description": "El área será afectada por vientos del oeste. Otra."})
        self.assertEqual(props["titulo"], "Alerta amarilla por viento")
        self.assertEqual(props["zones"], ["Vinchina"])
        self.assertEqual(props["body"], "El área será afectada por vientos del oeste.")
        self.assertTrue(props["timeLabel"].startswith("Vigente hasta las 03:00"))

    def test_dollar_and_money(self):
        from utils import service_data as sd

        rows = sd.parse_dollar([
            {"casa": "oficial", "compra": 1485, "venta": 1535, "fechaActualizacion": "x"},
            {"casa": "bolsa", "compra": 1534.3, "venta": 1542.5},
            {"casa": "tarjeta", "compra": None, "venta": 1995},
        ])
        self.assertEqual([r["name"] for r in rows], ["Oficial", "MEP"])
        self.assertEqual((sd.money(1535), sd.money(1542.5), sd.money(1618.4)), ("1.535", "1.542,50", "1.618,40"))

    def test_official_holidays_skip_regional(self):
        from utils import service_data as sd

        payload = {"mainEntity": {"itemListElement": [
            {"item": {"name": "Visita de Su Santidad el Papa León XIV", "additionalProperty": {"value": "inamovible"}, "startDate": "2026-11-09"}},
            {"item": {"name": "Visita (<a href='/x'>feriado en Córdoba</a>)", "additionalProperty": {"value": "especial"}, "startDate": "2026-11-10"}},
            {"item": {"name": "Día de la Soberanía Nacional (20/11)", "additionalProperty": {"value": "trasladable"}, "startDate": "2026-11-23"}},
        ]}}
        holidays = sd.parse_holidays(payload)
        self.assertEqual([h["date"] for h in holidays], ["2026-11-09", "2026-11-23"])
        self.assertEqual(holidays[1]["name"], "Día de la Soberanía Nacional")
        rows = sd.holiday_story_rows(holidays)
        self.assertEqual((rows[0]["day"], rows[0]["month"], rows[0]["weekday"]), ("9", "Nov", "Lunes"))

    def test_notice_classification(self):
        from utils.service_data import classify_notice as c

        self.assertEqual(c("CORTE DE LUZ PROGRAMADO EN EL BARRIO VIAL PARA ESTE MIÉRCOLES"), "luz")
        self.assertEqual(c("EDELAR INFORMÓ UN CORTE DE URGENCIA EN EL SERVICIO ELÉCTRICO DEL PARAJE SAN BERNARDO"), "luz")
        self.assertEqual(c("AGUAS RIOJANAS INFORMA CORTE DEL SERVICIO EN BARRIO CENTRO"), "agua")
        self.assertEqual(c("DESPEJARON LA RUTA 76 Y YA SE PUEDE CRUZAR A CHILE POR JAGÜEL"), "rutas")
        self.assertEqual(c("OBRAS HÍDRICAS PARA MEJORAR EL SUMINISTRO DE AGUA EN AMBIL"), "")
        self.assertEqual(c("SINIESTRO VIAL EN RUTA 9: AUTO TERMINÓ EN UNA ZANJA"), "")
        self.assertEqual(c("INAUGURARON NUEVAS LUMINARIAS EN LA AVENIDA MADRE TERESA DE CALCUTA"), "")

    def test_notice_zone(self):
        from utils.service_data import notice_zone as z

        self.assertEqual(z("CORTE DE LUZ PROGRAMADO EN EL BARRIO VIAL PARA ESTE MIÉRCOLES"), "Barrio Vial")
        self.assertEqual(z("CORTE DE LUZ PROGRAMADO PARA ESTE VIERNES EN ALPASINCHE"), "Alpasinche")
        self.assertEqual(z("EDELAR INFORMÓ UN CORTE DE URGENCIA EN EL SERVICIO ELÉCTRICO DEL PARAJE SAN BERNARDO"), "Paraje San Bernardo")
        self.assertEqual(z("CORTES DE LUZ PROGRAMADOS EN CAPITAL, SANAGASTA Y LLANOS SUR"), "Capital, Sanagasta y Llanos Sur")
        self.assertEqual(z("CONTROLARON UN INCENDIO FORESTAL EN PAGANCILLO QUE DEJÓ SIN LUZ A DOS BARRIOS"), "Pagancillo")
        self.assertEqual(z("CORTE TOTAL EN LA RUTA NACIONAL 40 POR MAL TIEMPO"), "Ruta Nacional 40")
        self.assertEqual(z("CERRADA RUTA NACIONAL 40 EN LA CUESTA DE MIRANDA"), "Ruta Nacional 40 · Cuesta de Miranda")
        # Alcance amplio: no nombra barrio porque afecta a toda una zona.
        self.assertEqual(z("CORTE DE AGUA ESTE MIÉRCOLES EN GRAN PARTE DE LA CAPITAL"), "Gran parte de la Capital")
        self.assertEqual(z("CORTES DE LUZ EN LA CAPITAL POR FALLAS TÉCNICAS", "Afectan a diversos sectores de la ciudad."), "Varios sectores de la Capital")
        # El lugar sólo en la bajada.
        self.assertEqual(z("CORTE DE LUZ PROGRAMADO PARA ESTE JUEVES", "EDELaR trabajará en la localidad de Aminga."), "Localidad de Aminga")
        # Sin dato: vacío, la historia dice "No especificada".
        self.assertEqual(z("CORTE DE LUZ PROGRAMADO PARA ESTE MARTES", "EDELaR informó tareas de mantenimiento."), "")
        self.assertEqual(z("SE REHABILITA EL TRÁNSITO EN RUTAS CLAVE TRAS EL MAL TIEMPO"), "")

    def test_notice_story_zone_and_title_case(self):
        from utils.social_formats import notice_story

        props = notice_story({"service": "luz", "title": "CORTE DE SUMINISTRO ELÉCTRICO EN EL BARRIO JOAQUÍN V. GONZÁLEZ POR TAREAS", "excerpt": "", "url": "u", "published_at": ""})
        self.assertEqual(props["place"], "Barrio Joaquín V. González")
        self.assertEqual(props["titulo"], "Corte de suministro eléctrico en el barrio Joaquín V. González por tareas")
        props = notice_story({"service": "agua", "title": "CORTE DE AGUA EN GRAN PARTE DE LA CAPITAL", "excerpt": "", "url": "u", "published_at": ""})
        self.assertEqual(props["titulo"], "Corte de agua en gran parte de la capital")
        self.assertEqual(notice_story({"service": "luz", "title": "CORTE DE LUZ PARA ESTE MARTES", "excerpt": "", "url": "u", "published_at": ""})["place"], "")

    def test_cuts_outside_la_rioja_do_not_count(self):
        from utils.service_data import is_riojan_notice as r

        self.assertTrue(r("CORTE DE LUZ PROGRAMADO EN EL BARRIO VIAL", "EDELaR informó una interrupción."))
        self.assertTrue(r("CORTE DE AGUA EN GRAN PARTE DE LA CAPITAL", "Trabajos en el Acueducto Ramal Oeste."))
        self.assertFalse(r("APAGÓN MASIVO EN EL AMBA: MILES DE USUARIOS SIN LUZ", "Cortes en barrios porteños y el conurbano."))
        self.assertFalse(r("CORTE DE LUZ EN CAPITAL FEDERAL", "Miles de usuarios afectados."))

    def test_recent_notices_skip_cuts_outside_la_rioja(self):
        import sqlite3
        import tempfile

        from utils.service_data import recent_notices

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "archive.sqlite3")
            conn = sqlite3.connect(path)
            conn.execute("create table archive_articles (title text, excerpt text, canonical_url text, published_at text)")
            conn.executemany("insert into archive_articles values (?, ?, ?, ?)", [
                ("CORTE DE LUZ PROGRAMADO EN EL BARRIO VIAL", "EDELaR informó una interrupción.", "https://x/1", "2026-11-02T12:00:00"),
                ("APAGÓN MASIVO EN EL AMBA: MILES DE USUARIOS SIN LUZ", "Cortes en barrios porteños.", "https://x/2", "2026-11-02T12:00:00"),
            ])
            conn.commit()
            conn.close()
            found = recent_notices(hours=24, now=datetime(2026, 11, 2, 10, 0, tzinfo=AR_TZ), db_path=path)
        self.assertEqual([n["url"] for n in found], ["https://x/1"])


class OfficialJsonSourcesTests(unittest.TestCase):
    def test_wordpress(self):
        from sources.strategies.json_api import parse_wordpress_json

        text = json.dumps([{"date": "2026-10-16T13:26:44", "link": "https://hacienda.larioja.gob.ar/quincena/", "title": {"rendered": "QUINCENA OCTUBRE &#8211; LUNES 19/10"}}])
        items = parse_wordpress_json(text, source_id="hacienda_larioja")
        self.assertEqual(items[0].title, "QUINCENA OCTUBRE – LUNES 19/10")
        self.assertEqual(parse_wordpress_json("<html>", source_id="x"), [])

    def test_neotec(self):
        from sources.strategies.json_api import parse_neotec_json

        text = json.dumps({"estado": 1, "datos": [{"idnoticia": "4167", "titulo": "Comienza la preventa de entradas para la Chaya 2027", "fecha_seteada": "15/10/2026", "copete": "Será el lunes."}]})
        items = parse_neotec_json(text, source_id="gobierno_larioja")
        self.assertEqual(items[0].url, "https://larioja.gob.ar/noticias/noticia.php?idnoticia=4167")
        self.assertEqual(items[0].published_at, "15/10/2026")
        self.assertEqual(parse_neotec_json(json.dumps({"estado": 0}), source_id="x"), [])

    def test_registry_uses_new_strategies(self):
        from sources.registry import get_source

        self.assertEqual(get_source("hacienda_larioja").fetch_strategy, "wordpress_json")
        gobierno = get_source("gobierno_larioja")
        self.assertEqual((gobierno.fetch_strategy, gobierno.host), ("neotec_json", "larioja.neotec.com.ar"))
        self.assertFalse(get_source("smn_news").enabled)


class _TempState(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def path(self, name: str) -> str:
        return os.path.join(self.tmp.name, name)


class StoryPublisherTests(_TempState):
    def setUp(self):
        super().setUp()
        from utils import story_publisher as sp

        self.sp = sp
        patcher = mock.patch.object(sp, "STATE_PATH", self.path("stories.json"))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_candidates_order_and_lookback(self):
        now = time.time()
        stamp = lambda hours: datetime.fromtimestamp(now - hours * 3600, AR_TZ).strftime("%Y-%m-%dT%H:%M:%S%z")
        media = [
            {"id": "1", "media_type": "IMAGE", "media_product_type": "FEED", "media_url": "https://cdn/1.jpg", "timestamp": stamp(1)},
            {"id": "2", "media_type": "VIDEO", "media_product_type": "REELS", "thumbnail_url": "https://cdn/2.jpg", "timestamp": stamp(2)},
            {"id": "3", "media_type": "IMAGE", "media_product_type": "FEED", "media_url": "https://cdn/3.jpg", "timestamp": stamp(3)},
            {"id": "4", "media_type": "IMAGE", "media_product_type": "FEED", "media_url": "https://cdn/4.jpg", "timestamp": stamp(9)},
            {"id": "5", "media_type": "CAROUSEL_ALBUM", "media_product_type": "FEED", "timestamp": stamp(1), "children": {"data": [{"media_type": "VIDEO"}, {"media_type": "IMAGE", "media_url": "https://cdn/5b.jpg"}]}},
        ]
        index = {"3": {"titulo": "Último momento: choque en la ruta 38", "seccion": "policiales", "source": "nuevarioja_policiales"}, "2": {"source": "tiempopopular_locales", "seccion": "sociedad"}}
        with mock.patch.object(self.sp, "_posted_index", return_value=index):
            out = self.sp.post_story_candidates(media, lookback_hours=6, state={"posted": {"post:1": {"ig_id": "s1"}}}, now=now)
        ids = [c["media_id"] for c in out]
        self.assertEqual(ids, ["3", "2", "5"])  # último momento, local, resto
        self.assertTrue(out[0]["breaking"])
        self.assertTrue(out[0]["explicit_breaking"])
        with mock.patch.object(self.sp, "download_image", return_value="x.jpg"):
            self.assertEqual(self.sp.story_for_candidate(out[0])[0]["kind"], "breaking")
            # Urgencia "amplia" del feed (p. ej. "detenidos") ordena primero pero no rotula.
            self.assertEqual(self.sp.story_for_candidate({**out[0], "explicit_breaking": False})[0]["kind"], "post")
        self.assertNotIn("1", ids)  # ya tiene historia
        self.assertNotIn("4", ids)  # fuera de la ventana
        self.assertEqual(next(c for c in out if c["media_id"] == "5")["image_url"], "https://cdn/5b.jpg")
        self.assertTrue(next(c for c in out if c["media_id"] == "2")["reel"])

    def test_publish_same_image_to_both_networks_and_records(self):
        with mock.patch("utils.r2_storage.is_configured", return_value=True), mock.patch(
            "utils.r2_storage.upload_temp", return_value=("https://r2/s.jpg", "tmp/story/s.jpg")
        ), mock.patch("utils.r2_storage.delete") as delete, mock.patch(
            "meta.ig_client.post_story_image", return_value=OperationResult(StageStatus.SUCCESS, external_id="ig1")
        ) as ig, mock.patch("meta.fb_client.post_photo_story", return_value=OperationResult(StageStatus.SUCCESS, external_id="fb1")) as fb:
            outcome = self.sp.publish_story("post:9", b"jpeg", instagram=True, facebook=True, meta={"kind": "post"})
            again = self.sp.publish_story("post:9", b"jpeg", instagram=True, facebook=True)
        self.assertEqual(outcome, {"ig": "success", "fb": "success"})
        self.assertEqual(again, {"ig": "skipped", "fb": "skipped"})
        ig.assert_called_once_with("https://r2/s.jpg")
        fb.assert_called_once_with(b"jpeg")
        delete.assert_called_once_with("tmp/story/s.jpg")
        self.assertTrue(self.sp.already_done("post:9"))
        self.assertEqual(self.sp.stories_today(), 1)

    def test_ambiguous_instagram_is_not_retried_nor_sent_to_facebook(self):
        ambiguous = OperationResult(StageStatus.DEGRADED, error_type="network_error", details={"publication_outcome": "unknown"})
        with mock.patch("utils.r2_storage.is_configured", return_value=True), mock.patch(
            "utils.r2_storage.upload_temp", return_value=("https://r2/s.jpg", "k")
        ), mock.patch("utils.r2_storage.delete"), mock.patch("meta.ig_client.post_story_image", return_value=ambiguous), mock.patch(
            "meta.fb_client.post_photo_story"
        ) as fb:
            outcome = self.sp.publish_story("svc:weather:2026-10-18", b"j", instagram=True, facebook=True)
        self.assertEqual(outcome["ig"], "ambiguous")
        fb.assert_not_called()
        self.assertTrue(self.sp.already_done("svc:weather:2026-10-18"))

    def test_props_are_complete(self):
        props = self.sp.story_props(kind="dollar", rows=[{"name": "Oficial", "sell": "1.535"}])
        self.assertEqual(set(self.sp.STORY_DEFAULTS) - set(props), set())
        self.assertEqual(props["kind"], "dollar")


class ServiceStoriesScheduleTests(_TempState):
    def setUp(self):
        super().setUp()
        from utils import social_formats as sf

        self.sf = sf
        patcher = mock.patch.object(sf, "STATE_PATH", self.path("formats.json"))
        patcher.start()
        self.addCleanup(patcher.stop)

    def _run(self, when: datetime, *, alerts=None, rows=None, holidays=None, notices=()):
        from utils import service_data as sd

        weather = sd.Weather(station="La Rioja", observed_at="09:00", observed_date="x", temp=15.2, sky="Despejado", humidity=40, wind="Norte 10", days=[{"date": when.date().isoformat(), "label": "Lun", "min": 10, "max": 25, "rain": 0}])
        with mock.patch.object(sd, "fetch_alerts", return_value=alerts or {"status": "none"}), mock.patch.object(sd, "fetch_weather", return_value=weather), mock.patch.object(
            sd, "fetch_dollar", return_value=rows or []
        ), mock.patch.object(sd, "upcoming_holidays", return_value=holidays or []), mock.patch.object(sd, "recent_notices", return_value=list(notices)):
            return self.sf.due_service_stories(when)

    def test_weather_only_in_the_morning(self):
        monday_9 = datetime(2026, 10, 19, 9, 10, tzinfo=AR_TZ)
        keys = [k for k, _, _ in self._run(monday_9)]
        self.assertIn("svc:weather:2026-10-19", keys)
        keys = [k for k, _, _ in self._run(datetime(2026, 10, 19, 14, 0, tzinfo=AR_TZ))]
        self.assertNotIn("svc:weather:2026-10-19", keys)

    def test_dollar_only_on_change_in_its_windows(self):
        rows = [{"house": "oficial", "name": "Oficial", "buy": 1485.0, "sell": 1535.0}]
        at_11 = datetime(2026, 10, 19, 11, 30, tzinfo=AR_TZ)
        jobs = self._run(at_11, rows=rows)
        dollar = [j for j in jobs if j[0].startswith("svc:dollar")]
        self.assertEqual(len(dollar), 1)
        self.sf.remember_dollar({"oficial": 1535.0})
        self.assertFalse([j for j in self._run(at_11, rows=rows) if j[0].startswith("svc:dollar")])
        saturday = datetime(2026, 10, 24, 11, 30, tzinfo=AR_TZ)
        self.assertFalse([j for j in self._run(saturday, rows=[{**rows[0], "sell": 1600.0}]) if j[0].startswith("svc:dollar")])

    def test_alert_holiday_and_notice(self):
        when = datetime(2026, 11, 2, 10, 0, tzinfo=AR_TZ)
        jobs = self._run(
            when,
            alerts={"status": "active", "level": "naranja", "phenomenon": "tormentas"},
            holidays=[{"date": "2026-11-09", "name": "Feriado", "kind": "inamovible"}],
            notices=[{"service": "luz", "title": "CORTE DE LUZ EN EL CENTRO", "excerpt": "Por obras.", "url": "https://lavozriojana.com/n/1", "published_at": "2026-11-02T12:00:00Z"}],
        )
        kinds = {props["kind"] for _, props, _ in jobs}
        self.assertTrue({"alert", "holidays", "notice", "weather"} <= kinds)
        alert = next(p for _, p, _ in jobs if p["kind"] == "alert")
        self.assertEqual(alert["titulo"], "Alerta naranja por tormentas")
        weather = next(p for _, p, _ in jobs if p["kind"] == "weather")
        self.assertIn("naranja", weather["alertSummary"])
        notice = next(p for _, p, _ in jobs if p["kind"] == "notice")
        self.assertEqual(notice["titulo"], "Corte de luz en el Centro")
        self.assertEqual(notice["place"], "Centro")


class BriefAndRecapTests(_TempState):
    def setUp(self):
        super().setUp()
        from utils import social_formats as sf

        self.sf = sf
        patcher = mock.patch.object(sf, "STATE_PATH", self.path("formats.json"))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_same_topic(self):
        a = {"title": "Miren Algañarás tomó una drástica decisión tras las acusaciones de Valentín Yankelevich"}
        b = {"title": "El apoyo incondicional de Valentina Pastore a Valentín Yankelevich"}
        c = {"title": "Tensión en las hornallas de MasterChef"}
        self.assertTrue(self.sf.same_topic(a, b))
        self.assertFalse(self.sf.same_topic(a, c))
        self.assertTrue(self.sf.same_topic({"title": "x", "story_key": "s1"}, {"title": "y", "story_key": "s1"}))

    def test_brief_selection_prefers_local_and_skips_sensitive(self):
        now = time.time()
        records = [
            {"titulo": "QUINTELA ENCABEZÓ LOS ACTOS", "source": "nuevarioja_politica", "web_url": "https://lavozriojana.com/a", "published_at_ts": now - 3600},
            {"titulo": "CHARLOTTE CANIGGIA Y UNA EXPERIENCIA", "source": "paparazzi", "web_url": "https://lavozriojana.com/b", "published_at_ts": now - 1800},
            {"titulo": "INVESTIGAN ABUSO EN UNA ESCUELA", "source": "nuevarioja_policiales", "web_url": "https://lavozriojana.com/c", "published_at_ts": now - 600},
            {"titulo": "BOMBEROS EN EL FAMATINA", "source": "nuevarioja_sociedad", "web_url": "https://lavozriojana.com/d", "published_at_ts": now - 7200},
            {"titulo": "VIEJA", "source": "nuevarioja_sociedad", "web_url": "https://lavozriojana.com/e", "published_at_ts": now - 30 * 3600},
        ]
        pages = {u: {"title": t, "photo_url": f"https://media/{u[-1]}.webp", "description": "Bajada."} for u, t in (
            ("https://lavozriojana.com/a", "Quintela encabezó los actos"), ("https://lavozriojana.com/b", "Charlotte Caniggia y una experiencia"),
            ("https://lavozriojana.com/d", "Bomberos en el Famatina"))}
        with mock.patch.object(self.sf, "_published_web", side_effect=lambda hours, now: [r for r in records if now - r["published_at_ts"] <= hours * 3600]), mock.patch.object(
            self.sf, "_archive_rows", return_value={"https://lavozriojana.com/b": {"category": "espectaculos"}}
        ):
            items = self.sf.select_brief_items(now=now, fetch=lambda url: pages.get(url))
        self.assertEqual([i["title"] for i in items], ["Quintela encabezó los actos", "Bomberos en el Famatina", "Charlotte Caniggia y una experiencia"])

    def test_caption_and_services(self):
        from utils import service_data as sd

        today = date(2026, 10, 19)
        weather = sd.Weather("La Rioja", "07:00", "x", 12.0, "Nublado", 60, "Sur 5", [{"date": "2026-10-19", "label": "Lun", "min": 12.6, "max": 24.9, "rain": 0}])
        dollar = [{"house": "oficial", "name": "Oficial", "buy": 1485.0, "sell": 1535.0}, {"house": "blue", "name": "Blue", "buy": 1535.0, "sell": 1555.0}]
        caption = self.sf.brief_caption([{"title": "Uno"}, {"title": "Dos"}, {"title": "Tres"}], today, weather, dollar)
        self.assertIn("lunes 19 de octubre", caption)
        self.assertIn("1️⃣ Uno", caption)
        self.assertIn("mínima de 13° y máxima de 25°", caption)
        self.assertIn("Dólar oficial $1.535 · blue $1.555", caption)
        rows = self.sf.brief_services(weather, {"status": "none"}, dollar, [{"date": "2026-11-09", "name": "F", "kind": "inamovible"}], [], today)
        self.assertEqual([r["label"] for r in rows], ["Clima", "Dólar oficial", "Dólar blue", "Próximo feriado", "Cortes anunciados"])
        self.assertEqual(rows[3]["note"], "Faltan 21 días")

    def test_brief_due_once_per_day(self):
        at_8 = datetime(2026, 10, 19, 8, 5, tzinfo=AR_TZ)
        self.assertTrue(self.sf.brief_due(at_8))
        self.assertFalse(self.sf.brief_due(datetime(2026, 10, 19, 12, 0, tzinfo=AR_TZ)))
        self.sf._mark_day("brief", "2026-10-19", ig_id="c1")
        self.assertFalse(self.sf.brief_due(at_8))

    def test_publish_brief_instagram_carousel_and_facebook_album(self):
        brief = {"date": "2026-10-19", "slides": [b"a", b"b", b"c"], "caption": "Texto. Todas las notas completas en lavozriojana.com"}
        with mock.patch.object(self.sf, "_upload_all", return_value=(["https://r2/1", "https://r2/2", "https://r2/3"], ["k1", "k2", "k3"])), mock.patch(
            "utils.r2_storage.delete"
        ), mock.patch("meta.ig_client.post_image_carousel", return_value=OperationResult(StageStatus.SUCCESS, external_id="c1")) as ig, mock.patch(
            "meta.fb_client.post_photo_album", return_value=OperationResult(StageStatus.SUCCESS, external_id="f1")
        ) as fb:
            outcome = self.sf.publish_morning_brief(brief, instagram=True, facebook=True)
        self.assertEqual(outcome, {"ig": "success", "fb": "success"})
        ig.assert_called_once()
        self.assertIn("https://lavozriojana.com", fb.call_args.args[1])
        self.assertFalse(self.sf.brief_due(datetime(2026, 10, 19, 8, 30, tzinfo=AR_TZ)))

    def test_weekly_due_only_sunday_evening(self):
        self.assertTrue(self.sf.weekly_due(datetime(2026, 10, 18, 20, 5, tzinfo=AR_TZ)))
        self.assertFalse(self.sf.weekly_due(datetime(2026, 10, 18, 12, 0, tzinfo=AR_TZ)))
        self.assertFalse(self.sf.weekly_due(datetime(2026, 10, 19, 20, 5, tzinfo=AR_TZ)))
        self.assertEqual(self.sf._reach_label(484224), "484 mil cuentas alcanzadas")
        self.assertEqual(self.sf._reach_label(1_250_000), "1,2 millones de cuentas alcanzadas")


class StoryUpdatesTests(unittest.TestCase):
    def test_detects_changed_figure_for_same_event(self):
        from utils import story_updates as su

        self.assertEqual(
            su.find_change("NAUFRAGIO EN EL RÍO PARANÁ: UN SOBREVIVIENTE Y TRES DESAPARECIDOS", "NAUFRAGIO EN EL RÍO PARANÁ: HALLARON A OTRO TRIPULANTE Y QUEDAN DOS DESAPARECIDOS"),
            ("desaparecidos", 3, 2),
        )

    def test_different_events_or_ambiguous_figures_are_ignored(self):
        from utils import story_updates as su

        self.assertIsNone(su.find_change("CHOQUE ENTRE AUTO Y MOTO DEJÓ DOS HERIDOS EN LA RIOJA", "CHOQUE EN RUTA 5 DEJÓ TRES HERIDOS EN CHILECITO"))
        self.assertEqual(su.facts("DOS HERIDOS Y TRES HERIDOS"), {})
        self.assertIsNone(su.find_change("INCENDIO EN FÁBRICA DE CHILECITO: DOS HERIDOS", "INCENDIO EN FÁBRICA DE CHILECITO: DOS HERIDOS"))

    def test_facebook_message_replaces_previous_update_header(self):
        from utils import story_updates as su

        first = su.facebook_message("Texto original", "Quedan dos desaparecidos", "16:40", "https://lavozriojana.com/n")
        second = su.facebook_message(first, "Quedan uno", "18:00", "https://lavozriojana.com/n")
        self.assertTrue(second.startswith("🔄 Actualización 18:00"))
        self.assertEqual(second.count("🔄"), 1)
        self.assertTrue(second.endswith("Texto original"))
        self.assertEqual(su.phrase("desaparecidos", 3), "Tres desaparecidos")
        self.assertEqual(su.phrase("víctimas", 1), "Una víctima")


class CommentRepliesTests(_TempState):
    def setUp(self):
        super().setUp()
        from utils import comment_replies as cr

        self.cr = cr
        patcher = mock.patch.object(cr, "STATE_PATH", self.path("comments.json"))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_prefilter(self):
        c = self.cr.is_candidate
        self.assertTrue(c("Perdón mi ignorancia, pero cocaína de colores?"))
        self.assertTrue(c("A qué hora empieza el corte de luz en el centro"))
        self.assertFalse(c("Corte moco?😂"))
        self.assertFalse(c("Los Kukas? 😂😂"))
        self.assertFalse(c("jajaja que es esto?"))
        self.assertFalse(c("@amiga mirá esto, qué te parece?"))
        self.assertFalse(c("Qué opinan de este pelotudo?"))
        self.assertFalse(c("Que tristeza x Dios 😢"))  # exclamación, no pregunta
        self.assertTrue(c("Dónde se pueden retirar los formularios"))

    def test_reply_must_stay_inside_the_note(self):
        source = "Los agentes encontraron dosis de estupefacientes con una coloración inusual. El hombre de 38 años quedó detenido."
        good = lambda **kw: json.dumps({"responder": True, "respuesta": "Según la causa, se encontraron dosis con una coloración inusual; no se informó el color.", "motivo": "en la nota"})
        invented = lambda **kw: json.dumps({"responder": True, "respuesta": "Tenían 12 dosis rosas.", "motivo": "x"})
        declined = lambda **kw: json.dumps({"responder": False, "respuesta": "", "motivo": "no está en la nota"})
        self.assertTrue(self.cr.propose_reply("¿cocaína de colores?", source, completion=good)["responder"])
        self.assertEqual(self.cr.propose_reply("¿cuántas dosis?", source, completion=invented)["motivo"], "rechazada:number_not_in_source")
        self.assertFalse(self.cr.propose_reply("¿para qué la llevan?", source, completion=declined)["responder"])
        broken = lambda **kw: "no es json"
        self.assertEqual(self.cr.propose_reply("x", source, completion=broken)["motivo"], "ai_error")

    def test_suggest_mode_never_publishes_and_auto_respects_cap(self):
        candidate = {"key": "instagram:c1", "platform": "instagram", "comment_id": "c1", "text": "¿A qué hora es?", "post_id": "m1", "record": {"titulo": "Acto a las 10", "texto_instagram": "El acto empieza a las 10."}}
        answer = lambda **kw: json.dumps({"responder": True, "respuesta": "Empieza a las 10, según la nota.", "motivo": "ok"})
        with mock.patch.object(self.cr, "article_text", return_value=""), mock.patch.object(self.cr, "_web_url_for", return_value=""), mock.patch(
            "meta.ig_client.reply_to_comment", return_value=OperationResult(StageStatus.SUCCESS, external_id="r1")
        ) as reply:
            counts = self.cr.process([candidate], publish=False, completion=answer)
            self.assertEqual(counts["proposed"], 1)
            reply.assert_not_called()
            self.assertEqual(self.cr.approve("instagram:c1"), "replied")
            reply.assert_called_once_with("c1", "Empieza a las 10, según la nota.")
            with mock.patch.dict(os.environ, {"COMMENT_REPLIES_MAX_PER_DAY": "1"}):
                counts = self.cr.process([{**candidate, "key": "instagram:c2", "comment_id": "c2"}], publish=True, completion=answer)
        self.assertEqual(counts["replied"], 0)  # el tope diario ya se usó


class MailerAndReportTests(_TempState):
    def test_mailer_requires_configuration(self):
        from utils import mailer

        with mock.patch.dict(os.environ, {"REPORT_EMAIL_TO": "", "SMTP_USER": "", "SMTP_PASSWORD": ""}):
            self.assertEqual(mailer.send_email("s", "<p>h</p>", "t").error_type, "smtp_not_configured")

    def test_mailer_sends_with_starttls(self):
        from utils import mailer

        env = {"REPORT_EMAIL_TO": "nahimsalta@gmail.com", "SMTP_USER": "bot@gmail.com", "SMTP_PASSWORD": "abcd efgh ijkl mnop", "SMTP_PORT": "587"}
        with mock.patch.dict(os.environ, env), mock.patch("smtplib.SMTP") as smtp:
            result = mailer.send_email("Asunto", "<p>h</p>", "texto")
        self.assertTrue(result.ok)
        session = smtp.return_value.__enter__.return_value
        session.starttls.assert_called_once()
        session.login.assert_called_once_with("bot@gmail.com", "abcdefghijklmnop")
        sent = session.send_message.call_args.args[0]
        self.assertEqual(sent["To"], "nahimsalta@gmail.com")

    def test_assess_and_render(self):
        from utils import ops_report

        facts = {
            "period": {"from": "a", "to": "b", "days": 3},
            "supervisor": {"status": "waiting", "stale": False, "age_minutes": 3, "cycle": 10},
            "logs": {"cycles": {"degraded": 40, "failed": 2}, "errors_by_log": {"run_ig.log": 3}, "top_errors": [{"log": "run_ig.log", "count": 3, "message": "x"}], "render_fallbacks": 11},
            "publications": {"web": 10, "instagram": 5, "facebook": 5, "comment_suggestions_pending": [{"pregunta": "¿?", "respuesta": "r"}]},
            "growth": {"instagram": {"followers": 10525, "delta": 839, "previous_delta": 1812}},
            "reach": {"reach": 1000, "interactions": 10, "reach_by_section": {}, "top": []},
            "sources": {"official_failing": ["smn_news"]},
            "service_sources": {"Dólar": "ok", "SMN clima": "falla (http_status:500)"},
            "tokens": {"Instagram": "10 días"},
            "disk": {"free_gb": 90},
        }
        level, notes = ops_report.assess(facts)
        self.assertEqual(level, "atención")
        self.assertTrue(any("vence" in n for n in notes))
        self.assertTrue(any("smn_news" in n for n in notes))
        html_body, text = ops_report.render(facts, level, notes, "Resumen.")
        self.assertIn("Respuestas a comentarios para revisar", html_body)
        self.assertIn("10.525", text)
        self.assertIn("+839", ops_report.subject(facts, level))

    def test_watchdog_one_alert_per_incident(self):
        from utils import ops_report

        with mock.patch.object(ops_report, "STATE_PATH", self.path("ops.json")):
            down = {"present": True, "stale": True, "age_seconds": 3 * 3600, "status": "ok", "data": {"supervisor_status": "waiting", "cycle_number": 5}}
            up = {"present": True, "stale": False, "age_seconds": 30, "status": "ok", "data": {"supervisor_status": "waiting", "cycle_number": 6}}
            with mock.patch.object(ops_report, "heartbeat_snapshot", return_value=down):
                self.assertIn("dejó de publicar", ops_report.watchdog_check()[0])
                self.assertIsNone(ops_report.watchdog_check())
            with mock.patch.object(ops_report, "heartbeat_snapshot", return_value=up):
                self.assertIn("volvió", ops_report.watchdog_check()[0])
                self.assertIsNone(ops_report.watchdog_check())


class StagesDisabledByDefaultTests(unittest.TestCase):
    def test_stages_are_no_work_without_flags(self):
        env = {k: "" for k in ("IG_STORIES_ENABLED", "FB_STORIES_ENABLED", "SOCIAL_FORMATS_INSTAGRAM_ENABLED", "SOCIAL_FORMATS_FACEBOOK_ENABLED", "COMMENT_REPLIES_MODE")}
        with mock.patch.dict(os.environ, env):
            from meta import run_comment_replies, run_social_formats, run_stories

            for module in (run_stories, run_social_formats, run_comment_replies):
                result = module.main()
                self.assertEqual(result.status, StageStatus.NO_WORK, module.__name__)
                self.assertTrue(result.details.get("disabled"))


class ArticleMediaTests(unittest.TestCase):
    def test_original_photo_from_og_code(self):
        from utils.article_media import parse_article_page

        page = (
            "<title>Naufragio en el río Paraná: un sobreviviente | La Voz Riojana</title>"
            '<meta property="og:image" content="https://media.lavozriojana.com/og/naufragio-43d83091fd.jpg"/>'
            '<meta property="article:section" content="Policiales"/>'
            '<img src="https://media.lavozriojana.com/noticias/2026/10/5878543daa1d9194d908.webp">'
            '<img src="https://media.lavozriojana.com/noticias/2026/10/43d83091fd1ad11387ad.webp">'
        )
        data = parse_article_page(page)
        self.assertEqual(data["title"], "Naufragio en el río Paraná: un sobreviviente")
        self.assertEqual(data["photo_url"], "https://media.lavozriojana.com/noticias/2026/10/43d83091fd1ad11387ad.webp")
        self.assertEqual(data["section"], "Policiales")
        cut = parse_article_page('<title>Teresita Madera en el Día de la Lealtad: críticas al modelo nacional y llamado a la autoc... | La Voz Riojana</title><meta property="og:title" content="Madera criticó el modelo nacional"/>')
        self.assertEqual(cut["title"], "Madera criticó el modelo nacional")


if __name__ == "__main__":
    unittest.main()
