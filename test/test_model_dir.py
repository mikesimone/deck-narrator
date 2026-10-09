#!/usr/bin/env python3
"""Unit tests for the bundled-model lookup (local_model_dir, voice_ref): no model needed."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import narrate  # noqa: E402


class LocalModel(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "voices").mkdir()
        for f in ("config.json", "kokoro-v1_0.pth", "voices/af_heart.pt", "voices/bm_george.pt"):
            (self.tmp / f).write_bytes(b"x")

    def test_env_dir_is_used(self):
        with mock.patch.dict(os.environ, {"DECK_NARRATOR_MODEL_DIR": str(self.tmp)}):
            self.assertEqual(narrate.local_model_dir(), self.tmp)
            self.assertEqual(narrate.voice_ref("af_heart"), str(self.tmp / "voices" / "af_heart.pt"))
            self.assertEqual(narrate.voice_ref("am_adam"), "am_adam")     # not bundled: downloaded by name

    def test_env_dir_without_model_is_an_error(self):
        (self.tmp / "kokoro-v1_0.pth").unlink()
        with mock.patch.dict(os.environ, {"DECK_NARRATOR_MODEL_DIR": str(self.tmp)}):
            with self.assertRaises(narrate.Fail):
                narrate.local_model_dir()

    def test_no_bundle_means_download(self):
        env = {k: v for k, v in os.environ.items() if k != "DECK_NARRATOR_MODEL_DIR"}
        with mock.patch.dict(os.environ, env, clear=True):
            if not (Path(narrate.__file__).parent / "model" / "config.json").exists():
                self.assertIsNone(narrate.local_model_dir())
                self.assertEqual(narrate.voice_ref("af_heart"), "af_heart")


if __name__ == "__main__":
    unittest.main()
