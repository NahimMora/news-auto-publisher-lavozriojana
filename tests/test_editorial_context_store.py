import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from editorial_context import context_store as cs


class ContextStoreTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmpdir.name) / "context_store_test.sqlite3"

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_store_and_get_fact_roundtrip(self):
        cs.store_fact(
            cs.ContextFact(
                entity_key="Ministerio de Salud",
                fact="Lanzo una campana de vacunacion en marzo",
                source_kind=cs.SOURCE_KIND_OFFICIAL_SOURCE,
                fact_type=cs.FACT_TYPE_HECHO_HISTORICO,
                source_url="https://salud.larioja.gob.ar/x",
            ),
            path=self.db_path,
        )
        facts = cs.get_facts("ministerio de salud", path=self.db_path)
        self.assertEqual(len(facts), 1)
        self.assertIn("campana de vacunacion", facts[0].fact)

    def test_historical_fact_has_no_ttl_expiration(self):
        cs.store_fact(
            cs.ContextFact(
                entity_key="x",
                fact="hecho historico",
                source_kind=cs.SOURCE_KIND_OWN_ARCHIVE,
                fact_type=cs.FACT_TYPE_HECHO_HISTORICO,
            ),
            path=self.db_path,
        )
        facts = cs.get_facts("x", path=self.db_path)
        self.assertEqual(len(facts), 1)
        self.assertIsNone(facts[0].expires_at)

    def test_weather_alert_expires_quickly_and_is_filtered_by_default(self):
        past_observed = time.time() - (7 * 3600)  # hace 7 horas, TTL de alerta es 6h
        expires_at = cs.compute_expires_at(cs.FACT_TYPE_ALERTA_METEOROLOGICA, "", past_observed)
        cs.store_fact(
            cs.ContextFact(
                entity_key="smn",
                fact="Alerta amarilla por tormentas",
                source_kind=cs.SOURCE_KIND_OFFICIAL_SOURCE,
                fact_type=cs.FACT_TYPE_ALERTA_METEOROLOGICA,
                expires_at=expires_at,
            ),
            path=self.db_path,
        )
        active = cs.get_facts("smn", path=self.db_path)
        self.assertEqual(active, [])
        including_expired = cs.get_facts("smn", include_expired=True, path=self.db_path)
        self.assertEqual(len(including_expired), 1)

    def test_cronograma_expires_at_event_date_not_fixed_ttl(self):
        future_date = (datetime.now(timezone.utc) + timedelta(days=200)).strftime("%Y-%m-%dT%H:%M:%SZ")
        cs.store_fact(
            cs.ContextFact(
                entity_key="anses",
                fact="El cronograma de pagos vence el dia indicado",
                source_kind=cs.SOURCE_KIND_OFFICIAL_SOURCE,
                fact_type=cs.FACT_TYPE_CRONOGRAMA,
                event_date=future_date,
            ),
            path=self.db_path,
        )
        facts = cs.get_facts("anses", path=self.db_path)
        self.assertEqual(facts[0].expires_at, future_date)

    def test_duplicate_fact_same_hash_is_upserted_not_duplicated(self):
        fact = cs.ContextFact(
            entity_key="x",
            fact="mismo hecho",
            source_kind=cs.SOURCE_KIND_OWN_ARCHIVE,
            source_url="https://a",
        )
        cs.store_fact(fact, path=self.db_path)
        cs.store_fact(fact, path=self.db_path)
        facts = cs.get_facts("x", path=self.db_path)
        self.assertEqual(len(facts), 1)

    def test_get_facts_for_entities_aggregates_multiple_keys(self):
        cs.store_fact(cs.ContextFact(entity_key="a", fact="fact a", source_kind=cs.SOURCE_KIND_OWN_ARCHIVE), path=self.db_path)
        cs.store_fact(cs.ContextFact(entity_key="b", fact="fact b", source_kind=cs.SOURCE_KIND_OWN_ARCHIVE), path=self.db_path)
        facts = cs.get_facts_for_entities(["a", "b"], path=self.db_path)
        self.assertEqual(len(facts), 2)


if __name__ == "__main__":
    unittest.main()
