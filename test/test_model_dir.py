#!/usr/bin/env python3
"""Unit tests for the bundled model and voice lookup (local_model_dir, voice_ref) and
--update-voices, with HuggingFace mocked: no model or network needed."""
import contextlib
import hashlib
import io
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
        # Keep this machine's own downloaded voices out of it.
        self.env = mock.patch.dict(os.environ, {"DECK_NARRATOR_VOICE_DIR": str(self.tmp / "no-user-voices")})
        self.env.start()
        self.addCleanup(self.env.stop)

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


class UpdateVoices(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.model = self.tmp / "model"
        (self.model / "voices").mkdir(parents=True)
        for f in ("config.json", "kokoro-v1_0.pth"):
            (self.model / f).write_bytes(b"x")
        (self.model / "voices" / "af_heart.pt").write_bytes(b"heart v1")
        (self.model / "voices" / "am_adam.pt").write_bytes(b"adam v1")
        self.user = self.tmp / "user"
        self.hub = self.tmp / "hub"
        self.hub.mkdir()
        self.env = mock.patch.dict(os.environ, {"DECK_NARRATOR_MODEL_DIR": str(self.model),
                                                "DECK_NARRATOR_VOICE_DIR": str(self.user)})
        self.env.start()

    def tearDown(self):
        self.env.stop()

    def remote(self, files):
        """Fake HuggingFace with these voice files (name -> bytes)."""
        for name, data in files.items():
            (self.hub / f"{name}.pt").write_bytes(data)
        entries = [mock.Mock(path=f"voices/{n}.pt", lfs=mock.Mock(sha256=hashlib.sha256(d).hexdigest()))
                   for n, d in files.items()]
        api = mock.Mock()
        api.return_value.list_repo_tree.return_value = entries
        download = mock.Mock(side_effect=lambda repo, fn: str(self.hub / Path(fn).name))
        return mock.patch.multiple("huggingface_hub", HfApi=api, hf_hub_download=download), download

    def run_update(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(narrate.update_voices(), 0)
        return out.getvalue().strip()

    def test_new_and_changed_voices_land_in_the_user_folder(self):
        patch, download = self.remote({"af_heart": b"heart v1", "am_adam": b"adam v2", "bf_new": b"new one"})
        with patch:
            line = self.run_update()
        self.assertEqual(line, "voices: 1 new (bf_new); 1 updated (am_adam)")
        self.assertEqual(sorted(p.name for p in self.user.iterdir()), ["am_adam.pt", "bf_new.pt"])
        self.assertEqual(download.call_count, 2)                       # af_heart unchanged: not fetched
        self.assertEqual(narrate.voice_ref("am_adam"), str(self.user / "am_adam.pt"))   # the update wins
        self.assertEqual(narrate.voice_ref("af_heart"), str(self.model / "voices" / "af_heart.pt"))
        self.assertIn("bf_new", narrate.available_voices())
        with patch:                                                    # second run: nothing to do
            self.assertEqual(self.run_update(), "voices: 0 new; 0 updated")

    def test_offline_is_not_an_error(self):
        api = mock.Mock()
        api.return_value.list_repo_tree.side_effect = OSError("no network")
        with mock.patch("huggingface_hub.HfApi", api):
            self.assertEqual(self.run_update(), "voices: offline")
        self.assertFalse(self.user.exists())

    def test_without_a_bundle_there_is_nothing_to_update(self):
        with mock.patch.object(narrate, "local_model_dir", return_value=None):
            self.assertEqual(self.run_update(), "voices: not bundled")


if __name__ == "__main__":
    unittest.main()
