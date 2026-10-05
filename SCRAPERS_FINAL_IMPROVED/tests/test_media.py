# tests/test_media.py
# Unit tests for _shared/media.py (fixed crop, resize, encode).
#
# Run:  .venv/bin/python tests/test_media.py

import io
import os
import sys
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "_shared"))

from PIL import Image  # noqa: E402
from media import (  # noqa: E402
    REKLAMA5_LOGO_CROP_TOP_PX,
    process_image,
    property_key,
)


def _png_bytes(img):
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


class TestReklamaFixedCrop(unittest.TestCase):
    def test_crop_is_a_sane_fixed_value(self):
        # Measured from the live photos: the watermark ends at y≈31 px.
        self.assertGreaterEqual(REKLAMA5_LOGO_CROP_TOP_PX, 32)
        self.assertLessEqual(REKLAMA5_LOGO_CROP_TOP_PX, 60)

    def test_fixed_crop_strips_the_watermark_strip(self):
        img = Image.new("RGB", (1200, 900), (10, 20, 30))
        out = process_image(_png_bytes(img), crop_top=REKLAMA5_LOGO_CROP_TOP_PX)
        self.assertEqual(out["cropped_top"], REKLAMA5_LOGO_CROP_TOP_PX)
        self.assertEqual(out["height"], 900 - REKLAMA5_LOGO_CROP_TOP_PX)


class TestProcessImage(unittest.TestCase):
    def test_resize_to_max_width(self):
        img = Image.new("RGB", (3000, 2000), (10, 20, 30))
        out = process_image(_png_bytes(img), max_width=1600)
        self.assertEqual(out["width"], 1600)
        self.assertEqual(out["height"], 1066)
        self.assertTrue(out["jpeg"])
        self.assertTrue(out["webp"])

    def test_crop_top_reduces_height(self):
        img = Image.new("RGB", (800, 600), (10, 20, 30))
        out = process_image(_png_bytes(img), crop_top=100)
        self.assertEqual(out["height"], 500)
        self.assertEqual(out["cropped_top"], 100)

    def test_no_webp(self):
        img = Image.new("RGB", (100, 100), (10, 20, 30))
        out = process_image(_png_bytes(img), want_webp=False)
        self.assertIsNone(out["webp"])


class TestPropertyKey(unittest.TestCase):
    def test_number_preferred(self):
        self.assertEqual(property_key("reklama5", "123", "1043"), "1043")

    def test_fallback_site_id(self):
        self.assertEqual(property_key("pazar3", "6184457"), "pazar3-6184457")


if __name__ == "__main__":
    unittest.main(verbosity=2)
