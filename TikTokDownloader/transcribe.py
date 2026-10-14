import sys
import os
import time
from pathlib import Path

# Ensure UTF-8 console output on Windows
if sys.platform == "win32":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    
    # Add NVIDIA CUDA runtime library directories to Windows DLL search path
    nvidia_base = Path(sys.prefix) / "Lib" / "site-packages" / "nvidia"
    if nvidia_base.exists():
        for sub in nvidia_base.iterdir():
            bin_dir = sub / "bin"
            if bin_dir.exists():
                try:
                    os.add_dll_directory(str(bin_dir))
                except Exception:
                    pass
                os.environ["PATH"] = str(bin_dir) + os.pathsep + os.environ.get("PATH", "")

def format_timestamp(seconds: float) -> str:
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds - int(seconds)) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"

def transcribe_video(video_path: str, model_size: str = "large-v3"):
    from faster_whisper import WhisperModel
    
    video_file = Path(video_path)
    if not video_file.exists():
        print(f"Error: File not found: {video_file}")
        return

    print(f"=== Faster-Whisper Transcription ===")
    print(f"Input file: {video_file.name}")
    print(f"Model: {model_size}")
    
    # Prefer NVIDIA GPU (cuda), with automatic fallback
    model = None
    for compute_type in ["int8_float16", "float16"]:
        try:
            print(f"Loading Whisper {model_size} on NVIDIA RTX 3050 (cuda, {compute_type})...")
            model = WhisperModel(model_size, device="cuda", compute_type=compute_type)
            print(f"Model successfully loaded on GPU ({compute_type})!")
            break
        except Exception as e:
            print(f"GPU {compute_type} initialization warning: {e}")

    if model is None:
        print("Falling back to CPU (int8, 8 threads)...")
        model = WhisperModel(model_size, device="cpu", compute_type="int8", cpu_threads=8)
        print("Model loaded on CPU successfully!")

    print("\nStarting transcription (Language: Chinese - Simplified)...")
    start_time = time.time()
    
    # Chinese initial prompt to enforce Simplified Chinese and proper punctuation
    initial_prompt = "以下是普通话的内容，全部使用简体中文输出并添加标点符号。"
    
    segments, info = model.transcribe(
        str(video_file),
        language="zh",
        initial_prompt=initial_prompt,
        beam_size=5,
        vad_filter=True, # Filter out silence/noise
    )

    print(f"Detected language: {info.language} (Probability: {info.language_probability:.2f})")
    print(f"Duration: {info.duration:.2f} seconds\n")
    print("--- Transcribing in progress ---")

    transcript_segments = []
    srt_lines = []
    txt_lines = []

    for i, segment in enumerate(segments, start=1):
        timestamp = f"[{format_timestamp(segment.start)} --> {format_timestamp(segment.end)}]"
        text = segment.text.strip()
        print(f"{timestamp} {text}", flush=True)
        
        transcript_segments.append(segment)
        txt_lines.append(text)
        
        # Build SRT entry
        srt_lines.append(f"{i}\n{format_timestamp(segment.start)} --> {format_timestamp(segment.end)}\n{text}\n")

    elapsed = time.time() - start_time
    print(f"\nTranscription completed in {elapsed:.1f} seconds!")

    # Save output files next to the video
    output_dir = video_file.parent
    base_name = video_file.stem
    
    txt_path = output_dir / f"{base_name}.txt"
    srt_path = output_dir / f"{base_name}.srt"

    with open(txt_path, "w", encoding="utf-8") as f:
        f.write("\n".join(txt_lines) + "\n")

    with open(srt_path, "w", encoding="utf-8") as f:
        f.write("\n".join(srt_lines) + "\n")

    print(f"\nFiles saved successfully:")
    print(f" - TXT: {txt_path}")
    print(f" - SRT (Subtitles): {srt_path}")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        target = sys.argv[1]
    else:
        # Default target (override by passing a file path argument)
        target = r"Volume/Download/sample.mp4"
    
    model_name = sys.argv[2] if len(sys.argv) > 2 else "large-v3"
    transcribe_video(target, model_name)
