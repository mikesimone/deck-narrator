# Your own voice

Deck Narrator can read your notes in **your own voice** (or a coworker's, with their OK)
instead of one of the built-in voices. It uses [Chatterbox](https://github.com/resemble-ai/chatterbox),
a free voice model from Resemble AI that copies a voice from a short recording.

It's optional and a separate download (4 to 6 GB, once), so it isn't part of the normal install.

> **Warning: it's painfully slow without an NVIDIA graphics card.** On a regular processor
> (no NVIDIA card, or a Mac), your own voice can take **several minutes per slide**, and a
> full deck can take hours. The built-in voices take seconds. If your PC has no NVIDIA card,
> try one slide before you start a whole deck. **Settings > Your own voice** says which it
> uses, and the log counts down the sentences while it works.
>
> **Upgrading from 1.3.0?** 1.3.0 used the processor even when there was an NVIDIA card.
> 1.3.1 fixes that, and adds a small download (about 200 MB) the first time you use your voice.

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

- **It's much slower than the built-in voices.** With an NVIDIA graphics card it keeps up. On
  a processor alone, or a Mac, expect several minutes per slide (see the warning at the top).
  The log shows each sentence as it's done and about how long is left. **Stop** stops it.
- **It checks itself.** Chatterbox sometimes stops a word early. Each sentence is listened
  to as it's made, and one that was cut short is made again (the log says so).
- **Its sample is made when you add it,** and kept, so **Play sample** is instant after that.
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
- **Removing Chatterbox:** **Remove Chatterbox...** in the same place deletes its 4 to 6 GB.
  Your voices are kept, and **Set up** brings it back.
- **Where it lives:** Chatterbox goes in `%LOCALAPPDATA%\deck-narrator\chatterbox` on
  Windows (`~/.local/share/deck-narrator/chatterbox` on Mac and Linux), and your voices in
  `my-voices` next to it. Uninstalling Deck Narrator leaves them: use **Remove Chatterbox...**
  first, or delete those folders.

## Voice packs

If you fine-tuned Chatterbox on a person's voice yourself, Deck Narrator can use the result.
Make a `.zip` (or a folder) with:

| File | What |
|---|---|
| `reference.wav` (or `.flac`, `.mp3`) | Required. 10 to 30 seconds of the person |
| `t3.safetensors` | Optional. Your fine-tuned T3 weights (Chatterbox 0.1.7's T3, same shape; `t3.` or `module.` prefixes are fine) |
| `voice.json` | Optional. `{"exaggeration": 0.5, "cfg_weight": 0.3, "temperature": 0.8}`; anything left out uses Chatterbox's default. Add `"timbre_reference": "clean.wav"` to use a second recording for the sound of the voice. `"pause_scale": 1.6` lengthens the pauses inside sentences, and `"speed": 0.95` slows the voice a little without changing its pitch (both 1.0 when left out) |
| the timbre recording | Optional, named in `voice.json`. A clean, quiet recording that sets how the voice *sounds*, while `reference.wav` still sets how it *speaks*. Useful when the recording that matches your delivery has room noise |

Then add it like a recording: **Add a voice...** and pick the `.zip`. Lower `cfg_weight` and
`exaggeration` make the voice slower and calmer.

## Command line

```
deck-narrator --install-own-voice                  set up Chatterbox (once)
deck-narrator --add-voice mike recording.wav       add a voice (or a voice pack .zip)
deck-narrator --list-voices                        your voices are listed first
deck-narrator deck.pptx --voice mike               narrate with it
deck-narrator --remove-voice mike                  delete it
deck-narrator --remove-own-voice-support           delete Chatterbox (keeps your voices)
```

`DECK_NARRATOR_TORCH_BACKEND` (`cpu`, `cu128`, ...) picks which PyTorch the setup installs,
instead of the automatic choice. More in the [Reference](REFERENCE.md#your-own-voice).
