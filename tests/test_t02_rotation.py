"""Rotación T02 de la placa de Instagram: elección y cableado al renderer."""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.growth_image_rules import ROTATION_LAYOUTS, rotation_layout, t02_rotation_enabled

ON = {"T02_LAYOUT_ROTATION_ENABLED": "true"}


class RotationLayoutTests(unittest.TestCase):
    def test_apagada_por_defecto(self):
        self.assertFalse(t02_rotation_enabled({}))
        self.assertIsNone(rotation_layout({"url": "https://x/1"}, has_photo=True, locality="Chilecito", values={}))

    def test_sin_foto_no_rota(self):
        self.assertIsNone(rotation_layout({"url": "https://x/1"}, has_photo=False, locality="Chilecito", values=ON))

    def test_elige_entre_los_tres_aprobados(self):
        seen = {rotation_layout({"url": f"https://lavozriojana.com/n/{i}"}, has_photo=True, locality="Chilecito", values=ON) for i in range(200)}
        self.assertEqual(seen, set(ROTATION_LAYOUTS))

    def test_sin_localidad_no_usa_portada_con_localidad(self):
        seen = {rotation_layout({"url": f"https://lavozriojana.com/n/{i}"}, has_photo=True, locality="", values=ON) for i in range(200)}
        self.assertEqual(seen, {"auto", "bloque"})

    def test_mismo_post_mismo_diseno(self):
        art = {"canonical_url": "https://lavozriojana.com/noticias/una"}
        first = rotation_layout(art, has_photo=True, locality="Olta", values=ON)
        for _ in range(10):
            self.assertEqual(rotation_layout(art, has_photo=True, locality="Olta", values=ON), first)

    def test_reparto_aproximadamente_parejo(self):
        picks = [rotation_layout({"url": f"https://lavozriojana.com/n/{i}"}, has_photo=True, locality="Capital", values=ON) for i in range(900)]
        for layout in ROTATION_LAYOUTS:
            self.assertGreater(picks.count(layout), 230, layout)


class RotationWiringTests(unittest.TestCase):
    def _render(self, env):
        from layout import image_generator as ig

        captured = {}

        def fake_render(composition, props, asset_paths=None, scale=1):
            captured["props"] = dict(props)
            from PIL import Image
            import io
            buf = io.BytesIO(); Image.new("RGB", (10, 10)).save(buf, "PNG")
            return buf.getvalue(), {}

        article = {"titulo": "Un hecho en Chilecito", "seccion": "interior", "url": "https://lavozriojana.com/noticias/x", "locality": "Chilecito"}
        decision = mock.Mock(version="v2", composition="AutomaticInstagramCardV2")
        decision.as_metadata.return_value = {}
        meta = {}
        with mock.patch.dict(os.environ, env, clear=False), \
             mock.patch.object(ig, "_materialize_image_for_remotion", return_value=("foto.jpg", "landscape", lambda: None)), \
             mock.patch.object(ig, "resolve_visual_version", return_value=decision), \
             mock.patch.object(ig, "_image_size", return_value=(1600, 900)), \
             mock.patch.object(ig, "_apply_growth_rules", return_value=None), \
             mock.patch("utils.remotion_renderer.render_still", side_effect=fake_render), \
             mock.patch("utils.visual_v2_props.locality_for", return_value="Chilecito"):
            ig._generate_instagram_remotion(article, render_meta=meta)
        return captured["props"], meta

    def test_apagada_deja_layout_auto(self):
        props, meta = self._render({"T02_LAYOUT_ROTATION_ENABLED": "false"})
        self.assertEqual(props["layout"], "auto")
        self.assertEqual(meta.get("t02_layout"), "off")

    def test_prendida_usa_un_diseno_aprobado(self):
        props, meta = self._render({"T02_LAYOUT_ROTATION_ENABLED": "true"})
        self.assertIn(props["layout"], ROTATION_LAYOUTS)
        self.assertEqual(meta.get("t02_layout"), props["layout"])


if __name__ == "__main__":
    unittest.main()
