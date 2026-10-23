# Minimax Handoff — Single-Narrator Caption Engine Revert

**Project:** `C:\Users\rudra\PycharmProjects\douyindownloader`
**Scope:** `dub_single_narrator.py` caption generation + `dubbing_studio/tts_engine.py` (engine untouched)
**Date:** 2026-10-22
**Owner of this handoff:** Minimax (single-narrator dubbing pipeline)

---

## 1. TL;DR

The custom caption function `align_subtitles_from_script()` was **removed**. Caption generation now runs
**exclusively through the original engine** in `dubbing_studio/tts_engine.py`:

```
generate_synced_hinglish_ass()   ->   srt_to_ass()      (zero styling overrides)
```

Restored look (engine defaults, verified in the regenerated ASS):

| Property | Broken (custom) | Restored (engine) |
|---|---|---|
| Font | Arial | **Montserrat ExtraBold** |
| Font size | 42 | **120** |
| Outline | 9.0 | **9.0** |
| Drop shadow | 2.5 | **2.5** |
| MarginV | 405 (auto-detect silently failed) | **351** (dynamic, from OCR blur box) |
| Timing source | character-duration math over the paragraph | **real spoken-word timings from Faster-Whisper** on the final narration master |

---

## 2. What was wrong

`align_subtitles_from_script()` (deleted) did three things that broke the caption pipeline:

1. **Bypassed the engine.** It never called `generate_synced_hinglish_ass()`; it called `srt_to_ass()`
   directly with hand-rolled overrides (`font_name="Arial"`, `font_size=42`).
2. **Invented the timing.** It split the continuous narration into sentences and distributed them
   proportionally by character count across the audio duration. Captions drifted away from the speech.
3. **Broke dynamic placement.** Because the SRT it wrote was named `..._single_narrator_<tag>.srt`,
   `srt_to_ass()`'s blur-box lookup (`<base>_clean_box.json` in `output/clean_videos/`) never matched,
   so MarginV silently fell back to the hardcoded 405 instead of the OCR-detected 351.

---

## 3. What was restored

### 3.1 New caption flow (`dub_single_narrator.py`)

| Function | Line | Role |
|---|---|---|
| `normalize_match_token()` | 408 | Normalises script/spoken tokens (Devanagari -> Latin via `dubbing_studio/hinglish.py`, punctuation stripped, lowercased) |
| `match_key()` | 424 | Consonant skeleton, so Roman `gehri` == Devanagari `गहरी` -> `gahari` |
| `align_token_indices()` | 432 | Needleman-Wunsch alignment between script words and spoken words |
| `transcribe_narration_words()` | 504 | Faster-Whisper `large-v3-turbo` word-level timestamps on the **final** narration master |
| `align_script_words_to_audio()` | 570 | Maps the exact script onto those real timings, emits phrase-level `placed_blocks` |
| `write_placed_blocks_srt()` | 668 | Emergency fallback only (engine writer failed) |
| `generate_synced_captions()` | 688 | Orchestrator — calls the engine, copies the synced SRT artifact |

Pipeline call site: `dub_single_narrator.py:1076`.

### 3.2 Engine call (zero overrides)

```python
generate_synced_hinglish_ass(
    master_wav=master_wav,      # narration_perfect_timed_<tag>.wav
    placed_blocks=placed_blocks,# real Whisper-aligned blocks
    output_ass=output_ass,
    margin_v=caption_margin_v,  # dynamic OCR value, or None -> engine default
    run_whisper=True,
)
```

`generate_synced_hinglish_ass()` internally writes the timeline-synced SRT and calls
`srt_to_ass(sub_for_ass, out_ass_p, margin_v=margin_v, to_hinglish=False)` — engine defaults for
font, size, outline, shadow. **No custom styling arguments are passed anywhere in this pipeline.**

### 3.3 Dynamic MarginV

