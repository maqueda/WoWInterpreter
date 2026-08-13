import time
import unittest
from PIL import Image, ImageDraw

from Bridge.kt07_decoder import COLS, Geometry, MAGIC, decode_at, decode_near_anchor

IDEAL = (31, 92, 163, 224)


def _frame_bytes(text):
    payload = list(text.encode("utf-8"))
    checksum = (sum(MAGIC) + len(payload) + sum(payload)) % 256
    return list(MAGIC) + [len(payload)] + payload + [checksum]


def _symbols(text):
    result = []
    for value in _frame_bytes(text):
        result.extend(((value >> 6) & 3, (value >> 4) & 3, (value >> 2) & 3, value & 3))
    return result


def render(text, geometry, size=(900, 260)):
    image = Image.new("RGB", size, (8, 8, 8))
    draw = ImageDraw.Draw(image)
    for index, symbol in enumerate(_symbols(text)):
        col, row = index % COLS, index // COLS
        x0 = geometry.x + col * geometry.pitch_x
        y0 = geometry.y + row * geometry.pitch_y
        x1 = geometry.x + (col + 1) * geometry.pitch_x
        y1 = geometry.y + (row + 1) * geometry.pitch_y
        level = IDEAL[symbol]
        draw.rectangle((int(round(x0)), int(round(y0)), int(round(x1)) - 1,
                        int(round(y1)) - 1), fill=(level, level, level))
    return image


class KT07DecoderTests(unittest.TestCase):
    def test_exact_geometries(self):
        cases = (
            Geometry(7.0, 12.0, 2.5, 2.5),
            Geometry(11.25, 17.5, 2.75, 3.0),
            Geometry(7.0, 12.0, 3.0, 3.0),
            Geometry(12.25, 16.5, 3.25, 3.5),
            Geometry(13.5, 19.25, 4.5, 4.25),
            Geometry(21.0, 24.0, 6.0, 6.0),
            Geometry(30.25, 31.5, 8.0, 7.75),
        )
        for geometry in cases:
            with self.subTest(geometry=geometry):
                image = render("hello 世界", geometry)
                self.assertEqual("hello 世界", decode_at(image, geometry))

    def test_fractional_origin_drift_matrix(self):
        pitches = (2.5, 2.75, 3.0, 3.25, 3.5, 4.25)
        origins = ((7.0, 10.0), (7.25, 10.5), (11.5, 17.25))
        for pitch in pitches:
            for x, y in origins:
                geometry = Geometry(x, y, pitch, pitch)
                with self.subTest(geometry=geometry):
                    image = render("KT07 scale test", geometry)
                    self.assertEqual("KT07 scale test", decode_at(image, geometry))

    def test_adaptive_search_recovers_three_pixel_case(self):
        geometry = Geometry(7.0, 10.0, 3.0, 3.0)
        image = render("can you invite me?", geometry)
        result = decode_near_anchor(image, (7, 1, 43, 7), 3.0)
        self.assertIsNotNone(result)
        self.assertEqual("can you invite me?", result[0])

    def test_adaptive_search_handles_anisotropic_fractional_pitch(self):
        geometry = Geometry(12.25, 16.5, 3.25, 3.5)
        image = render("我们需要一个治疗。", geometry)
        result = decode_near_anchor(image, (8, 2, 45, 8), 3.25)
        self.assertIsNotNone(result)
        self.assertEqual("我们需要一个治疗。", result[0])

    def test_checksum_corruption_is_rejected(self):
        geometry = Geometry(10.0, 15.0, 4.0, 4.0)
        image = render("checksum", geometry)
        data = _frame_bytes("checksum")
        checksum_byte = len(data) - 1
        first_symbol = checksum_byte * 4
        col, row = first_symbol % COLS, first_symbol // COLS
        x0 = int(round(geometry.x + col * geometry.pitch_x))
        y0 = int(round(geometry.y + row * geometry.pitch_y))
        draw = ImageDraw.Draw(image)
        draw.rectangle((x0, y0, x0 + 3, y0 + 3), fill=(224, 224, 224))
        self.assertIsNone(decode_at(image, geometry))

    def test_magic_without_valid_frame_never_passes(self):
        geometry = Geometry(8.0, 12.0, 3.0, 3.0)
        image = render("valid", geometry)
        payload_symbol = 5 * 4
        col, row = payload_symbol % COLS, payload_symbol // COLS
        x0 = int(round(geometry.x + col * geometry.pitch_x))
        y0 = int(round(geometry.y + row * geometry.pitch_y))
        ImageDraw.Draw(image).rectangle((x0, y0, x0 + 2, y0 + 2),
                                        fill=(224, 224, 224))
        self.assertIsNone(decode_at(image, geometry))

    def test_locked_fast_path_is_cheap(self):
        geometry = Geometry(7.0, 10.0, 3.0, 3.0)
        image = render("fast path", geometry)
        start = time.perf_counter()
        for _ in range(100):
            self.assertEqual("fast path", decode_at(image, geometry))
        elapsed = time.perf_counter() - start
        self.assertLess(elapsed, 1.0, f"100 locked decodes took {elapsed:.3f}s")

    def test_bounded_negative_calibration_does_not_run_away(self):
        image = Image.new("RGB", (360, 260), (8, 8, 8))
        start = time.perf_counter()
        self.assertIsNone(decode_near_anchor(image, (7, 1, 43, 7), 3.0))
        elapsed = time.perf_counter() - start
        self.assertLess(elapsed, 2.0, f"negative calibration took {elapsed:.3f}s")


if __name__ == "__main__":
    unittest.main()
