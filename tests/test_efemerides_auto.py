"""Efemérides automáticas desde la página de la fecha en Wikipedia (sin red)."""
from __future__ import annotations

import datetime
import json
import os
import tempfile
import unittest
from unittest import mock

from utils import efemerides_auto as ea
from utils import format_reels as fr

DAY_WIKITEXT = """
== Acontecimientos ==
* [[1573]]: en [[Argentina]], [[Juan de Garay]] funda la aldea de [[Santa Fe de la Vera Cruz]].
* [[1863]]: en la aldea de [[Loma Blanca]] ―a 175&nbsp;km de la villa de [[ciudad de La Rioja (Argentina)|La Rioja]]― el [[Ángel Vicente Peñaloza|Chacho]] es asesinado.<ref>{{cita web|url=https://x.org|título=X}}</ref>
* 1990: en [[España]], [[Madrid]] inaugura algo.
* 2017: en [[Argentina]], [[Desaparición del ARA San Juan (S-42)|desaparece el submarino]] ''[[ARA San Juan (S-42)]]''.
== Nacimientos ==
* [[1788]]: [[Facundo Quiroga]], militar argentino (f. 1835).
* [[1866]]: [[Lola Mora]], escultora argentina (f. 1936).
== Fallecimientos ==
* [[Fallecidos en noviembre de 2017|2017]]: [[Camilo Cervino]], futbolista argentino (n. 1926).
== Celebraciones ==
* [[Archivo:Flag of the United Nations.svg|20px]] [[Organización de las Naciones Unidas]]:
** Día Internacional de Algo.<br><small>Proclamado en 1999.</small>
=== Por países ===
* {{ARG}}:
** Día Nacional por la Memoria del submarino [[ARA San Juan (S-42)|ARA «San Juan»]].<br><small>Establecido por la Ley 27758 de 2024, el {{fecha|17|10|2024}}.<ref name="a"/></small>
** <small>'''Por provincias'''</small>:
*** [[Provincia de Misiones|Misiones]]:
**** Aniversario de [[Puerto Rico (Argentina)|Puerto Rico]].<br><small>Fundada en 1919.</small>
* {{BEL}}:
** [[Día del Rey (Bélgica)|Día del Rey]].
=== Santoral católico ===
* San [[Alberto Magno]].
== Referencias ==
"""

ARTICLE = ("El ARA San Juan (S-42) fue un submarino de la Armada Argentina. El 15 de noviembre de 2017 perdió contacto en el mar "
           "argentino, frente al golfo San Jorge, mientras navegaba hacia Mar del Plata con 44 tripulantes. ") * 4


class Resp:
    def __init__(self, data, status=200):
        self.status_code, self._data = status, data

    def json(self):
        return self._data


def make_getter(*, license="CC BY 2.5", categories=None):
    categories = categories or {"Facundo Quiroga": ["Categoría:Nacidos en la provincia de La Rioja (Argentina)"],
                                "Lola Mora": ["Categoría:Escultoras de Argentina"], "Camilo Cervino": ["Categoría:Futbolistas de Argentina"]}

    def getter(url, params=None, headers=None, timeout=None):
        assert headers and "LaVozRiojanaBot" in headers["User-Agent"]
        if params["action"] == "parse":
            return Resp({"parse": {"wikitext": DAY_WIKITEXT}})
        prop = params.get("prop")
        if prop == "categories":
            titles = params["titles"].split("|")
            return Resp({"query": {"pages": [{"title": t, "categories": [{"title": c} for c in categories.get(t, [])]} for t in titles]}})
        if prop == "extracts|pageimages":
            return Resp({"query": {"pages": [{"title": "ARA San Juan (S-42)", "extract": ARTICLE, "pageimage": "S42.jpg"}]}})
        if prop == "imageinfo":
            meta = {"LicenseShortName": {"value": license}, "Artist": {"value": "<a href='x'>Martin Otero</a>"},
                    "ImageDescription": {"value": "Submarino ARA San Juan"}}
            return Resp({"query": {"pages": [{"imageinfo": [{"thumburl": "https://upload.wikimedia.org/s42.jpg", "thumbwidth": 1280,
                                                              "thumbheight": 900, "extmetadata": meta,
                                                              "descriptionurl": "https://commons.wikimedia.org/wiki/File:S42.jpg"}]}]}})
        raise AssertionError(params)

    return getter


