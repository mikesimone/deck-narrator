#!/usr/bin/env python3
"""Unit tests for finding the tools a video needs: the renderer choice (PowerPoint,
else LibreOffice), the bundled ffmpeg, and the PowerPoint build passes. Nothing is
actually rendered: the exporters are mocked."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import narrate  # noqa: E402


class Renderer(unittest.TestCase):
    def setUp(self):
        os.environ.pop("DECK_NARRATOR_RENDERER", None)

    def choose(self, choice, ppt, lo=True):
        soffice = mock.patch.object(narrate, "find_soffice",
                                    return_value="soffice" if lo else None,
                                    side_effect=None if lo else narrate.Fail("no LibreOffice"))
        with mock.patch.object(narrate, "powerpoint_installed", return_value=ppt), soffice:
            return narrate.choose_renderer(choice)

    def test_auto_prefers_powerpoint(self):
        self.assertEqual(self.choose("auto", ppt=True), "powerpoint")
        self.assertEqual(self.choose("auto", ppt=True, lo=False), "powerpoint")   # Office alone is enough

    def test_auto_without_powerpoint_uses_libreoffice(self):
        self.assertEqual(self.choose("auto", ppt=False), "libreoffice")
        with self.assertRaises(narrate.Fail):
            self.choose("auto", ppt=False, lo=False)

    def test_explicit_choices(self):
        self.assertEqual(self.choose("libreoffice", ppt=True), "libreoffice")
        with self.assertRaises(narrate.Fail):
            self.choose("powerpoint", ppt=False)

    def test_environment_overrides(self):
        with mock.patch.dict(os.environ, {"DECK_NARRATOR_RENDERER": "libreoffice"}):
            self.assertEqual(self.choose("auto", ppt=True), "libreoffice")

    def test_not_windows_means_no_powerpoint(self):
        with mock.patch.object(narrate, "IS_WINDOWS", False):
            self.assertFalse(narrate.powerpoint_installed())


class BundledFfmpeg(unittest.TestCase):
    def test_bundled_copy_wins_over_path(self):
        tmp = Path(tempfile.mkdtemp())
        exe = tmp / "ffmpeg" / ("ffmpeg.exe" if narrate.IS_WINDOWS else "ffmpeg")
        exe.parent.mkdir()
        exe.write_bytes(b"")
        env = {k: v for k, v in os.environ.items() if k != "DECK_NARRATOR_FFMPEG"}
        with mock.patch.object(narrate, "app_dir", return_value=tmp), mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual(narrate.find_ffmpeg(), str(exe))

    def test_environment_wins_over_bundled(self):
        tmp = Path(tempfile.mkdtemp())
        mine = tmp / "my-ffmpeg"
        mine.write_bytes(b"")
        with mock.patch.dict(os.environ, {"DECK_NARRATOR_FFMPEG": str(mine)}):
            self.assertEqual(narrate.find_ffmpeg(), str(mine))


class PowerPointPasses(unittest.TestCase):
    def test_every_build_state_comes_from_its_own_slide(self):
        """The demo deck (same as test/anim-deck.pptx) through the PowerPoint path: pass 0 exports every slide (hidden
        ones too, page N = slide N); later passes only the slides that still have states."""
        deck = HERE.parent / "examples" / "demo-deck.pptx"   # committed; test/anim-deck.pptx is generated later
        slides = narrate.read_deck(deck)
        selected = [s for s in slides if not s["hidden"]]
        calls = []

        def fake_export(path, outdir, pages):
            calls.append(list(pages))
            return [outdir / f"s-{n}.png" for n in pages]

        tmp = Path(tempfile.mkdtemp())
        with mock.patch.object(narrate, "export_powerpoint", side_effect=fake_export), \
             mock.patch.object(narrate, "export_pdf", side_effect=AssertionError("LibreOffice used")):
            out = narrate.render_states(deck, tmp, slides, selected, "powerpoint")
        n_passes = max(len(s["builds"].states) for s in selected)
        self.assertEqual(len(calls), n_passes)
        self.assertEqual(calls[0], [s["number"] for s in slides])
        for s in selected:
            for v in range(len(s["builds"].states)):
                self.assertEqual(out[(s["number"], v)].name, f"s-{s['number']}.png")
                self.assertEqual(out[(s["number"], v)].parent.name, f"ppt{v}")


if __name__ == "__main__":
    unittest.main()
