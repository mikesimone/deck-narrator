# Your own voice

Deck Narrator can read your notes in **your own voice** (or a coworker's, with their OK)
instead of one of the built-in voices. It uses [Chatterbox](https://github.com/resemble-ai/chatterbox),
a free voice model from Resemble AI that copies a voice from a short recording.

It's optional and a separate download (4 to 6 GB, once), so it isn't part of the normal install.

## Contents

- [Set it up](#set-it-up)
- [Add a voice](#add-a-voice)
- [Use it](#use-it)
- [Good to know](#good-to-know)
- [Voice packs (for people who train their own model)](#voice-packs)
- [Command line](#command-line)

## Set it up

Pick one:

- **In the app:** open **Settings**, and under **Your own voice** click **Set up**.
- **On Windows, while installing:** if PowerPoint or LibreOffice is already on the PC, the
  installer's last page has a box, **Set up your own voice now**. Tick it before **Finish**.
- **Command line:** `deck-narrator --install-own-voice`

A window shows the progress. It downloads about 4 to 6 GB (more on a PC with an NVIDIA
graphics card, because it gets the graphics-card version), so it can take a while. You only
do it once. If it stops partway (say, the Wi-Fi drops), click **Repair** (the same button)
and it picks up where it left off.

## Add a voice

1. **Record about 20 seconds of the person talking.** 10 to 30 seconds is right. Talk the
   way you want the videos to sound, in a quiet room, with no music behind you. A phone's
   voice recorder is fine. Save it as `.wav`, `.mp3` or `.flac`.
2. In **Settings**, under **Your own voice**, click **Add a voice...** and pick the recording.
3. Type a short name, like `mike`. Lowercase letters, numbers, `-` and `_` only.

The voice now shows in the **Voice** list at the top, marked **(your own voice)**. Click
**Play sample** to hear it.

**Only add someone's voice with their permission.**

## Use it

- **For a whole deck:** pick it in the **Voice** list and click **Make video**.
- **For part of a deck:** put `[voice: mike]` in the speaker notes, the same way you switch
  between built-in voices (see [Switching voices](GUIDE.md#switching-voices)). Your voice and
  the built-in ones can share a deck.

## Good to know

- **It's slower than the built-in voices.** With an NVIDIA graphics card it's quick. On a
  PC without one, or a Mac, expect a few minutes per slide. Try one slide first.
- **The same notes always sound the same.** Make the video again and each sentence comes out
  exactly as before, so changing one slide doesn't change the others.
- **Speed doesn't apply.** The **Speed** setting is for the built-in voices only. Your voice
  talks at the pace of your recording.
- **Fixing a word:** pronunciation rules written in phonemes (`[word](/phonemes/)`) only work
  for the built-in voices; your voice reads the plain word. To change how your voice says
  something, spell it the way it sounds in the notes, for example `Zscaler=Zee-scaler` in
  your dictionary (see [PRONUNCIATION.md](PRONUNCIATION.md)).
- **Everything stays on your computer.** The recording, the voice and the speech never leave
  it. Chatterbox puts an inaudible watermark in the audio it makes, so it can be identified
  as AI-made.
- **Removing a voice:** **Settings** > **Your own voice**, pick it, click **Remove**.
- **Where it lives:** Chatterbox goes in `%LOCALAPPDATA%\deck-narrator\chatterbox` on
  Windows (`~/.local/share/deck-narrator/chatterbox` on Mac and Linux), and your voices in
  `my-voices` next to it. Uninstalling Deck Narrator leaves them; delete those folders to
  free the space.

## Voice packs

If you fine-tuned Chatterbox on a person's voice yourself, Deck Narrator can use the result.
Make a `.zip` (or a folder) with:

| File | What |
|---|---|
| `reference.wav` (or `.flac`, `.mp3`) | Required. 10 to 30 seconds of the person |
| `t3.safetensors` | Optional. Your fine-tuned T3 weights (Chatterbox 0.1.7's T3, same shape; `t3.` or `module.` prefixes are fine) |
| `voice.json` | Optional. `{"exaggeration": 0.5, "cfg_weight": 0.3, "temperature": 0.8}`; anything left out uses Chatterbox's default |

Then add it like a recording: **Add a voice...** and pick the `.zip`. Lower `cfg_weight` and
`exaggeration` make the voice slower and calmer.

## Command line

```
deck-narrator --install-own-voice                  set up Chatterbox (once)
deck-narrator --add-voice mike recording.wav       add a voice (or a voice pack .zip)
deck-narrator --list-voices                        your voices are listed first
deck-narrator deck.pptx --voice mike               narrate with it
deck-narrator --remove-voice mike                  delete it
```

`DECK_NARRATOR_TORCH_BACKEND` (`cpu`, `cu128`, ...) picks which PyTorch the setup installs,
instead of the automatic choice. More in the [Reference](REFERENCE.md#your-own-voice).
