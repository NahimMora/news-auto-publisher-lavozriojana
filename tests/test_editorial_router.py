from __future__ import annotations

import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock


def _noticia(
    titulo,
    *,
    seccion="deportes",  # fuera de BREAKING_CATEGORIES: no dispara "breaking" por accidente
    hashtag_localidad="#Chilecito",
    canonical_url=None,
    fecha="2026-07-28",
):
    return {
        "titulo_original": titulo,
        "titulo": titulo,
        "seccion": seccion,
        "hashtag_localidad": hashtag_localidad,
        "canonical_url": canonical_url or f"https://example.com/{abs(hash(titulo))}",
        "fecha": fecha,
        "meta_queue_key": f"link:{abs(hash(titulo))}",
    }


class EditorialRouterPureLogicTests(unittest.TestCase):
    """Pruebas de ``evaluate_routing``: no tocan disco."""

    def test_first_and_second_post_of_topic_are_automatic(self):
        from utils.editorial_router import evaluate_routing

        first = _noticia("Un incendio afecta un local en Chilecito")
        decision1 = evaluate_routing(first, recent_topic_entries=[], now_ts=1000)
        self.assertEqual("automatic", decision1.route_by_channel["instagram"])
        self.assertEqual(1, decision1.topic_post_number)
        self.assertEqual("automatic", decision1.editorial_route)

        second = _noticia("Bomberos trabajan en el incendio de Chilecito")
        entry1 = {
            "ts": 1000,
            "titulo": first["titulo"],
            "canonical_url": first["canonical_url"],
            "route": "automatic",
            "breaking": False,
            "material_update": False,
        }
        decision2 = evaluate_routing(second, recent_topic_entries=[entry1], now_ts=1100)
        self.assertEqual("automatic", decision2.route_by_channel["instagram"])
        self.assertEqual(2, decision2.topic_post_number)

    def test_third_post_of_same_topic_is_candidate(self):
        from utils.editorial_router import evaluate_routing

        third = _noticia("Vecinos de Chilecito relatan el incendio")
        prior_entries = [
            {"ts": 1000, "titulo": "Un incendio afecta un local en Chilecito", "canonical_url": "a", "route": "automatic"},
            {"ts": 1100, "titulo": "Bomberos trabajan en el incendio de Chilecito", "canonical_url": "b", "route": "automatic"},
        ]
        decision = evaluate_routing(third, recent_topic_entries=prior_entries, now_ts=1200)
        self.assertEqual("candidate", decision.route_by_channel["instagram"])
        self.assertEqual(3, decision.topic_post_number)
        self.assertIn("topic_cap_exceeded", decision.route_reason)
        # Web y Facebook conservan comportamiento automático actual.
        self.assertEqual("automatic", decision.route_by_channel["web"])
        self.assertEqual("automatic", decision.route_by_channel["facebook"])

    def test_breaking_exceeds_topic_cap(self):
        from utils.editorial_router import evaluate_routing

        prior_entries = [
            {"ts": 1000, "titulo": "Un choque en Chilecito deja heridos leves", "canonical_url": "a", "route": "automatic"},
            {"ts": 1100, "titulo": "Peritos trabajan en el choque de Chilecito", "canonical_url": "b", "route": "automatic"},
        ]
        third = _noticia(
            "Hay dos muertos tras el choque en Chilecito",
            seccion="policiales",
        )
        decision = evaluate_routing(third, recent_topic_entries=prior_entries, now_ts=1200)
        self.assertTrue(decision.breaking)
        self.assertEqual("automatic", decision.route_by_channel["instagram"])
        self.assertIn("exception:breaking", decision.route_reason)

    def test_material_update_exceeds_topic_cap(self):
        from utils.editorial_router import evaluate_routing

        prior_entries = [
            {"ts": 1000, "titulo": "Buscan a un hombre desaparecido en Chilecito", "canonical_url": "a", "route": "automatic"},
            {"ts": 1100, "titulo": "Continúa la búsqueda del hombre en Chilecito", "canonical_url": "b", "route": "automatic"},
        ]
        third = _noticia(
            "Hallado el hombre que buscaban en Chilecito",
            seccion="sociedad",
        )
        decision = evaluate_routing(third, recent_topic_entries=prior_entries, now_ts=1200)
        self.assertTrue(decision.material_update)
        self.assertEqual("automatic", decision.route_by_channel["instagram"])
        self.assertIn("exception:material_update", decision.route_reason)

    def test_first_post_is_never_material_update(self):
        from utils.editorial_router import evaluate_routing

        first = _noticia("Hallado el hombre que buscaban en Chilecito", seccion="sociedad")
        decision = evaluate_routing(first, recent_topic_entries=[], now_ts=1000)
        self.assertFalse(decision.material_update)
        self.assertEqual("automatic", decision.route_by_channel["instagram"])

    def test_exact_technical_duplicate_is_suppressed(self):
        from utils.editorial_router import evaluate_routing

        original = "Un incendio afecta un local en Chilecito"
        prior_entries = [
            {"ts": 1000, "titulo": original, "canonical_url": "https://a.com/1", "route": "automatic"},
        ]
        duplicate = _noticia(original, canonical_url="https://mirror.example.com/1")
        decision = evaluate_routing(duplicate, recent_topic_entries=prior_entries, now_ts=1050)
        self.assertEqual("suppressed", decision.editorial_route)
        self.assertEqual("suppressed", decision.route_by_channel["instagram"])
        self.assertIn("suppressed:", decision.route_reason)

    def test_no_riojan_link_is_candidate_even_as_first_post(self):
        from utils.editorial_router import evaluate_routing

        national = _noticia(
            "El Gobierno nacional anunció una nueva medida económica",
            seccion="politica",
            hashtag_localidad="",
        )
        decision = evaluate_routing(national, recent_topic_entries=[], now_ts=1000)
        self.assertEqual("candidate", decision.route_by_channel["instagram"])
        self.assertIn("gate:no_riojan_link", decision.route_reason)
        self.assertEqual("candidate", decision.editorial_route)
        # Web/Facebook no cambian: siguen automáticos.
        self.assertEqual("automatic", decision.route_by_channel["web"])
        self.assertEqual("automatic", decision.route_by_channel["facebook"])

    def test_decision_reason_is_never_empty_and_is_auditable(self):
        from utils.editorial_router import evaluate_routing

        decision = evaluate_routing(_noticia("Una nota cualquiera sobre Chilecito"), now_ts=1000)
        self.assertTrue(decision.route_reason)
        self.assertIsInstance(decision.route_reason, str)


