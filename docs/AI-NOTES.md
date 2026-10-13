# Let an AI write your notes

**The best videos come from having an AI chatbot write the speaker notes and fix the
pronunciations.** ChatGPT, Claude, Copilot, Gemini or similar are good at exactly this:
turning slide bullets into natural spoken sentences, putting each `[click]` where the slide's
animation happens, and spelling out the abbreviations and product names a voice would trip over.

> Uploading a deck sends it to that AI company. Deck Narrator itself never sends your deck
> anywhere. For a work deck, check your company's rules on AI tools first.

## How

1. Open your AI chatbot and attach your PowerPoint file (`.pptx`).
2. Copy the prompt below, paste it into the chat, and send it.
3. Most chatbots that can run code give you back the deck with the new notes in it. Save it
   and open it in Deck Narrator. If yours gives you text instead, copy each slide's notes
   into PowerPoint (**View > Notes**, then click under the slide).
4. In Deck Narrator, click **Check builds** to see that the `[click]`s line up with the
   animations, then **Check pronunciation** to catch any word still at risk. Then **Make
   video**.

## The prompt

Copy all of this:

```text
I'm turning this PowerPoint deck into a narrated video with a text-to-speech tool called
Deck Narrator. It reads each slide's speaker notes out loud, word for word. Please rewrite
the speaker notes of every slide so they sound good spoken.

How to write the notes:
- Write what a presenter would SAY, in full sentences, not the bullet text. Keep it
  conversational and to the point: 2 to 5 sentences per slide unless the slide needs more.
- Keep my existing notes' meaning and facts. Don't invent numbers, names or claims.
- Punctuation is pacing: a comma is a short pause, a period a longer one.
- Write numbers, symbols and abbreviations the way they should be said: "version two point
  oh", not "v2.0"; "thirty percent", not "30%"; "for example", not "e.g.".
- Respell any acronym, product name or unusual word the voice might misread, as plain words
  that sound right: "NGINX" -> "engine x", "SQL" -> "sequel", "GIF" -> "jif", "OPSWAT" ->
  "op swat". Say acronyms that are spelled out with spaces: "N V M E".
- Watch for words with two pronunciations (read, record, present, lead, live, close, wind,
  object, content). Reword the sentence so the meaning is unmistakable, for example
  "present it to the team" rather than ending a sentence on "or present".

Animation:
- Look at each slide's animations (the slide's timing XML in the .pptx). Count the "On
  Click" steps; emphasis and motion-path steps count too, but "With Previous" and "After
  Previous" don't start a new step.
- Put exactly that many [click] markers in that slide's notes, each at the point where the
  narration should move on to the thing that appears. Text before the first [click] is said
  while the slide first appears.
- A slide with no animations gets no [click].

Special markers (type them exactly like this; nothing else in square brackets is read out):
- [click] advances the slide's animation.
- [voice: am_michael] switches to another narrator from that point on, including later
  slides. [voice: default] goes back. Only use voices if I ask for more than one narrator.

What to give me back:
- If you can edit files, give me the deck back as a .pptx with these notes in it and
  nothing else changed.
- Otherwise, list the notes slide by slide ("Slide 1:", "Slide 2:", ...).
- After that, list every word you respelled, one per line as WORD=respelling (for example
  NGINX=engine x), so I can add them to Deck Narrator's pronunciation dictionary.
```

## Afterwards

The `WORD=respelling` lines at the end are worth keeping: put them in your pronunciation
dictionary (the **Pronunciation** tab in Deck Narrator, **Edit** next to **Dictionary**; one rule per line) and every future deck says
those words right, even in notes you write yourself. [Fixing
pronunciation](PRONUNCIATION.md#the-pronunciation-file-every-occurrence) explains the file.

If a word still comes out wrong, **Check pronunciation** lets you hear the choices and pick
one. [Fixing pronunciation](PRONUNCIATION.md) has the details.
