"""Compactación del journal de eventos y de los terminales de la cola durable.

KNOWN_ISSUES 96: cada evento y cada transición reescribían archivos de decenas
de MB con el texto completo de cada nota.
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_NOTA = {
    "titulo": "Detuvieron a un sospechoso en Chilecito",
    "url": "https://example.com/nota",
    "canonical_url": "https://example.com/nota",
    "source": "tiempopopular_policiales",
    "seccion": "policiales",
    "fecha": "2026-10-16",
    "parrafos": ["Párrafo largo"] * 20,
    "texto_instagram": "Caption larga",
    "imagen": "C:/FotosLVR/x.jpg",
}


class QueueEventsCompactionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "queue_events.json"
        env = mock.patch.dict(os.environ, {"LVR_QUEUE_EVENTS_PATH": str(self.path)})
        env.start()
        self.addCleanup(env.stop)

    def _events(self):
        return json.loads(self.path.read_text(encoding="utf-8"))

    def test_new_event_keeps_identity_without_heavy_text(self):
        from utils.queue_events import record_queue_event

        record_queue_event(stage="rewrite", status="expired", reason="article_age_exceeded:1d", item=_NOTA)
        item = self._events()[0]["item"]
        self.assertEqual(_NOTA["titulo"], item["titulo"])
        self.assertEqual(_NOTA["canonical_url"], item["canonical_url"])
        self.assertNotIn("parrafos", item)
        self.assertNotIn("texto_instagram", item)
        self.assertIn("parrafos", _NOTA, "no debe mutar la nota original")

    def test_previous_events_are_compacted_on_next_append(self):
        from utils.queue_events import record_queue_event

        old = {"event_id": "viejo", "stage": "rewrite", "status": "dead_letter", "reason": "x", "timestamp": 1,
               "item": dict(_NOTA), "metadata": {}}
        self.path.write_text(json.dumps([old]), encoding="utf-8")
        record_queue_event(stage="web", status="completed", reason="", item={"titulo": "otra"})
        events = self._events()
        self.assertEqual(["viejo", events[1]["event_id"]], [e["event_id"] for e in events])
        self.assertNotIn("parrafos", events[0]["item"])
        self.assertEqual(_NOTA["titulo"], events[0]["item"]["titulo"])


class DurableQueueCompactionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        from utils.durable_queue import DurableQueue

        self.state = root / "state.json"
        self.staging = root / "staging.json"
        self.queue = DurableQueue(str(self.state), "rewrite")

    def _load(self):
        return json.loads(self.state.read_text(encoding="utf-8"))

    def _enqueue(self, *notas):
        self.staging.write_text(json.dumps(list(notas)), encoding="utf-8")
        self.queue.transfer_from_legacy(str(self.staging))

    def test_completed_and_expired_drop_heavy_text_but_keep_dedup(self):
        otra = {**_NOTA, "titulo": "Otra nota", "url": "https://example.com/otra", "canonical_url": "https://example.com/otra"}
        self._enqueue(_NOTA, otra)
        first = self.queue.claim_one()
        self.queue.complete(first["id"])
        second = self.queue.claim_one()
        self.queue.expire(second["id"], "article_age_exceeded:1d")

        state = self._load()
        for bucket in ("completed", "expired"):
            payload = state[bucket][0]["payload"]
            self.assertNotIn("parrafos", payload)
            self.assertIn("titulo", payload)

        # El id sigue deduplicando: la misma nota no vuelve a entrar.
        self._enqueue(_NOTA)
        self.assertEqual([], self._load()["pending"])

    def test_dead_letter_and_pending_keep_full_payload(self):
        otra = {**_NOTA, "titulo": "Pendiente", "url": "https://example.com/p", "canonical_url": "https://example.com/p"}
        self._enqueue(_NOTA, otra)
        job = self.queue.claim_one()
        self.queue.dead_letter(job["id"], "blocked_by_editorial_keyword")
        state = self._load()
        self.assertIn("parrafos", state["dead_letter"][0]["payload"])
        self.assertIn("parrafos", state["pending"][0]["payload"])

    def test_existing_terminal_entries_are_compacted_on_next_transition(self):
        self._enqueue(_NOTA)
        state = self._load()
        legacy = dict(state["pending"].pop(0), status="completed")
        state["completed"].append(legacy)
        self.state.write_text(json.dumps(state), encoding="utf-8")
        self.assertIn("parrafos", self._load()["completed"][0]["payload"])

        otra = {**_NOTA, "titulo": "Nueva", "url": "https://example.com/n", "canonical_url": "https://example.com/n"}
        self._enqueue(otra)
        self.queue.complete(self.queue.claim_one()["id"])
        self.assertTrue(all("parrafos" not in job["payload"] for job in self._load()["completed"]))


if __name__ == "__main__":
    unittest.main()
