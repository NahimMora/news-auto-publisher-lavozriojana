import unittest

from editorial_context.context_depth import ContextDepth, decide_depth
from editorial_context.enrichment_slots import Snippet, build_enrichment_slots


class DecideDepthTests(unittest.TestCase):
    def test_no_evidence_returns_none(self):
        self.assertEqual(
            decide_depth(best_archive_score=0.0, archive_item_count=0, has_official_context=False, has_strong_story=False),
            ContextDepth.NONE,
        )

    def test_weak_official_context_alone_gives_light(self):
        self.assertEqual(
            decide_depth(best_archive_score=0.0, archive_item_count=0, has_official_context=True, has_strong_story=False),
            ContextDepth.LIGHT,
        )

    def test_strong_archive_match_gives_standard(self):
        self.assertEqual(
            decide_depth(best_archive_score=0.65, archive_item_count=1, has_official_context=False, has_strong_story=False),
            ContextDepth.STANDARD,
        )

    def test_strong_story_overrides_to_story_depth(self):
        self.assertEqual(
            decide_depth(best_archive_score=0.3, archive_item_count=1, has_official_context=False, has_strong_story=True),
            ContextDepth.STORY,
        )

    def test_default_never_starts_at_story_without_strong_signal(self):
        result = decide_depth(best_archive_score=0.5, archive_item_count=1, has_official_context=False, has_strong_story=False)
        self.assertNotEqual(result, ContextDepth.STORY)


class EnrichmentSlotsTests(unittest.TestCase):
    def test_no_evidence_all_unavailable_except_never_available_impacto(self):
        slots = build_enrichment_slots(current_text="", archive_snippets=[], official_snippets=[])
        for slot in slots:
            self.assertFalse(slot.available)

    def test_contexto_available_with_archive_snippet(self):
        slots = build_enrichment_slots(
            archive_snippets=[Snippet(text="En junio se habia anunciado la obra", source_url="https://lavozriojana.com/a")]
        )
        contexto = next(s for s in slots if s.type == "CONTEXTO")
        self.assertTrue(contexto.available)
        self.assertEqual(contexto.source_refs, ["https://lavozriojana.com/a"])

    def test_datos_slot_detects_currency_pattern(self):
        slots = build_enrichment_slots(
            official_snippets=[Snippet(text="El bono sera de $50.000 para los beneficiarios", source_url="https://anses.gob.ar/x")]
        )
        datos = next(s for s in slots if s.type == "DATOS")
        self.assertTrue(datos.available)

    def test_proximo_paso_detects_cue_phrase(self):
        slots = build_enrichment_slots(
            official_snippets=[Snippet(text="La medida entrara en vigencia a partir del 1 de octubre", source_url="https://x.gob.ar")]
        )
        proximo = next(s for s in slots if s.type == "PROXIMO_PASO")
        self.assertTrue(proximo.available)

    def test_impacto_never_available_without_deterministic_signal(self):
        slots = build_enrichment_slots(
            archive_snippets=[Snippet(text="algo", source_url="https://x")],
            official_snippets=[Snippet(text="$100 mas", source_url="https://y")],
        )
        impacto = next(s for s in slots if s.type == "IMPACTO")
        self.assertFalse(impacto.available)

    def test_cambio_detects_differing_numbers(self):
        slots = build_enrichment_slots(
            current_text="El bono ahora sera de $70.000",
            archive_snippets=[Snippet(text="El bono anterior era de $50.000", source_url="https://x")],
        )
        cambio = next(s for s in slots if s.type == "CAMBIO")
        self.assertTrue(cambio.available)


if __name__ == "__main__":
    unittest.main()
