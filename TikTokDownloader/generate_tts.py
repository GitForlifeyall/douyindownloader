import sys
import os
import re
import time
import numpy as np
import soundfile as sf
import subprocess
from pathlib import Path
from kokoro_onnx import Kokoro

# Ensure UTF-8 output on Windows
if sys.platform == "win32":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

def parse_time(timestr: str) -> float:
    # Format: HH:MM:SS,mmm
    h, m, rest = timestr.split(":")
    s, ms = rest.split(",")
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0

def load_srt_blocks(srt_path: str):
    with open(srt_path, "r", encoding="utf-8") as f:
        content = f.read()

    pattern = r'(\d+)\s*\n(\d{2}:\d{2}:\d{2},\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2},\d{3})\s*\n(.*?)(?=\n\s*\d+\s*\n\d{2}:\d{2}:\d{2}|$)'
    matches = re.findall(pattern, content, re.DOTALL)
    
    blocks = []
    for match in matches:
        idx, start_str, end_str, text = match
        clean_text = " ".join(text.strip().split())
        if clean_text:
            blocks.append({
                "index": int(idx),
                "start": parse_time(start_str),
                "end": parse_time(end_str),
                "start_str": start_str,
                "end_str": end_str,
                "text": clean_text
            })
    return blocks

def main(srt_file=None, output_dir=None):
    srt_file = srt_file or os.environ.get("DUB_SRT_FILE", "input.srt")
    model_path = os.environ.get("KOKORO_MODEL_PATH", "models/kokoro-v1.0.onnx")
    voices_path = os.environ.get("KOKORO_VOICES_PATH", "models/voices-v1.0.bin")
    output_dir = Path(output_dir or os.environ.get("DUB_OUTPUT_DIR", "output"))
    original_video = Path(os.environ.get("DUB_ORIGINAL_VIDEO", "")) if os.environ.get("DUB_ORIGINAL_VIDEO") else None

    print("=== Kokoro TTS Narration Generator ===")
    print(f"Input text file: {srt_file}")
    print(f"Voice: am_michael (Male, Engaging Movie Recap Style)")
    # Ensure CUDA 12 and cuDNN DLLs are discoverable
    venv = Path(sys.executable).parent.parent / "Lib" / "site-packages"
    dll_dirs = [
        str(venv / p)
        for p in [
            "nvidia/cublas/bin",
            "nvidia/cudnn/bin",
            "nvidia/cuda_nvrtc/bin",
            "nvidia/cuda_runtime/bin",
            "nvidia/cufft/bin",
            "nvidia/curand/bin",
            "nvidia/cusparse/bin",
            "nvidia/nvjitlink/bin",
            "onnxruntime/capi",
        ]
        if (venv / p).exists()
    ]
    for p in dll_dirs:
        os.add_dll_directory(p)
    os.environ["PATH"] = ";".join(dll_dirs) + ";" + os.environ.get("PATH", "")

    import onnxruntime as ort
    providers = ["CUDAExecutionProvider", "CPUExecutionProvider"] if "CUDAExecutionProvider" in ort.get_available_providers() else ["CPUExecutionProvider"]
    
    sess_opts = ort.SessionOptions()
    sess_opts.log_severity_level = 3  # Quiet non-critical logs
    sess = ort.InferenceSession(model_path, sess_options=sess_opts, providers=providers)
    active_ep = sess.get_providers()[0]
    print(f"Active ONNX Runtime Provider: {active_ep} ({'NVIDIA RTX GPU' if 'CUDA' in active_ep else 'CPU'})")

    kokoro = Kokoro.from_session(sess, voices_path)
    sample_rate = 24000
    print("Kokoro TTS initialized successfully!\n")

    blocks = load_srt_blocks(srt_file)
    print(f"Total subtitle blocks to synthesize: {len(blocks)}")
    
    last_end = max(b["end"] for b in blocks)
    total_timeline_sec = max(last_end + 10.0, 930.0) # Match video length
    synced_buffer = np.zeros(int(total_timeline_sec * sample_rate), dtype=np.float32)
    continuous_audio_list = []
    
    # 0.35s pause for continuous narration
    pause_samples = np.zeros(int(0.35 * sample_rate), dtype=np.float32)

    start_total_time = time.time()
    voice_name = "am_michael"
    cursor_sample = 0

    for i, b in enumerate(blocks, start=1):
        text = b["text"]
        t_start = b["start"]
        t_end = b["end"]
        target_dur = t_end - t_start

        # Dynamic speed adjustment if text is very long for the time window
        char_count = len(text.split())
        expected_dur = char_count * 0.4
        if expected_dur > target_dur * 1.3:
            speed = 1.15
        elif expected_dur > target_dur * 1.1:
            speed = 1.08
        else:
            speed = 1.0

        try:
            samples, _ = kokoro.create(text, voice=voice_name, speed=speed, lang="en-us")
        except Exception as e:
            print(f"[{i}/{len(blocks)}] Error generating block {b['index']}: {e}", flush=True)
            continue

        audio_len = len(samples)
        
        # 1. Add to Continuous list
        continuous_audio_list.append(samples)
        continuous_audio_list.append(pause_samples)

        # 2. Add to Timeline-Synchronized buffer (STRICT SINGLE-VOICE NON-OVERLAP)
        start_idx = max(int(t_start * sample_rate), cursor_sample)
        end_idx = start_idx + audio_len

        if end_idx > len(synced_buffer):
            # Extend buffer if needed
            synced_buffer = np.pad(synced_buffer, (0, end_idx - len(synced_buffer)))

        # Assign directly into timeline and advance cursor to guarantee zero overlap
        synced_buffer[start_idx:end_idx] = samples
        cursor_sample = end_idx + int(0.06 * sample_rate) # 60ms natural breath pause

        print(f"[{i}/{len(blocks)}] [{b['start_str']} -> {b['end_str']}] (Dur: {audio_len/sample_rate:.1f}s, start: {start_idx/sample_rate:.1f}s) {text[:60]}...", flush=True)

    # Normalize buffers to prevent clipping
    max_sync = np.max(np.abs(synced_buffer))
    if max_sync > 1.0:
        synced_buffer = synced_buffer / max_sync * 0.98

    continuous_audio = np.concatenate(continuous_audio_list)
    max_cont = np.max(np.abs(continuous_audio))
    if max_cont > 1.0:
        continuous_audio = continuous_audio / max_cont * 0.98

    total_elapsed = time.time() - start_total_time
    print(f"\nAll {len(blocks)} blocks generated in {total_elapsed:.1f} seconds! (Speed: ~{total_timeline_sec / total_elapsed:.1f}x real-time)\n")

    # Save outputs
    synced_wav = output_dir / "english_voiceover_synced.wav"
    synced_mp3 = output_dir / "english_voiceover_synced.mp3"
    cont_wav = output_dir / "english_voiceover_continuous.wav"
    cont_mp3 = output_dir / "english_voiceover_continuous.mp3"

    print("Saving audio files...")
    sf.write(str(synced_wav), synced_buffer, sample_rate)
    sf.write(str(cont_wav), continuous_audio, sample_rate)

    # Convert to MP3 using ffmpeg
    print("Converting to high-quality MP3 with FFmpeg...")
    subprocess.run(["ffmpeg", "-y", "-i", str(synced_wav), "-b:a", "192k", str(synced_mp3)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(["ffmpeg", "-y", "-i", str(cont_wav), "-b:a", "192k", str(cont_mp3)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    print("\nSaved:")
    print(f" 1. Synced WAV: {synced_wav}")
    print(f" 2. Synced MP3: {synced_mp3}")
    print(f" 3. Continuous WAV: {cont_wav}")
    print(f" 4. Continuous MP3: {cont_mp3}")

    # Optionally create dubbed video if original exists
    if original_video is not None and original_video.exists():
        dubbed_video = output_dir / "english_dubbed_video.mp4"
        print(f"\nMerging synchronized English audio into original video -> {dubbed_video.name}...")
        # Replace original audio with synced English voiceover
        cmd = [
            "ffmpeg", "-y",
            "-i", str(original_video),
            "-i", str(synced_mp3),
            "-c:v", "copy",
            "-c:a", "aac",
            "-b:a", "192k",
            "-map", "0:v:0",
            "-map", "1:a:0",
            "-shortest",
            str(dubbed_video)
        ]
        res = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if res.returncode == 0:
            print(f" Dubbed Video created successfully: {dubbed_video}")

    print("\n=== All tasks finished successfully! ===")

if __name__ == "__main__":
    main()
