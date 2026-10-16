#!/usr/bin/env python3
"""Your own voice (Chatterbox): adding and removing voices, voice packs, and the talk with
own_voice_worker.py, using a stand-in worker so neither Chatterbox nor its model is needed.
The real thing runs in CI's own-voice job."""
import json
import os
import shutil
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import narrate  # noqa: E402
import own_voice_worker  # noqa: E402

# Answers like own_voice_worker.py, with a tone (and some silence around it) for speech.
FAKE_WORKER = r'''
import json, sys
import numpy as np, soundfile as sf
print(json.dumps({"ready": True, "device": "cpu", "sr": 24000}), flush=True)
for line in sys.stdin:
    req = json.loads(line)
    if req["cmd"] == "quit":
        break
    if req["cmd"] == "load":
        print(json.dumps({"ok": True}), flush=True)
    elif req["cmd"] == "say":
        if "explode" in req["text"]:
            print(json.dumps({"error": "boom"}), flush=True)
            continue
        with open(req["out"] + ".txt", "a", encoding="utf-8") as f:
            f.write(req["text"] + "\n")
        t = np.arange(24000) / 24000
        tone = 0.3 * np.sin(2 * np.pi * 220 * t)
        audio = np.concatenate([np.zeros(12000), tone, np.zeros(12000)]).astype("float32")
        sf.write(req["out"], audio, 24000, subtype="FLOAT")
        print(json.dumps({"ok": True, "seconds": len(audio) / 24000}), flush=True)
'''


def recording(path, seconds):
    t = np.arange(int(24000 * seconds)) / 24000
    sf.write(path, (0.2 * np.sin(2 * np.pi * 180 * t)).astype("float32"), 24000)
    return path


class OwnVoiceCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="dn-own-test-"))
        self.env = mock.patch.dict(os.environ, {
            "DECK_NARRATOR_MY_VOICES": str(self.tmp / "my-voices"),
            "DECK_NARRATOR_OWN_VOICE_HOME": str(self.tmp / "chatterbox"),
        })
        self.env.start()

    def tearDown(self):
        self.env.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def pack(self, members):
        z = self.tmp / "pack.zip"
        with zipfile.ZipFile(z, "w") as f:
            for name, data in members.items():
                f.writestr(name, data)
        return z


class AddAndRemove(OwnVoiceCase):
    def test_recording_becomes_a_voice(self):
        narrate.add_voice("Mike", recording(self.tmp / "mike.wav", 12))
        self.assertEqual(list(narrate.own_voices()), ["mike"])
        self.assertTrue((self.tmp / "my-voices" / "mike" / "reference.wav").is_file())
        self.assertTrue(narrate.is_own_voice("mike"))
        self.assertEqual(narrate.check_voice_name("mike", "x"), "mike")
        self.assertEqual(narrate.available_voices()[0], "mike")       # yours first, then the built-in ones
        self.assertIn("af_heart", narrate.available_voices())

    def test_bad_names(self):
        rec = recording(self.tmp / "r.wav", 12)
        for bad in ("af_heart", "am_mike", "jane doe", "default", "", "x" * 33, "-lead"):
            with self.assertRaises(narrate.Fail, msg=bad):
                narrate.add_voice(bad, rec)
        self.assertEqual(narrate.own_voices(), {})

    def test_too_short_and_not_audio(self):
        with self.assertRaises(narrate.Fail):
            narrate.add_voice("mike", recording(self.tmp / "short.wav", 2))
        (self.tmp / "notes.txt").write_text("hi")
        with self.assertRaises(narrate.Fail):
            narrate.add_voice("mike", self.tmp / "notes.txt")
        self.assertEqual(narrate.own_voices(), {})

    def test_voice_pack(self):
        rec = recording(self.tmp / "r.wav", 12).read_bytes()
        z = self.pack({"mike/reference.wav": rec, "mike/t3.safetensors": b"weights",
                       "mike/voice.json": json.dumps({"cfg_weight": 0.3, "temperature": "0.8", "evil": "x"})})
        narrate.add_voice("mike", z)
        d = narrate.own_voices()["mike"]
        self.assertEqual((d / "t3.safetensors").read_bytes(), b"weights")
        self.assertEqual(json.loads((d / "voice.json").read_text()), {"cfg_weight": 0.3, "temperature": 0.8})
        self.assertEqual(own_voice_worker.settings_of(d), {"exaggeration": 0.5, "cfg_weight": 0.3, "temperature": 0.8})

    def test_pack_needs_one_recording_and_one_model(self):
        rec = recording(self.tmp / "r.wav", 12).read_bytes()
        with self.assertRaises(narrate.Fail):
            narrate.add_voice("mike", self.pack({"a.wav": rec, "b.wav": rec}))
        with self.assertRaises(narrate.Fail):
            narrate.add_voice("mike", self.pack({"reference.wav": rec, "a.safetensors": b"1", "b.safetensors": b"2"}))
        with self.assertRaises(narrate.Fail):
            narrate.add_voice("mike", self.pack({"voice.json": "{}"}))

    def test_adding_again_replaces(self):
        rec = recording(self.tmp / "r.wav", 12).read_bytes()
        narrate.add_voice("mike", self.pack({"reference.wav": rec, "t3.safetensors": b"w"}))
        narrate.add_voice("mike", self.tmp / "r.wav")
        self.assertFalse((narrate.own_voices()["mike"] / "t3.safetensors").exists())

    def test_remove(self):
        narrate.add_voice("mike", recording(self.tmp / "r.wav", 12))
        narrate.remove_voice("mike")
        self.assertEqual(narrate.own_voices(), {})
        with self.assertRaises(narrate.Fail):
            narrate.remove_voice("mike")

    def test_notes_can_switch_to_it(self):
        narrate.add_voice("mike", recording(self.tmp / "r.wav", 12))
        parts, _, end = narrate.parse_script("Hi. [voice: Mike] I'm Mike.", "af_heart", "af_heart", 1)
        self.assertEqual([p["voice"] for p in parts], ["af_heart", "mike"])
        self.assertEqual(end, "mike")
        with self.assertRaises(narrate.Fail):
            narrate.parse_script("[voice: nobody] hi", "af_heart", "af_heart", 1)


