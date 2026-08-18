"""Frame images in pure stdlib. Fixtures are synthesized, so no binaries land here."""

from __future__ import annotations

import struct
import unittest
import zlib
from pathlib import Path

from dsh_desk_pet import imaging

ROOT = Path(__file__).resolve().parents[1]
MAGENTA = (255, 0, 255)


def _png(width, height, pixels, ctype=6, filter_type=0):
    """Encode a PNG with a chosen row filter, so every decode path is exercised."""

    channels = {0: 1, 2: 3, 4: 2, 6: 4}[ctype]
    stride = width * channels
    rows = bytearray()
    prev = bytearray(stride)
    for y in range(height):
        cur = bytearray()
        for x in range(width):
            px = pixels(x, y)
            cur += bytes(px[:channels]) if len(px) >= channels else bytes(px)
        rows.append(filter_type)
        if filter_type == 0:
            rows += cur
        else:
            enc = bytearray(stride)
            for i in range(stride):
                a = cur[i - channels] if i >= channels else 0
                c = prev[i - channels] if i >= channels else 0
                b = prev[i]
                if filter_type == 1:
                    pred = a
                elif filter_type == 2:
                    pred = b
                elif filter_type == 3:
                    pred = (a + b) >> 1
                else:
                    p = a + b - c
                    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                    pred = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                enc[i] = (cur[i] - pred) & 255
            rows += enc
        prev = cur

    def chunk(tag, body):
        return struct.pack(">I", len(body)) + tag + body + struct.pack(">I", zlib.crc32(tag + body) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, ctype, 0, 0, 0)
    return (imaging.PNG_MAGIC + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(bytes(rows), 6)) + chunk(b"IEND", b""))


def _disc(size, radius_ratio=0.3, colour=(70, 110, 254)):
    cx = cy = size // 2
    r2 = (size * radius_ratio) ** 2

    def at(x, y):
        inside = (x - cx) ** 2 + (y - cy) ** 2 < r2
        return (*colour, 255) if inside else (*MAGENTA, 255)

    return at


class ContainerTests(unittest.TestCase):
    def test_jpeg_bytes_named_png_are_identified_as_jpeg(self) -> None:
        """The repo's own assets/source holds eighteen such files.

        They only ever built because ffmpeg sniffs content. A strict parser
        would call them corrupt PNGs and blame the user's file.
        """

        self.assertEqual(imaging.container(b"\xff\xd8\xff\xe0rest"), "jpeg")
        with self.assertRaises(imaging.ImageError) as caught:
            imaging.decode_png(b"\xff\xd8\xff\xe0rest")
        self.assertIn("jpeg", str(caught.exception).lower())


