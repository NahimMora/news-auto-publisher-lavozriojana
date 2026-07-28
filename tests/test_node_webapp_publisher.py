from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from PIL import Image

from layout import image_generator
from meta import fb_client, ig_client
from openIA import rewrite_news
from pipeline.node_webapp import editorial, media, publisher
from pipeline.node_webapp.editorial import EditorialResult, EditorialSection
from pipeline.node_webapp.media import MediaResult
from utils import manual_video_queue, social_queue
from utils.operation_result import OperationResult
from utils.stage_result import StageStatus


class FakeResponse:
    def __init__(self, status_code=200, data=None, text="", content_type="application/json"):
        self.status_code = status_code
        self._data = data
        self.text = text
        self.headers = {"Content-Type": content_type}

    def json(self):
        if self._data is None:
            raise ValueError("no json")
        return self._data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)

    def close(self):
        pass


def sample_news(**overrides):
    data = {
        "titulo": "Vialidad Provincial intensifica mejoras viales en Aimogasta",
        "titulo_original": "Vialidad Provincial consolida tareas de mantenimiento vial",
        "seccion": "Interior",
        "fecha": "2026-06-27",
        "source": "tiempopopular_locales",
        "canonical_url": "https://www.tiempopopular.com.ar/2026/06/27/vialidad",
        "parrafos": [
            "Vialidad Provincial avanzo con tareas de conservacion y enripiado en rutas de Capital y Aimogasta.",
            "Los trabajos incluyeron limpieza de banquinas, perfilado y mejoras en caminos rurales.",
            "Las acciones buscan fortalecer la transitabilidad en distintos departamentos.",
        ],
        "hashtag_localidad": "#Aimogasta",
    }
    data.update(overrides)
    return data


