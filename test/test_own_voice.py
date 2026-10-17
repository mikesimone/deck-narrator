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

    def test_voice_pack_with_timbre(self):
        rec = recording(self.tmp / "r.wav", 12).read_bytes()
        z = self.pack({"reference.wav": rec, "clean.wav": rec,
                       "voice.json": json.dumps({"timbre_reference": "clean.wav", "cfg_weight": 0.3, "junk": 1})})
        narrate.add_voice("mike", z)
        d = self.tmp / "my-voices" / "mike"
        self.assertEqual(json.loads((d / "voice.json").read_text()),
                         {"cfg_weight": 0.3, "timbre_reference": "timbre_reference.wav"})
        self.assertEqual(own_voice_worker.timbre_of(d), d / "timbre_reference.wav")
        with self.assertRaises(narrate.Fail):
            narrate.add_voice("jane", self.pack({"reference.wav": rec, "voice.json": '{"timbre_reference": "x.wav"}'}))

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

    def test_device_choice_reaches_the_worker_unresolved(self):
        """Chatterbox's own torch decides auto; deck-narrator's (CPU-only in the installer) must not."""
        seen = []
        real = narrate.subprocess.Popen

        def spy(cmd, *a, **k):
            seen.append(cmd)
            return real(cmd, *a, **k)
        with mock.patch.object(narrate.subprocess, "Popen", spy), \
                mock.patch.object(narrate, "resolve_device", side_effect=AssertionError("Kokoro's device asked for")):
            tts = narrate.TTS("auto")
            try:
                tts.synthesize("mike", "Hello there.", 1.0)
            finally:
                tts.close()
        self.assertEqual(seen[0][-2:], ["--device", "auto"])

    def test_long_text_is_cut_short_for_your_voice_and_counted(self):
        text = " ".join(f"This is sentence number {i} of a fairly long paragraph." for i in range(10))
        self.assertGreater(narrate.own_chunks(text), 2)
        self.assertTrue(all(len(c) <= narrate.OWN_CHUNK_CHARS for c in narrate.split_sentences(text, narrate.OWN_CHUNK_CHARS)))
        tts = narrate.TTS("cpu")
        tts.own_total = narrate.own_chunks(text)
        try:
            with mock.patch.object(narrate, "log") as log:
                tts.synthesize("mike", text, 1.0)
        finally:
            tts.close()
        lines = [c.args[0] for c in log.call_args_list if c.args[0].startswith("Your voice:")]
        self.assertEqual(len(lines), tts.own_total)
        self.assertIn(f"{tts.own_total} of {tts.own_total} sentences", lines[-1])
        self.assertIsNotNone(tts.floor)                 # measured for the room tone


class Sound(unittest.TestCase):
    def test_fade_edges(self):
        a = np.ones(24000, dtype=np.float32)
        f = narrate.fade_edges(a)
        self.assertEqual(f[0], 0.0)
        self.assertEqual(f[-1], 0.0)
        self.assertEqual(f[12000], 1.0)
        self.assertEqual(a[0], 1.0)                     # the input is left alone

    def test_room_tone_level_and_clamp(self):
        def db(x):
            return 20 * np.log10(np.sqrt((x ** 2).mean()))
        self.assertAlmostEqual(db(narrate.room_tone(48000, -60)), -60, places=1)
        self.assertAlmostEqual(db(narrate.room_tone(48000, -20)), -45, places=1)
        self.assertAlmostEqual(db(narrate.room_tone(48000, -99)), -70, places=1)
        np.testing.assert_array_equal(narrate.room_tone(1000, -60), narrate.room_tone(1000, -60))   # same every run

    def test_noise_floor(self):
        rng = np.random.default_rng(1)
        hiss = (10 ** (-55 / 20) * rng.standard_normal(24000)).astype(np.float32)
        t = np.arange(24000) / 24000
        speech = np.concatenate([hiss, hiss + 0.3 * np.sin(2 * np.pi * 200 * t).astype(np.float32)])
        self.assertAlmostEqual(narrate.noise_floor(speech), -55, delta=3)
        self.assertIsNone(narrate.noise_floor(np.zeros(24000, dtype=np.float32)))


