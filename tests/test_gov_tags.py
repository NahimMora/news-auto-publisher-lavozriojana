"""Etiquetas del Gobierno de La Rioja y ubicación en Instagram."""
from __future__ import annotations

import json
import os
import re
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from meta import ig_client
from utils import gov_tags, ig_location
from utils.social_caption import build_instagram_caption


class FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


def _local(text, *, seccion="sociedad", source="nuevarioja_sociedad", titulo="Nota"):
    return {"titulo": titulo, "texto_instagram": text, "seccion": seccion, "source": source}


class DirectoryTests(unittest.TestCase):
    def test_directory_is_well_formed(self):
        with open(gov_tags.DIRECTORY_PATH, encoding="utf-8") as handle:
            entries = json.load(handle)["entries"]
        handles = [h for e in entries for h in (e.get("institution"), e.get("person")) if h]
        self.assertEqual(len(handles), len(set(handles)), "cuenta repetida en el directorio")
        for entry in entries:
            self.assertTrue(entry.get("institution") or entry.get("person"), entry["area"])
            self.assertTrue(entry.get("aliases") or entry.get("person_aliases"), entry["area"])
        for handle in handles:
            self.assertRegex(handle, r"^[a-z0-9._]{1,30}$")

    def test_locations_table_only_accepts_numeric_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "loc.json"
            path.write_text(json.dumps({"locations": {"Chilecito": "123456789", "Chamical": "", "Olta": "abc"}}), encoding="utf-8")
            ig_location._locations.cache_clear()
            self.addCleanup(ig_location._locations.cache_clear)
            with patch.object(ig_location, "LOCATIONS_PATH", str(path)), patch.dict(os.environ, {"IG_LOCATION_ENABLED": "true"}):
                ig_location._locations.cache_clear()
                table = ig_location._locations(str(path))
                with patch.object(ig_location, "_locations", return_value=table):
                    self.assertEqual("123456789", ig_location.location_id_for({"locality": "Chilecito · Famatina"}))
                    self.assertEqual("", ig_location.location_id_for({"locality": "Chamical"}))
                    self.assertEqual("", ig_location.location_id_for({"locality": "Olta"}))
                    self.assertEqual("", ig_location.location_id_for({}))
            with patch.dict(os.environ, {"IG_LOCATION_ENABLED": "false"}):
                self.assertEqual("", ig_location.location_id_for({"locality": "Chilecito"}))


class MatchingTests(unittest.TestCase):
    def test_ministry_tags_institution_and_minister(self):
        note = _local("El Ministerio de Educación lanzó un programa de becas para escuelas rurales.")
        self.assertEqual(["mineducacionlarioja", "arielmartinezlar"], gov_tags.handles_for(note))

    def test_ministry_without_verified_minister_tags_only_institution(self):
        note = _local("La Secretaría de Justicia informó la campaña de mediación en Chilecito.")
        self.assertEqual(["secretariadejusticialr"], gov_tags.handles_for(note))
        note = _local("El Ministerio de Salud informó la campaña de vacunación en Chilecito.")
        self.assertEqual(["saludlarioja", "juancarlosvergaralr"], gov_tags.handles_for(note))

    def test_accents_and_case_do_not_matter(self):
        note = _local("el ministerio de educacion confirmó el calendario")
        self.assertIn("mineducacionlarioja", gov_tags.handles_for(note))

    def test_national_ministry_is_not_tagged(self):
        note = _local("El Ministerio de Salud de la Nación envió dosis a las provincias.")
        self.assertEqual([], gov_tags.handles_for(note))
        note = _local("El Ministerio de Educación nacional recortó fondos.")
        self.assertEqual([], gov_tags.handles_for(note))

    def test_national_context_blocks_ministry_aliases(self):
        note = _local("Renuncia en el Ministerio de Seguridad: el subsecretario del Gobierno nacional dejó el cargo.")
        self.assertEqual([], gov_tags.handles_for(note))

    def test_relative_with_same_surname_is_not_the_governor(self):
        note = _local("El presidente de Edelar, Jerónimo Quintela, reconoció un aumento de la morosidad.")
        self.assertEqual([], gov_tags.handles_for(note))
        self.assertEqual(
            ["gobiernodelarioja", "ricardocquintela"],
            gov_tags.handles_for(_local("El gobernador Ricardo Quintela inauguró la obra.")),
        )

    def test_non_local_sources_are_never_tagged(self):
        for source in ("infobae_policiales", "paparazzi", "nuevarioja_internacionales"):
            note = _local("El Ministerio de Educación lanzó un programa.", source=source)
            self.assertEqual([], gov_tags.handles_for(note), source)

    def test_policiales_are_excluded_by_default(self):
        note = _local("El ministro de Seguridad Miguel Zárate encabezó un operativo.", seccion="Policiales", source="nuevarioja_policiales")
        self.assertEqual([], gov_tags.handles_for(note))
        with patch.dict(os.environ, {"GOV_TAGS_EXCLUDED_SECTIONS": "deportes"}):
            self.assertIn("dr.miguelzarate", gov_tags.handles_for(note))

    def test_person_name_needs_a_role_in_the_text(self):
        # Homónimo sin cargo: no se etiqueta.
        self.assertEqual([], gov_tags.handles_for(_local("Patricia Herrera ganó el torneo de truco del barrio.")))
        note = _local("La secretaria Patricia Herrera presentó la agenda cultural de noviembre.")
        self.assertEqual(["patriciaherrerados"], gov_tags.handles_for(note))

    def test_word_boundaries(self):
        # "APOS" no debe saltar dentro de otra palabra.
        self.assertEqual([], gov_tags.handles_for(_local("Los capos del fútbol local apostaron fuerte.")))
        self.assertEqual(["aposlr", "m.claudiaortiz"], gov_tags.handles_for(_local("APOS amplió la cobertura de prestaciones.")))