`dub_single_narrator.py:1065` resolves the caption height from the OCR blur box via the existing
project helper `dubbing_studio.block_aligner.load_detected_margin_v(clean_video)` (reads
`output/clean_videos/<base>_clean_box.json` -> `margin_v: 351`). If no box JSON exists, `margin_v`
stays `None` and the engine applies its own default (405).

---

## 4. Why Whisper alignment (and not text math)

The narration is one continuous TTS take, so there are no per-block timestamps to reuse. The timings
therefore have to come from the audio itself — which is exactly what the engine's own docstring
describes ("Runs Faster-Whisper on master_wav to capture exact real-world spoken word/phrase
boundaries") and what `dub_single_narrator.py`'s module docstring already claimed at line 16.

Measured on the current project video (92.99s narration, 316 script words):

```
script tokens: 316 | whisper tokens: 320 | DP anchors: 286 (90.5%)
first caption at 0.42s (= real speech start) | last caption ends 92.88s (= real speech end)
```

Two tricks made the alignment reliable:

1. **`initial_prompt` biasing Whisper towards Roman script** (`WHISPER_HINGLISH_PROMPT`,
   `dub_single_narrator.py:59`). Without it Whisper emitted 250 Devanagari words; with it, 320 words
   in Roman/Latin — matching the Roman-script narration script almost 1:1.
2. **Consonant-skeleton matching + Needleman-Wunsch** instead of plain string equality. Plain
   comparison matched only 41% of words (`meter` vs `meeter`, `gehri` vs `gahari`); skeleton matching
   plus the DP alignment reaches 90.5%.

Unmatched script words are interpolated between their nearest anchors, then the word timeline is
forced monotonic and non-overlapping so blocks never collide.

---

## 5. Verification

Run on the existing project assets (no TTS API calls needed):

```
python dub_single_narrator.py --video "<output/clean_videos/视界之外 - 河北深山里的悬空大殿古人究竟是_clean.mp4>"
```

Regenerated `output/subtitles/视界之外 - 河北深山里的悬空大殿古人究竟是_single_narrator_sarvam.ass`:

```
Style: Default,Montserrat ExtraBold,120,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,9.0,2.5,2,40,40,351,1
Dialogue: 0,0:00:00.42,0:00:01.14,Default,,0,0,0,,70 meter gehri
Dialogue: 0,0:00:01.14,0:00:01.80,Default,,0,0,0,,khai par hawa
Dialogue: 0,0:00:01.80,0:00:02.52,Default,,0,0,0,,mein latka hua
...
```

* 121 dialogue events, every one **<= 3 words**.
* Engine log confirms the intended path: *"Script is already in Hinglish! Exact audio-synced
  voiceover blocks matched 1:1."*
* Blocks verified monotonic, non-overlapping, inside the narration duration.

### Full pipeline re-run (end to end, cached audio)

```
python dub_single_narrator.py --video "output\clean_videos\视界之外 - 河北深山里的悬空大殿古人究竟是_clean.mp4"
[Cache] Reusing existing timed audio (92.99s).
[Smart Pacing] Fastening background video B-roll by 1.145x (106.90s -> 93.34s) for zero dead tail.
[Subtitles] Dynamic MarginV=351 detected from ..._clean_box.json
[Subtitles] Reusing cached narration word alignment: narration_whisper_words.json
[Subtitles] Aligned 316 script words to 320 spoken words (286 exact anchors).
[SUCCESS] Final video ready at: output\final_videos\..._single_narrator.mp4 (92.99s, tail 0.01s)
```

Burned-caption frames were extracted from the new final video and inspected: large bold white
Montserrat with a thick black outline, sitting low on the blur plate (t=2s -> "mein latka hua",
t=30s -> "yaani concrete rebar").

### Artifact cleanup

`output/subtitles/..._single_narrator_sarvam_hinglish.ass` (the stale Arial-42 mirror written by the
old custom path) was **deleted**. The reverted code no longer produces that mirror, and leaving it
next to the new ASS was a footgun for anyone re-rendering by hand.

---

## 6. Files touched

| File | Change |
|---|---|
| `dub_single_narrator.py` | Removed `align_subtitles_from_script()`; added Whisper alignment + engine-driven caption generation; pipeline now calls `generate_synced_captions()` |
| `dubbing_studio/tts_engine.py` | **Unchanged** — this is the engine that was restored to service |
| `output/subtitles/*_single_narrator_sarvam.ass` | Regenerated with engine styling |
| `output/subtitles/*_single_narrator_sarvam.srt` | Regenerated (timeline-synced SRT) |
| `output/subtitles/*_single_narrator_sarvam_hinglish.ass` | Deleted (stale Arial-42 mirror) |
| `output/final_videos/*_single_narrator.mp4` | Re-muxed with the restored captions |
| `output/audio_stems/single_narrator_*/narration_whisper_words.json` | New alignment cache |

`dubbing_studio/tts_engine.py` was deliberately **not** modified — the fix was to route the single-narrator
pipeline back through it, not to change the engine.

---

## 7. Caching & artifacts

* Whisper word alignment is cached at
  `output/audio_stems/single_narrator_<base>/narration_whisper_words.json`.
* The cache is invalidated automatically when the narration WAV is newer than the cache
  (`dub_single_narrator.py:504`), and `--force` always re-aligns.
* The engine writes its timeline-synced SRT next to the master WAV
  (`narration_perfect_timed_<tag>_synced.srt`); `generate_synced_captions()` copies it to
  `output/subtitles/<base>_single_narrator_<tag>.srt` for inspection.

---

## 8. Known caveats / fallbacks

1. **No Whisper / GPU failure** -> the pipeline logs a notice and falls back to distributing the script
   over the narration duration. Captions still render through the engine (correct styling), but timing
   is approximate again. Treat this as a degraded mode, not the normal path.
2. **Devanagari script input** -> if the narration script is Devanagari, `generate_synced_hinglish_ass()`
   takes its legacy Gemini transliteration branch and converts to natural Hinglish itself. That is
   engine behaviour and was intentionally left untouched.
3. **English loanwords** -> Whisper sometimes writes them phonetically in Devanagari (`ब्रिज` for
   "bridge"). These land in the interpolation band between anchors, so their caption may appear a few
   hundred ms early/late. The text itself is still the exact script wording.
4. `generate_synced_hinglish_ass(run_whisper=True)` still ignores that flag internally (pre-existing
   engine behaviour) — the Whisper step lives in the caller, as it does in `tts_google.py` / `tts.py`.

---

## 9. Next steps (not done yet)

* [x] Re-mux the final video with the restored captions ->
      `output/final_videos/视界之外 - 河北深山里的悬空大殿古人究竟是_single_narrator.mp4` (92.99s).
* [ ] Review the burned result on-device: caption baseline should sit on the blur plate at
      MarginV 351 and be ~2.8x larger than the old build.
* [ ] If the Devanagari branch is ever exercised, verify the Gemini transliteration keeps the
      Whisper-derived timings (it rewrites text, not timestamps).
* [ ] Decide whether the `_hinglish.ass` mirror should be re-enabled for single-narrator builds
      (`srt_to_ass` only mirrors when `to_hinglish=True`; the engine's synced path uses `False`).

---

## 10. Useful commands

```powershell
# regenerate captions only (reuses cached narration + Whisper alignment)
python dub_single_narrator.py --video "output\clean_videos\<base>_clean.mp4"

# force full rebuild (new TTS audio + fresh alignment + fresh captions)
python dub_single_narrator.py --video "output\clean_videos\<base>_clean.mp4" --force

# check the style line of any generated ASS
Select-String -Path "output\subtitles\*_single_narrator_*.ass" -Pattern "^Style:"
```