SCRIPT = {
    "foto_pertinente": True, "anio": 2017,
    "gancho": "Un 15 de noviembre de 2017 desaparecía en el mar argentino el submarino ARA San Juan.",
    "lugar": "",
    "quien": {"locucion": "El ARA San Juan navegaba con 44 tripulantes.", "apodo": "ARA San Juan", "nombre": "Submarino ARA San Juan",
              "chips": ["44 tripulantes"], "claves": ["tripulantes"]},
    "donde": {"locucion": "Perdió contacto frente al golfo San Jorge.", "chips": ["Golfo San Jorge"], "claves": ["golfo"]},
    "anios": {"locucion": "Hoy se cumplen {anios} años.", "claves": ["años"]},
    "fecha_hoy": {"locucion": "Cada 15 de noviembre se recuerda a los 44 tripulantes.", "sello": "Día Nacional", "detalle": "Ley 27758",
                  "claves": ["Día Nacional"]},
}


def make_completion(pick_id, script=None):
    def completion(**kw):
        if kw["stage"] == "format_reels_ef_pick":
            return json.dumps({"elegidas": [{"id": pick_id, "prioridad": 2, "articulo": "ARA San Juan (S-42)", "motivo": "memoria"}]})
        return json.dumps(script or SCRIPT)

    return completion


class ParseTests(unittest.TestCase):
    def test_plain_drops_refs_templates_and_links(self):
        self.assertEqual(ea.plain("Ley 27758, el {{fecha|17|10|2024}}.<ref name='a'/> [[ARA San Juan (S-42)|ARA «San Juan»]] ''x''"),
                         "Ley 27758, el 17 de octubre de 2024. ARA «San Juan» x")

    def test_parse_day_keeps_argentina_un_and_skips_other_countries_and_saints(self):
        items = ea.parse_day(DAY_WIKITEXT)
        texts = [i.text for i in items]
        self.assertFalse(any("Madrid" in t or "Día del Rey" in t or "Alberto" in t for t in texts), texts)
        chacho = next(i for i in items if i.year == 1863)
        self.assertTrue(chacho.riojan)
        self.assertIn("Ángel Vicente Peñaloza", chacho.links)
        un = next(i for i in items if "Internacional" in i.text)
        self.assertIsNone(un.year)
        memoria = next(i for i in items if "Memoria" in i.text)
        self.assertTrue(memoria.argentine)
        self.assertEqual(memoria.links, ["ARA San Juan (S-42)"])
        self.assertIn("17 de octubre de 2024", memoria.text)
        cervino = next(i for i in items if i.section == "fallecimiento")
        self.assertEqual(cervino.year, 2017)

    def test_births_only_for_riojans(self):
        items = ea.candidates(datetime.date(2026, 11, 15), getter=make_getter())
        people = [i.links[0] for i in items if i.section in {"nacimiento", "fallecimiento"}]
        self.assertEqual(people, ["Facundo Quiroga"])


class PhotoTests(unittest.TestCase):
    def test_free_license_is_accepted_with_credit(self):
        pic, why = ea.photo("S42.jpg", getter=make_getter())
        self.assertEqual(why, "")
        self.assertEqual(pic.credit, "Martin Otero (CC BY 2.5), vía Wikimedia Commons")
        self.assertEqual(pic.description, "Submarino ARA San Juan")

    def test_non_free_license_is_rejected(self):
        for lic in ("CC BY-NC 4.0", "CC BY-ND 2.0", "Fair use", ""):
            pic, why = ea.photo("S42.jpg", getter=make_getter(license=lic))
            self.assertIsNone(pic, lic)
            self.assertIn("licencia", why)


class PrepareTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = mock.patch.dict(os.environ, {"LVR_DATA_DIR": self.tmp.name, "LVR_LOGS_DIR": self.tmp.name})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.day = datetime.date(2026, 11, 15)
        self.memoria = next(i.id for i in ea.parse_day(DAY_WIKITEXT) if "Memoria" in i.text)
        self.hecho = next(i.id for i in ea.parse_day(DAY_WIKITEXT) if i.year == 2017 and i.section == "hecho")

    def test_event_with_related_commemoration_builds_a_checked_plan(self):
        auto = ea.prepare(self.day, getter=make_getter(), completion=make_completion(self.hecho))
        self.assertEqual(auto.scope, "nacional")
        self.assertIn("Ley 27758", auto.cand.body)  # la conmemoración del mismo tema entra como fuente
        plan, warnings = fr.validate_ef(auto.entry, auto.cand, self.day)
        self.assertEqual(warnings, [])
        self.assertEqual(plan.beats[3].value, "9")
        plan.scope, plan.credit = auto.scope, auto.photo.credit
        caption = fr.caption_for(plan, auto.cand)
        self.assertIn("📷 Foto: Martin Otero (CC BY 2.5), vía Wikimedia Commons", caption)
        self.assertIn("#Argentina", caption)
        self.assertNotIn("#HistoriaRiojana", caption)

    def test_invented_data_or_unrelated_photo_never_passes(self):
        bad = dict(SCRIPT, quien=dict(SCRIPT["quien"], locucion="El ARA San Juan navegaba con 52 tripulantes."))
        with mock.patch.object(ea.time, "sleep"):
            with self.assertRaises(ea.NoEfemeride) as ctx:
                ea.prepare(self.day, getter=make_getter(), completion=make_completion(self.hecho, bad))
        self.assertIn("52", str(ctx.exception))
        with self.assertRaises(ea.NoEfemeride) as ctx:
            ea.prepare(self.day, getter=make_getter(), completion=make_completion(self.hecho, dict(SCRIPT, foto_pertinente=False)))
        self.assertIn("foto", str(ctx.exception))

    def test_nothing_chosen_is_no_efemeride(self):
        completion = lambda **kw: json.dumps({"elegidas": []})  # noqa: E731
        with self.assertRaises(ea.NoEfemeride):
            ea.prepare(self.day, getter=make_getter(), completion=completion)

    def test_unknown_id_or_article_is_ignored(self):
        items = ea.parse_day(DAY_WIKITEXT)
        completion = lambda **kw: json.dumps({"elegidas": [{"id": "zz", "prioridad": 1}, {"id": self.memoria, "prioridad": 2,  # noqa: E731
                                                                                          "articulo": "Inventado"}]})
        picks = ea.choose(items, completion=completion)
        self.assertEqual([(i.id, a, p) for i, a, p in picks], [(self.memoria, "ARA San Juan (S-42)", 2)])


class AutoStageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = mock.patch.dict(os.environ, {"LVR_DATA_DIR": self.tmp.name, "LVR_LOGS_DIR": self.tmp.name, "FORMAT_REELS_EF_AUTO": "true"})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_no_efemeride_is_recorded_once(self):
        from meta import run_format_reels as stage

        with mock.patch.object(fr, "load_efemerides", return_value=[]), \
                mock.patch.object(ea, "prepare", side_effect=ea.NoEfemeride("nada")) as prep:
            self.assertEqual(stage.run_ef({}), ("no_work", {"ef": "sin efeméride automática"}))
            state = fr.load_state()
            self.assertEqual(state["items"][f"ef:auto:{fr.now_ar().date().isoformat()}"]["status"], "rejected")
            self.assertEqual(stage.run_ef(state)[0], "no_work")
        self.assertEqual(prep.call_count, 1)

    def test_network_failure_is_retried_without_mark(self):
        from meta import run_format_reels as stage

        with mock.patch.object(fr, "load_efemerides", return_value=[]), \
                mock.patch.object(ea, "prepare", side_effect=RuntimeError("Wikipedia respondió 503")), \
                mock.patch.object(stage, "logger"):
            self.assertEqual(stage.run_ef({}), ("error", {"ef": "fuente_ilegible"}))
        self.assertEqual(fr.load_state(), {})

    def test_auto_is_off_without_flag(self):
        from meta import run_format_reels as stage

        with mock.patch.dict(os.environ, {"FORMAT_REELS_EF_AUTO": "false"}), \
                mock.patch.object(fr, "load_efemerides", return_value=[]), mock.patch.object(ea, "prepare") as prep:
            self.assertEqual(stage.run_ef({}), ("no_work", {"ef": "sin efeméride hoy"}))
        prep.assert_not_called()

    def test_ready_efemeride_is_rendered_with_scope_and_credit(self):
        from meta import run_format_reels as stage

        day = fr.now_ar().date()
        auto = ea.prepare(datetime.date(2026, 11, 15), getter=make_getter(),
                          completion=make_completion(next(i.id for i in ea.parse_day(DAY_WIKITEXT) if i.year == 2017 and i.section == "hecho")))
        auto.entry["fecha"] = f"{day.month:02d}-{day.day:02d}"
        with mock.patch.object(fr, "load_efemerides", return_value=[]), mock.patch.object(ea, "prepare", return_value=auto), \
                mock.patch.object(stage, "_render_ef", return_value=("done", {"ef": {"ig": "success"}})) as render:
            self.assertEqual(stage.run_ef({})[0], "done")
        _key, plan, _cand, url, _day = render.call_args.args
        self.assertEqual((plan.scope, plan.credit, url), ("nacional", auto.photo.credit, auto.photo.url))
        self.assertEqual(render.call_args.kwargs, {"min_side": 560})


if __name__ == "__main__":
    unittest.main()
