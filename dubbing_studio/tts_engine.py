#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
dubbing_studio/tts_engine.py
============================
GPU-accelerated Kokoro ONNX Text-to-Speech synthesis and FFmpeg video dubbing muxer.
"""

import os
import sys
import re
import json
import time
import subprocess
from pathlib import Path
from typing import Optional, Union, List, Dict, Any

import numpy as np
import soundfile as sf

from .env_loader import configure_runtime_environment
configure_runtime_environment()


def parse_time(time_str: str) -> float:
    time_str = time_str.strip().replace(",", ".")
    parts = time_str.split(":")
    if len(parts) == 3:
        return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
    elif len(parts) == 2:
        return float(parts[0]) * 60 + float(parts[1])
    return float(parts[0])


def load_srt_blocks(srt_path: Union[str, Path]) -> List[Dict[str, Any]]:
    content = Path(srt_path).read_text(encoding="utf-8")
    content = content.replace("\r\n", "\n").replace("\r", "\n").strip()

    blocks = []
    chunks = [c.strip() for c in content.split("\n\n") if c.strip()]
    for chk in chunks:
        lines = [l.strip() for l in chk.split("\n") if l.strip()]
        if len(lines) >= 3 and "-->" in lines[1]:
            idx_val = int(lines[0]) if lines[0].isdigit() else len(blocks) + 1
            ts_parts = lines[1].split("-->")
            s_sec = parse_time(ts_parts[0])
            e_sec = parse_time(ts_parts[1])
            text_val = " ".join(" ".join(lines[2:]).split())
            blocks.append({
                "index": idx_val,
                "start": s_sec,
                "end": e_sec,
                "duration": round(e_sec - s_sec, 2),
                "text": text_val
            })
    return blocks


def srt_to_ass(
    srt_path: Union[str, Path],
    ass_path: Optional[Union[str, Path]] = None,
    target_w: int = 1080,
    target_h: int = 1920,
    font_size: int = 120,
    margin_v: Optional[int] = None,
    font_name: str = "Montserrat ExtraBold",
    to_hinglish: bool = True
) -> Path:
    """
    Converts SRT subtitles into an ultra-clean, high-visibility ASS format.
    Designed for 9:16 Shorts/Reels with bold typography (120pt Montserrat ExtraBold),
    thick 9.0px outline, 2.5px shadow, strictly <=3 words per chunk, and 
    optimal positioning directly over the lower-third blurred plate.
    Always converts Hindi Devanagari to colloquial Romanized Hinglish.
    """
    srt_p = Path(srt_path)
    ass_p = Path(ass_path) if ass_path else srt_p.with_suffix(".ass")
    blocks = load_srt_blocks(srt_p)
    if not blocks:
        return ass_p

    # Auto-load MarginV from detected box JSON if not explicitly provided
    if margin_v is None:
        margin_v = 405
        parent_dir = srt_p.parent
        clean_name = srt_p.stem.replace("_hindi", "").replace("_raw", "").replace("_hinglish", "")
        candidates = [
            parent_dir.parent / "clean_videos" / f"{clean_name}_clean_box.json",
            parent_dir / f"{clean_name}_box.json",
            parent_dir / f"{clean_name}_clean_box.json"
        ]
        for c in candidates:
            if c.exists():
                try:
                    data = json.loads(c.read_text(encoding="utf-8"))
                    if "y_center" in data:
                        margin_v = max(180, target_h - int(data["y_center"]) - 65)
                    else:
                        margin_v = max(180, int(data.get("margin_v", 405)) - 30)
                    print(f"[srt_to_ass] Dynamic MarginV={margin_v} loaded from {c.name}")
                    break
                except Exception:
                    pass

    def to_ass_time(sec: float) -> str:
        h = int(sec // 3600)
        m = int((sec % 3600) // 60)
        s = int(sec % 60)
        cs = int(round((sec - int(sec)) * 100))
        if cs >= 100:
            cs = 99
        return f"{h}:{m:02d}:{s:02d}.{cs:02d}"

    # Auto-detect language script (Devanagari vs Latin) & convert to Hinglish
    sample_text = " ".join([b["text"] for b in blocks[:10]])
    is_devanagari = any('\u0900' <= ch <= '\u097F' for ch in sample_text)
    if to_hinglish and is_devanagari:
        try:
            from .hinglish import text_to_hinglish
        except ImportError:
            from dubbing_studio.hinglish import text_to_hinglish
        for b in blocks:
            b["text"] = text_to_hinglish(b["text"])

    ass_header = f"""[Script Info]
