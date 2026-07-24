from __future__ import annotations

import importlib
import logging
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock


class RewriteRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.env = mock.patch.dict(
            os.environ,
            {
                "LVR_DATA_DIR": self.temp.name,
                "LVR_LOGS_DIR": str(self.root / "logs"),
                "JSON_BACKUP_ENABLED": "false",
                "OPENAI_FALLBACK_MODE": "allow_non_sensitive",
                "ARTICLE_MAX_AGE_DAYS": "3650",
            },
            clear=False,
        )
        self.env.start()
        self.addCleanup(self.env.stop)
        self.addCleanup(logging.shutdown)

    def _module(self):
        import openIA.rewrite_news as rewrite_news

        return importlib.reload(rewrite_news)

    def _items(self):
        titles = [
            "El hospital de Chilecito incorporó un tomógrafo",
            "Vialidad reparó el camino rural de Famatina",
            "La universidad abrió becas para estudiantes",
            "El club Andino ganó el torneo provincial",
            "Productores de Arauco iniciaron la cosecha",
            "Chamical sumó una nueva ambulancia",
            "Villa Unión presentó su agenda cultural",
            "Aimogasta renovó luminarias en tres barrios",
            "Chepes habilitó un centro de atención vecinal",
            "La Rioja lanzó una campaña de vacunación",
        ]
        return [
            {
                "titulo": titles[index],
                "url": f"https://example.com/noticia-{index}",
                "canonical_url": f"https://example.com/noticia-{index}",
                "seccion": "sociedad",
                "parrafos": [f"Contenido verificable y específico asociado al caso {index}."],
                "fecha": "2026-07-23",
                "source": "fixture",
            }
            for index in range(10)
        ]

    @staticmethod
    def _rewritten(item):
        return {
            **item,
            "titulo_original": item["titulo"],
            "titulo_instagram": item["titulo"][:80],
            "texto_instagram": item["parrafos"][0],
            "cta": "¿Qué opinás?",
            "fallbacks_used": {},
        }

    def test_interrupt_after_third_then_restart_completes_exactly_once(self):
        from utils.file_manager import load_json, save_json

        module = self._module()
        source = self.root / "noticias_norewrite_locales.json"
        save_json(str(source), self._items())
        module.INPUT_FILES = [str(source)]
        module.META_OUTPUT = str(self.root / "noticias_meta.json")
        module.WEB_OUTPUT = str(self.root / "noticias_web_pending.json")
        module.REWRITE_STATE = str(self.root / "rewrite_queue_state.json")

        calls = 0

        def interrupting(item):
            nonlocal calls
            calls += 1
            if calls == 4:
                raise KeyboardInterrupt("corte simulado")
            return self._rewritten(item)

        with self.assertRaises(KeyboardInterrupt):
            module.run_rewrite_pipeline(processor=interrupting)

        result = module.run_rewrite_pipeline(processor=self._rewritten)

        meta = load_json(module.META_OUTPUT, [], expected_type=list)
        web = load_json(module.WEB_OUTPUT, [], expected_type=list)
        self.assertEqual(10, len(meta))
        self.assertEqual(10, len(web))
        self.assertEqual(10, len({item["meta_queue_key"] for item in meta}))
        self.assertEqual(10, len({item["web_queue_key"] for item in web}))
        state = load_json(module.REWRITE_STATE, {}, expected_type=dict)
        self.assertEqual(10, len(state["completed"]))
        self.assertEqual(7, result.succeeded, "la ejecución reanudada procesa las siete restantes")

    def test_disallowed_fallback_goes_to_dead_letter_not_output(self):
        from utils.file_manager import load_json, save_json

        module = self._module()
        source = self.root / "noticias_norewrite_policiales.json"
        item = self._items()[0]
        item["seccion"] = "policiales"
        save_json(str(source), [item])
        module.INPUT_FILES = [str(source)]
        module.META_OUTPUT = str(self.root / "noticias_meta.json")
        module.WEB_OUTPUT = str(self.root / "noticias_web_pending.json")
        module.REWRITE_STATE = str(self.root / "rewrite_queue_state.json")

        def fallback(payload):
            result = self._rewritten(payload)
            result["fallbacks_used"] = {"caption": True}
            return result

        result = module.run_rewrite_pipeline(processor=fallback)

        state = load_json(module.REWRITE_STATE, {}, expected_type=dict)
        self.assertEqual(1, len(state["dead_letter"]))
        self.assertEqual([], load_json(module.META_OUTPUT, [], expected_type=list))
        self.assertEqual([], load_json(module.WEB_OUTPUT, [], expected_type=list))
        self.assertEqual(1, result.failed)


if __name__ == "__main__":
    unittest.main()
