# Script presets

A **preset** is an alternative scriptwriter system prompt — think of it as a
reusable "voice" or "persona" for the writer. Swap presets to change the *style*
of every video without touching code.

- The **default** writer lives one level up at [`../scriptgen_system.md`](../scriptgen_system.md).
- Any `.md` file you drop in **this folder** can be selected as the writer.

## Use a preset

Set `SCRIPT_PROMPT` in your `.env` to the preset's filename (with or without `.md`):

```
SCRIPT_PROMPT=example
```

Now every `python run.py make` / `batch` uses `prompts/presets/example.md`. Leave
`SCRIPT_PROMPT` blank to fall back to the default writer.

> Tip: `CONTENT_NICHE` (in `.env`) layers a subject focus on top of whichever
> preset is active — e.g. preset = your storytelling voice, niche = "personal finance".

## Make your own

1. Copy [`example.md`](example.md) to `prompts/presets/my-style.md`.
2. Edit the voice, structure, and rules to taste.
3. Set `SCRIPT_PROMPT=my-style` in `.env`.

### What a good preset keeps

The pipeline expects the model to return structured scenes, so a preset should still:

- produce **4–5 scenes**, one short narration line each (~40–55 words total);
- describe a **vivid, distinct `image_prompt`** per scene (no on-screen/readable text);
- mark exactly **one** scene `hero: true`, and give each a short `motion_prompt`;
- write the social copy (title, description, captions, hashtags) with **no brand or link**.

Tone, framework, pacing, and visual direction may vary by preset. The mandatory provocative, source-grounded opening hook is appended to every prompt and should not be overridden.
