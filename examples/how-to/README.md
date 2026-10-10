# How-to deck

`deck-narrator-how-to.pptx` is a 19-slide tour of the Deck Narrator window (version 1.2.5,
Windows), made to be turned into a narrated how-to video by Deck Narrator itself:

```
deck-narrator examples/how-to/deck-narrator-how-to.pptx
```

or open it in the GUI and press **Make video**. The result is about 8 minutes long; it took
under 6 minutes on a 4-core CPU with no GPU. The finished video is
[`deck-narrator-how-to.mp4`](deck-narrator-how-to.mp4), right here.

What's in it:

- **Screenshots only, many of them.** Deck Narrator doesn't play video embedded in slides,
  so every bit of motion (typing a deck path, a render's progress, the Check pronunciation
  steps, the app updating itself from 1.2.1 to 1.2.5) is a run of screenshots revealed by
  "Appear on click" builds, cued by `[click]` in the notes. Each later screenshot sits on
  a background panel, so nothing from the one before shows around its edges. Check builds
  shows 15 slides with builds, every `[click]` count matching.
- **The narration makes the sounds itself.** Instead of recorded audio, the notes have the
  voice say what you'd hear: a word spelled out letter by letter, then the fixed
  `[NGINX](/ˈɛnʤən ˈɛks/)`; both readings of present side by side, as
  `[present](/pɹˈɛzᵊnt/)` and `[present](/pɹizˈɛnt/)`; and the Adam, Emma and Michael
  voices introducing themselves with `[voice: ...]` markers.
- **Self-contained pronunciation.** Every fix is inline in the notes, so it renders the
  same with or without a personal dictionary. Checked with an empty one: the words
  `--check-pronunciation` still lists all have one reading that is already right, and
  `live` (as in "things live in Settings") is fixed inline.
