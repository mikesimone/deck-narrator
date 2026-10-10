# How-to deck

`deck-narrator-how-to.pptx` is a 16-slide tour of the Deck Narrator window (version 1.2.1,
Windows), made to be turned into a narrated how-to video by Deck Narrator itself:

```
deck-narrator examples/how-to/deck-narrator-how-to.pptx
```

or open it in the GUI and press **Make video**. The result is about 6 minutes long; it took
under 4 minutes on a 4-core CPU with no GPU. The finished video is
[`deck-narrator-how-to.mp4`](deck-narrator-how-to.mp4), right here.

What's in it:

- **Screenshots** of every tab and window, with "Appear on click" builds, so the video steps
  through each part as the narration reaches it (Check builds shows 7 slides with builds,
  every `[click]` count matching).
- **Speaker notes** written as the script, using the deck-narrator syntax it explains:
  `[click]` for builds, a `[voice: am_michael]` switch on the "Writing the script" slide, and
  inline phoneme fixes for NGINX, NVIDIA and LibreOffice. `--check-pronunciation` finds
  nothing left to fix (the words it lists are all read correctly).
- **Four screen recordings with sound** (Play sample, Make video, Check pronunciation, a
  pronunciation file) embedded on their own slides. They play when you open the deck in
  PowerPoint. Deck Narrator doesn't play embedded media (see Known limits in the main README),
  so in the narrated video those slides show the clip's poster frame while the narration
  describes it.
