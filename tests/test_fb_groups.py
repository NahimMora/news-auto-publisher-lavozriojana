"""Grupos de Facebook por localidad: a qué grupo va cada nota y la cola."""
from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from unittest import mock

NOW = time.time()


def _note(n: int, title: str, **extra) -> dict:
    return {"titulo": title, "canonical_url": f"https://src/{n}", "web_url": f"https://lavozriojana.com/noticias/n{n}",
            "excerpt": "", "source": "nuevarioja_locales", **extra}


class LocalityTests(unittest.TestCase):
    def test_interior_first_capital_by_default(self):
        from utils import fb_groups as fg

        self.assertEqual(fg.localities_for(_note(1, "Inauguraron un hospital en Chilecito")), ["Chilecito"])
        self.assertEqual(fg.localities_for(_note(2, "Choque en la capital y en Aimogasta")), ["Aimogasta"])
        self.assertEqual(fg.localities_for(_note(3, "Corte de luz en el barrio Vargas de La Rioja")), ["Capital"])
        self.assertEqual(fg.localities_for(_note(4, "Ruta en Villa Unión y Chamical")), ["Villa Unión", "Chamical"])
        # Palabra completa: "Olta" no se confunde con otras palabras.
        self.assertNotIn("Olta", fg.localities_for(_note(5, "Revolta en la Legislatura riojana")))
        self.assertEqual(fg.localities_for({"titulo": "El dólar subió en Buenos Aires", "source": "infobae"}), [])

    def test_text_has_title_and_clean_link(self):
        from utils import fb_groups as fg

        text = fg.compose({**_note(1, "Inauguraron un hospital"), "web_url": "https://lavozriojana.com/noticias/x?a=1"},
                          "Chilecito")
        self.assertIn("Inauguraron un hospital", text)
        self.assertTrue(text.endswith("https://lavozriojana.com/noticias/x"))


class QueueTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = mock.patch.dict(os.environ, {"LVR_DATA_DIR": self.tmp.name})
        patcher.start()
        self.addCleanup(patcher.stop)

    def write(self, name, value):
        with open(os.path.join(self.tmp.name, name), "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False)

    def seed(self, notes, ages_min):
        self.write("noticias_meta.json", notes)
        self.write("noticias_web_publicadas.json", [])
        self.write("paparazzi_reels_posted.json", {"posted": {}})
        self.write("fb_posted.json", {"posted": {n["canonical_url"]: {"canonical_url": n["canonical_url"], "external_id": "x",
                                                                       "posted_at": NOW - a * 60} for n, a in zip(notes, ages_min)}})

    def test_plan_routes_and_caps(self):
        from utils import fb_groups as fg

        self.seed([_note(1, "Obra en Chilecito"), _note(2, "Choque en barrio de La Rioja"), _note(3, "Otro choque en La Rioja")],
                  [30, 20, 10])
        fg.start_watermark(NOW - 3600)
        self.assertEqual(fg.plan(now=NOW), 1 + 2 + 2)
        state = fg.load_state()
        chilecito = [p for p in state["posts"].values() if p["locality"] == "Chilecito"]
        self.assertEqual([p["group_id"] for p in chilecito], ["1560682947543824"])
        # La más reciente primero; un grupo que acaba de publicar espera un ciclo.
        key, post = fg.next_post(state, now=NOW)
        self.assertIn("Otro choque", post["title"])
        fg.mark(key, status=fg.POSTED, posted_at=int(NOW))
        _, second = fg.next_post(fg.load_state(), now=NOW)
        self.assertNotEqual(second["group_id"], post["group_id"])
        # 50 minutos después el mismo grupo vuelve a estar disponible.
        later = [p for k, p in [fg.next_post(fg.load_state(), now=NOW + 51 * 60)] if p]
        self.assertTrue(later)
        with mock.patch.dict(os.environ, {"FB_GROUPS_MAX_PER_GROUP_DAY": "1", "FB_GROUPS_GROUP_GAP_MINUTES": "0"}):
            # Techo diario de seguridad.
            _, capped = fg.next_post(fg.load_state(), now=NOW + 60)
            self.assertNotEqual(capped["group_id"], post["group_id"])
        # No se vuelve a encolar lo mismo.
        self.assertEqual(fg.plan(now=NOW), 0)

    def test_old_items_expire_and_block_stops(self):
        from utils import fb_groups as fg

        self.seed([_note(1, "Obra en Chilecito")], [30])
        fg.start_watermark(NOW - 3600)
        fg.plan(now=NOW)
        self.assertEqual(fg.expire_old(now=NOW + 9 * 3600), 1)
        self.assertIsNone(fg.next_post(fg.load_state(), now=NOW + 9 * 3600))
        fg.set_blocked("aviso:captcha", hours=1)
        self.assertTrue(fg.blocked(fg.load_state()))


class StageTests(unittest.TestCase):
    def test_disabled_by_default(self):
        from meta import run_fb_groups

        with mock.patch.dict(os.environ, {"FB_GROUPS_ENABLED": "false"}):
            self.assertEqual(run_fb_groups.main().status.value, "no_work")

    def test_starts_worker_only_when_needed(self):
        from meta import run_fb_groups

        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.dict(os.environ, {"FB_GROUPS_ENABLED": "true", "LVR_DATA_DIR": tmp}), \
                mock.patch.object(run_fb_groups.fg, "plan", return_value=0), \
                mock.patch.object(run_fb_groups.fg, "next_post", return_value=("k", {})), \
                mock.patch.object(run_fb_groups.fg, "in_active_hours", return_value=True), \
                mock.patch.object(run_fb_groups, "worker_running", side_effect=[False, True]), \
                mock.patch.object(run_fb_groups, "spawn_worker", return_value=42) as spawn:
            self.assertEqual(run_fb_groups.main().details["worker"], "started:42")
            self.assertEqual(run_fb_groups.main().details["worker"], "running")
        spawn.assert_called_once()


if __name__ == "__main__":
    unittest.main()
