#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
dubbing_studio/narrator_detector.py
===================================
Detects NARRATOR vs in-scene CHARACTER DIALOGUE blocks in movie-recap videos
by combining:
1. Acoustic voice-embedding similarity & pitch/energy clustering on isolated `speech.wav`.
2. Contextual classification via Gemini (`NARRATOR` vs `DIALOGUE`) informed by acoustic scores.
3. Restoring `DIALOGUE` segments from `speech.wav` back into `sfx.wav` so character voices
   are preserved cleanly rather than silenced.
"""

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import soundfile as sf

from .key_pool import get_active_gemini_keys, is_gemini_dead_error, mark_gemini_key_dead


def _parse_srt_time(ts: str) -> float:
    ts = ts.strip().replace(",", ".")
    parts = ts.split(":")
    if len(parts) == 3:
        return float(parts[0]) * 3600.0 + float(parts[1]) * 60.0 + float(parts[2])
    if len(parts) == 2:
        return float(parts[0]) * 60.0 + float(parts[1])
    return 0.0


def _format_srt_time(sec: float) -> str:
    sec = max(0.0, float(sec))
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = int(sec % 60)
    ms = int(round((sec - int(sec)) * 1000))
    if ms >= 1000:
        s += 1
        ms -= 1000
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def parse_srt_blocks(srt_path: Path) -> List[Dict[str, Any]]:
    text = Path(srt_path).read_text(encoding="utf-8", errors="replace").strip()
    if not text:
        return []
    blocks: List[Dict[str, Any]] = []
    for chunk in re.split(r"\r?\n\r?\n+", text):
        lines = [ln.strip() for ln in chunk.splitlines() if ln.strip()]
        if len(lines) < 3:
            continue
        ts_line = lines[1]
        if "-->" not in ts_line:
            continue
        t0_s, t1_s = [p.strip() for p in ts_line.split("-->", 1)]
        try:
            idx = int(re.sub(r"\D", "", lines[0]) or (len(blocks) + 1))
        except Exception:
            idx = len(blocks) + 1
        blocks.append({
            "index": idx,
            "start": _parse_srt_time(t0_s),
            "end": _parse_srt_time(t1_s),
            "start_str": t0_s,
            "end_str": t1_s,
            "text": " ".join(lines[2:]),
        })
    return blocks


def write_srt_blocks(blocks: List[Dict[str, Any]], out_path: Path) -> Path:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    lines: List[str] = []
    for new_idx, b in enumerate(blocks, 1):
        lines.append(str(new_idx))
        lines.append(f"{_format_srt_time(b['start'])} --> {_format_srt_time(b['end'])}")
        lines.append(b["text"].strip())
        lines.append("")
    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path


def _extract_acoustic_profiles(
    blocks: List[Dict[str, Any]],
    speech_wav: Path,
) -> List[Dict[str, Any]]:
    """Compute speaker feature vectors (MFCC + Spectral + RMS + Pitch) per SRT block."""
    import librosa

    with open(speech_wav, "rb") as f_in:
        audio, sr = sf.read(f_in)
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    audio = np.asarray(audio, dtype=np.float32)

    if sr != 16000:
        audio = librosa.resample(audio, orig_sr=sr, target_sr=16000)
        sr = 16000

    feats: List[Optional[np.ndarray]] = []
    durs: List[float] = []
    rms_vals: List[float] = []

    for b in blocks:
        i0 = max(0, int(b["start"] * sr))
        i1 = min(len(audio), int(b["end"] * sr))
        seg = audio[i0:i1]
        dur = max(0.05, (i1 - i0) / float(sr))
        durs.append(dur)
        rms = float(np.sqrt(np.mean(seg ** 2) + 1e-12)) if len(seg) > 0 else 0.0
        rms_vals.append(rms)

        if len(seg) < int(0.25 * sr) or rms < 1e-4:
            feats.append(None)
            continue

        try:
            mfcc = librosa.feature.mfcc(y=seg, sr=sr, n_mfcc=20, n_fft=512, hop_length=160)
            mfcc_mean = np.mean(mfcc, axis=1)
            mfcc_std = np.std(mfcc, axis=1)
            cent = float(np.mean(librosa.feature.spectral_centroid(y=seg, sr=sr)))
            zcr = float(np.mean(librosa.feature.zero_crossing_rate(y=seg)))
            vec = np.concatenate([mfcc_mean, mfcc_std * 0.5, [cent / 1000.0, zcr * 10.0, np.log10(rms + 1e-6)]])
            feats.append(vec.astype(np.float32))
        except Exception:
            feats.append(None)

    valid_idx = [i for i, v in enumerate(feats) if v is not None]
    profiles: List[Dict[str, Any]] = []

    if len(valid_idx) >= 3:
        mat = np.stack([feats[i] for i in valid_idx], axis=0)
        # Unit-normalize raw feature vectors without mean-subtraction to preserve absolute voice timbre similarity
        norms = np.maximum(np.linalg.norm(mat, axis=1, keepdims=True), 1e-6)
        unit_mat = mat / norms

        # Anchor narrator centroid on duration-weighted majority
        weights = np.array([durs[i] * (1.0 + min(2.0, rms_vals[i] * 10.0)) for i in valid_idx], dtype=np.float32)
        init_centroid = np.average(unit_mat, axis=0, weights=weights)
        init_centroid /= max(np.linalg.norm(init_centroid), 1e-6)
        sims_init = unit_mat @ init_centroid
        cutoff = float(np.percentile(sims_init, 25))
        core_mask = sims_init >= cutoff
        if np.any(core_mask):
            narrator_centroid = np.average(unit_mat[core_mask], axis=0, weights=weights[core_mask])
            narrator_centroid /= max(np.linalg.norm(narrator_centroid), 1e-6)
        else:
            narrator_centroid = init_centroid

        sims_all = unit_mat @ narrator_centroid
        sim_map = {valid_idx[k]: float(sims_all[k]) for k in range(len(valid_idx))}
    else:
        sim_map = {i: 0.90 for i in range(len(blocks))}

    for i, b in enumerate(blocks):
        sim = sim_map.get(i, 0.85)
        profiles.append({
            "index": b["index"],
            "start": b["start"],
            "end": b["end"],
            "text": b["text"],
            "narrator_sim": round(sim, 3),
            "rms_db": round(float(20.0 * np.log10(max(rms_vals[i], 1e-7))), 1),
        })
    return profiles


def _classify_roles_with_gemini(profiles: List[Dict[str, Any]]) -> Optional[Dict[int, str]]:
    """Single structured Gemini call combining transcript context + acoustic narrator similarity."""
    if not profiles:
        return None

    keys = get_active_gemini_keys()
    if not keys:
        return None

    try:
        from google import genai
        from google.genai import types
    except Exception:
        return None

    lines_payload = []
    for p in profiles:
        lines_payload.append(
            f"#{p['index']} [{p['start']:.2f}s-{p['end']:.2f}s | voice_sim={p['narrator_sim']:.2f} | vol={p['rms_db']}dB]: {p['text']}"
        )
    prompt = (
        "You are analyzing a Whisper transcript of a movie-recap video.\n"
        "Each subtitle block comes from EITHER:\n"
        "1) NARRATOR: The main voiceover narrator explaining/summarizing the movie in 3rd-person commentary.\n"
        "2) DIALOGUE: In-scene movie character speech/dialogue/shouting (1st/2nd person lines, direct character exchanges, or voice outliers).\n\n"
        "Signals provided per block:\n"
        "- Text meaning & grammar (PRIMARY): 3rd-person story recap/commentary (e.g., describing what the protagonist/villain did next) is ALWAYS NARRATOR even if the narrator sounds excited. Direct character speech, 1st/2nd-person dialogue, questions/answers between characters, or shouted exclamations in-scene = DIALOGUE.\n"
        "- `voice_sim`: Acoustic cosine similarity (0.0 to 1.0) to the dominant studio narrator voice. Low `voice_sim` (< 0.55) reinforces DIALOGUE for short/ambiguous lines; high `voice_sim` (>= 0.70) reinforces NARRATOR.\n"
        "- `vol`: Audio loudness in dB. Movie characters often sound quieter/more distant vs steady studio narrator.\n\n"
        "Return ONLY valid JSON: {\"roles\": {\"1\": \"NARRATOR\", \"2\": \"DIALOGUE\", ...}} covering EVERY block ID.\n"
        "If unsure, prefer NARRATOR.\n\n"
        "Blocks:\n" + "\n".join(lines_payload)
    )

    classifier_models = ["gemini-3.5-flash-lite", "gemini-3.8-flash", "gemini-flash-latest"]
    for idx, k in enumerate(keys[:5]):
        model_name = classifier_models[idx % len(classifier_models)]
        try:
            client = genai.Client(api_key=k, http_options={"timeout": 20000})
            resp = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.0,
                    response_mime_type="application/json",
                ),
            )
            raw_json = (resp.text or "").strip()
            data = json.loads(raw_json)
            roles_raw = data.get("roles") if isinstance(data, dict) else None
            if isinstance(roles_raw, dict):
                out: Dict[int, str] = {}
                for k_id, val in roles_raw.items():
                    try:
                        bid = int(re.sub(r"\D", "", str(k_id)))
                        norm = "DIALOGUE" if "DIALOG" in str(val).upper() else "NARRATOR"
                        out[bid] = norm
                    except Exception:
                        continue
                if out:
                    return out
        except Exception as e:
            if is_gemini_dead_error(str(e)):
                mark_gemini_key_dead(k, reason=str(e)[:120])
            continue
    return None


def restore_dialogue_audio_to_sfx(
    sfx_wav: Path,
    speech_wav: Path,
    dialogue_blocks: List[Dict[str, Any]],
    out_wav: Path,
    dialogue_gain: float = 0.95,
    pad_sec: float = 0.12,
    fade_sec: float = 0.04,
) -> Path:
    """
    Restores original character dialogue windows from `speech.wav` back into `sfx.wav`
    with smooth raised-cosine fades so movie dialogues are NOT silenced when narrator is dubbed.
    """
    with open(sfx_wav, "rb") as f_sfx:
        sfx_audio, sfx_sr = sf.read(f_sfx)
    with open(speech_wav, "rb") as f_sp:
        sp_audio, sp_sr = sf.read(f_sp)

    if sfx_audio.ndim > 1:
        sfx_audio = sfx_audio.mean(axis=1)
    if sp_audio.ndim > 1:
        sp_audio = sp_audio.mean(axis=1)

    sfx_audio = np.asarray(sfx_audio, dtype=np.float32)
    sp_audio = np.asarray(sp_audio, dtype=np.float32)

    if sp_sr != sfx_sr:
        import librosa
        sp_audio = librosa.resample(sp_audio, orig_sr=sp_sr, target_sr=sfx_sr)

    n = min(len(sfx_audio), len(sp_audio))
    mask = np.zeros(n, dtype=np.float32)
    fade_samples = max(1, int(fade_sec * sfx_sr))

    for b in dialogue_blocks:
        # Zero-Chinese Audio Rule: Never restore Chinese dialogue into English dubs.
        # Only authentic non-Chinese speech/screams/groans are restored.
        block_text = str(b.get("text", "")).strip()
        if re.search(r"[\u4e00-\u9fff]", block_text):
            continue

        i0 = max(0, int((float(b["start"]) - pad_sec) * sfx_sr))
        i1 = min(n, int((float(b["end"]) + pad_sec) * sfx_sr))
        if i1 <= i0:
            continue
        seg_mask = np.ones(i1 - i0, dtype=np.float32)
        f = min(fade_samples, (i1 - i0) // 3)
        if f > 0:
            ramp = 0.5 * (1.0 - np.cos(np.pi * np.arange(f, dtype=np.float32) / float(f)))
            seg_mask[:f] = ramp
            seg_mask[-f:] = ramp[::-1]
        mask[i0:i1] = np.maximum(mask[i0:i1], seg_mask)

    mixed = sfx_audio[:n] + sp_audio[:n] * mask * float(dialogue_gain)
    peak = float(np.max(np.abs(mixed))) if len(mixed) else 0.0
    if peak > 0.98:
        mixed = mixed * (0.98 / peak)

    out_wav = Path(out_wav)
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    with open(out_wav, "wb") as f_out:
        sf.write(f_out, mixed, sfx_sr, format="WAV")
    return out_wav


def detect_narrator_and_dialogue(
    raw_srt: Path,
    speech_wav: Path,
    sfx_wav: Optional[Path],
    narrator_srt_out: Path,
    sfx_with_dialogue_out: Optional[Path] = None,
    roles_json_out: Optional[Path] = None,
    force: bool = False,
) -> Dict[str, Any]:
    """
    Separates NARRATOR vs DIALOGUE blocks, writes narrator-only SRT for clean translation/dubbing,
    and restores original character dialogue audio into `sfx.wav`.
    """
    blocks = parse_srt_blocks(raw_srt)
    if not blocks or not Path(speech_wav).exists():
        return {
            "narrator_srt": raw_srt,
            "sfx_track": sfx_wav,
            "narrator_count": len(blocks),
            "dialogue_count": 0,
            "roles": [],
        }

    # Cache hit for resume hygiene: reuse existing speaker role classification & artifacts when force=False
    if not force and roles_json_out and Path(roles_json_out).exists():
        try:
            cached = json.loads(Path(roles_json_out).read_text(encoding="utf-8"))
            cached_roles = cached.get("blocks", [])
            if isinstance(cached_roles, list) and len(cached_roles) == len(blocks):
                diag_cnt = int(cached.get("dialogue_blocks", 0))
                narr_cnt = int(cached.get("narrator_blocks", len(blocks) - diag_cnt))
                if diag_cnt == 0:
                    print(f"[NarratorDetector] Reusing cached speaker roles ({narr_cnt} narrator, 0 dialogue) -> 0 LLM calls")
                    return {
                        "narrator_srt": raw_srt,
                        "sfx_track": sfx_wav,
                        "narrator_count": narr_cnt,
                        "dialogue_count": 0,
                        "roles": cached_roles,
                    }
                need_sfx = bool(sfx_wav and Path(sfx_wav).exists() and sfx_with_dialogue_out)
                sfx_ready = (not need_sfx) or Path(sfx_with_dialogue_out).exists()
                if Path(narrator_srt_out).exists() and sfx_ready:
                    print(f"[NarratorDetector] Reusing cached speaker roles ({narr_cnt} narrator, {diag_cnt} dialogue) -> 0 LLM calls")
                    return {
                        "narrator_srt": narrator_srt_out,
                        "sfx_track": Path(sfx_with_dialogue_out) if need_sfx else sfx_wav,
                        "narrator_count": narr_cnt,
                        "dialogue_count": diag_cnt,
                        "roles": cached_roles,
                    }
        except Exception:
            pass

    profiles = _extract_acoustic_profiles(blocks, Path(speech_wav))
    gemini_roles = _classify_roles_with_gemini(profiles)

    roles_list: List[Dict[str, Any]] = []
    narrator_blocks: List[Dict[str, Any]] = []
    dialogue_blocks: List[Dict[str, Any]] = []

    for b, prof in zip(blocks, profiles):
        if gemini_roles and b["index"] in gemini_roles:
            role = gemini_roles[b["index"]]
        else:
            # Conservative acoustic fallback: Recap videos are dominant narration.
            # Default to NARRATOR to prevent original narrator audio leaking into SFX.
            # Only classify as DIALOGUE if voice similarity is an extreme outlier (< 0.35) and quiet/distant.
            is_extreme_outlier = prof["narrator_sim"] < 0.35 and prof.get("rms_db", 0.0) < -20.0
            role = "DIALOGUE" if is_extreme_outlier else "NARRATOR"
        roles_list.append({**prof, "role": role})
        if role == "DIALOGUE":
            dialogue_blocks.append(b)
        else:
            narrator_blocks.append(b)

    # Safety: guard against false-positive dialogue clusters that leak narrator voice
    if not gemini_roles and len(dialogue_blocks) > 0.30 * len(blocks):
        print(f"[NarratorDetector] False-positive dialogue cluster ({len(dialogue_blocks)}/{len(blocks)}). Forcing all blocks to NARRATOR to protect audio mix.")
        narrator_blocks = blocks
        dialogue_blocks = []
        for r in roles_list:
            r["role"] = "NARRATOR"

    # Safety: never allow 0 narrator blocks (would leave video with empty voiceover)
    if not narrator_blocks:
        narrator_blocks = blocks
        dialogue_blocks = []
        for r in roles_list:
            r["role"] = "NARRATOR"

    if roles_json_out:
        Path(roles_json_out).parent.mkdir(parents=True, exist_ok=True)
        Path(roles_json_out).write_text(
            json.dumps(
                {
                    "total_blocks": len(blocks),
                    "narrator_blocks": len(narrator_blocks),
                    "dialogue_blocks": len(dialogue_blocks),
                    "blocks": roles_list,
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    if dialogue_blocks:
        write_srt_blocks(narrator_blocks, narrator_srt_out)
        out_sfx = sfx_wav
        if sfx_wav and Path(sfx_wav).exists() and sfx_with_dialogue_out:
            out_sfx = restore_dialogue_audio_to_sfx(
                sfx_wav=Path(sfx_wav),
                speech_wav=Path(speech_wav),
                dialogue_blocks=dialogue_blocks,
                out_wav=Path(sfx_with_dialogue_out),
            )
        return {
            "narrator_srt": narrator_srt_out,
            "sfx_track": out_sfx,
            "narrator_count": len(narrator_blocks),
            "dialogue_count": len(dialogue_blocks),
            "roles": roles_list,
        }

    return {
        "narrator_srt": raw_srt,
        "sfx_track": sfx_wav,
        "narrator_count": len(narrator_blocks),
        "dialogue_count": 0,
        "roles": roles_list,
    }