class CapsTests(unittest.TestCase):
    def test_disabled_by_default(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("GOV_TAGS_ENABLED", None)
            self.assertEqual([], gov_tags.select_tags(_local("El Ministerio de Educación lanzó un programa.")))

    def test_per_post_and_daily_caps(self):
        note = _local("El Ministerio de Educación y el Ministerio de Vivienda firmaron un convenio.")
        env = {"GOV_TAGS_ENABLED": "true", "GOV_TAGS_MAX_PER_POST": "3", "GOV_TAGS_DAILY_MAX": "5"}
        with patch.dict(os.environ, env):
            self.assertEqual(3, len(gov_tags.select_tags(note)))
            self.assertEqual(1, len(gov_tags.select_tags(note, used_last_24h=4)))
            self.assertEqual([], gov_tags.select_tags(note, used_last_24h=5))

    def test_daily_count_uses_recent_records_only(self):
        now = time.time()
        records = [
            {"posted_at": now - 3600, "gov_tags": ["a", "b"]},
            {"posted_at": now - 2 * 86400, "gov_tags": ["c"]},
            {"posted_at": "x", "gov_tags": ["d"]},
            {"posted_at": now},
        ]
        self.assertEqual(2, gov_tags.tags_used_last_24h(records, now=now))

    def test_image_tags_have_coordinates_inside_the_image(self):
        tags = json.loads(gov_tags.image_user_tags(["a", "b"]))
        for tag in tags:
            self.assertTrue(0 < tag["x"] < 1 and 0 < tag["y"] < 1)
        self.assertEqual([{"username": "a"}], json.loads(gov_tags.reel_user_tags(["a"])))


class InstagramIntegrationTests(unittest.TestCase):
    def _post(self, responses, note, *, extra_env=None):
        with tempfile.TemporaryDirectory() as tmp:
            env = {
                "IG_IMAGE_CONTAINER_WAIT_SECONDS": "0",
                "IG_ALLOW_ORIGINAL_IMAGE_FALLBACK": "true",
                "GOV_TAGS_ENABLED": "true",
                "IG_LOCATION_ENABLED": "true",
                **(extra_env or {}),
            }
            with patch.object(ig_client, "IG_ACCOUNT_ID", "ig"), patch.object(ig_client, "IG_ACCESS_TOKEN", "token"), patch.object(
                ig_client, "IG_STATE_PATH", str(Path(tmp) / "ig.json")
            ), patch.object(ig_client, "IG_RATE_LIMIT_PATH", str(Path(tmp) / "rate.json")), patch.object(
                ig_client.r2_storage, "is_configured", return_value=False
            ), patch.object(ig_location, "_locations", return_value={"chilecito": "987654321"}), patch.dict(
                os.environ, env, clear=False
            ), patch.object(ig_client.requests, "post", side_effect=responses) as post:
                result = ig_client.post_to_instagram_detailed(note)
                saved = json.loads((Path(tmp) / "ig.json").read_text(encoding="utf-8")) if (Path(tmp) / "ig.json").exists() else {}
        return result, [call.kwargs["data"] for call in post.call_args_list], saved

    def _note(self):
        return {
            **_local("El Ministerio de Educación lanzó un programa de becas."),
            "imagen_url": "https://media.example/nota.jpg",
            "dedup_key": "link:gov",
            "locality": "Chilecito",
        }

    def test_tags_mentions_and_location_go_to_the_container(self):
        result, calls, saved = self._post([FakeResponse(200, {"id": "c"}), FakeResponse(200, {"id": "m"})], self._note())
        self.assertTrue(result.ok)
        create = calls[0]
        usernames = [t["username"] for t in json.loads(create["user_tags"])]
        self.assertEqual(["mineducacionlarioja", "arielmartinezlar"], usernames)
        self.assertEqual("987654321", create["location_id"])
        self.assertTrue(create["caption"].endswith("@mineducacionlarioja @arielmartinezlar"))
        self.assertEqual(["mineducacionlarioja", "arielmartinezlar"], saved["posted"]["link:gov"]["gov_tags"])
        self.assertTrue(result.details["user_tags_applied"])

    def test_rejected_tags_retry_once_without_extras(self):
        rejected = FakeResponse(400, {"error": {"code": 100, "error_subcode": 2207024, "message": "user tag"}})
        result, calls, _saved = self._post(
            [rejected, FakeResponse(200, {"id": "c"}), FakeResponse(200, {"id": "m"})], self._note()
        )
        self.assertTrue(result.ok)
        self.assertIn("user_tags", calls[0])
        self.assertNotIn("user_tags", calls[1])
        self.assertNotIn("location_id", calls[1])
        self.assertFalse(result.details["user_tags_applied"])

    def test_rate_limit_is_not_retried_without_extras(self):
        limited = FakeResponse(400, {"error": {"code": 9, "error_subcode": 2207042}})
        result, calls, _saved = self._post([limited], self._note())
        self.assertEqual("rate_limit", result.error_type)
        self.assertEqual(1, len(calls))

    def test_flags_off_keep_the_historic_payload(self):
        result, calls, _saved = self._post(
            [FakeResponse(200, {"id": "c"}), FakeResponse(200, {"id": "m"})],
            self._note(),
            extra_env={"GOV_TAGS_ENABLED": "false", "IG_LOCATION_ENABLED": "false"},
        )
        self.assertTrue(result.ok)
        self.assertNotIn("user_tags", calls[0])
        self.assertNotIn("location_id", calls[0])
        self.assertNotIn("@", calls[0]["caption"])

    def test_local_reel_gets_tags_without_coordinates(self):
        item = {**self._note(), "video_url": "https://media.example/r.mp4", "share_to_feed": True}
        env = {"GOV_TAGS_ENABLED": "true", "IG_LOCATION_ENABLED": "true"}
        with tempfile.TemporaryDirectory() as tmp, patch.object(ig_client, "IG_ACCOUNT_ID", "ig"), patch.object(
            ig_client, "IG_ACCESS_TOKEN", "token"
        ), patch.object(ig_client, "IG_STATE_PATH", str(Path(tmp) / "ig.json")), patch.object(
            ig_client, "IG_RATE_LIMIT_PATH", str(Path(tmp) / "rate.json")
        ), patch.object(ig_location, "_locations", return_value={"chilecito": "987654321"}), patch.dict(os.environ, env), patch.object(
            ig_client, "_wait_video_container", return_value=ig_client.OperationResult(ig_client.StageStatus.SUCCESS, external_id="c")
        ), patch.object(ig_client.requests, "post", side_effect=[FakeResponse(200, {"id": "c"}), FakeResponse(200, {"id": "m"})]) as post:
            result = ig_client.post_reel_video_to_instagram(item)
        create = post.call_args_list[0].kwargs["data"]
        self.assertTrue(result.ok)
        self.assertEqual([{"username": "mineducacionlarioja"}, {"username": "arielmartinezlar"}], json.loads(create["user_tags"]))
        self.assertEqual("987654321", create["location_id"])
        self.assertEqual(["mineducacionlarioja", "arielmartinezlar"], result.details["gov_tags"])

    def test_facebook_caption_never_carries_mentions(self):
        note = {**self._note(), "gov_tags": ["mineducacionlarioja"]}
        self.assertIsNone(re.search(r"@mineducacionlarioja", build_instagram_caption(note)))
        self.assertIn("@mineducacionlarioja", ig_client._build_caption(note))


if __name__ == "__main__":
    unittest.main()