class EditorialTests(unittest.TestCase):
    def test_render_editorial_html_uses_lr_blocks_and_lists(self):
        result = EditorialResult(
            title="Titulo",
            excerpt="Extracto",
            lead="Lead <seguro>",
            source_paragraph="Segun publico Tiempo Popular, dato de fuente.",
            sections=[
                EditorialSection(
                    heading="Que se sabe",
                    paragraphs=["Parrafo central"],
                    items=["Primer dato", "Segundo dato"],
                )
            ],
            key_points=["Aimogasta", "Interior"],
        )

        html = editorial.render_editorial_html(result)

        self.assertIn('<p class="lr-lead">Lead &lt;seguro&gt;</p>', html)
        self.assertIn('<p class="lr-source">', html)
        self.assertIn('<div class="lr-key-points"><span>Aimogasta</span><span>Interior</span></div>', html)
        self.assertIn("<h2>Que se sabe</h2>", html)
        self.assertIn("<ul><li>Primer dato</li><li>Segundo dato</li></ul>", html)

    def test_validation_rejects_invented_facts(self):
        noticia = sample_news(
            parrafos=[
                "El Ministerio de Salud informo una jornada el 26 de junio con 15 instituciones.",
            ]
        )
        result = EditorialResult(
            title="Juan Perez anuncio 99 instituciones",
            excerpt="El acto sera el 28 de julio.",
            lead="Juan Perez anuncio 99 instituciones para el 28 de julio.",
            source_paragraph="Segun publico Tiempo Popular, la actividad fue informada.",
            sections=[EditorialSection(heading="Detalles", paragraphs=["Participaron 99 instituciones."])],
        )
        editorial.render_editorial_html(result)

        warnings = editorial.validate_editorial_result(result, noticia, check_similarity=False)

        self.assertTrue(any(w.startswith("invented_number:99") for w in warnings))
        self.assertTrue(any(w.startswith("invented_date:28 de julio") for w in warnings))
        self.assertTrue(any("Juan Perez" in w for w in warnings))

    def test_validation_accepts_numeric_digits_when_source_uses_spanish_words(self):
        noticia = sample_news(
            parrafos=[
                "Se sortearon tres autos: dos unidades para Capital y una para el interior.",
            ]
        )
        result = editorial.build_fallback_editorial(noticia)
        result.lead = "El sorteo entregó 3 autos."
        result.sections = [
            EditorialSection(
                heading="Distribución",
                paragraphs=["La organización destinó 2 unidades a Capital y 1 al interior."],
            )
        ]
        editorial.render_editorial_html(result)

        warnings = editorial.validate_editorial_result(
            result,
            noticia,
            check_similarity=False,
        )

        self.assertFalse(any(w == "invented_number:2" for w in warnings), warnings)
        self.assertFalse(any(w == "invented_number:3" for w in warnings), warnings)

    def test_validation_does_not_treat_articles_as_numeric_one(self):
        noticia = sample_news(
            parrafos=["Fue un encuentro con una propuesta cultural para toda la familia."]
        )
        result = editorial.build_fallback_editorial(noticia)
        result.title = "Se entregó 1 premio"
        result.lead = "La organización entregó 1 premio durante el encuentro."
        editorial.render_editorial_html(result)

        warnings = editorial.validate_editorial_result(
            result,
            noticia,
            check_similarity=False,
        )

        self.assertIn("invented_number:1", warnings)

    def test_validation_rejects_disallowed_html(self):
        noticia = sample_news()
        result = editorial.build_fallback_editorial(noticia)
        result.content_html += "\n<script>alert(1)</script>"

        warnings = editorial.validate_editorial_result(result, noticia, check_similarity=False)

        self.assertIn("disallowed_html_tag:script", warnings)

    def test_generic_editorial_nouns_and_leading_connectors_are_not_proper_names(self):
        noticia = sample_news()
        result = editorial.build_fallback_editorial(noticia)
        result.title = "Avanza el operativo tras un trágico fallecimiento en Aimogasta"
        result.lead = "En Capital continúan las tareas informadas. Están activas."
        editorial.render_editorial_html(result)

        warnings = editorial.validate_editorial_result(
            result,
            noticia,
            check_similarity=False,
        )

        self.assertFalse(
            any("Fallecimiento" in warning for warning in warnings),
            warnings,
        )
        self.assertFalse(any("Avanza" in warning for warning in warnings), warnings)
        self.assertFalse(any("Están" in warning for warning in warnings), warnings)
        self.assertFalse(any("En Capital" in warning for warning in warnings), warnings)

    def test_validation_still_rejects_single_invented_name_inside_sentence(self):
        noticia = sample_news()
        result = editorial.build_fallback_editorial(noticia)
        result.lead = "La actividad se realizará en Córdoba."
        editorial.render_editorial_html(result)

        warnings = editorial.validate_editorial_result(
            result,
            noticia,
            check_similarity=False,
        )

        self.assertTrue(any("Córdoba" in warning for warning in warnings), warnings)

    def test_prepare_editorial_retries_when_quality_score_is_low(self):
        noticia = sample_news()
        low_quality = {
            "title": "Vialidad Provincial intensifica mejoras viales en Aimogasta",
            "excerpt": "Vialidad Provincial informo nuevas tareas de mantenimiento vial en rutas riojanas.",
            "lead": "Los equipos de Vialidad Provincial trabajan sobre rutas de Capital y Aimogasta.",
            "source_paragraph": "Segun publico Tiempo Popular, Vialidad Provincial avanzo con tareas viales.",
            "sections": [
                {
                    "heading": "Trabajos en marcha",
                    "paragraphs": [
                        "Las tareas incluyen conservacion, limpieza de banquinas y mejoras en caminos rurales.",
                    ],
                }
            ],
            "closing_paragraph": "",
            "key_points": ["Aimogasta", "Vialidad Provincial"],
            "seo_title": "Vialidad Provincial mejora rutas en Aimogasta",
            "meta_description": "La nota detalla trabajos de mantenimiento vial en rutas de Capital y Aimogasta.",
            "social_title": "Vialidad Provincial mejora rutas en Aimogasta",
            "social_description": "Las tareas incluyen limpieza de banquinas, perfilado y mejoras en caminos rurales.",
            "focus_keyword": "Vialidad Provincial",
            "quality_score": 0.5,
            "tags": ["Aimogasta", "Vialidad Provincial"],
        }
        high_quality = dict(
            low_quality,
            quality_score=0.92,
            lead=(
                "Vialidad Provincial mantiene tareas sobre rutas de Capital "
                "y Aimogasta."
            ),
        )

        with patch.dict(
            os.environ,
            {
                "ENABLE_EDITORIAL_NEWS_ENRICHER": "true",
                "EDITORIAL_ENRICHER_MAX_REVISIONS": "1",
                "EDITORIAL_ENRICHER_MIN_SCORE": "0.86",
            },
            clear=False,
        ), patch(
            "pipeline.node_webapp.editorial._call_ai_enricher",
            side_effect=[low_quality, high_quality],
        ) as call_ai:
            result = editorial.prepare_editorial(noticia)

        self.assertFalse(result.fallback_used)
        self.assertEqual(result.quality_score, 0.92)
        self.assertEqual(call_ai.call_count, 2)
        self.assertIsNone(call_ai.call_args_list[0].kwargs["feedback"])
        self.assertIsNone(call_ai.call_args_list[0].kwargs["previous_attempt"])
        self.assertIn("quality_score_below_threshold", call_ai.call_args_list[1].kwargs["feedback"])
        previous_attempt = call_ai.call_args_list[1].kwargs["previous_attempt"]
        self.assertEqual(
            previous_attempt["title"],
            "Vialidad Provincial intensifica mejoras viales en Aimogasta",
        )
        self.assertEqual(previous_attempt["quality_score"], 0.5)

    def test_feedback_covers_every_rejection_reason(self):
        feedback = editorial._feedback_for_warnings(
            [
                "invented_number:99",
                "copy_paste_similarity:0.95",
                "quality_score_below_threshold:0.50",
                "disallowed_html_tag:script",
                "unsafe_judicial_claim:es culpable",
                "revision_no_material_change",
            ],
            min_score=0.86,
        )

        self.assertIn("99", feedback)
        self.assertIn("reorganiza", feedback.lower())
        self.assertIn("0.86", feedback)
        self.assertIn("html", feedback.lower())
        self.assertIn("culpabilidad", feedback.lower())
        self.assertIn("cambios materiales", feedback.lower())

    def test_openai_payload_contains_feedback_and_previous_attempt(self):
        create = Mock(
            return_value=SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(content='{"quality_score": 0.9}')
                    )
                ]
            )
        )
        client = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(create=create),
            )
        )
        previous = {
            "title": "Intento anterior",
            "lead": "Texto anterior",
            "quality_score": 0.5,
        }

        with patch.dict(
            os.environ,
            {
                "OPENAI_API_KEY": "test-only",
                "OPENAI_RETRY_COUNT": "1",
            },
            clear=False,
        ), patch("openai.OpenAI", return_value=client):
            editorial._call_ai_enricher(
                sample_news(),
                feedback="Cambiar estructura y titulo",
                previous_attempt=previous,
            )

        user_payload = json.loads(create.call_args.kwargs["messages"][1]["content"])
        self.assertEqual(
            user_payload["revision_feedback"],
            "Cambiar estructura y titulo",
        )
        self.assertEqual(user_payload["previous_attempt"], previous)
        self.assertEqual(create.call_args.kwargs["temperature"], 0.55)

    def test_identical_revision_receives_explicit_no_change_feedback(self):
        noticia = sample_news()
        low_quality = {
            "title": "Vialidad Provincial intensifica mejoras viales en Aimogasta",
            "excerpt": "Vialidad Provincial informo tareas de mantenimiento vial.",
            "lead": "Los equipos trabajan sobre rutas de Capital y Aimogasta.",
            "source_paragraph": "Segun publico Tiempo Popular, avanzaron las tareas viales.",
            "sections": [
                {
                    "heading": "Trabajos en marcha",
                    "paragraphs": ["Las tareas incluyen conservacion y limpieza de banquinas."],
                }
            ],
            "closing_paragraph": "",
            "key_points": ["Aimogasta", "Vialidad Provincial"],
            "seo_title": "Vialidad Provincial mejora rutas",
            "meta_description": "Trabajos de mantenimiento vial.",
            "social_title": "Mejoras en rutas",
            "social_description": "Continuan las tareas viales.",
            "focus_keyword": "Vialidad Provincial",
            "quality_score": 0.5,
            "tags": ["Aimogasta", "Vialidad Provincial"],
        }
        accepted = dict(
            low_quality,
            quality_score=0.92,
            title="Mejoras viales avanzan en Aimogasta",
        )

        with patch.dict(
            os.environ,
            {
                "ENABLE_EDITORIAL_NEWS_ENRICHER": "true",
                "EDITORIAL_ENRICHER_MAX_REVISIONS": "2",
                "EDITORIAL_ENRICHER_MIN_SCORE": "0.86",
            },
            clear=False,
        ), patch(
            "pipeline.node_webapp.editorial._call_ai_enricher",
            side_effect=[low_quality, low_quality, accepted],
        ) as call_ai:
            result = editorial.prepare_editorial(noticia)

        self.assertFalse(result.fallback_used)
        self.assertEqual(call_ai.call_count, 3)
        self.assertIn(
            "revision_no_material_change",
            call_ai.call_args_list[2].kwargs["feedback"],
        )
        self.assertIn(
            "cambios materiales",
            call_ai.call_args_list[2].kwargs["feedback"].lower(),
        )

    def test_changing_only_self_reported_score_is_not_a_material_revision(self):
        noticia = sample_news()
        payload = {
            "title": "Vialidad Provincial intensifica mejoras viales en Aimogasta",
            "excerpt": "Vialidad Provincial informo tareas de mantenimiento vial.",
            "lead": "Los equipos trabajan sobre rutas de Capital y Aimogasta.",
            "source_paragraph": "Segun publico Tiempo Popular, avanzaron las tareas.",
            "sections": [
                {
                    "heading": "Trabajos en marcha",
                    "paragraphs": ["Las tareas incluyen conservacion de caminos."],
                }
            ],
            "closing_paragraph": "",
            "key_points": ["Aimogasta", "Vialidad Provincial"],
            "seo_title": "Vialidad Provincial mejora rutas",
            "meta_description": "Trabajos de mantenimiento vial.",
            "social_title": "Mejoras en rutas",
            "social_description": "Continuan las tareas viales.",
            "focus_keyword": "Vialidad Provincial",
            "quality_score": 0.5,
            "tags": ["Aimogasta", "Vialidad Provincial"],
        }

        with patch.dict(
            os.environ,
            {
                "ENABLE_EDITORIAL_NEWS_ENRICHER": "true",
                "EDITORIAL_ENRICHER_MAX_REVISIONS": "1",
                "EDITORIAL_ENRICHER_MIN_SCORE": "0.86",
                "EDITORIAL_FINAL_ATTEMPT_ACTION": "publish_last_safe",
            },
            clear=False,
        ), patch(
            "pipeline.node_webapp.editorial._call_ai_enricher",
            side_effect=[payload, dict(payload, quality_score=0.92)],
        ):
            result = editorial.prepare_editorial(noticia)

        self.assertTrue(result.final_attempt_used)
        self.assertIn("revision_no_material_change", result.warnings)
        self.assertEqual(
            [],
            result.revision_history[-1]["material_changed_fields"],
        )

    def test_sixth_safe_attempt_is_published_instead_of_original_fallback(self):
        noticia = sample_news(titulo="Titulo original")
        attempts = []
        for number in range(1, 7):
            attempts.append(
                {
                    "title": f"Version editorial {number}",
                    "excerpt": "Resumen editorial verificable.",
                    "lead": "Vialidad Provincial informo tareas sobre rutas riojanas.",
                    "source_paragraph": "Segun publico Tiempo Popular, avanzaron las tareas.",
                    "sections": [
                        {
                            "heading": "Trabajos en marcha",
                            "paragraphs": ["Las tareas incluyen conservacion de caminos."],
                        }
                    ],
                    "closing_paragraph": "",
                    "key_points": ["Aimogasta", "Vialidad Provincial"],
                    "seo_title": f"Version editorial {number}",
                    "meta_description": "Trabajos viales en La Rioja.",
                    "social_title": f"Version editorial {number}",
                    "social_description": "Continuan las tareas viales.",
                    "focus_keyword": "Vialidad Provincial",
                    "quality_score": 0.92,
                    "tags": ["Aimogasta", "Vialidad Provincial"],
                }
            )

        with patch.dict(
            os.environ,
            {
                "ENABLE_EDITORIAL_NEWS_ENRICHER": "true",
                "EDITORIAL_ENRICHER_MAX_REVISIONS": "5",
                "EDITORIAL_ENRICHER_MIN_SCORE": "0.86",
                "EDITORIAL_FINAL_ATTEMPT_ACTION": "publish_last_safe",
            },
            clear=False,
        ), patch(
            "pipeline.node_webapp.editorial._call_ai_enricher",
            side_effect=attempts,
        ), patch(
            "pipeline.node_webapp.editorial.validate_editorial_result",
            return_value=["copy_paste_similarity:0.95"],
        ):
            result = editorial.prepare_editorial(noticia)

        self.assertEqual(result.title, "Version editorial 6")
        self.assertTrue(result.fallback_used)
        self.assertTrue(result.final_attempt_used)
        self.assertEqual(result.attempt_count, 6)
        self.assertIn("copy_paste_similarity:0.95", result.warnings)


