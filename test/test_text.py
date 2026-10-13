#!/usr/bin/env python3
"""Unit tests for the text handling in narrate.py: no GPU, no model, no LibreOffice.

Run:  .venv/bin/python -m unittest discover -s test -v
(test/verify.sh runs these first, then the end-to-end check.)
"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import narrate  # noqa: E402


def rules_from(text):
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as f:
        f.write(text)
    return narrate.load_pronunciations(f.name)


class CleanNotes(unittest.TestCase):
    def test_strips_stage_directions(self):
        self.assertEqual(narrate.clean_notes("Hi. [pause] Next [click] slide."), "Hi. Next slide.")

    def test_keeps_phoneme_override(self):
        self.assertEqual(narrate.clean_notes("or [present](/pɹizˈɛnt/), ok"), "or [present](/pɹizˈɛnt/), ok")

    def test_keeps_stress_nudge(self):
        self.assertEqual(narrate.clean_notes("I [really](-1) mean it"), "I [really](-1) mean it")

    def test_no_space_before_punctuation(self):
        self.assertEqual(narrate.clean_notes("done [click]."), "done.")

    def test_collapses_whitespace(self):
        self.assertEqual(narrate.clean_notes("  a\n\n b\t c  "), "a b c")

    def test_empty(self):
        self.assertEqual(narrate.clean_notes(None), "")
        self.assertEqual(narrate.clean_notes("[pause]"), "")


class Overrides(unittest.TestCase):
    def check(self, raw):
        narrate.check_overrides([{"number": 7, "raw_notes": raw}])

    def test_detached_phonemes_fail_with_slide_number(self):
        with self.assertRaisesRegex(narrate.Fail, "slide 7"):
            self.check("or [present] (/pɹizˈɛnt/), ok")

    def test_detached_nudge_fails(self):
        with self.assertRaises(narrate.Fail):
            self.check("[really] (-1)")

    def test_attached_is_fine(self):
        self.check("or [present](/pɹizˈɛnt/), ok")

    def test_ordinary_parentheses_are_fine(self):
        self.check("costs (5) dollars [click] (see chart)")


class Pronunciations(unittest.TestCase):
    def test_whole_word_case_sensitive(self):
        r = rules_from("RTX=R T X\nSQL=sequel\n")
        self.assertEqual(narrate.apply_pronunciations("RTX RTXs ARTX sql SQL", r), "R T X RTXs ARTX sql sequel")

    def test_longest_first_regardless_of_order(self):
        r = rules_from("NVMe=N V M E\nNVMe-oF=N V M E over fabrics\n")
        self.assertEqual(narrate.apply_pronunciations("NVMe-oF and NVMe", r), "N V M E over fabrics and N V M E")

    def test_single_pass_no_rescan(self):
        r = rules_from("A=B\nB=C\n")
        self.assertEqual(narrate.apply_pronunciations("A B", r), "B C")

    def test_inline_override_wins(self):
        r = rules_from("present=gift\n")
        self.assertEqual(narrate.apply_pronunciations("a present, [present](/pɹizˈɛnt/)", r),
                         "a gift, [present](/pɹizˈɛnt/)")

    def test_replacement_can_be_an_override(self):
        r = rules_from("Kubernetes=[Kubernetes](/kˌubəɹnˈɛtiz/)\n")
        self.assertEqual(narrate.apply_pronunciations("Kubernetes!", r), "[Kubernetes](/kˌubəɹnˈɛtiz/)!")

    def test_built_in_ai_and_your_rule_wins(self):
        builtin = narrate.BUILTIN_PRONUNCIATIONS
        out = narrate.apply_pronunciations("AI, AI's and AI-driven, not ai or GenAI", builtin)
        self.assertEqual(out.count("[AI](/"), 3)
        self.assertIn("not ai or GenAI", out)
        mine = builtin + rules_from("AI=artificial intelligence\n")
        self.assertEqual(narrate.apply_pronunciations("AI", mine), "artificial intelligence")
        self.assertEqual(narrate.apply_pronunciations("[AI](/x/)", builtin), "[AI](/x/)")

    def test_comments_and_blanks(self):
        self.assertEqual(rules_from("# hi\n\n  # indented\nX=y\n"), [("X", "y")])

    def test_bad_line_names_file_and_line(self):
        with self.assertRaisesRegex(narrate.Fail, r":2: expected word=replacement"):
            rules_from("X=y\nnonsense\n")


class SentenceSplit(unittest.TestCase):
    def words(self, s):
        return s.split()

    def test_nothing_lost_and_chunks_bounded(self):
        text = " ".join(f"Sentence number {i} has a few words, then a clause, and ends." for i in range(40))
        chunks = narrate.split_sentences(text)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(c) <= narrate.CHUNK_CHARS for c in chunks))
        self.assertEqual(self.words(" ".join(chunks)), self.words(text))

    def test_run_on_sentence_without_periods(self):
        text = ", ".join(["one long clause with no end in sight"] * 30)
        chunks = narrate.split_sentences(text)
        self.assertTrue(all(len(c) <= narrate.CHUNK_CHARS for c in chunks))
        self.assertEqual(self.words(" ".join(chunks)), self.words(text))

    def test_override_never_split(self):
        text = ("Filler sentence here. " * 15) + "We [present](/pɹizˈɛnt/) it."
        self.assertTrue(any("[present](/pɹizˈɛnt/)" in c for c in narrate.split_sentences(text)))


class SlideRange(unittest.TestCase):
    def test_forms(self):
        self.assertEqual(narrate.parse_slide_range("3-5"), {3, 4, 5})
        self.assertEqual(narrate.parse_slide_range("1,4,6-8"), {1, 4, 6, 7, 8})

    def test_bad(self):
        import argparse
        for bad in ("0", "5-3", "a", "1-"):
            with self.assertRaises(argparse.ArgumentTypeError):
                narrate.parse_slide_range(bad)


if __name__ == "__main__":
    unittest.main()
