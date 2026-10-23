#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
dubbing_studio/transcriber.py
=============================
GPU-accelerated audio transcription module using Faster-Whisper.
Extracts audio from video and generates timestamped standard .srt subtitles.
"""

import time
from pathlib import Path
from typing import Optional, Union

from .env_loader import configure_runtime_environment
configure_runtime_environment()


def format_timestamp(seconds: float) -> str:
    """Format total seconds to standard SRT timestamp format (HH:MM:SS,mmm)."""
    hrs = int(seconds // 3600)
    mins = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int(round((seconds - int(seconds)) * 1000))
    if millis >= 1000:
        secs += 1
        millis -= 1000
    return f"{hrs:02d}:{mins:02d}:{secs:02d},{millis:03d}"


class Transcriber:
    """Faster-Whisper transcription engine with GPU/CPU support."""

    def __init__(self, model_size: str = "large-v3-turbo", device: str = "cuda"):
        self.model_size = model_size
        self.device = device
        self._model = None

    def _load_model(self):
        if self._model is not None:
            return self._model

        from faster_whisper import WhisperModel

        if self.device == "cuda":
            for compute_type in ["int8_float16", "float16"]:
                try:
                    print(f"[Transcriber] Initializing Faster-Whisper {self.model_size} on NVIDIA GPU ({compute_type})...")
                    self._model = WhisperModel(self.model_size, device="cuda", compute_type=compute_type)
                    print(f"[Transcriber] Successfully loaded on CUDA ({compute_type})!")
                    return self._model
                except Exception as e:
                    print(f"[Transcriber] CUDA {compute_type} initialization warning: {e}")

        print("[Transcriber] Falling back to CPU execution (int8, 8 threads)...")
        self._model = WhisperModel(self.model_size, device="cpu", compute_type="int8", cpu_threads=8)
        print("[Transcriber] Successfully loaded on CPU!")
        return self._model

    def transcribe(
        self,
        video_path: Union[str, Path],
        output_srt: Optional[Union[str, Path]] = None,
        beam_size: int = 1,
        force: bool = False
    ) -> Path:
        """
        Transcribe video audio to standard SRT file.
        """
        v_path = Path(video_path)
        if not v_path.exists():
            raise FileNotFoundError(f"Video file not found: {v_path}")

        out_srt = Path(output_srt) if output_srt else v_path.parent / f"{v_path.stem}.srt"

        if not force and out_srt.exists() and out_srt.stat().st_size > 100:
            print(f"[Transcriber] Existing transcript found: {out_srt.name}. Skipping transcription.")
            return out_srt

        print(f"\n==========================================")
        print(f"[Transcriber] Transcribing Video Audio to SRT")
        print(f"Video: {v_path.name}")
        print(f"Model: {self.model_size}")
        print(f"==========================================")

        # Ensure video has an audio stream, or extract audio from speech/original stem if clean video has no audio
        audio_target = str(v_path)
        try:
            probe_p = subprocess.run(
                ["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries", "stream=codec_type", "-of", "json", str(v_path)],
                capture_output=True, text=True, check=True
            )
            has_audio = bool(json.loads(probe_p.stdout).get("streams"))
        except Exception:
            has_audio = False

        if not has_audio:
            print(f"[Transcriber] Input '{v_path.name}' has no audio track. Checking candidate audio stems/sources...")
            candidates = [
                v_path.parent.parent / "audio_stems" / f"stems_{v_path.stem.replace('_clean', '')}" / "speech.wav",
                v_path.parent.parent / "audio_stems" / f"stems_{v_path.stem.replace('_clean', '')}" / "no_vocals.wav",
                v_path.parent.parent.parent / "input" / f"{v_path.stem.replace('_clean', '')}.mp4",
                Path("input") / f"{v_path.stem.replace('_clean', '')}.mp4",
            ]
            # Also search input folder for fuzzy match
            input_dir = Path("input")
            if input_dir.exists():
                for p in input_dir.glob("*.mp4"):
                    if any(part in p.name for part in v_path.stem.split(" - ")):
                        candidates.append(p)

            for cand in candidates:
                if cand.exists() and cand.stat().st_size > 10000:
                    print(f"[Transcriber] Found source audio track from: {cand.name}")
                    audio_target = str(cand)
                    break

        model = self._load_model()
        start_t = time.time()
        segments, info = model.transcribe(
            audio_target,
            beam_size=beam_size,
            word_timestamps=True,
            vad_filter=True,
            vad_parameters=dict(min_silence_duration_ms=250)
        )

        print(f"[Transcriber] Detected source language: {info.language} (Probability: {info.language_probability:.2f})")
        print(f"[Transcriber] Extracting sentence-level phrase blocks...")

        sentence_punct = {'。', '！', '？', '!', '?'}
        clause_punct = {'，', '、', ',', '；', ';'}
        split_blocks = []
        current_words = []
        current_start = None

        for s in segments:
            if not getattr(s, "words", None):
                if s.text.strip():
                    split_blocks.append((s.start, s.end, s.text.strip()))
                continue

            for w in s.words:
                if current_start is None:
                    current_start = w.start
                current_words.append(w.word)
                dur = w.end - current_start
                has_sent = any(p in w.word for p in sentence_punct)
                has_clause = any(p in w.word for p in clause_punct)

                # Split on full sentence end (>= 2.5s) or long clause (>= 5.5s) or hard limit (>= 7.5s)
                if (has_sent and dur >= 2.5) or (has_clause and dur >= 5.5) or dur >= 7.5:
                    text_chunk = "".join(current_words).strip()
                    if text_chunk:
                        split_blocks.append((current_start, w.end, text_chunk))
                    current_words = []
                    current_start = None

        if current_words and current_start is not None:
            text_chunk = "".join(current_words).strip()
            if text_chunk:
                split_blocks.append((current_start, s.end, text_chunk))

        # Fallback if splitting produced no blocks
        if not split_blocks:
            for s in segments:
                if s.text.strip():
                    split_blocks.append((s.start, s.end, s.text.strip()))

        srt_lines = []
        for i, (st, en, txt) in enumerate(split_blocks, 1):
            s_str = format_timestamp(st)
            e_str = format_timestamp(en)
            srt_lines.append(f"{i}\n{s_str} --> {e_str}\n{txt}\n")

        out_srt.write_text("\n".join(srt_lines), encoding="utf-8")
        print(f"[Transcriber] Transcription complete in {time.time() - start_t:.1f}s ({len(split_blocks)} blocks) -> {out_srt.name}")
        return out_srt
