from __future__ import annotations

import importlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock


def _local(key, *, seccion="policiales", video=False):
    item = {
        "titulo": f"local-{key}",
        "canonical_url": f"https://example.com/local-{key}",
        "seccion": seccion,
        "source": "tiempopopular_policiales",
    }
    if video:
        item["video_url"] = f"https://example.com/video-{key}.mp4"
    return item


def _paparazzi(key, *, video=False, score=0):
    item = {
        "titulo": f"paparazzi-{key}",
        "canonical_url": f"https://paparazzi.com.ar/{key}",
        "seccion": "espectaculos",
        "source": "paparazzi",
        "paparazzi_relevance_score": score,
    }
    if video:
        item["video_url"] = f"https://paparazzi.com.ar/video-{key}.mp4"
    return item


def _infobae(key, *, video=False, titulo=None):
    return {
        "titulo": titulo or f"infobae-{key}",
        "canonical_url": f"https://infobae.com/{key}",
        "seccion": "policiales",
        "source": "infobae_policiales",
        **({"video_url": f"https://infobae.com/video-{key}.mp4"} if video else {}),
    }


class SelectBatchPureTests(unittest.TestCase):
    def setUp(self):
        from utils import publish_selection

        self.module = importlib.reload(publish_selection)

    def test_respects_per_bucket_caps(self):
        pending = (
            [_local(i) for i in range(10)]
            + [_paparazzi(i) for i in range(5)]
            + [_infobae(i) for i in range(5)]
        )
        with mock.patch.dict(
            os.environ,
            {
                "PUBLISH_LOCAL_MAX_PER_RUN": "6",
                "PUBLISH_PAPARAZZI_MAX_PER_RUN": "2",
                "PUBLISH_INFOBAE_MAX_PER_RUN": "2",
            },
            clear=False,
        ):
            selected, rest = self.module.select_batch(pending)

        buckets = {"local": 0, "paparazzi": 0, "infobae": 0}
        for item in selected:
            buckets[self.module._bucket_name(item)] += 1
        self.assertEqual({"local": 6, "paparazzi": 2, "infobae": 2}, buckets)
        self.assertEqual(len(pending) - 10, len(rest))

    def test_local_bucket_prioritizes_policiales_and_interior(self):
        """Deportes queda afuera del balde local por completo (categoría de
        relleno excluida) — ver test_local_bucket_never_fills_with_excluded_categories."""
        pending = [
            _local("dep", seccion="deportes"),
            _local("soc", seccion="sociedad"),
            _local("pol", seccion="policiales"),
            _local("int", seccion="interior"),
        ]
        with mock.patch.dict(os.environ, {"PUBLISH_LOCAL_MAX_PER_RUN": "10"}, clear=False):
            selected, _rest = self.module.select_batch(pending)

        self.assertEqual(
            ["local-pol", "local-int", "local-soc"],
            [item["titulo"] for item in selected],
        )

    def test_local_bucket_fills_with_other_non_excluded_categories_when_short_on_priority_ones(self):
        pending = [_local("soc1", seccion="sociedad"), _local("soc2", seccion="sociedad")]
        with mock.patch.dict(os.environ, {"PUBLISH_LOCAL_MAX_PER_RUN": "6"}, clear=False):
            selected, _rest = self.module.select_batch(pending)

        self.assertEqual(2, len(selected))

    def test_paparazzi_bucket_orders_video_first_then_relevance_score(self):
        pending = [
            _paparazzi("no_video_high_score", video=False, score=9),
            _paparazzi("video_low_score", video=True, score=1),
            _paparazzi("video_high_score", video=True, score=8),
        ]
        with mock.patch.dict(os.environ, {"PUBLISH_PAPARAZZI_MAX_PER_RUN": "10"}, clear=False):
            selected, _rest = self.module.select_batch(pending)

        self.assertEqual(
            ["paparazzi-video_high_score", "paparazzi-video_low_score", "paparazzi-no_video_high_score"],
            [item["titulo"] for item in selected],
        )

    def test_infobae_bucket_orders_video_first_then_breaking_keyword_intensity(self):
        pending = [
            _infobae("mild", video=False, titulo="Un hecho policial en la ciudad"),
            _infobae("video_weak", video=True, titulo="Un hecho ocurrido ayer"),
            _infobae(
                "strong_no_video",
                video=False,
                titulo="Femicidio y homicidio en un ataque con disparos",
            ),
        ]
        with mock.patch.dict(os.environ, {"PUBLISH_INFOBAE_MAX_PER_RUN": "10"}, clear=False):
            selected, _rest = self.module.select_batch(pending)

        self.assertEqual("Un hecho ocurrido ayer", selected[0]["titulo"])

    def test_paparazzi_and_infobae_never_counted_as_local(self):
        pending = [_paparazzi("a"), _infobae("b")]
        with mock.patch.dict(os.environ, {"PUBLISH_LOCAL_MAX_PER_RUN": "10"}, clear=False):
            selected, _rest = self.module.select_batch(pending)

        self.assertEqual(0, len([item for item in selected if self.module._is_local(item)]))

    def test_local_bucket_never_fills_with_excluded_categories(self):
        """Deportes/espectaculos no deben completar el balde local aunque no
        haya nada mas disponible — la capacidad libre se redirige a las
        fuentes nacionales en vez de usarse con categorias de relleno."""
        pending = [
            _local("dep1", seccion="deportes"),
            _local("dep2", seccion="deportes"),
            _local("pol1", seccion="policiales"),
        ]
        with mock.patch.dict(
            os.environ,
            {"PUBLISH_LOCAL_MAX_PER_RUN": "6", "PUBLISH_PAPARAZZI_MAX_PER_RUN": "0", "PUBLISH_INFOBAE_MAX_PER_RUN": "0"},
            clear=False,
        ):
            selected, rest = self.module.select_batch(pending)

        self.assertEqual(["local-pol1"], [item["titulo"] for item in selected])
        self.assertEqual({"local-dep1", "local-dep2"}, {item["titulo"] for item in rest})

    def test_unused_local_capacity_redistributes_to_paparazzi_and_infobae(self):
        pending = (
            [_local("pol1", seccion="policiales")]  # solo 1 candidata local elegible
            + [_paparazzi(f"p{i}", video=True, score=5) for i in range(5)]
            + [_infobae(f"i{i}", video=True) for i in range(5)]
        )
        with mock.patch.dict(
            os.environ,
            {
                "PUBLISH_LOCAL_MAX_PER_RUN": "6",
                "PUBLISH_PAPARAZZI_MAX_PER_RUN": "2",
                "PUBLISH_INFOBAE_MAX_PER_RUN": "2",
            },
            clear=False,
        ):
            selected, _rest = self.module.select_batch(pending)

        buckets = {"local": 0, "paparazzi": 0, "infobae": 0}
        for item in selected:
            buckets[self.module._bucket_name(item)] += 1
        # cupo local libre (5) se reparte: +3 paparazzi, +2 infobae
        self.assertEqual({"local": 1, "paparazzi": 5, "infobae": 4}, buckets)
        self.assertEqual(10, len(selected))

    def test_redistributed_capacity_falls_back_to_the_other_national_bucket_if_one_is_short(self):
        """Si paparazzi no tiene suficientes candidatas para usar su extra,
        ese remanente pasa a infobae en vez de perderse."""
        pending = (
            [_local("pol1", seccion="policiales")]
            + [_paparazzi("p0", video=True, score=5)]  # solo 1 disponible
            + [_infobae(f"i{i}", video=True) for i in range(6)]
        )
        with mock.patch.dict(
            os.environ,
            {
                "PUBLISH_LOCAL_MAX_PER_RUN": "6",
                "PUBLISH_PAPARAZZI_MAX_PER_RUN": "2",
                "PUBLISH_INFOBAE_MAX_PER_RUN": "2",
            },
            clear=False,
        ):
            selected, _rest = self.module.select_batch(pending)

        buckets = {"local": 0, "paparazzi": 0, "infobae": 0}
        for item in selected:
            buckets[self.module._bucket_name(item)] += 1
        self.assertEqual(1, buckets["local"])
        self.assertEqual(1, buckets["paparazzi"])  # todo lo disponible, aunque el cupo extra era mayor
        self.assertEqual(6, buckets["infobae"])  # se llevo su propio extra + el remanente de paparazzi


class ComputeNextBatchIOTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def _module(self):
        from utils import publish_selection

        module = importlib.reload(publish_selection)
        module.META_PATH = str(self.root / "noticias_meta.json")
        module.WEB_PATH = str(self.root / "noticias_web_pending.json")
        return module

    def test_stamps_both_queues_by_shared_identity(self):
        from utils.file_manager import load_json, save_json

        module = self._module()
        meta_item = _local("x")
        web_item = {**meta_item, "web_queue_key": "w1"}
        save_json(module.META_PATH, [meta_item])
        save_json(module.WEB_PATH, [web_item])

        with mock.patch.dict(os.environ, {"PUBLISH_LOCAL_MAX_PER_RUN": "6"}, clear=False):
            result = module.compute_next_batch()

        self.assertEqual(1, result["selected"])
        self.assertEqual(1, result["local"])
        meta_after = load_json(module.META_PATH, [], expected_type=list)
        web_after = load_json(module.WEB_PATH, [], expected_type=list)
        self.assertTrue(meta_after[0]["selected_for_publish"])
        self.assertTrue(web_after[0]["selected_for_publish"])
        self.assertEqual(meta_after[0]["publish_batch_id"], web_after[0]["publish_batch_id"])
        self.assertEqual("local", meta_after[0]["publish_bucket"])

    def test_already_selected_items_are_not_reselected(self):
        from utils.file_manager import load_json, save_json

        module = self._module()
        already = {**_local("x"), "selected_for_publish": True, "publish_batch_id": "old"}
        save_json(module.META_PATH, [already])
        save_json(module.WEB_PATH, [])

        with mock.patch.dict(os.environ, {"PUBLISH_LOCAL_MAX_PER_RUN": "6"}, clear=False):
            result = module.compute_next_batch()

        self.assertEqual(0, result["selected"])
        meta_after = load_json(module.META_PATH, [], expected_type=list)
        self.assertEqual("old", meta_after[0]["publish_batch_id"])

    def test_no_pending_items_returns_zero_without_error(self):
        from utils.file_manager import save_json

        module = self._module()
        save_json(module.META_PATH, [])
        save_json(module.WEB_PATH, [])

        result = module.compute_next_batch()

        self.assertEqual(0, result["selected"])
        self.assertIsNone(result["batch_id"])

    def test_excludes_meta_items_whose_web_queue_entry_already_expired(self):
        """Regresión real de producción: noticias_meta.json es un histórico
        que se poda por su propio TTL, independiente de noticias_web_pending.json
        (que además se vacía al publicar). Un ítem que ya no está en ninguna
        de las dos colas nunca va a conseguir web_url — no debe seleccionarse,
        aunque siga en meta.json esperando."""
        from utils.file_manager import load_json, save_json

        module = self._module()
        orphaned = _local("orphaned")  # ya no está en la cola web, nunca se publicó
        still_pending = _local("pending")  # sigue vivo en la cola web
        already_published = _local("published")
        already_published["web_url"] = "https://lavozriojana.com/noticias/ya-publicada"
        save_json(module.META_PATH, [orphaned, still_pending, already_published])
        save_json(module.WEB_PATH, [still_pending])

        with mock.patch.dict(os.environ, {"PUBLISH_LOCAL_MAX_PER_RUN": "6"}, clear=False):
            result = module.compute_next_batch()

        self.assertEqual(2, result["selected"])
        meta_after = load_json(module.META_PATH, [], expected_type=list)
        selected_titles = {item["titulo"] for item in meta_after if item.get("selected_for_publish")}
        self.assertEqual({"local-pending", "local-published"}, selected_titles)


if __name__ == "__main__":
    unittest.main()