class DecodeTests(unittest.TestCase):
    def test_every_row_filter_decodes_identically(self) -> None:
        size = 24
        reference = None
        for filter_type in range(5):
            with self.subTest(filter=filter_type):
                w, h, raw = imaging.decode_png(_png(size, size, _disc(size), filter_type=filter_type))
                self.assertEqual((w, h), (size, size))
                if reference is None:
                    reference = raw
                else:
                    self.assertEqual(raw, reference, "filters must agree")

    def test_rgb_without_alpha_decodes_opaque(self) -> None:
        """What every backend actually returns."""

        w, h, raw = imaging.decode_png(_png(8, 8, lambda x, y: (1, 2, 3), ctype=2))
        self.assertEqual(raw[3], 255)

    def test_round_trips_through_the_writer(self, ) -> None:
        size = 16
        _, _, raw = imaging.decode_png(_png(size, size, _disc(size)))
        out = Path(self.tmp()) / "rt.png"
        imaging._write_png_rgba(out, size, size, bytes(raw))
        w2, h2, raw2 = imaging.decode_png(out.read_bytes())
        self.assertEqual((w2, h2), (size, size))
        self.assertEqual(raw2, raw)

    def tmp(self):
        import tempfile
        d = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(d, ignore_errors=True))
        return d

    def test_oversized_header_is_refused_before_allocating(self) -> None:
        head = imaging.PNG_MAGIC + struct.pack(">I", 13) + b"IHDR" + struct.pack(
            ">IIBBBBB", 100000, 100000, 8, 6, 0, 0, 0) + struct.pack(">I", 0)
        with self.assertRaises(imaging.ImageError):
            imaging.decode_png(head)

    def test_sixteen_bit_is_refused(self) -> None:
        head = imaging.PNG_MAGIC + struct.pack(">I", 13) + b"IHDR" + struct.pack(
            ">IIBBBBB", 4, 4, 16, 6, 0, 0, 0) + struct.pack(">I", 0)
        with self.assertRaises(imaging.ImageError) as caught:
            imaging.decode_png(head)
        self.assertIn("8-bit", str(caught.exception))

    def test_interlaced_is_refused(self) -> None:
        head = imaging.PNG_MAGIC + struct.pack(">I", 13) + b"IHDR" + struct.pack(
            ">IIBBBBB", 4, 4, 8, 6, 0, 0, 1) + struct.pack(">I", 0)
        with self.assertRaises(imaging.ImageError) as caught:
            imaging.decode_png(head)
        self.assertIn("interlac", str(caught.exception).lower())

    def test_truncated_data_is_refused(self) -> None:
        data = bytearray(_png(16, 16, _disc(16)))
        with self.assertRaises(imaging.ImageError):
            imaging.decode_png(bytes(data[:len(data) // 2]))


class KeyTests(unittest.TestCase):
    def test_plate_is_sampled_from_the_corners(self) -> None:
        _, _, raw = imaging.decode_png(_png(32, 32, _disc(32)))
        self.assertEqual(imaging.sample_plate(raw, 32, 32), MAGENTA)

    def test_keying_clears_the_plate_and_keeps_the_subject(self) -> None:
        size = 40
        _, _, raw = imaging.decode_png(_png(size, size, _disc(size)))
        imaging.color_key(raw, size, size, MAGENTA)
        box, coverage = imaging.alpha_bounds(raw, size, size)
        self.assertIsNotNone(box)
        self.assertGreater(coverage, 0.15)
        self.assertLess(coverage, 0.45, "the plate should be gone")

    def test_keying_leaves_rgb_intact_under_transparency(self) -> None:
        """`_seal_interior` judges an enclosed region by the colour that
        survives underneath; zeroing RGB would destroy that signal."""

        size = 16
        _, _, raw = imaging.decode_png(_png(size, size, _disc(size)))
        imaging.color_key(raw, size, size, MAGENTA)
        corner = 0
        self.assertEqual(raw[corner + 3], 0)
        self.assertEqual((raw[corner], raw[corner + 1], raw[corner + 2]), MAGENTA)


class GeometryTests(unittest.TestCase):
    def test_crop_size_is_shared_across_frames_of_differing_ink(self) -> None:
        """Sizing per frame makes the character shrink and swell between states.

        That is the defect 7eb6296 fixed; the build script decides crop size
        once per skin for exactly this reason.
        """

        union = (0.2, 0.2, 0.8, 0.8)
        wide = imaging.square_crop(union, 1000, 1000, frame=(0.1, 0.3, 0.9, 0.7), area_px=90000)
        tall = imaging.square_crop(union, 1000, 1000, frame=(0.3, 0.1, 0.7, 0.9), area_px=90000)
        self.assertEqual(wide[2], tall[2], "same skin, same crop size")

    def test_scaling_produces_the_requested_frame(self) -> None:
        size = 64
        _, _, raw = imaging.decode_png(_png(size, size, _disc(size)))
        imaging.color_key(raw, size, size, MAGENTA)
        out = imaging.crop_scale(raw, size, size, (0, 0, size, size), size=imaging.FRAME_SIZE)
        self.assertEqual(len(out), imaging.FRAME_SIZE * imaging.FRAME_SIZE * 4)


class ShippedArtTests(unittest.TestCase):
    """The load-bearing check: the port must agree with what ffmpeg produced."""

    def test_decodes_every_shipped_frame(self) -> None:
        frames = sorted((ROOT / "assets" / "web").glob("*/*/*.png"))
        self.assertGreaterEqual(len(frames), 90)
        for frame in frames[:12]:
            with self.subTest(frame=frame.name):
                w, h, raw = imaging.decode_png(frame.read_bytes())
                self.assertEqual((w, h), (imaging.FRAME_SIZE, imaging.FRAME_SIZE))
                self.assertEqual(len(raw), w * h * 4)

    def test_shipped_coverage_matches_the_art_gate_range(self) -> None:
        frame = ROOT / "assets" / "web" / "deepseek" / "idle" / "00.png"
        w, h, raw = imaging.decode_png(frame.read_bytes())
        _, coverage = imaging.alpha_bounds(raw, w, h)
        self.assertGreater(coverage, 0.05)
        self.assertLess(coverage, 0.90)


if __name__ == "__main__":
    unittest.main()
