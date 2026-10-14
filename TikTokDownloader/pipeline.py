import os
import sys
import re
import time
import asyncio
import argparse
import subprocess
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Add project root and src to path
CURRENT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CURRENT_DIR.parent
sys.path.append(str(CURRENT_DIR))
sys.path.append(str(CURRENT_DIR / "src"))

# Setup CUDA DLL paths for GPU acceleration
VENV_SITE = CURRENT_DIR / ".venv" / "Lib" / "site-packages"
DLL_DIRS = [
    str(VENV_SITE / p)
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
    if (VENV_SITE / p).exists()
]
for p in DLL_DIRS:
    os.add_dll_directory(p)
os.environ["PATH"] = ";".join(DLL_DIRS) + ";" + os.environ.get("PATH", "")

def format_timestamp(seconds: float) -> str:
    hrs = int(seconds // 3600)
    mins = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int(round((seconds - int(seconds)) * 1000))
    return f"{hrs:02d}:{mins:02d}:{secs:02d},{millis:03d}"

# =====================================================================
# STEP 1: Video Download via DouK-Downloader / link extractor
# =====================================================================
def download_video(url: str, output_dir: Path) -> Path:
    print(f"\n==========================================")
    print(f"[Step 1/5] Downloading Douyin/TikTok Video")
    print(f"URL: {url}")
    print(f"==========================================")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Check if input is already a local video file
    if Path(url).exists() and Path(url).suffix.lower() in [".mp4", ".mkv", ".mov"]:
        print(f"Input is already a local video: {url}")
        return Path(url)

    from src.application import TikTokDownloader
    from src.interface import Detail, DetailTikTok
    from src.link import Extractor, ExtractorTikTok
    from src.extract import Extractor as DataExtractor
    from src.downloader import Downloader
    from src.storage import RecordManager

    async def _async_download(target_url: str):
        is_tiktok = "tiktok.com" in target_url.lower()
        async with TikTokDownloader() as app:
            app.check_config()
            await app.check_settings(False)
            
            link_extractor = ExtractorTikTok(app.parameter) if is_tiktok else Extractor(app.parameter)
            ids = await link_extractor.run(target_url, type_="detail")
            if not ids:
                raise RuntimeError(f"Could not extract video ID from URL: {target_url}")
            
            detail_id = ids[0]
            print(f"Found video ID: {detail_id}. Fetching metadata...")
            detail_obj = (DetailTikTok if is_tiktok else Detail)(app.parameter, detail_id=detail_id)
            detail_data = await detail_obj.run()
            if not detail_data:
                raise RuntimeError(f"Failed to fetch detail metadata for ID: {detail_id}")
            
            before_files = set(output_dir.glob("*.mp4"))
            record_manager = RecordManager()
            root, params, logger_cls = record_manager.run(app.parameter)
            data_extractor = DataExtractor(app.parameter)
            downloader = Downloader(app.parameter)

            async with logger_cls(root, console=app.console, **params) as record:
                extracted_info = await data_extractor.run([detail_data], record, tiktok=is_tiktok)
                if not extracted_info:
                    raise RuntimeError("Failed to extract downloadable video stream.")
                desc = extracted_info[0].get('desc', 'video')
                print(f"Downloading: {desc}")
                await downloader.run(extracted_info, "detail", tiktok=is_tiktok)
            
            after_files = set(output_dir.glob("*.mp4"))
            new_files = list(after_files - before_files)
            if new_files:
                print(f"Downloaded video saved to: {new_files[0].name}")
                return new_files[0]
            
            # If not detected as new, find video with matching ID
            matching = [f for f in output_dir.glob("*.mp4") if detail_id in f.name]
            if matching:
                return matching[0]
            
            # Fallback to latest non-dubbed video
            raw_videos = [f for f in output_dir.glob("*.mp4") if "dubbed" not in f.name and "half" not in f.name]
            if raw_videos:
                return max(raw_videos, key=lambda f: f.stat().st_mtime)

            raise RuntimeError("Download completed, but no raw video file found in Download folder.")

    return asyncio.run(_async_download(url))

# =====================================================================
# STEP 2: GPU Transcription via Faster-Whisper
# =====================================================================
def transcribe_video(video_path: Path, output_srt: Path, model_size: str = "large-v3-turbo") -> Path:
    print(f"\n==========================================")
    print(f"[Step 2/5] Transcribing Audio to SRT (NVIDIA RTX GPU)")
    print(f"Video: {video_path.name}")
    print(f"Model: {model_size} (int8_float16)")
    print(f"==========================================")
    
    if output_srt.exists() and output_srt.stat().st_size > 100:
        print(f"Existing transcript found: {output_srt.name}. Skipping transcription.")
        return output_srt

    from faster_whisper import WhisperModel
    model = WhisperModel(model_size, device="cuda", compute_type="int8_float16")
    
    start_t = time.time()
    segments, info = model.transcribe(str(video_path), beam_size=1, word_timestamps=False)
    
    srt_lines = []
    print(f"Detected language: {info.language} (Probability: {info.language_probability:.2f})")
    print("Transcribing segments...")

    for i, seg in enumerate(segments, 1):
        start_str = format_timestamp(seg.start)
        end_str = format_timestamp(seg.end)
        text = seg.text.strip()
        srt_lines.append(f"{i}\n{start_str} --> {end_str}\n{text}\n")

    output_srt.write_text("\n".join(srt_lines), encoding="utf-8")
    print(f"Transcription complete in {time.time() - start_t:.1f}s -> {output_srt.name}")
    return output_srt

# =====================================================================
# STEP 3: Dub-Optimized Translation via Gemini
# =====================================================================
def translate_srt(input_srt: Path, target_lang: str, output_srt: Path, api_keys: list = None) -> Path:
    print(f"\n==========================================")
    print(f"[Step 3/5] Translating Subtitles with Gemini")
    print(f"Target Language: {target_lang}")
    print(f"Output: {output_srt.name}")
    print(f"==========================================")
    
    if output_srt.exists() and output_srt.stat().st_size > 100:
        print(f"Existing translated SRT found: {output_srt.name}. Skipping translation.")
        return output_srt

    from translator import GeminiTranslator
    translator = GeminiTranslator(api_keys=api_keys)
    translated_content = translator.translate_srt(str(input_srt), target_language=target_lang)
    output_srt.write_text(translated_content, encoding="utf-8")
    print(f"Translation complete -> {output_srt.name}")
    return output_srt

# =====================================================================
# STEP 4 & 5: Single-Voice GPU TTS & Final Video Dubbing
# =====================================================================
def run_tts_and_dub(dubbed_srt: Path, original_video: Path, final_video: Path, voice: str = "am_michael", lang: str = "English", base_speed: float = 1.28):
    print(f"\n==========================================")
    print(f"[Step 4/5 & 5/5] Synthesizing Voice & Dubbing Video (GPU)")
    print(f"Voice: {voice}")
    print(f"Base Speed: {base_speed}x (Fast-Paced Recap)")
    print(f"SRT: {dubbed_srt.name}")
    print(f"Target Video: {final_video.name}")
    print(f"==========================================")
    
    import soundfile as sf
    import numpy as np
    import onnxruntime as ort
    from kokoro_onnx import Kokoro
    from generate_tts import load_srt_blocks

    model_path = os.environ.get(
        "KOKORO_MODEL_PATH", str(CURRENT_DIR / "models" / "kokoro-v1.0.onnx")
    )
    voices_path = os.environ.get(
        "KOKORO_VOICES_PATH", str(CURRENT_DIR / "models" / "voices-v1.0.bin")
    )

    sess_opts = ort.SessionOptions()
    sess_opts.log_severity_level = 3
    providers = ["CUDAExecutionProvider", "CPUExecutionProvider"] if "CUDAExecutionProvider" in ort.get_available_providers() else ["CPUExecutionProvider"]
    session = ort.InferenceSession(model_path, sess_options=sess_opts, providers=providers)
    active_ep = session.get_providers()[0]
    print(f"Active TTS Provider: {active_ep} ({'NVIDIA RTX GPU' if 'CUDA' in active_ep else 'CPU'})")

    kokoro = Kokoro.from_session(session, voices_path)
    sample_rate = 24000

    # Determine Kokoro language code
    if lang.lower().startswith("hi") or voice.startswith("h"):
        kokoro_lang = "hi"
    elif lang.lower().startswith("ja") or voice.startswith("j"):
        kokoro_lang = "ja"
    elif lang.lower().startswith("zh") or voice.startswith("z"):
        kokoro_lang = "zh"
    elif lang.lower().startswith("es") or voice.startswith("e"):
        kokoro_lang = "es"
    elif lang.lower().startswith("fr") or voice.startswith("f"):
        kokoro_lang = "fr"
    elif lang.lower().startswith("it") or voice.startswith("i"):
        kokoro_lang = "it"
    elif lang.lower().startswith("pt") or voice.startswith("p"):
        kokoro_lang = "pt"
    else:
        kokoro_lang = "en-us"

    blocks = load_srt_blocks(str(dubbed_srt))
    if not blocks:
        raise RuntimeError(f"No subtitle blocks found in {dubbed_srt}")

    last_end = max(b["end"] for b in blocks)
    total_sec = max(last_end + 15.0, 100.0)
    synced_buffer = np.zeros(int(total_sec * sample_rate), dtype=np.float32)

    cursor_sample = 0
    start_time = time.time()

    print(f"Synthesizing {len(blocks)} subtitle blocks at ~{base_speed}x speed (Kokoro lang: {kokoro_lang})...")
    for i, b in enumerate(blocks, 1):
        text = b["text"]
        t_start = b["start"]
        t_end = b["end"]
        target_dur = max(t_end - t_start, 0.8)

        # Fast-paced movie recap dynamic speed
        word_count = len(text.split())
        est_dur = word_count / 3.0
        if est_dur > target_dur:
            speed = min(round(base_speed * (est_dur / target_dur), 2), 1.45)
        else:
            speed = base_speed

        try:
            samples, _ = kokoro.create(text, voice=voice, speed=speed, lang=kokoro_lang)
        except Exception as e:
            print(f"[{i}/{len(blocks)}] Error on block {b['index']}: {e}")
            continue

        audio_len = len(samples)

        # STRICT NON-OVERLAPPING PLACEMENT (GUARANTEES 1 SINGLE VOICE)
        start_idx = max(int(t_start * sample_rate), cursor_sample)
        end_idx = start_idx + audio_len

        if end_idx > len(synced_buffer):
            synced_buffer = np.pad(synced_buffer, (0, end_idx - len(synced_buffer) + 48000))

        synced_buffer[start_idx:end_idx] = samples
        cursor_sample = end_idx + int(0.025 * sample_rate)  # 25ms tight breath pause

        if i % 10 == 0 or i == len(blocks):
            print(f"  [{i}/{len(blocks)}] Generated block {b['index']} (Speed: {speed}x)")

    # Normalize audio
    max_amp = np.max(np.abs(synced_buffer))
    if max_amp > 1.0:
        synced_buffer = synced_buffer / max_amp * 0.98

    # Save temp synced audio
    temp_wav = dubbed_srt.parent / f"temp_dub_{dubbed_srt.stem}.wav"
    temp_mp3 = dubbed_srt.parent / f"temp_dub_{dubbed_srt.stem}.mp3"
    sf.write(str(temp_wav), synced_buffer, sample_rate)
    
    subprocess.run(["ffmpeg", "-y", "-i", str(temp_wav), "-b:a", "192k", str(temp_mp3)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # Remux video with clean audio
    print(f"\nMuxing dubbed audio into final video...")
    cmd = [
        "ffmpeg", "-y",
        "-i", str(original_video),
        "-i", str(temp_mp3),
        "-c:v", "copy",
        "-c:a", "aac",
        "-b:a", "192k",
        "-map", "0:v:0",
        "-map", "1:a:0",
        "-shortest",
        str(final_video)
    ]
    res = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if res.returncode == 0:
        print(f"\n SUCCESS! Dubbed video created: {final_video}")
    else:
        print(f"\n Error muxing video with FFmpeg.")

# =====================================================================
# Main Orchestrator
# =====================================================================
def main():
    parser = argparse.ArgumentParser(description="End-to-End Douyin Video Localization & Dubbing Pipeline")
    parser.add_argument("--url", type=str, default="", help="Douyin/TikTok video URL or path to local MP4")
    parser.add_argument("--lang", type=str, default="English", help="Target translation language (e.g., English, Hindi)")
    parser.add_argument("--voice", type=str, default="", help="Kokoro voice model (default: am_michael for English, hm_omega for Hindi)")
    parser.add_argument("--speed", type=float, default=1.28, help="Base speech speed (default: 1.28 for fast-paced recap, range: 1.15 - 1.40)")
    args = parser.parse_args()

    download_dir = CURRENT_DIR / "Volume" / "Download"
    
    # Auto-pick default voice according to language if not specified
    voice = args.voice
    if not voice:
        if args.lang.lower().startswith("hi"):
            voice = "hm_omega"
        else:
            voice = "am_michael"

    # 1. Download
    video_path = download_video(args.url or "https://www.douyin.com/jingxuan?modal_id=7692716250396429595", download_dir)

    # 2. Transcribe
    base_stem = video_path.stem
    chinese_srt = download_dir / f"{base_stem}.srt"
    transcribe_video(video_path, chinese_srt, model_size="large-v3-turbo")

    # 3. Translate
    dubbed_srt = download_dir / f"{base_stem}_{args.lang.lower()}.srt"
    translate_srt(chinese_srt, args.lang, dubbed_srt)

    # 4 & 5. TTS & Dub
    final_video = download_dir / f"{base_stem}_{args.lang.lower()}_dubbed.mp4"
    run_tts_and_dub(dubbed_srt, video_path, final_video, voice=voice, lang=args.lang, base_speed=args.speed)

if __name__ == "__main__":
    main()