class PayloadAndApiTests(unittest.TestCase):
    def test_build_post_payload_uses_private_api_contract_fields(self):
        noticia = sample_news()
        result = editorial.build_fallback_editorial(noticia)
        media_result = MediaResult(
            ok=True,
            main_image={
                "url": "https://media.lavozriojana.com/noticias/2026/06/a.webp",
                "width": 1200,
                "height": 800,
                "alt": "Alt",
                "caption": "Caption",
                "credit": "Tiempo Popular",
            },
            og_image_url="https://media.lavozriojana.com/og/a.jpg",
        )

        with patch.dict(os.environ, {"WEBAPP_DEFAULT_AUTHOR": "Redaccion La Voz Riojana"}, clear=False):
            payload = publisher.build_post_payload(
                noticia,
                result,
                media_result,
                published_at="2026-06-30T12:00:00Z",
            )

        self.assertEqual(payload["categorySlug"], "interior")
        self.assertEqual(payload["status"], "published")
        self.assertEqual(payload["publishedAt"], "2026-06-30T12:00:00Z")
        self.assertEqual(payload["authorName"], "Redacción Interior")
        self.assertIn("contentHtml", payload)
        self.assertIn("mainImage", payload)
        self.assertEqual(payload["ogImageUrl"], "https://media.lavozriojana.com/og/a.jpg")
        self.assertEqual(payload["sourceUrl"], noticia["canonical_url"])
        self.assertEqual(payload["sourceName"], "Tiempo Popular")
        self.assertEqual(payload["metadata"]["sourceName"], "Tiempo Popular")
        self.assertIn("externalId", payload["metadata"])

    def test_validate_post_payload_rejects_invalid_contract_fields(self):
        payload = {
            "title": "Corto",
            "excerpt": "Breve",
            "contentHtml": "",
            "categorySlug": "categoria-libre",
            "status": "published",
            "publishedAt": "2999-01-01T00:00:00Z",
            "mainImage": {"url": "nota-local.jpg", "width": 0, "height": "x", "alt": ""},
            "tags": ["", "x" * 101],
        }

        warnings = publisher.validate_post_payload(payload)

        self.assertIn("title_length_out_of_range:5", warnings)
        self.assertIn("excerpt_length_out_of_range:5", warnings)
        self.assertIn("contentHtml_empty", warnings)
        self.assertIn("invalid_categorySlug:categoria-libre", warnings)
        self.assertIn("publishedAt_in_future", warnings)
        self.assertIn("mainImage_url_invalid", warnings)
        self.assertIn("mainImage_width_invalid", warnings)
        self.assertIn("mainImage_height_invalid", warnings)
        self.assertIn("mainImage_alt_required", warnings)
        self.assertIn("invalid_tag_length:0", warnings)
        self.assertIn("invalid_tag_length:101", warnings)

    def test_classify_reclassifies_scraper_locales_section(self):
        noticia = sample_news(seccion="locales")
        with patch("pipeline.node_webapp.publisher._clasificar", return_value="Politica") as classifier:
            result = publisher.classify(noticia)

        self.assertEqual(result, "Politica")
        classifier.assert_called_once()

    def test_classify_keeps_valid_editorial_section(self):
        noticia = sample_news(seccion="Interior")
        with patch("pipeline.node_webapp.publisher._clasificar") as classifier:
            result = publisher.classify(noticia)

        self.assertEqual(result, "Interior")
        classifier.assert_not_called()

    def test_classify_prefers_web_categoria_over_scraper_section(self):
        noticia = sample_news(seccion="locales", categoria="Politica")
        with patch("pipeline.node_webapp.publisher._clasificar") as classifier:
            result = publisher.classify(noticia)

        self.assertEqual(result, "Politica")
        classifier.assert_not_called()

    def test_post_payload_accepts_only_200_201_with_ok_true(self):
        payload = {"title": "Nota"}
        env = {
            "WEBAPP_BASE_URL": "https://lavozriojana.com.ar",
            "PRIVATE_API_KEY": "secret",
            "WEBAPP_REQUEST_RETRIES": "1",
        }

        with patch.dict(os.environ, env, clear=False), patch(
            "pipeline.node_webapp.publisher.requests.post",
            return_value=FakeResponse(201, {"ok": True}),
        ) as post:
            self.assertTrue(publisher.post_payload(payload))
            args, kwargs = post.call_args
            self.assertEqual(args[0], "https://lavozriojana.com.ar/api/private/posts")
            self.assertEqual(kwargs["headers"]["x-api-key"], "secret")

        with patch.dict(os.environ, env, clear=False), patch(
            "pipeline.node_webapp.publisher.requests.post",
            return_value=FakeResponse(201, {"ok": False}),
        ):
            self.assertFalse(publisher.post_payload(payload))

        with patch.dict(os.environ, env, clear=False), patch(
            "pipeline.node_webapp.publisher.requests.post",
            return_value=FakeResponse(401, {"ok": False}),
        ):
            with self.assertRaises(publisher.InvalidCredentialError):
                publisher.post_payload(payload)

        with patch.dict(os.environ, env, clear=False), patch(
            "pipeline.node_webapp.publisher.requests.post",
            return_value=FakeResponse(429, {"ok": False}),
        ):
            self.assertFalse(publisher.post_payload(payload))

    def test_sync_meta_web_link_updates_meta_and_social_queues(self):
        noticia = sample_news()
        queue_key = publisher._queue_key(noticia)
        response_data = {"ok": True, "data": {"id": 77, "slug": "vialidad-aimogasta"}}

        with tempfile.TemporaryDirectory() as tmpdir:
            meta_path = Path(tmpdir) / "noticias_meta.json"
            social_path = Path(tmpdir) / "noticias_sociales_pendientes.json"
            meta_path.write_text(json.dumps([{"meta_queue_key": queue_key, "titulo": "Meta"}]), encoding="utf-8")
            social_path.write_text(json.dumps([{"dedup_key": queue_key, "titulo": "Social"}]), encoding="utf-8")

            with patch("pipeline.node_webapp.publisher.META_OUTPUT", str(meta_path)), patch(
                "pipeline.node_webapp.publisher.SOCIAL_OUTPUT",
                str(social_path),
            ):
                public_url = publisher.sync_meta_web_link(
                    noticia,
                    response_data,
                    "https://lavozriojana.com.ar",
                )

            saved_meta = json.loads(meta_path.read_text(encoding="utf-8"))
            saved_social = json.loads(social_path.read_text(encoding="utf-8"))

        self.assertEqual(public_url, "https://lavozriojana.com.ar/noticias/vialidad-aimogasta")
        self.assertEqual(saved_meta[0]["web_url"], public_url)
        self.assertEqual(saved_meta[0]["noticia_url"], public_url)
        self.assertEqual(saved_meta[0]["web_slug"], "vialidad-aimogasta")
        self.assertEqual(saved_meta[0]["web_post_id"], "77")
        self.assertEqual(saved_social[0]["web_url"], public_url)