; Script generated with Audio-Synced Hinglish <=3 Words Per Event
ScriptType: v4.00+
PlayResX: {target_w}
PlayResY: {target_h}
WrapStyle: 0
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.709

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{font_name},{font_size},&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,9.0,2.5,2,40,40,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    # Chunk sentences into snappy <= 3 words events
    events = []
    for b in blocks:
        st = b["start"]
        en = b["end"]
        words = b["text"].split()
        if not words:
            continue
        w_chunks = []
        curr = []
        for w in words:
            cand = " ".join(curr + [w])
            # Strict safety width: max 15 chars or 3 words so 120pt text never touches screen edges
            if curr and (len(cand) > 15 or len(curr) >= 3 or any(curr[-1].endswith(p) for p in [".", "!", "?", ","])):
                w_chunks.append(curr)
                curr = [w]
            else:
                curr.append(w)
            if any(w.endswith(p) for p in [".", "!", "?", ","]):
                w_chunks.append(curr)
                curr = []
        if curr:
            w_chunks.append(curr)

        dur = max(0.4, en - st)
        total_chars = max(1, sum(len(" ".join(c)) for c in w_chunks))
        cur_t = st
        for c in w_chunks:
            c_text = " ".join(c)
            c_dur = dur * (len(c_text) / float(total_chars))
            events.append({"start": cur_t, "end": cur_t + c_dur, "text": c_text})
            cur_t += c_dur

    ass_lines = [ass_header.strip()]
    for i, e in enumerate(events):
        t_st = to_ass_time(e["start"])
        # Seamlessly hold text until next event begins so no flicker/blinking
        if i < len(events) - 1:
            t_en = to_ass_time(events[i+1]["start"])
        else:
            t_en = to_ass_time(e["end"])
        clean_txt = e["text"].replace("\n", " ").strip()
        ass_lines.append(f"Dialogue: 0,{t_st},{t_en},Default,,0,0,0,,{clean_txt}")

    content = "\n".join(ass_lines) + "\n"
    ass_p.write_text(content, encoding="utf-8")

    # Also mirror to dedicated _hinglish.ass if applicable
    if to_hinglish:
        hinglish_ass = srt_p.parent / f"{srt_p.stem.replace('_hindi', '').replace('_raw', '')}_hinglish.ass"
        if hinglish_ass != ass_p:
            hinglish_ass.write_text(content, encoding="utf-8")

    return ass_p