class EditorialRouterPersistenceTests(unittest.TestCase):
    """Pruebas de ``apply_routing``/``report_routing``: usan disco aislado."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.data = self.root / "data"
        self.data.mkdir()
        self.env = {
            "LVR_DATA_DIR": str(self.data),
            "LVR_LOGS_DIR": str(self.root / "logs"),
            "LVR_BACKUP_DIR": str(self.root / "backups"),
            "LVR_QUARANTINE_DIR": str(self.root / "quarantine"),
            "JSON_BACKUP_ENABLED": "false",
        }
        self.patch = mock.patch.dict(os.environ, self.env, clear=False)
        self.patch.start()
        self.addCleanup(self.patch.stop)

        from utils import editorial_router

        self.router = editorial_router
        self.addCleanup(self._close_logger)

    def _close_logger(self):
        for handler in list(self.router.logger.handlers):
            handler.close()
            self.router.logger.removeHandler(handler)

    def test_apply_routing_persists_topic_state_and_events(self):
        first = _noticia("Un incendio afecta un local en Chilecito")
        decision = self.router.apply_routing(first, now_ts=1000)
        self.assertEqual("automatic", decision.route_by_channel["instagram"])

        from utils.file_manager import load_json

        state = load_json(str(self.data / "topic_publication_state.json"), {}, expected_type=dict)
        self.assertIn(decision.topic_key, state)
        self.assertEqual(1, len(state[decision.topic_key]["instagram"]))

        events = load_json(str(self.data / "editorial_routing_events.json"), [], expected_type=list)
        self.assertEqual(1, len(events))
        self.assertEqual("editorial_router", events[0]["stage"])
        self.assertTrue(events[0]["reason"])

    def test_third_post_becomes_a_recorded_candidate(self):
        titles = [
            "Un incendio afecta un local en Chilecito",
            "Bomberos trabajan en el incendio de Chilecito",
            "Vecinos de Chilecito relatan el incendio",
        ]
        decisions = [self.router.apply_routing(_noticia(t), now_ts=1000 + i * 10) for i, t in enumerate(titles)]
        self.assertEqual(["automatic", "automatic", "candidate"], [d.route_by_channel["instagram"] for d in decisions])

        candidates = self.router.list_candidates(channel="instagram")
        self.assertEqual(1, len(candidates))
        self.assertEqual(titles[2], candidates[0]["titulo"])
        self.assertEqual("candidate", candidates[0]["status"])

    def test_report_routing_never_modifies_state(self):
        from utils.file_manager import load_json

        first = _noticia("Un incendio afecta un local en Chilecito")
        self.router.apply_routing(first, now_ts=1000)

        state_path = str(self.data / "topic_publication_state.json")
        candidates_path = str(self.data / "editorial_candidates.json")
        events_path = str(self.data / "editorial_routing_events.json")

        before_state = load_json(state_path, {}, expected_type=dict)
        before_candidates = load_json(candidates_path, [], expected_type=list)
        before_events = load_json(events_path, [], expected_type=list)

        second = _noticia("Bomberos trabajan en el incendio de Chilecito")
        third = _noticia("Vecinos de Chilecito relatan el incendio")
        rows = self.router.report_routing([second, third], now_ts=1100)

        # El reporte simula el efecto secuencial (2do automático, 3ro candidata)...
        self.assertEqual(["automatic", "candidate"], [row["route_by_channel"]["instagram"] for row in rows])

        # ...pero no persiste absolutamente nada.
        after_state = load_json(state_path, {}, expected_type=dict)
        after_candidates = load_json(candidates_path, [], expected_type=list)
        after_events = load_json(events_path, [], expected_type=list)
        self.assertEqual(before_state, after_state)
        self.assertEqual(before_candidates, after_candidates)
        self.assertEqual(before_events, after_events)

    def test_candidate_status_transitions(self):
        national = _noticia(
            "El Gobierno nacional anunció una nueva medida económica",
            seccion="politica",
            hashtag_localidad="",
        )
        self.router.apply_routing(national, now_ts=1000)
        candidates = self.router.list_candidates(channel="instagram")
        self.assertEqual(1, len(candidates))
        candidate_id = candidates[0]["candidate_id"]

        promoted = self.router.update_candidate_status(candidate_id, "automatic", operator="qa")
        self.assertEqual("automatic", promoted["status"])
        self.assertEqual(1, len(promoted["manual_override_history"]))

        back = self.router.update_candidate_status(candidate_id, "candidate")
        self.assertEqual("candidate", back["status"])

        # Idempotente: pedir el mismo status actual no falla ni duplica historial.
        noop = self.router.update_candidate_status(candidate_id, "candidate")
        self.assertEqual("candidate", noop["status"])
        self.assertEqual(len(back["manual_override_history"]), len(noop["manual_override_history"]))

        with self.assertRaises(ValueError):
            # discarded -> automatic no es una transición declarada.
            self.router.update_candidate_status(candidate_id, "discarded")
            self.router.update_candidate_status(candidate_id, "automatic")

        with self.assertRaises(KeyError):
            self.router.update_candidate_status("no-existe", "discarded")

    def test_candidate_to_automatic_syncs_underlying_noticia_route(self):
        national = _noticia(
            "El Gobierno nacional anunció una nueva medida económica",
            seccion="politica",
            hashtag_localidad="",
            canonical_url="https://a.com/sync-1",
        )
        national["meta_queue_key"] = "link:sync-1"
        from utils.file_manager import save_json

        self.router.apply_routing(national, now_ts=1000)
        save_json(str(self.data / "noticias_meta.json"), [national])

        candidates = self.router.list_candidates(channel="instagram")
        candidate_id = candidates[0]["candidate_id"]

        self.router.update_candidate_status(candidate_id, "automatic", operator="qa")

        from utils.file_manager import load_json

        meta_items = load_json(str(self.data / "noticias_meta.json"), [], expected_type=list)
        self.assertEqual("automatic", meta_items[0]["route_by_channel"]["instagram"])


class ManualOverrideTransitionTests(unittest.TestCase):
    """Casos A/B/C del override manual automatic<->candidate (disco aislado)."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.data = self.root / "data"
        self.data.mkdir()
        self.env = {
            "LVR_DATA_DIR": str(self.data),
            "LVR_LOGS_DIR": str(self.root / "logs"),
            "LVR_BACKUP_DIR": str(self.root / "backups"),
            "LVR_QUARANTINE_DIR": str(self.root / "quarantine"),
            "JSON_BACKUP_ENABLED": "false",
        }
        self.patch = mock.patch.dict(os.environ, self.env, clear=False)
        self.patch.start()
        self.addCleanup(self.patch.stop)

        from utils import editorial_router

        self.router = editorial_router
        self.addCleanup(self._close_logger)

    def _close_logger(self):
        for handler in list(self.router.logger.handlers):
            handler.close()
            self.router.logger.removeHandler(handler)

    def _seed_automatic_noticia(self, *, identity="link:auto-1", social_state="pending"):
        from utils.file_manager import save_json

        noticia = _noticia("Un incendio afecta un comercio en Chilecito", seccion="interior")
        noticia["meta_queue_key"] = identity
        noticia["dedup_key"] = identity
        noticia["route_by_channel"] = {"web": "automatic", "facebook": "automatic", "instagram": "automatic"}
        noticia["editorial_route"] = "automatic"
        save_json(str(self.data / "noticias_meta.json"), [noticia])

        social_item = dict(noticia)
        if social_state is not None:
            social_item["instagram_state"] = social_state
        save_json(str(self.data / "noticias_sociales_pendientes.json"), [social_item])
        return identity

    # ── Caso A: automatic pendiente -> candidate ─────────────────────────

    def test_demote_automatic_pending_removes_from_automatic_selection(self):
        identity = self._seed_automatic_noticia()

        result = self.router.demote_automatic_to_candidate(
            identity, reason="nota nacional sin vinculo riojano comprobado", operator="operator"
        )

        self.assertTrue(result["changed"])
        self.assertEqual("automatic", result["previous_route"])
        self.assertEqual("candidate", result["new_route"])
        self.assertIsNotNone(result["candidate_id"])

        from utils.file_manager import load_json

        meta_items = load_json(str(self.data / "noticias_meta.json"), [], expected_type=list)
        self.assertEqual("candidate", meta_items[0]["route_by_channel"]["instagram"])

        social_items = load_json(str(self.data / "noticias_sociales_pendientes.json"), [], expected_type=list)
        self.assertEqual("excluded", social_items[0]["instagram_state"])
        self.assertFalse(social_items[0]["instagram_done"])

        candidates = self.router.list_candidates(channel="instagram")
        self.assertEqual(1, len(candidates))
        self.assertEqual("operator_demotion", candidates[0]["origin"])
        self.assertEqual("candidate", candidates[0]["status"])

    def test_demote_persists_routing_event_with_required_fields(self):
        identity = self._seed_automatic_noticia()
        self.router.demote_automatic_to_candidate(identity, reason="motivo de prueba", operator="qa-operator")

        from utils.file_manager import load_json

        events = load_json(str(self.data / "editorial_routing_events.json"), [], expected_type=list)
        self.assertEqual(1, len(events))
        metadata = events[0]["metadata"]
        self.assertEqual("automatic", metadata["previous_route"])
        self.assertEqual("candidate", metadata["new_route"])
        self.assertIn("changed_at_ts", metadata)
        self.assertEqual("qa-operator", metadata["changed_by"])
        self.assertEqual("motivo de prueba", metadata["reason"])

    def test_demote_refuses_when_already_published(self):
        identity = self._seed_automatic_noticia(social_state="completed")
        with self.assertRaises(ValueError):
            self.router.demote_automatic_to_candidate(identity, reason="x")

    def test_demote_refuses_when_claim_in_flight(self):
        identity = self._seed_automatic_noticia(social_state="processing")
        with self.assertRaises(ValueError):
            self.router.demote_automatic_to_candidate(identity, reason="x")

    def test_demote_is_idempotent_on_double_execution(self):
        identity = self._seed_automatic_noticia()
        first = self.router.demote_automatic_to_candidate(identity, reason="motivo")
        second = self.router.demote_automatic_to_candidate(identity, reason="motivo otra vez")

        self.assertTrue(first["changed"])
        self.assertFalse(second["changed"])
        self.assertEqual(first["candidate_id"], second["candidate_id"])

        candidates = self.router.list_candidates(channel="instagram")
        self.assertEqual(1, len(candidates))  # no se duplicó

        from utils.file_manager import load_json

        events = load_json(str(self.data / "editorial_routing_events.json"), [], expected_type=list)
        self.assertEqual(1, len(events))  # no se duplicó el evento

    def test_demote_raises_if_noticia_not_found(self):
        with self.assertRaises(KeyError):
            self.router.demote_automatic_to_candidate("link:no-existe", reason="x")

    # ── Caso B: automatic ya publicada -> candidata premium (reuso) ──────

    def test_add_published_to_candidates_never_alters_history(self):
        from utils.file_manager import save_json, load_json

        identity = "link:published-1"
        noticia = _noticia("Alerta meteorológica en Chilecito", seccion="interior")
        noticia["meta_queue_key"] = identity
        noticia["route_by_channel"] = {"web": "automatic", "facebook": "automatic", "instagram": "automatic"}
        save_json(str(self.data / "noticias_meta.json"), [noticia])

        ig_posted_before = {
            "posted": {
                identity: {
                    "posted_at": 1000,
                    "dedup_key": identity,
                    "external_id": "ig-real-12345",
                    "titulo": noticia["titulo"],
                }
            }
        }
        save_json(str(self.data / "ig_posted.json"), ig_posted_before)

        result = self.router.add_published_to_candidates(identity, reason="reutilizar para carrusel premium")
        self.assertTrue(result["changed"])
        self.assertIsNotNone(result["candidate_id"])

        # La evidencia histórica de publicación no se tocó.
        ig_posted_after = load_json(str(self.data / "ig_posted.json"), {}, expected_type=dict)
        self.assertEqual(ig_posted_before, ig_posted_after)

        # La ruta de la noticia real sigue siendo "automatic" (no se finge lo contrario).
        meta_items = load_json(str(self.data / "noticias_meta.json"), [], expected_type=list)
        self.assertEqual("automatic", meta_items[0]["route_by_channel"]["instagram"])

        candidates = self.router.list_candidates(channel="instagram")
        self.assertEqual(1, len(candidates))
        self.assertEqual("published_reuse", candidates[0]["origin"])

        events = load_json(str(self.data / "editorial_routing_events.json"), [], expected_type=list)
        self.assertEqual(1, len(events))
        self.assertEqual("automatic", events[0]["metadata"]["previous_route"])
        self.assertEqual("automatic", events[0]["metadata"]["new_route"])

    def test_add_published_refuses_without_real_evidence(self):
        with self.assertRaises(ValueError):
            self.router.add_published_to_candidates("link:never-published", reason="x")

    def test_add_published_is_idempotent_on_double_execution(self):
        from utils.file_manager import save_json

        identity = "link:published-2"
        save_json(str(self.data / "ig_posted.json"), {"posted": {identity: {"external_id": "ig-1"}}})

        first = self.router.add_published_to_candidates(identity, reason="motivo")
        second = self.router.add_published_to_candidates(identity, reason="motivo otra vez")

        self.assertTrue(first["changed"])
        self.assertFalse(second["changed"])
        self.assertEqual(first["candidate_id"], second["candidate_id"])
        self.assertEqual(1, len(self.router.list_candidates(channel="instagram")))

    # ── Caso C: candidate <-> automatic, candidate <-> discarded ─────────

    def test_candidate_to_automatic_when_not_yet_published(self):
        identity = self._seed_automatic_noticia()
        demoted = self.router.demote_automatic_to_candidate(identity, reason="motivo")
        candidate_id = demoted["candidate_id"]

        result = self.router.update_candidate_status(candidate_id, "automatic", operator="qa")
        self.assertEqual("automatic", result["status"])

        from utils.file_manager import load_json

        meta_items = load_json(str(self.data / "noticias_meta.json"), [], expected_type=list)
        self.assertEqual("automatic", meta_items[0]["route_by_channel"]["instagram"])

    def test_candidate_to_discarded_and_back_to_candidate(self):
        identity = self._seed_automatic_noticia()
        demoted = self.router.demote_automatic_to_candidate(identity, reason="motivo")
        candidate_id = demoted["candidate_id"]

        discarded = self.router.update_candidate_status(candidate_id, "discarded")
        self.assertEqual("discarded", discarded["status"])

        back = self.router.update_candidate_status(candidate_id, "candidate")
        self.assertEqual("candidate", back["status"])