class CutOffCheck(unittest.TestCase):
    def test_heard_ok(self):
        ok = own_voice_worker.heard_ok
        self.assertTrue(ok("Here is the plan for next quarter.", "Here is the plan for next quarter.")[0])
        self.assertFalse(ok("Here is the plan for next quarter.", "Here is the plan for next")[0])
        self.assertFalse(ok("Here is the plan for next quarter.", "")[0])
        self.assertFalse(ok("Here is the plan for next quarter.", "quarter")[0])          # most of it missing
        self.assertTrue(ok("We shipped it in 2026.", "We shipped it in twenty twenty-six.")[0])
        self.assertTrue(ok("It's done.", "Its done.")[0])
        a, b = ok("one two three four", "one two")[1], ok("one two three four", "one two three four")[1]
        self.assertLess(a, b)

    def test_timbre_reference(self):
        d = Path(tempfile.mkdtemp(prefix="dn-timbre-"))
        try:
            self.assertIsNone(own_voice_worker.timbre_of(d))
            (d / "voice.json").write_text(json.dumps({"timbre_reference": "timbre_reference.wav"}))
            with self.assertRaises(FileNotFoundError):
                own_voice_worker.timbre_of(d)
            (d / "timbre_reference.wav").write_bytes(b"x")
            self.assertEqual(own_voice_worker.timbre_of(d), d / "timbre_reference.wav")
            (d / "voice.json").write_text(json.dumps({"timbre_reference": "../../etc/passwd"}))
            with self.assertRaises(FileNotFoundError):     # only files in the voice folder
                own_voice_worker.timbre_of(d)
        finally:
            shutil.rmtree(d)


class Setup(OwnVoiceCase):
    def test_where_it_runs(self):
        self.assertEqual(narrate.own_voice_where({}), "")
        self.assertEqual(narrate.own_voice_where({"cuda": True, "gpu": "RTX 5090"}), "RTX 5090")
        self.assertEqual(narrate.own_voice_where({"cuda": False, "mps": True}), "Apple Silicon GPU")
        self.assertEqual(narrate.own_voice_where({"cuda": False, "mps": False}), "processor")

    def test_remove_support_keeps_voices(self):
        narrate.add_voice("mike", recording(self.tmp / "r.wav", 12))
        home = self.tmp / "chatterbox"
        (home / "venv").mkdir(parents=True)
        (home / "ready.json").write_text("{}")
        self.assertEqual(narrate.remove_own_voice_support(), 0)
        self.assertFalse(home.exists())
        self.assertEqual(list(narrate.own_voices()), ["mike"])
        self.assertEqual(narrate.remove_own_voice_support(), 0)      # nothing there: fine

    def test_setup_needs_disk_space(self):
        with mock.patch.object(narrate.shutil, "disk_usage", return_value=mock.Mock(free=2e9)):
            with self.assertRaises(narrate.Fail) as e:
                narrate.install_own_voice()
        self.assertIn("GB free", str(e.exception))

    def test_kept_sample(self):
        with mock.patch.dict(os.environ, {"DECK_NARRATOR_SAMPLE_CACHE": str(self.tmp / "samples")}):
            (self.tmp / "samples").mkdir()
            (self.tmp / "samples" / "abc.wav").write_bytes(b"RIFF")
            self.assertTrue(narrate.keep_sample("abc.wav"))
            self.assertTrue((self.tmp / "samples" / "kept" / "abc.wav").is_file())
            self.assertIn(self.tmp / "samples" / "kept", narrate.sample_cache_dirs())
            self.assertTrue(narrate.keep_sample("abc.wav"))
            self.assertFalse(narrate.keep_sample("missing.wav"))


if __name__ == "__main__":
    unittest.main()
