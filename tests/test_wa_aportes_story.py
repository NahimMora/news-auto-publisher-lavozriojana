"""Historia "Mandanos tu noticia" por WhatsApp (WA-D4): ventana, enlace y etapa."""
from __future__ import annotations

import json
import os
import re
import tempfile
import unittest
from datetime import datetime
from unittest import mock

from utils.social_time import AR_TZ

FRIDAY, SATURDAY = "2026-10-30", "2026-10-31"


def at(day: str, hour: int, minute: int = 10) -> datetime:
    return datetime.fromisoformat(f"{day}T{hour:02d}:{minute:02d}:00").replace(tzinfo=AR_TZ)


class _Data(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = mock.patch.dict(os.environ, {"LVR_DATA_DIR": self.tmp.name, "LVR_OUTPUT_DIR": self.tmp.name})
        patcher.start()
        self.addCleanup(patcher.stop)

    def write(self, name: str, value) -> None:
        with open(os.path.join(self.tmp.name, name), "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False)

    def read(self, name: str):
        with open(os.path.join(self.tmp.name, name), encoding="utf-8") as handle:
            return json.load(handle)


class WaAportesStoryTests(_Data):
    def test_due_only_after_join_story_same_day(self):
        from utils import wa_aportes_story as wa

        self.assertFalse(wa.due(at(FRIDAY, 20), state={}))  # todavía no salió la de "Sumate"
        self.write("wa_join_story.json", {"days": {FRIDAY: {"status": "unverified"}}})
        self.assertFalse(wa.due(at(FRIDAY, 20), state={}))
        self.write("wa_join_story.json", {"days": {FRIDAY: {"status": "completed"}}})
        self.assertTrue(wa.due(at(FRIDAY, 20), state={}))
        self.assertFalse(wa.due(at(FRIDAY, 19), state={}))
        self.assertFalse(wa.due(at(FRIDAY, 23), state={}))
        self.assertFalse(wa.due(at(FRIDAY, 21), state={"days": {FRIDAY: {"status": "unverified"}}}))
        self.write("wa_join_story.json", {"days": {SATURDAY: {"status": "completed"}}})
        self.assertFalse(wa.due(at(SATURDAY, 20), state={}))  # sábado no es día de "Sumate"

    def test_number_link_and_display(self):
        from utils import wa_aportes_story as wa

        with mock.patch.dict(os.environ, {"WA_APORTES_NUMBER": ""}):
            os.environ.pop("WA_APORTES_NUMBER")
            digits = wa.number()
        self.assertEqual(digits, "5493804922704")
        self.assertEqual(wa.display_number(digits), "380 492-2704")
        self.assertRegex(wa.link(digits), r"^https://wa\.me/5493804922704\?text=Hola%2C%20La%20Voz%20Riojana\.")
        for bad in ("12345", "1 555 123 4567", "abc"):
            with mock.patch.dict(os.environ, {"WA_APORTES_NUMBER": bad}), self.assertRaises(ValueError):
                wa.number()

    def test_props_rotate_by_day_and_link_box_matches_composition(self):
        from utils import wa_aportes_story as wa

        a = wa.props_for(at(FRIDAY, 20, 4), "5493804922704")
        b = wa.props_for(at("2026-10-31", 20, 4), "5493804922704")
        self.assertEqual(a["clock"], "20:04")
        self.assertEqual(a["number"], "380 492-2704")
        self.assertNotEqual(a["question"], b["question"])
        tsx = open(os.path.join(os.path.dirname(__file__), "..", "remotion", "src", "v2", "social", "WaAportesStory.tsx"), encoding="utf-8").read()
        consts = {k: int(re.search(rf"export const {k} = (\d+);", tsx).group(1)) for k in ("BUTTON_TOP", "BUTTON_H", "BUTTON_SIDE")}
        self.assertEqual((wa._BUTTON_TOP, wa._BUTTON_H, wa._BUTTON_SIDE), (consts["BUTTON_TOP"], consts["BUTTON_H"], consts["BUTTON_SIDE"]))
        box = wa.LINK_BOX
        self.assertLess(box["y"] + box["height"] / 2, 0.86)  # fuera de la caja de respuesta

    def test_disabled_by_default(self):
        from meta import run_wa_aportes_story as stage

        with mock.patch.dict(os.environ, {"WA_APORTES_STORY_ENABLED": "false"}):
            self.assertEqual(stage.main().status.value, "no_work")

    def test_render_failure_publishes_nothing(self):
        from meta import run_wa_aportes_story as stage
        from utils import wa_aportes_story as wa

        plan = mock.Mock(channel_enabled=mock.Mock(return_value=True))
        with mock.patch.dict(os.environ, {"WA_APORTES_STORY_ENABLED": "true"}), \
                mock.patch.object(stage, "deployment_plan", return_value=plan), \
                mock.patch.object(wa, "due", return_value=True), \
                mock.patch.object(wa, "render", side_effect=RuntimeError("remotion: boom")), \
                mock.patch.object(stage, "publish") as publish:
            self.assertEqual(stage.main().status.value, "degraded")
        publish.assert_not_called()
        self.assertFalse(os.path.exists(os.path.join(self.tmp.name, "wa_aportes_story.json")))

    def test_stage_unverified_blocks_retry_and_cleans_files(self):
        from meta import instagrapi_client as igc
        from meta import run_wa_aportes_story as stage
        from utils import wa_aportes_story as wa

        video = os.path.join(self.tmp.name, "v.mp4")
        thumb = os.path.join(self.tmp.name, "v.jpg")
        for path in (video, thumb):
            open(path, "wb").close()
        plan = mock.Mock(channel_enabled=mock.Mock(return_value=True))
        with mock.patch.dict(os.environ, {"WA_APORTES_STORY_ENABLED": "true"}), \
                mock.patch.object(stage, "deployment_plan", return_value=plan), \
                mock.patch.object(wa, "due", return_value=True), \
                mock.patch.object(wa, "render", return_value=(video, thumb)), \
                mock.patch.object(stage, "publish", side_effect=igc.NativeStoryError(igc.UNVERIFIED, "timeout")) as publish:
            self.assertEqual(stage.main().status.value, "degraded")
        self.assertTrue(publish.call_args.args[2].startswith("https://wa.me/5493804922704"))
        [(day, entry)] = self.read("wa_aportes_story.json")["days"].items()
        self.assertEqual(entry["status"], "unverified")
        self.assertFalse(os.path.exists(video) or os.path.exists(thumb))
        self.write("wa_join_story.json", {"days": {day: {"status": "completed"}}})
        self.assertFalse(wa.due(datetime.fromisoformat(f"{day}T20:30:00").replace(tzinfo=AR_TZ)))


if __name__ == "__main__":
    unittest.main()