class EditorialRouterInstagramGateTests(unittest.TestCase):
    """El router sólo debe afectar meta/run_ig.py cuando está habilitado."""

    def test_bootstrap_ignores_router_when_disabled_by_default(self):
        from meta import run_ig

        items = [
            {
                "dedup_key": "national",
                "titulo": "Nota nacional",
                "seccion": "politica",
                "web_url": "https://lavozriojana.com/n",
                "route_by_channel": {"web": "automatic", "facebook": "automatic", "instagram": "candidate"},
            }
        ]
        with mock.patch.dict(os.environ, {"EDITORIAL_ROUTER_ENABLED": "false"}, clear=False), mock.patch.object(
            run_ig, "load_json", return_value=items
        ), mock.patch.object(run_ig, "enqueue") as enqueue:
            included, omitted, missing = run_ig._bootstrap_queue()

        self.assertEqual(1, included)
        self.assertEqual(0, omitted)
        enqueue.assert_called_once()

    def test_bootstrap_excludes_router_candidates_when_enabled(self):
        from meta import run_ig

        items = [
            {
                "dedup_key": "national",
                "titulo": "Nota nacional",
                "seccion": "politica",
                "web_url": "https://lavozriojana.com/n",
                "route_by_channel": {"web": "automatic", "facebook": "automatic", "instagram": "candidate"},
            },
            {
                "dedup_key": "local",
                "titulo": "Nota riojana",
                "seccion": "interior",
                "web_url": "https://lavozriojana.com/l",
                "route_by_channel": {"web": "automatic", "facebook": "automatic", "instagram": "automatic"},
            },
        ]
        with mock.patch.dict(os.environ, {"EDITORIAL_ROUTER_ENABLED": "true"}, clear=False), mock.patch.object(
            run_ig, "load_json", return_value=items
        ), mock.patch.object(run_ig, "enqueue") as enqueue:
            included, omitted, missing = run_ig._bootstrap_queue()

        self.assertEqual(1, included)
        self.assertEqual(1, omitted)
        enqueue.assert_called_once_with(items[1], platform="instagram")

    def test_bootstrap_treats_missing_route_metadata_as_automatic(self):
        """Ítems que nunca pasaron por el router (o donde el router falló) no
        deben bloquearse silenciosamente aunque el flag esté encendido."""
        from meta import run_ig

        items = [
            {
                "dedup_key": "legacy",
                "titulo": "Nota vieja sin metadata de ruteo",
                "seccion": "sociedad",
                "web_url": "https://lavozriojana.com/legacy",
            }
        ]
        with mock.patch.dict(os.environ, {"EDITORIAL_ROUTER_ENABLED": "true"}, clear=False), mock.patch.object(
            run_ig, "load_json", return_value=items
        ), mock.patch.object(run_ig, "enqueue") as enqueue:
            included, omitted, missing = run_ig._bootstrap_queue()

        self.assertEqual(1, included)
        enqueue.assert_called_once()


class TopicKeyHeuristicTests(unittest.TestCase):
    def test_sentence_start_capitalization_is_not_treated_as_entity(self):
        """Regresión en el mismo espíritu de LVR-075: una mayúscula de
        inicio de oración no debe, por sí sola, alterar el topic_key."""
        from utils.editorial_router import compute_topic_key

        a = compute_topic_key(_noticia("Incendio afecta a un local en Chilecito"))
        b = compute_topic_key(_noticia("Un foco ígneo afecta a un local en Chilecito"))
        # Ambos títulos comparten sólo la entidad real "Chilecito"; deben
        # coincidir aunque difieran en cómo arrancan la oración.
        self.assertEqual(a, b)

    def test_generic_words_alone_do_not_merge_unrelated_topics(self):
        from utils.editorial_router import compute_topic_key

        a = compute_topic_key(_noticia("Un incendio afecta un comercio en Chilecito", hashtag_localidad="#Chilecito"))
        b = compute_topic_key(_noticia("Un incendio afecta una vivienda en Aimogasta", hashtag_localidad="#Aimogasta"))
        self.assertNotEqual(a, b)


if __name__ == "__main__":
    unittest.main()
