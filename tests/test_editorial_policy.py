from __future__ import annotations

import unittest


class EditorialFallbackPolicyTests(unittest.TestCase):
    def test_non_sensitive_fallback_can_be_allowed_and_is_measurable(self):
        from utils.editorial_policy import evaluate_fallback_policy

        decision = evaluate_fallback_policy(
            {
                "titulo": "El municipio anunció nuevas obras barriales",
                "seccion": "sociedad",
                "parrafos": ["El municipio anunció tareas en distintos barrios."],
            },
            {
                "original_title": True,
                "category": True,
                "caption": True,
            },
            mode="allow_non_sensitive",
        )

        self.assertTrue(decision.allowed)
        self.assertTrue(decision.degraded)
        self.assertEqual(
            {"original_title", "category", "caption"},
            set(decision.fallbacks),
        )

    def test_policiales_judicial_minors_and_breaking_are_strict(self):
        from utils.editorial_policy import evaluate_fallback_policy

        cases = [
            {
                "titulo": "Investigan un robo",
                "seccion": "policiales",
                "parrafos": ["La fiscalía investiga el hecho."],
            },
            {
                "titulo": "La Justicia abrió una causa",
                "seccion": "sociedad",
                "parrafos": ["Interviene un juez y la fiscalía."],
            },
            {
                "titulo": "Buscan a una adolescente",
                "seccion": "sociedad",
                "parrafos": ["La menor fue vista por última vez el lunes."],
            },
            {
                "titulo": "Urgente: fuerte choque en Capital",
                "seccion": "sociedad",
                "parrafos": ["El choque ocurrió durante la mañana."],
            },
        ]
        for item in cases:
            with self.subTest(title=item["titulo"]):
                decision = evaluate_fallback_policy(
                    item,
                    {"caption": True},
                    mode="allow_non_sensitive",
                )
                self.assertFalse(decision.allowed)
                self.assertTrue(decision.strict)
                self.assertTrue(decision.reason)

    def test_block_mode_rejects_any_fallback(self):
        from utils.editorial_policy import evaluate_fallback_policy

        decision = evaluate_fallback_policy(
            {"titulo": "Nota general", "seccion": "sociedad", "parrafos": []},
            {"original_title": True},
            mode="block",
        )

        self.assertFalse(decision.allowed)
        self.assertEqual("fallback_blocked_by_policy", decision.reason)

    def test_no_fallback_is_normal_success_even_for_sensitive_content(self):
        from utils.editorial_policy import evaluate_fallback_policy

        decision = evaluate_fallback_policy(
            {"titulo": "Investigan un hecho", "seccion": "policiales", "parrafos": []},
            {},
            mode="block",
        )

        self.assertTrue(decision.allowed)
        self.assertFalse(decision.degraded)

    def test_safe_final_attempt_is_allowed_but_degraded_for_sensitive_content(self):
        from utils.editorial_policy import evaluate_web_fallback

        decision = evaluate_web_fallback(
            {
                "titulo": "Investigan un hecho",
                "seccion": "policiales",
                "parrafos": ["La investigación continúa."],
            },
            True,
            final_attempt_used=True,
        )

        self.assertTrue(decision.allowed)
        self.assertTrue(decision.degraded)
        self.assertTrue(decision.strict)
        self.assertEqual("editorial_final_attempt_published", decision.reason)


if __name__ == "__main__":
    unittest.main()