class MediaTests(unittest.TestCase):
    def test_prepare_media_uploads_main_and_og_with_verified_urls(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            image_path = Path(tmpdir) / "source.jpg"
            work_dir = Path(tmpdir) / "web_media"
            work_dir.mkdir()
            Image.new("RGB", (900, 700), color=(20, 80, 140)).save(image_path, "JPEG")
            noticia = sample_news(imagen_optimizada=str(image_path))
            upload_calls = []

            def fake_upload(path, key, content_type, *, cache_control=None):
                upload_calls.append((Path(path).suffix, key, content_type, cache_control))
                return f"https://media.lavozriojana.com/{key}", key

            with patch("pipeline.node_webapp.media.MEDIA_WORK_DIR", work_dir), patch(
                "pipeline.node_webapp.media.r2_storage.upload_file",
                side_effect=fake_upload,
            ), patch(
                "pipeline.node_webapp.media.verify_public_image_url",
                return_value=True,
            ):
                result = media.prepare_media(noticia, noticia["titulo"])

        self.assertTrue(result.ok)
        self.assertEqual(len(upload_calls), 2)
        self.assertTrue(upload_calls[0][1].startswith("noticias/2026/06/"))
        self.assertEqual(upload_calls[0][2], "image/webp")
        self.assertEqual(upload_calls[0][3], "public, max-age=31536000, immutable")
        self.assertTrue(upload_calls[1][1].startswith("og/"))
        self.assertEqual(upload_calls[1][2], "image/jpeg")
        self.assertEqual(upload_calls[1][3], "public, max-age=31536000, immutable")
        self.assertEqual(result.main_image["width"], 900)
        self.assertEqual(result.main_image["height"], 700)
        self.assertTrue(result.og_image_url.endswith(".jpg"))

    def test_verify_public_image_url_requires_image_content_type(self):
        with patch.dict(
            os.environ,
            {
                "WEB_PUBLIC_MEDIA_CHECK_ENABLED": "true",
                "WEB_PUBLIC_MEDIA_CHECK_ATTEMPTS": "1",
                "WEB_PUBLIC_MEDIA_CHECK_INITIAL_DELAY_SECONDS": "0",
            },
            clear=False,
        ), patch("pipeline.node_webapp.media.requests.head", return_value=FakeResponse(200, content_type="image/webp")):
            self.assertTrue(media.verify_public_image_url("https://media.lavozriojana.com/a.webp"))

        with patch.dict(
            os.environ,
            {
                "WEB_PUBLIC_MEDIA_CHECK_ENABLED": "true",
                "WEB_PUBLIC_MEDIA_CHECK_ATTEMPTS": "1",
                "WEB_PUBLIC_MEDIA_CHECK_INITIAL_DELAY_SECONDS": "0",
            },
            clear=False,
        ), patch("pipeline.node_webapp.media.requests.head", return_value=FakeResponse(200, content_type="text/html")), patch(
            "pipeline.node_webapp.media.requests.get",
            return_value=FakeResponse(200, content_type="text/html"),
        ):
            self.assertFalse(media.verify_public_image_url("https://media.lavozriojana.com/a.webp"))

    def test_verify_public_image_url_respects_disabled_flag(self):
        with patch.dict(
            os.environ,
            {"WEB_PUBLIC_MEDIA_CHECK_ENABLED": "false"},
            clear=False,
        ), patch("pipeline.node_webapp.media.requests.head") as head:
            self.assertTrue(media.verify_public_image_url("https://media.lavozriojana.com/a.webp"))
            head.assert_not_called()


class ImageGeneratorTests(unittest.TestCase):
    def test_facebook_generator_size_is_og_ratio(self):
        self.assertEqual((image_generator.FB_W, image_generator.FB_H), (1200, 630))


class FacebookClientTests(unittest.TestCase):
    def test_link_preview_prewarm_requires_public_og_image(self):
        page = FakeResponse(200, None)
        page.text = (
            '<html><head><meta property="og:image" '
            'content="https://media.lavozriojana.com/og/nota.jpg"></head></html>'
        )
        page.headers = {"Content-Type": "text/html; charset=utf-8"}
        image = FakeResponse(200, None)
        image.headers = {"Content-Type": "image/jpeg"}

        with patch("meta.fb_client.safe_get", side_effect=[page, image]) as get:
            result = fb_client.prewarm_link_preview(
                "https://lavozriojana.com.ar/noticias/nota"
            )

        self.assertTrue(result.ok)
        self.assertEqual(result.details["og_image_url"], "https://media.lavozriojana.com/og/nota.jpg")
        self.assertEqual(get.call_count, 2)
        self.assertIn("facebookexternalhit", get.call_args_list[0].kwargs["headers"]["User-Agent"])

    def test_link_preview_prewarm_fails_without_og_image(self):
        page = FakeResponse(200, None)
        page.text = "<html><head><title>Nota</title></head></html>"
        page.headers = {"Content-Type": "text/html"}

        with patch("meta.fb_client.safe_get", return_value=page):
            result = fb_client.prewarm_link_preview(
                "https://lavozriojana.com.ar/noticias/nota"
            )

        self.assertEqual(result.status, StageStatus.DEGRADED)
        self.assertEqual(result.error_type, "link_preview_missing_og_image")

    def test_facebook_posts_meta_text_with_web_link_preview(self):
        noticia = sample_news(
            texto_instagram="Texto corto para Meta",
            web_url="https://lavozriojana.com.ar/noticias/vialidad-aimogasta",
            dedup_key="link:test",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "fb_posted.json"
            with patch("meta.fb_client.PAGE_ID", "page123"), patch(
                "meta.fb_client.FB_STATE_PATH",
                str(state_path),
            ), patch("meta.fb_client.DISABLED_PAGE_IDS", set()), patch(
                "meta.fb_client.get_page_token",
                return_value="token",
            ), patch(
                "meta.fb_client.prewarm_link_preview",
                return_value=OperationResult(StageStatus.SUCCESS),
            ) as prewarm, patch(
                "meta.fb_client._prewarm_enabled",
                return_value=True,
            ), patch(
                "meta.fb_client.requests.post",
                return_value=FakeResponse(200, {"id": "page123_1"}),
            ) as post:
                ok = fb_client.post_to_facebook(noticia)

            saved_state = json.loads(state_path.read_text(encoding="utf-8"))

        self.assertTrue(ok)
        args, kwargs = post.call_args
        self.assertEqual(args[0], f"{fb_client.GRAPH_API}/page123/feed")
        self.assertEqual(kwargs["data"]["link"], noticia["web_url"])
        self.assertTrue(kwargs["data"]["message"].startswith(noticia["titulo"]))
        self.assertIn(ig_client._build_caption(noticia), kwargs["data"]["message"])
        self.assertIn(noticia["web_url"], kwargs["data"]["message"])
        self.assertNotIn("files", kwargs)
        self.assertIn("link:test", saved_state["posted"])
        prewarm.assert_called_once_with(noticia["web_url"])

    def test_facebook_waits_when_web_link_is_missing(self):
        noticia = sample_news(texto_instagram="Texto corto para Meta")

        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "fb_posted.json"
            with patch("meta.fb_client.PAGE_ID", "page123"), patch(
                "meta.fb_client.FB_STATE_PATH",
                str(state_path),
            ), patch("meta.fb_client.DISABLED_PAGE_IDS", set()), patch(
                "meta.fb_client.get_page_token",
            ) as token, patch("meta.fb_client.requests.post") as post:
                ok = fb_client.post_to_facebook(noticia)

        self.assertFalse(ok)
        token.assert_not_called()
        post.assert_not_called()


class InstagramVideoClientTests(unittest.TestCase):
    def test_instagram_posts_video_as_reel(self):
        noticia = {
            "media_type": "video",
            "video_url": "https://media.lavozriojana.com/reels/test.mp4",
            "source_video_url": "https://youtube.com/watch?v=abc",
            "titulo": "Video policial",
            "texto_instagram": "Caption del video",
            "seccion": "Policiales",
            "dedup_key": "video:test",
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "ig_posted.json"
            with patch("meta.ig_client.IG_ACCOUNT_ID", "ig123"), patch(
                "meta.ig_client.IG_ACCESS_TOKEN",
                "token",
            ), patch(
                "meta.ig_client.IG_STATE_PATH",
                str(state_path),
            ), patch(
                "meta.ig_client.is_rate_limited",
                return_value=False,
            ), patch(
                "meta.ig_client.IG_VIDEO_PROCESSING_POLL_SECONDS",
                0,
            ), patch(
                "meta.ig_client.requests.get",
                return_value=FakeResponse(200, {"status_code": "FINISHED"}),
            ), patch(
                "meta.ig_client.requests.post",
                side_effect=[
                    FakeResponse(200, {"id": "container123"}),
                    FakeResponse(200, {"id": "media123"}),
                ],
            ) as post:
                ok = ig_client.post_to_instagram(noticia)

            saved_state = json.loads(state_path.read_text(encoding="utf-8"))

        self.assertTrue(ok)
        first_call = post.call_args_list[0]
        self.assertEqual(first_call.args[0], f"{ig_client.GRAPH_API}/ig123/media")
        self.assertEqual(first_call.kwargs["data"]["media_type"], "REELS")
        self.assertEqual(first_call.kwargs["data"]["video_url"], noticia["video_url"])
        self.assertIn("Caption del video", first_call.kwargs["data"]["caption"])
        self.assertIn("video:test", saved_state["posted"])
        self.assertEqual(saved_state["posted"]["video:test"]["titulo"], "Video policial")

    def test_instagram_skips_similar_without_fabricating_publication_record(self):
        noticia = {
            "titulo": "Búsqueda de adolescente desaparecido en Chilecito",
            "texto_instagram": "Caption nuevo",
            "seccion": "Policiales",
            "dedup_key": "link:new",
            "imagen_url": "https://media.lavozriojana.com/post.jpg",
        }
        previous_state = {
            "posted": {
                "link:old": {
                    "posted_at": 123,
                    "dedup_key": "link:old",
                    "titulo": "Buscan adolescente desaparecido en Chilecito",
                    "url": "https://example.com/old",
                }
            }
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "ig_posted.json"
            state_path.write_text(json.dumps(previous_state), encoding="utf-8")
            with patch("meta.ig_client.IG_ACCOUNT_ID", "ig123"), patch(
                "meta.ig_client.IG_ACCESS_TOKEN",
                "token",
            ), patch(
                "meta.ig_client.IG_STATE_PATH",
                str(state_path),
            ), patch(
                "meta.ig_client.is_rate_limited",
                return_value=False,
            ), patch(
                "meta.ig_client.requests.post",
            ) as post:
                ok = ig_client.post_to_instagram(noticia)

            saved_state = json.loads(state_path.read_text(encoding="utf-8"))

        self.assertTrue(ok)
        post.assert_not_called()
        self.assertNotIn("link:new", saved_state["posted"])
        self.assertIn("link:old", saved_state["posted"])


class ManualVideoQueueTests(unittest.TestCase):
    def test_enqueue_video_requires_direct_public_video_and_deduplicates(self):
        payload = {
            "source_url": "https://www.youtube.com/watch?v=abc",
            "video_url": "https://media.lavozriojana.com/reels/abc.mp4",
            "title": "Jurado confirma nuevas medidas de seguridad",
            "caption": "Caption del reel",
            "seccion": "Policiales",
            "top_text": "Ultimo momento",
            "bottom_text": "Seguinos",
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            queue_path = Path(tmpdir) / "noticias_sociales_pendientes.json"
            with patch("utils.manual_video_queue.SOCIAL_QUEUE_PATH", str(queue_path)):
                item, added_first = manual_video_queue.enqueue_video(payload)
                _same_item, added_second = manual_video_queue.enqueue_video(payload)
                saved = json.loads(queue_path.read_text(encoding="utf-8"))

        self.assertTrue(added_first)
        self.assertFalse(added_second)
        self.assertEqual(len(saved), 1)
        self.assertEqual(item["media_type"], "video")
        self.assertEqual(item["source_platform"], "youtube")
        self.assertEqual(item["seccion"], "policiales")
        self.assertEqual(saved[0]["video_url"], payload["video_url"])

    def test_save_video_draft_accepts_source_link_without_direct_mp4(self):
        payload = {
            "source_url": "https://www.instagram.com/reel/abc/",
            "title": "Video del interior",
            "caption": "Caption",
            "seccion": "Interior",
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            drafts_path = Path(tmpdir) / "videos_manuales_borradores.json"
            with patch("utils.manual_video_queue.DRAFTS_PATH", str(drafts_path)):
                item, added = manual_video_queue.save_video_draft(payload)
                saved = json.loads(drafts_path.read_text(encoding="utf-8"))

        self.assertTrue(added)
        self.assertEqual(item["manual_status"], "draft")
        self.assertTrue(item["needs_direct_video_url"])
        self.assertEqual(saved[0]["source_platform"], "instagram")


class QueueTests(unittest.TestCase):
    def test_publish_pending_removes_only_successful_items(self):
        noticias = [
            {"titulo": "A", "web_queue_key": "link:a"},
            {"titulo": "B", "web_queue_key": "link:b"},
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            queue = Path(tmpdir) / "noticias_web_pending.json"
            history = Path(tmpdir) / "noticias_web_publicadas.json"
            queue.write_text(json.dumps(noticias), encoding="utf-8")
            with patch("pipeline.node_webapp.publisher.INPUT", str(queue)), patch(
                "pipeline.node_webapp.publisher.PUBLISHED_HISTORY",
                str(history),
            ), patch(
                "pipeline.node_webapp.publisher.publish_one_detailed",
                side_effect=[
                    {"published": True, "featured": False, "error": None},
                    {
                        "published": False,
                        "featured": False,
                        "error": "network_error",
                        "retryable": True,
                        "terminal": False,
                    },
                ],
            ):
                publisher.publish_pending()

            saved = json.loads(queue.read_text(encoding="utf-8"))
        self.assertEqual([item["titulo"] for item in saved], ["B"])

    def test_publish_pending_stops_batch_on_401_and_keeps_rest(self):
        noticias = [
            {"titulo": "A", "web_queue_key": "link:a"},
            {"titulo": "B", "web_queue_key": "link:b"},
            {"titulo": "C", "web_queue_key": "link:c"},
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            queue = Path(tmpdir) / "noticias_web_pending.json"
            history = Path(tmpdir) / "noticias_web_publicadas.json"
            queue.write_text(json.dumps(noticias), encoding="utf-8")
            with patch("pipeline.node_webapp.publisher.INPUT", str(queue)), patch(
                "pipeline.node_webapp.publisher.PUBLISHED_HISTORY",
                str(history),
            ), patch(
                "pipeline.node_webapp.publisher.publish_one_detailed",
                side_effect=[
                    {"published": True, "featured": False, "error": None},
                    publisher.InvalidCredentialError("bad key"),
                ],
            ):
                publisher.publish_pending()

            saved = json.loads(queue.read_text(encoding="utf-8"))
        self.assertEqual([item["titulo"] for item in saved], ["B", "C"])

    def test_publish_pending_reports_rate_limit_as_degraded_and_defers_rest(self):
        noticias = [
            {"titulo": "A", "web_queue_key": "link:a"},
            {"titulo": "B", "web_queue_key": "link:b"},
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            queue = Path(tmpdir) / "noticias_web_pending.json"
            history = Path(tmpdir) / "noticias_web_publicadas.json"
            queue.write_text(json.dumps(noticias), encoding="utf-8")
            with patch("pipeline.node_webapp.publisher.INPUT", str(queue)), patch(
                "pipeline.node_webapp.publisher.PUBLISHED_HISTORY",
                str(history),
            ), patch(
                "pipeline.node_webapp.publisher.publish_one_detailed",
                return_value={
                    "published": False,
                    "featured": False,
                    "error": "rate_limit",
                    "retryable": True,
                    "terminal": False,
                    "next_retry_at": 9999999999,
                },
            ):
                result = publisher.publish_pending()
            saved = json.loads(queue.read_text(encoding="utf-8"))
        self.assertEqual(result.status.value, "degraded")
        self.assertEqual(result.exit_code, 2)
        self.assertEqual(result.next_retry_at, 9999999999)
        self.assertEqual([item["titulo"] for item in saved], ["A", "B"])

    def test_publish_pending_prioritizes_sections_and_defers_extra_deportes(self):
        noticias = [
            {"titulo": "dep1", "web_queue_key": "link:dep1", "categoria": "Deportes"},
            {"titulo": "dep2", "web_queue_key": "link:dep2", "categoria": "Deportes"},
            {"titulo": "pol1", "web_queue_key": "link:pol1", "categoria": "Policiales"},
            {"titulo": "int1", "web_queue_key": "link:int1", "categoria": "Interior"},
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            queue = Path(tmpdir) / "noticias_web_pending.json"
            history = Path(tmpdir) / "noticias_web_publicadas.json"
            queue.write_text(json.dumps(noticias), encoding="utf-8")
            with patch("pipeline.node_webapp.publisher.INPUT", str(queue)), patch(
                "pipeline.node_webapp.publisher.PUBLISHED_HISTORY",
                str(history),
            ), patch.dict(
                os.environ,
                {"WEB_MAX_DEPORTES_PER_RUN": "1", "WEB_PUBLISH_MAX_PER_RUN": "0"},
                clear=False,
            ), patch(
                "pipeline.node_webapp.publisher.publish_one_detailed",
                return_value={"published": True, "featured": False, "error": None},
            ) as publish_one:
                publisher.publish_pending()

            saved = json.loads(queue.read_text(encoding="utf-8"))

        self.assertEqual(
            [call.args[0]["titulo"] for call in publish_one.call_args_list],
            ["pol1", "int1", "dep1"],
        )
        self.assertEqual([item["titulo"] for item in saved], ["dep2"])

    def test_filter_publish_duplicates_skips_cross_source_pending_and_history(self):
        history = [
            sample_news(
                titulo="Vialidad Provincial mejora rutas en Aimogasta",
                titulo_original="Vialidad Provincial mejora rutas en Aimogasta",
                web_queue_key="link:old",
                source="tiempopopular_interior",
            )
        ]
        duplicate = sample_news(
            titulo="Vialidad Provincial mejora rutas en Aimogasta",
            titulo_original="Vialidad Provincial mejora rutas en Aimogasta",
            canonical_url="https://nuevarioja.com.ar/interior/vialidad-provincial-mejora-rutas-en-aimogasta.htm",
            source="nuevarioja_interior",
            web_queue_key="link:new",
        )
        fresh = sample_news(
            titulo="El municipio anuncio una nueva obra en Chilecito",
            titulo_original="El municipio anuncio una nueva obra en Chilecito",
            canonical_url="https://nuevarioja.com.ar/interior/obra-chilecito.htm",
            web_queue_key="link:fresh",
            parrafos=[
                "El municipio informo avances en una obra urbana que mejorara la circulacion en Chilecito.",
                "Los trabajos forman parte de un plan local con intervenciones en distintos barrios.",
            ],
        )

        unique, skipped = publisher._filter_publish_duplicates([duplicate, fresh], history)

        self.assertEqual(skipped, 1)
        self.assertEqual([item["titulo"] for item in unique], [fresh["titulo"]])

        unique, skipped = publisher._filter_publish_duplicates([fresh, dict(fresh, web_queue_key="link:other")], [])

        self.assertEqual(skipped, 1)
        self.assertEqual([item["web_queue_key"] for item in unique], ["link:fresh"])


class SocialQueueTests(unittest.TestCase):
    def test_priority_interleave_prioritizes_and_round_robins_categories(self):
        items = [
            {"titulo": "dep1", "seccion": "Deportes"},
            {"titulo": "dep2", "seccion": "Deportes"},
            {"titulo": "dep3", "seccion": "Deportes"},
            {"titulo": "pol1", "seccion": "Policiales"},
            {"titulo": "int1", "seccion": "Interior"},
            {"titulo": "soc1", "seccion": "Sociedad"},
            {"titulo": "dep4", "seccion": "Deportes"},
            {"titulo": "pol2", "seccion": "Policiales"},
        ]

        ordered = social_queue._priority_interleave(items)

        self.assertEqual(
            [item["titulo"] for item in ordered],
            ["pol1", "int1", "soc1", "dep1", "pol2", "dep2", "dep3", "dep4"],
        )

    def test_get_pending_applies_social_deportes_cap(self):
        now = int(time.time())
        items = [
            {"titulo": "dep1", "seccion": "Deportes", "social_queued_at": now},
            {"titulo": "dep2", "seccion": "Deportes", "social_queued_at": now},
            {"titulo": "pol1", "seccion": "Policiales", "social_queued_at": now},
            {"titulo": "int1", "seccion": "Interior", "social_queued_at": now},
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            queue_path = Path(tmpdir) / "noticias_sociales_pendientes.json"
            queue_path.write_text(json.dumps(items), encoding="utf-8")
            with patch("utils.social_queue.QUEUE_PATH", str(queue_path)), patch.dict(
                os.environ,
                {"SOCIAL_MAX_DEPORTES_PER_RUN": "1"},
                clear=False,
            ):
                pending = social_queue.get_pending("instagram", max_items=10)

        self.assertEqual([item["titulo"] for item in pending], ["pol1", "int1", "dep1"])

    def test_sync_done_from_posted_state_marks_already_published_items(self):
        items = [
            {"titulo": "repetida", "dedup_key": "link:posted", "instagram_done": False},
            {"titulo": "nueva", "dedup_key": "link:new", "instagram_done": False},
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            queue_path = Path(tmpdir) / "noticias_sociales_pendientes.json"
            queue_path.write_text(json.dumps(items), encoding="utf-8")
            with patch("utils.social_queue.QUEUE_PATH", str(queue_path)):
                changed = social_queue.sync_done_from_posted_state("instagram", {"link:posted"})
                saved = json.loads(queue_path.read_text(encoding="utf-8"))

        self.assertEqual(changed, 1)
        self.assertTrue(saved[0]["instagram_done"])
        self.assertIn("instagram_done_at", saved[0])
        self.assertFalse(saved[1]["instagram_done"])

    def test_enqueue_can_scope_pending_platform(self):
        noticia = sample_news(titulo="Nota scoped")
        with tempfile.TemporaryDirectory() as tmpdir:
            queue_path = Path(tmpdir) / "noticias_sociales_pendientes.json"
            with patch("utils.social_queue.QUEUE_PATH", str(queue_path)):
                social_queue.enqueue(dict(noticia), platform="facebook")
                saved = json.loads(queue_path.read_text(encoding="utf-8"))
                self.assertFalse(saved[0]["facebook_done"])
                self.assertTrue(saved[0]["instagram_done"])

                social_queue.enqueue(dict(noticia), platform="instagram")
                saved = json.loads(queue_path.read_text(encoding="utf-8"))

        self.assertFalse(saved[0]["facebook_done"])
        self.assertFalse(saved[0]["instagram_done"])

    def test_enqueue_does_not_reactivate_completed_platform(self):
        noticia = sample_news(titulo="Nota ya publicada", dedup_key="link:posted")
        items = [
            {
                "titulo": "Nota ya publicada",
                "dedup_key": "link:posted",
                "facebook_done": False,
                "instagram_done": True,
                "instagram_done_at": 123,
            }
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            queue_path = Path(tmpdir) / "noticias_sociales_pendientes.json"
            queue_path.write_text(json.dumps(items), encoding="utf-8")
            with patch("utils.social_queue.QUEUE_PATH", str(queue_path)):
                social_queue.enqueue(dict(noticia), platform="instagram")
                saved = json.loads(queue_path.read_text(encoding="utf-8"))

        self.assertTrue(saved[0]["instagram_done"])
        self.assertEqual(saved[0]["instagram_done_at"], 123)


class RewriteQueueTests(unittest.TestCase):
    def test_meta_item_is_social_specific_without_full_scrape_body(self):
        noticia = sample_news(
            imagen="C:/local/raw.jpg",
            imagen_optimizada="C:/local/opt.jpg",
            titulo_instagram="Titulo social",
            texto_instagram="Caption social",
            cta="Pregunta",
            queued_at=123,
        )

        item = rewrite_news.build_meta_item(noticia)

        self.assertEqual(item["texto_instagram"], "Caption social")
        self.assertEqual(item["excerpt"], noticia["parrafos"][0])
        self.assertIn("meta_queue_key", item)
        self.assertNotIn("parrafos", item)
        self.assertNotIn("imagen", item)
        self.assertNotIn("imagen_optimizada", item)

    def test_web_item_keeps_complete_scraped_news_without_social_fields(self):
        noticia = sample_news(
            titulo="Titulo original scrapeado",
            seccion="locales",
            imagen="C:/local/raw.jpg",
            imagen_optimizada="C:/local/opt.jpg",
            texto_instagram="Caption social",
            cta="Pregunta",
            queued_at=123,
        )

        item = rewrite_news.build_web_item(
            noticia,
            editorial_seed={"titulo_instagram": "Titulo social", "seccion": "Politica"},
        )

        self.assertEqual(item["titulo"], "Titulo social")
        self.assertEqual(item["titulo_original_scrapeado"], "Titulo original scrapeado")
        self.assertEqual(item["seccion"], "locales")
        self.assertEqual(item["categoria"], "Politica")
        self.assertEqual(item["parrafos"], noticia["parrafos"])
        self.assertEqual(item["imagen"], "C:/local/raw.jpg")
        self.assertEqual(item["imagen_optimizada"], "C:/local/opt.jpg")
        self.assertIn("web_queue_key", item)
        self.assertIn("web_queued_at", item)
        self.assertNotIn("titulo_instagram", item)
        self.assertNotIn("texto_instagram", item)
        self.assertNotIn("cta", item)

    def test_append_queue_items_uses_original_for_web_and_rewritten_for_meta(self):
        original = sample_news(
            titulo="Titulo original scrapeado",
            seccion="locales",
            imagen="C:/local/raw.jpg",
            imagen_optimizada="C:/local/opt.jpg",
        )
        rewritten = dict(
            original,
            titulo="Titulo reescrito para redes",
            seccion="Politica",
            titulo_instagram="Titulo social",
            texto_instagram="Caption social",
            cta="Pregunta",
            queued_at=123,
        )
        pending_meta: list[dict] = []
        pending_web: list[dict] = []

        meta_added, web_added = rewrite_news.append_queue_items(
            original_noticia=original,
            rewritten_noticia=rewritten,
            pending_meta=pending_meta,
            pending_web=pending_web,
        )

        self.assertTrue(meta_added)
        self.assertTrue(web_added)
        self.assertEqual(pending_meta[0]["titulo"], "Titulo reescrito para redes")
        self.assertEqual(pending_meta[0]["seccion"], "Politica")
        self.assertEqual(pending_meta[0]["texto_instagram"], "Caption social")
        self.assertNotIn("parrafos", pending_meta[0])
        self.assertEqual(pending_web[0]["titulo"], "Titulo social")
        self.assertEqual(pending_web[0]["titulo_original_scrapeado"], "Titulo original scrapeado")
        self.assertEqual(pending_web[0]["seccion"], "locales")
        self.assertEqual(pending_web[0]["categoria"], "Politica")
        self.assertEqual(pending_web[0]["parrafos"], original["parrafos"])
        self.assertEqual(pending_web[0]["imagen_optimizada"], "C:/local/opt.jpg")
        self.assertNotIn("titulo_instagram", pending_web[0])

    def test_append_queue_items_skips_cross_source_duplicate_titles(self):
        original = sample_news(
            titulo="Vialidad Provincial mejora rutas en Aimogasta",
            canonical_url="https://www.tiempopopular.com.ar/2026/06/27/vialidad",
            source="tiempopopular_interior",
        )
        rewritten = dict(
            original,
            titulo="Vialidad Provincial mejora rutas en Aimogasta",
            seccion="Interior",
            titulo_instagram="Vialidad Provincial mejora rutas en Aimogasta",
            texto_instagram="Caption social",
        )
        duplicate_original = sample_news(
            titulo="Vialidad Provincial mejora rutas en Aimogasta",
            canonical_url="https://nuevarioja.com.ar/interior/vialidad-provincial-mejora-rutas-en-aimogasta.htm",
            source="nuevarioja_interior",
        )
        duplicate_rewritten = dict(
            duplicate_original,
            titulo="Vialidad Provincial mejora rutas en Aimogasta",
            seccion="Interior",
            titulo_instagram="Vialidad Provincial mejora rutas en Aimogasta",
            texto_instagram="Caption social",
        )
        pending_meta: list[dict] = []
        pending_web: list[dict] = []

        first_meta, first_web = rewrite_news.append_queue_items(
            original_noticia=original,
            rewritten_noticia=rewritten,
            pending_meta=pending_meta,
            pending_web=pending_web,
        )
        dup_meta, dup_web = rewrite_news.append_queue_items(
            original_noticia=duplicate_original,
            rewritten_noticia=duplicate_rewritten,
            pending_meta=pending_meta,
            pending_web=pending_web,
        )

        self.assertTrue(first_meta)
        self.assertTrue(first_web)
        self.assertFalse(dup_meta)
        self.assertFalse(dup_web)
        self.assertEqual(len(pending_meta), 1)
        self.assertEqual(len(pending_web), 1)

    def test_normalize_meta_queue_migrates_legacy_full_items_to_web_queue(self):
        legacy = sample_news(
            imagen="C:/local/raw.jpg",
            imagen_optimizada="C:/local/opt.jpg",
            titulo_instagram="Titulo social",
            texto_instagram="Caption social",
            queued_at=123,
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            meta_path = Path(tmpdir) / "noticias_meta.json"
            web_path = Path(tmpdir) / "noticias_web_pending.json"
            meta_path.write_text(json.dumps([legacy]), encoding="utf-8")
            web_path.write_text("[]", encoding="utf-8")

            with patch("openIA.rewrite_news.META_OUTPUT", str(meta_path)), patch(
                "openIA.rewrite_news.WEB_OUTPUT",
                str(web_path),
            ):
                normalized = rewrite_news.normalize_meta_queue()

            saved_meta = json.loads(meta_path.read_text(encoding="utf-8"))
            saved_web = json.loads(web_path.read_text(encoding="utf-8"))

        self.assertEqual(normalized, saved_meta)
        self.assertNotIn("parrafos", saved_meta[0])
        self.assertEqual(saved_web[0]["parrafos"], legacy["parrafos"])
        self.assertEqual(saved_web[0]["imagen_optimizada"], "C:/local/opt.jpg")


if __name__ == "__main__":
    unittest.main()
