#!/usr/bin/env python3
"""Unit tests for gui.py's command building: no display, no model, no LibreOffice.

The GUI runs the CLI, so what matters is that it can reach every CLI option and
builds the command line the CLI expects. The window itself is exercised by
test/gui_smoke.py (Linux, virtual display) and by CI on Windows (installed MSI).
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import narrate  # noqa: E402

try:
    import gui  # noqa: E402
except ImportError as e:            # a Python built without tkinter
    gui = None
    REASON = str(e)


def form(**over):
    f = {"deck": "/decks/talk.pptx", "output": "", "voice": "af_heart", "speed": "1.0", "device": "auto",
         "pronunciations": "", "slides": "", "pad": "0.75", "empty_duration": "3.0", "build_hold": "1.0",
         "skip_empty": False, "no_builds": False, "keep_temp": False, "allow_desktop": False,
         "sample_text": "Hello", "phonemes_text": "", "sample_out": "/tmp/s.wav"}
    f.update(over)
    return f


@unittest.skipIf(gui is None, "tkinter not available")
class GuiCoversCli(unittest.TestCase):
    def test_every_cli_option_has_a_control(self):
        dests = {a.dest for a in narrate.build_parser()._actions}
        self.assertEqual(dests - gui.COVERED, set(), "CLI options the GUI can't set")
        self.assertEqual(gui.COVERED - dests, set(), "GUI claims options the CLI doesn't have")


@unittest.skipIf(gui is None, "tkinter not available")
class BuildArgs(unittest.TestCase):
    def parse(self, args):
        return narrate.build_parser().parse_args(args)

    def test_video_defaults_parse_to_cli_defaults(self):
        a = self.parse(gui.build_args(form(), "video"))
        d = self.parse(["/decks/talk.pptx"])
        for k in ("deck", "voice", "speed", "pad", "empty_duration", "build_hold", "device",
                  "skip_empty", "no_builds", "keep_temp", "output", "slides", "pronunciations", "renderer"):
            self.assertEqual(getattr(a, k), getattr(d, k), k)

    def test_video_every_option(self):
        a = self.parse(gui.build_args(form(output="/out/v.mp4", voice="bm_george", speed="1.2", device="cpu",
                                           pronunciations="/p.txt", slides="1, 3-4", pad="0.5",
                                           empty_duration="2", build_hold="1.5", skip_empty=True,
                                           no_builds=True, keep_temp=True, renderer="libreoffice"), "video"))
        self.assertEqual(a.renderer, "libreoffice")
        self.assertEqual((a.output, a.voice, a.speed, a.device, a.pronunciations), ("/out/v.mp4", "bm_george", 1.2, "cpu", "/p.txt"))
        self.assertEqual(a.slides, {1, 3, 4})
        self.assertEqual((a.pad, a.empty_duration, a.build_hold), (0.5, 2.0, 1.5))
        self.assertTrue(a.skip_empty and a.no_builds and a.keep_temp)

    def test_show_modes(self):
        self.assertTrue(self.parse(gui.build_args(form(), "builds")).show_builds)
        self.assertTrue(self.parse(gui.build_args(form(), "phonemes")).show_phonemes)
        a = self.parse(gui.build_args(form(phonemes_text="a present"), "phonemes_text"))
        self.assertEqual((a.phonemes, a.deck), ("a present", None))

    def test_sample(self):
        a = self.parse(gui.build_args(form(sample_text="Hi there", voice="am_adam", speed="0.9"), "sample"))
        self.assertEqual((a.sample, a.voice, a.speed, a.output, a.deck), ("Hi there", "am_adam", 0.9, "/tmp/s.wav", None))

    def test_missing_inputs_are_user_errors(self):
        with self.assertRaises(ValueError):
            gui.build_args(form(deck=""), "video")
        with self.assertRaises(ValueError):
            gui.build_args(form(sample_text="  "), "sample")
        with self.assertRaises(ValueError):
            gui.build_args(form(phonemes_text=""), "phonemes_text")

    def test_voice_labels_round_trip(self):
        for v in narrate.KNOWN_VOICES:
            self.assertEqual(gui.voice_from_label(gui.voice_label(v)), v)


@unittest.skipIf(gui is None, "tkinter not available")
@unittest.skipIf(gui is None, "tkinter not available")
class OwnVoiceArgs(unittest.TestCase):
    def parse(self, args):
        return narrate.build_parser().parse_args(args)

    def test_modes(self):
        self.assertTrue(self.parse(gui.build_args(form(), "install_own_voice")).install_own_voice)
        a = self.parse(gui.build_args(form(own_voice_name=" Mike ", own_voice_file="/r/mike.zip"), "add_voice"))
        self.assertEqual(a.add_voice, ["mike", "/r/mike.zip"])
        self.assertEqual(self.parse(gui.build_args(form(own_voice_name="mike"), "remove_voice")).remove_voice, "mike")

    def test_bad_input(self):
        for f in (form(own_voice_name="af_heart", own_voice_file="/r.wav"), form(own_voice_name="mike"),
                  form(own_voice_name="jane doe", own_voice_file="/r.wav")):
            with self.assertRaises(ValueError):
                gui.build_args(f, "add_voice")
        with self.assertRaises(ValueError):
            gui.build_args(form(), "remove_voice")

    def test_label(self):
        self.assertEqual(gui.voice_label("mike"), "mike  (your own voice)")
        self.assertEqual(gui.voice_from_label(gui.voice_label("mike")), "mike")


class SameWord(unittest.TestCase):
    """Use this on a new word settles every listed instance of it (issue #6)."""

    def issues(self):
        return [{"word": "Zscaler", "kind": "unknown"}, {"word": "OPSWAT", "kind": "spelled"},
                {"word": "Zscaler", "kind": "unknown"}, {"word": "zscaler", "kind": "unknown"},
                {"word": "present", "kind": "heteronym"}, {"word": "ZSCALER", "kind": "spelled"}]

    def test_every_instance_and_capitalization(self):
        rows, spellings = gui.same_word(self.issues(), "Zscaler", ("unknown", "spelled"))
        self.assertEqual(rows, [0, 2, 3, 5])
        self.assertEqual(spellings, ["Zscaler", "ZSCALER", "zscaler"])

    def test_heteronyms_are_left_alone(self):
        issues = self.issues() + [{"word": "Present", "kind": "unknown"}]
        rows, spellings = gui.same_word(issues, "Present", ("unknown", "spelled"))
        self.assertEqual(rows, [6])
        self.assertEqual(spellings, ["Present"])


class Updates(unittest.TestCase):
    def release(self, tag, digest="sha256:" + "ab" * 32):
        return {"tag_name": tag, "assets": [
            {"name": "deck-narrator-windows-x64.zip", "browser_download_url": "https://x/zip", "size": 1},
            {"name": f"deck-narrator-{tag[1:]}-x64.msi", "browser_download_url": "https://x/msi",
             "size": 590_000_000, "digest": digest}]}

    def test_only_newer_releases_count(self):
        u = gui.update_from_release(self.release("v1.10.0"), "1.9.3")
        self.assertEqual((u["version"], u["url"], u["sha256"]), ("1.10.0", "https://x/msi", "ab" * 32))
        self.assertIsNone(gui.update_from_release(self.release("v1.2.1"), "1.2.1"))
        self.assertIsNone(gui.update_from_release(self.release("v1.2.0"), "1.2.1"))
        self.assertIsNone(gui.update_from_release({"tag_name": "v9.0.0", "assets": []}, "1.2.1"))
        self.assertIsNone(gui.update_from_release({}, "1.2.1"))

    def test_missing_checksum_is_reported_as_none(self):
        self.assertIsNone(gui.update_from_release(self.release("v2.0.0", digest=None), "1.2.1")["sha256"])

    def test_only_the_installed_copy_updates_itself(self):
        self.assertFalse(gui.installed_by_msi())       # tests run from source


if __name__ == "__main__":
    unittest.main()