class KokoroTTS:
    """Kokoro ONNX TTS synthesizer and dubbing engine."""

    def __init__(
        self,
        model_path: Optional[Union[str, Path]] = None,
        voices_path: Optional[Union[str, Path]] = None
    ):
        model_candidates = [
            Path(model_path) if model_path else None,
            Path(os.environ.get("KOKORO_MODEL_PATH", "")) if os.environ.get("KOKORO_MODEL_PATH") else None,
            Path(r"C:\Users\rudra\PycharmProjects\captions videos maker\kokoro-v1.0.onnx"),
            Path(__file__).resolve().parent.parent / "TikTokDownloader" / "models" / "kokoro-v1.0.onnx",
        ]
        voice_candidates = [
            Path(voices_path) if voices_path else None,
            Path(os.environ.get("KOKORO_VOICES_PATH", "")) if os.environ.get("KOKORO_VOICES_PATH") else None,
            Path(r"C:\Users\rudra\PycharmProjects\captions videos maker\voices-v1.0.bin"),
            Path(__file__).resolve().parent.parent / "TikTokDownloader" / "models" / "voices-v1.0.bin",
        ]

        self.model_path = next((p for p in model_candidates if p and p.exists()), None)
        self.voices_path = next((p for p in voice_candidates if p and p.exists()), None)

        if not self.model_path:
            raise FileNotFoundError("Kokoro ONNX model file not found. Set KOKORO_MODEL_PATH in .env.")
        if not self.voices_path:
            raise FileNotFoundError("Kokoro voices bin file not found. Set KOKORO_VOICES_PATH in .env.")

        self._kokoro = None

    def _load_engine(self):
        if self._kokoro is not None:
            return self._kokoro

        import onnxruntime as ort
        from kokoro_onnx import Kokoro

        sess_opts = ort.SessionOptions()
        sess_opts.log_severity_level = 3
        providers = (
            ["CUDAExecutionProvider", "CPUExecutionProvider"]
            if "CUDAExecutionProvider" in ort.get_available_providers()
            else ["CPUExecutionProvider"]
        )

        session = ort.InferenceSession(str(self.model_path), sess_options=sess_opts, providers=providers)
        active_ep = session.get_providers()[0]
        print(f"[KokoroTTS] Active ONNX Provider: {active_ep} ({'NVIDIA GPU' if 'CUDA' in active_ep else 'CPU'})")

        self._kokoro = Kokoro.from_session(session, str(self.voices_path))
        return self._kokoro

    def detect_kokoro_language(self, lang: str, voice: str) -> str:
        l_lower = lang.lower()
        if l_lower.startswith("hi") or voice.startswith("h"):
            return "hi"
        elif l_lower.startswith("ja") or voice.startswith("j"):
            return "ja"
        elif l_lower.startswith("zh") or voice.startswith("z"):
            return "zh"
        elif l_lower.startswith("es") or voice.startswith("e"):
            return "es"
        elif l_lower.startswith("fr") or voice.startswith("f"):
            return "fr"
        elif l_lower.startswith("it") or voice.startswith("i"):
            return "it"
        elif l_lower.startswith("pt") or voice.startswith("p"):
            return "pt"
        return "en-us"

    def synthesize_and_dub(
        self,
        dubbed_srt: Union[str, Path],
        original_video: Union[str, Path],
        final_video: Optional[Union[str, Path]] = None,
        voice: str = "am_michael",
        lang: str = "English",
        base_speed: float = 1.28,
        **kwargs
    ) -> Path:
        srt_path = Path(dubbed_srt)
        vid_path = Path(original_video)
        out_vid = Path(final_video) if final_video else srt_path.parent / f"{srt_path.stem}_dubbed.mp4"

        print(f"\n==========================================")
        print(f"[KokoroTTS] Synthesizing Voiceover Audio Track")
        print(f"Voice: {voice} | Language: {lang} | Base Speed: {base_speed}x")
        print(f"Subtitles: {srt_path.name}")
        print(f"Target Video: {out_vid.name}")
        print(f"==========================================")

        engine = self._load_engine()
        sample_rate = 24000
        kokoro_lang = self.detect_kokoro_language(lang, voice)

        blocks = load_srt_blocks(srt_path)
        if not blocks:
            raise RuntimeError(f"No subtitle blocks found in {srt_path}")

        last_end = max(b["end"] for b in blocks)
        total_sec = max(last_end + 15.0, 100.0)
        synced_buffer = np.zeros(int(total_sec * sample_rate), dtype=np.float32)

        cursor_sample = 0
        t_start_proc = time.time()

        print(f"[KokoroTTS] Generating audio for {len(blocks)} blocks (Kokoro lang: {kokoro_lang})...")
        for i, b in enumerate(blocks, 1):
            text = b["text"]
            t_start = b["start"]
            t_end = b["end"]
            target_dur = max(t_end - t_start, 0.8)

            # Dynamic pacing calculation
            word_count = len(text.split())
            est_dur = word_count / 3.0
            if est_dur > target_dur:
                speed = min(round(base_speed * (est_dur / target_dur), 2), 1.45)
            else:
                speed = base_speed

            try:
                samples, _ = engine.create(text, voice=voice, speed=speed, lang=kokoro_lang)
            except Exception as e:
                print(f"[KokoroTTS] Warning on block #{b['index']}: {e}")
                continue

            audio_len = len(samples)
            start_idx = max(int(t_start * sample_rate), cursor_sample)
            end_idx = start_idx + audio_len

            if end_idx > len(synced_buffer):
                synced_buffer = np.pad(synced_buffer, (0, end_idx - len(synced_buffer) + 48000))

            synced_buffer[start_idx:end_idx] = samples
            cursor_sample = end_idx + int(0.025 * sample_rate)  # 25ms tight pause

            if i % 10 == 0 or i == len(blocks):
                print(f"  [{i}/{len(blocks)}] Generated block #{b['index']} (Speed: {speed}x)")

        # Normalize audio volume
        max_amp = np.max(np.abs(synced_buffer))
        if max_amp > 1.0:
            synced_buffer = synced_buffer / max_amp * 0.98

        # Save synchronized audio
        temp_wav = srt_path.parent / f"temp_dub_{srt_path.stem}.wav"
        temp_mp3 = srt_path.parent / f"temp_dub_{srt_path.stem}.mp3"
        sf.write(str(temp_wav), synced_buffer, sample_rate)

        subprocess.run(
            ["ffmpeg", "-y", "-i", str(temp_wav), "-b:a", "192k", str(temp_mp3)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )

        print(f"[KokoroTTS] Audio synthesized in {time.time() - t_start_proc:.1f}s.")
        print(f"[KokoroTTS] Muxing dubbed audio into final video...")

        needs_transcode = False
        try:
            probe_p = subprocess.run(
                ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height,codec_name", "-of", "json", str(vid_path)],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=5
            )
            probe_data = json.loads(probe_p.stdout.decode("utf-8"))
            vstream = probe_data.get("streams", [{}])[0]
            vw, vh = int(vstream.get("width", 0)), int(vstream.get("height", 0))
            vcodec = vstream.get("codec_name", "")
            if vw > 1080 or vh > 1920 or vcodec != "hevc":
                needs_transcode = True
        except Exception:
            needs_transcode = False

        if needs_transcode:
            v_args = ["-vf", "scale='if(gt(iw,ih),-2,min(1080,iw))':'if(gt(iw,ih),min(1080,ih),-2)':flags=lanczos", "-c:v", "hevc_nvenc", "-preset", "p4", "-b:v", "3600k", "-maxrate", "5000k", "-bufsize", "8000k", "-tag:v", "hvc1"]
        else:
            v_args = ["-c:v", "copy"]

        cmd = [
            "ffmpeg", "-y",
            "-i", str(vid_path),
            "-i", str(temp_mp3),
            *v_args,
            "-c:a", "aac",
            "-b:a", "192k",
            "-map", "0:v:0",
            "-map", "1:a:0",
            "-shortest",
            str(out_vid)
        ]
        res = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if res.returncode == 0:
            print(f"\n[KokoroTTS] SUCCESS! Dubbed video created: {out_vid}")
            return out_vid
        else:
            raise RuntimeError(f"FFmpeg error remuxing video. Code: {res.returncode}")


def generate_synced_hinglish_ass(
    master_wav: Union[str, Path],
    placed_blocks: List[Dict[str, Any]],
    output_ass: Union[str, Path],
    margin_v: Optional[int] = None,
    run_whisper: bool = True
) -> Path:
    """
    Builds a frame-perfect Hinglish ASS subtitle track matching what was actually synthesized:
    1. Writes out a timeline-synced Devanagari SRT from placed block timestamps [T_start, T_end].
    2. Runs Faster-Whisper on master_wav to capture exact real-world spoken word/phrase boundaries.
    3. Sends the Hindi Devanagari SRT to Gemini LLM to transcreate into natural, modern Hinglish
       (proper English spellings for English loanwords, colloquial Romanized Hindi for Hindi words).
    4. Converts into high-retention <=3 words ASS captions centered over the blur box (margin_v).
    """
    master_wav_p = Path(master_wav)
    out_ass_p = Path(output_ass)
    base_stem = master_wav_p.stem
    subs_dir = master_wav_p.parent

    # 1. First, create the exact Timeline-Synced SRT from placed blocks
    synced_srt_path = subs_dir / f"{base_stem}_synced.srt"
    synced_lines = []
    for b in placed_blocks:
        idx = b.get("index", 1)
        st = b.get("start", b.get("start_sec", 0.0))
        et = b.get("end", b.get("end_sec", st + 1.0))
        text = b.get("text", "")
        hrs_s, mins_s, secs_s = int(st // 3600), int((st % 3600) // 60), int(st % 60)
        ms_s = int(round((st - int(st)) * 1000))
        hrs_e, mins_e, secs_e = int(et // 3600), int((et % 3600) // 60), int(et % 60)
        ms_e = int(round((et - int(et)) * 1000))
        ts = f"{hrs_s:02d}:{mins_s:02d}:{secs_s:02d},{ms_s:03d} --> {hrs_e:02d}:{mins_e:02d}:{secs_e:02d},{ms_e:03d}"
        synced_lines.append(f"{idx}\n{ts}\n{text}\n")

    synced_content = "\n".join(synced_lines).strip() + "\n"
    synced_srt_path.write_text(synced_content, encoding="utf-8")

    # Check if text contains Devanagari script
    has_devanagari = bool(re.search(r'[\u0900-\u097F]', synced_content))

    if has_devanagari:
        # Colloquial Roman Hinglish (Recommended for Shorts/Reels):
        # Maps the synchronized Devanagari SRT to Roman Hinglish using our existing transliterator.
        # This retains the Montserrat ExtraBold typography with zero changes to timing.
        try:
            from .hinglish import srt_to_hinglish
        except ImportError:
            from dubbing_studio.hinglish import srt_to_hinglish

        print(f"[Subtitles] Mapping synchronized Devanagari SRT to Roman Hinglish using text_to_hinglish...")
        hinglish_content = srt_to_hinglish(synced_content)
        hinglish_srt_path = subs_dir / f"{base_stem}_hinglish.srt"
        hinglish_srt_path.write_text(hinglish_content, encoding="utf-8")
        print(f"[Subtitles] Synced Roman Hinglish SRT created: {hinglish_srt_path.name}")
        sub_for_ass = hinglish_srt_path
    else:
        print(f"[Subtitles] Script is already in Roman alphabet! Audio-synced blocks matched 1:1.")
        sub_for_ass = synced_srt_path

    # 4. Generate ASS format with <=3 words/screen and dynamic MarginV
    # to_hinglish=True guarantees that any Devanagari characters render cleanly in Montserrat ExtraBold
    srt_to_ass(sub_for_ass, out_ass_p, margin_v=margin_v, to_hinglish=True)
    print(f"[Subtitles] Generated matching Hinglish ASS subtitle track: {out_ass_p.name}")
    return out_ass_p