class Helpers(unittest.TestCase):
    def test_plain_text_drops_phoneme_overrides(self):
        self.assertEqual(narrate.plain_text("We use [AI](/ˌAˈI/) and [read](+1) it."), "We use AI and read it.")
        self.assertEqual(narrate.plain_text("A [note] stays"), "A [note] stays")

    def test_seed_is_stable(self):
        self.assertEqual(narrate.text_seed("mike", "Hello."), narrate.text_seed("mike", "Hello."))
        self.assertNotEqual(narrate.text_seed("mike", "Hello."), narrate.text_seed("jane", "Hello."))

    def test_trim_edges(self):
        audio = np.concatenate([np.zeros(24000), 0.3 * np.ones(2400), np.zeros(24000)]).astype("float32")
        out = narrate.trim_edges(audio)
        self.assertAlmostEqual(len(out) / 24000, 0.1 + 2 * 0.05, places=2)
        self.assertEqual(len(narrate.trim_edges(np.zeros(100, dtype="float32"))), 100)

    def test_plain_state(self):
        w = np.zeros(1)
        self.assertEqual(list(own_voice_worker.plain_state({"t3.a": w, "t3.b": w})), ["a", "b"])
        self.assertEqual(list(own_voice_worker.plain_state({"module.t3.a": w})), ["a"])
        self.assertEqual(list(own_voice_worker.plain_state({"a": w, "t3.b": w})), ["a", "t3.b"])

    def test_child_env_undoes_frozen_paths(self):
        with mock.patch.dict(os.environ, {"PYTHONHOME": "/frozen", "LD_LIBRARY_PATH": "/frozen/lib",
                                          "LD_LIBRARY_PATH_ORIG": "/usr/lib"}):
            env = narrate.child_env(X=1)
        self.assertNotIn("PYTHONHOME", env)
        self.assertEqual(env["LD_LIBRARY_PATH"], "/usr/lib")
        self.assertEqual(env["X"], "1")


class Speaking(OwnVoiceCase):
    """TTS with an own voice, through a stand-in worker running in this Python."""

    def setUp(self):
        super().setUp()
        narrate.add_voice("mike", recording(self.tmp / "r.wav", 12))
        home = self.tmp / "chatterbox"
        home.mkdir()
        (home / "ready.json").write_text("{}")
        worker = self.tmp / "fake_worker.py"
        worker.write_text(FAKE_WORKER, encoding="utf-8")
        # Chatterbox's Python is this one (it has numpy and soundfile); the worker is the stand-in.
        self.patches = [mock.patch.object(narrate, "worker_script", lambda: worker),
                        mock.patch.object(narrate, "own_python", lambda: Path(sys.executable))]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        super().tearDown()

    def test_says_each_sentence_as_plain_text(self):
        tts = narrate.TTS("cpu")
        try:
            audio = tts.synthesize("mike", "First [AI](/ˌAˈI/) sentence. Second one.", 1.0)
            log = (tts.own.tmp / "say.wav.txt").read_text(encoding="utf-8").splitlines()
        finally:
            tts.close()
        self.assertEqual(log, ["First AI sentence. Second one."])        # one chunk, overrides read as words
        self.assertIsNone(tts.model)                                     # Kokoro never loaded
        self.assertAlmostEqual(len(audio) / narrate.SAMPLE_RATE, 1.1, places=1)   # silence trimmed

    def test_worker_error_is_a_user_error(self):
        tts = narrate.TTS("cpu")
        try:
            with self.assertRaises(narrate.Fail) as e:
                tts.synthesize("mike", "Please explode.", 1.0)
            self.assertIn("boom", str(e.exception))
        finally:
            tts.close()

    def test_not_set_up(self):
        (self.tmp / "chatterbox" / "ready.json").unlink()
        with self.assertRaises(narrate.Fail) as e:
            narrate.TTS("cpu").pipe("mike")
        self.assertIn("--install-own-voice", str(e.exception))

    def test_phonemes_show_the_words(self):
        self.assertEqual(narrate.phonemize("mike", "[AI](/ˌAˈI/) rocks"), "(reads the words) AI rocks")


if __name__ == "__main__":
    unittest.main()
