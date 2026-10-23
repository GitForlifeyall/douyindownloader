import os
import sys
import subprocess
from pathlib import Path
import numpy as np
import soundfile as sf

from dubbing_studio.env_loader import configure_runtime_environment
configure_runtime_environment()
from dubbing_studio.tts_google import GoogleGeminiTTS, trim_silence

OUTPUT_DIR = Path("output")
VIDEO_FILE = OUTPUT_DIR / "2026-09-07 13.36.00-Video-宋应星-恭喜你，成功发明出古法汽水 #古法... #格瓦斯 #百young非遗计划 #科普.mp4"
BGM_FILE = OUTPUT_DIR / "stems_2026-09-07 13.36.00-Video-宋应星-恭喜你，成功发明出古法汽水 #古法... #格瓦斯 #百young非遗计划 #科普" / "no_vocals.wav"

VOICES = [
    {
        "name": "Puck",
        "description": "High-pitched, playful, lively storytelling voice (Male)",
        "prompt": "[Tone: Playful, high-energy, animated storytelling for YouTube Shorts] अगर तुम पड़ोसी की रोटियों को मोटे टुकड़ों में काटकर जाली पर रखो, और धीमी आंच में एकदम क्रिस्पी और गोल्डन भून लो!"
    },
    {
        "name": "Aoede",
        "description": "High-medium bright pitch, breezy, engaging instructional voice (Female)",
        "prompt": "[Tone: Breezy, bright, upbeat instructional female narrator] अगर तुम पड़ोसी की रोटियों को मोटे टुकड़ों में काटकर जाली पर रखो, और धीमी आंच में एकदम क्रिस्पी और गोल्डन भून लो!"
    },
    {
        "name": "Kore",
        "description": "Medium pitch, clear, firm, articulate instructional voice (Female)",
        "prompt": "[Tone: Confident, clear, professional instructional narration] अगर तुम पड़ोसी की रोटियों को मोटे टुकड़ों में काटकर जाली पर रखो, और धीमी आंच में एकदम क्रिस्पी और गोल्डन भून लो!"
    },
    {
        "name": "Orus",
        "description": "Medium pitch, warm, natural conversational explainer voice (Male)",
        "prompt": "[Tone: Warm, conversational, engaging male storytelling explainer] अगर तुम पड़ोसी की रोटियों को मोटे टुकड़ों में काटकर जाली पर रखो, और धीमी आंच में एकदम क्रिस्पी और गोल्डन भून लो!"
    }
]

MODELS = [
    "gemini-3.8-flash-tts",
    "gemini-2.5-flash-preview-tts",
    "gemini-3.1-flash-tts-preview",
    "gemini-2.5-pro-preview-tts",
    "gemini-3.8-flash-lite-tts",
]

def synthesize_with_model_fallback(client, voice_name, prompt):
    for m in MODELS:
        try:
            print(f"    Trying model: {m} for voice: {voice_name}...")
            res = client.models.generate_content(
                model=m,
                contents=prompt,
                config={
                    "response_modalities": ["AUDIO"],
                    "speech_config": {"voice_config": {"prebuilt_voice_config": {"voice_name": voice_name}}}
                }
            )
            part = res.candidates[0].content.parts[0]
            raw_bytes = part.inline_data.data
            audio_array = np.frombuffer(raw_bytes, dtype=np.int16).astype(np.float32) / 32768.0
            print(f"    ✓ Succeeded using {m}!")
            return audio_array, 24000
        except Exception as e:
            print(f"    Notice: {m} failed ({e}). Trying next...")
            continue
    raise RuntimeError(f"All models exhausted for voice {voice_name}")

def main():
    if not VIDEO_FILE.exists():
        print(f"Error: Video file not found: {VIDEO_FILE}")
        sys.exit(1)
    if not BGM_FILE.exists():
        print(f"Error: BGM file not found: {BGM_FILE}")
        sys.exit(1)

    print(f"Found input video: {VIDEO_FILE.name}")
    print(f"Found BGM stem: {BGM_FILE}")

    # Extract 10-second BGM slice
    bgm_10s_path = OUTPUT_DIR / "temp_bgm_10s.wav"
    subprocess.run([
        "ffmpeg", "-y", "-ss", "0", "-t", "10",
        "-i", str(BGM_FILE),
        "-ar", "24000", "-ac", "2",
        str(bgm_10s_path)
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)

    tts = GoogleGeminiTTS(model="gemini-3.8-flash-tts")

    for item in VOICES:
        v_name = item["name"]
        output_mp4 = OUTPUT_DIR / f"{v_name}.mp4"
        
        if output_mp4.exists() and output_mp4.stat().st_size > 1000000:
            print(f"\n[SKIP] {output_mp4} already exists ({output_mp4.stat().st_size} bytes).")
            continue

        print(f"\n--- Generating Voice: {v_name} ({item['description']}) ---")
        
        # Synthesize audio with model fallback
        audio_array, sr = synthesize_with_model_fallback(tts.client, v_name, item["prompt"])
        
        # Trim digital zero-padding
        audio_array = trim_silence(audio_array)
        duration = len(audio_array) / sr
        print(f"  Synthesized audio duration: {duration:.2f}s")
        
        # Pad with silence to full 10 seconds
        total_samples = int(10.0 * sr)
        voice_track = np.zeros(total_samples, dtype=np.float32)
        offset_samples = int(0.15 * sr)
        copy_len = min(len(audio_array), total_samples - offset_samples)
        voice_track[offset_samples : offset_samples + copy_len] = audio_array[:copy_len]
        
        voice_wav_path = OUTPUT_DIR / f"temp_voice_{v_name}.wav"
        sf.write(str(voice_wav_path), voice_track, sr)

        # Mux with video (0-10s) and sidechain ducking BGM
        filtergraph = (
            "[1:a]volume=0.75[bgm];"
            "[2:a]highpass=f=80,treble=g=3:f=3000,acompressor=threshold=-18dB:ratio=3.5:attack=5:release=60,loudnorm=I=-12:TP=-0.5:LRA=6,asplit=2[voice_sc][voice_mix];"
            "[bgm][voice_sc]sidechaincompress=threshold=0.08:ratio=5:attack=20:release=250[ducked_bgm];"
            "[ducked_bgm][voice_mix]amix=inputs=2:weights=0.85 1.35:normalize=0[mixed];"
            "[mixed]alimiter=limit=0.99:attack=5:release=50[aout]"
        )

        cmd = [
            "ffmpeg", "-y",
            "-ss", "0", "-t", "10", "-i", str(VIDEO_FILE),
            "-i", str(bgm_10s_path),
            "-i", str(voice_wav_path),
            "-filter_complex", filtergraph,
            "-map", "0:v",
            "-map", "[aout]",
            "-c:v", "libx264", "-preset", "fast", "-crf", "20",
            "-c:a", "aac", "-b:a", "192k",
            str(output_mp4)
        ]
        
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        print(f"  ✓ Successfully rendered: {output_mp4} (size: {output_mp4.stat().st_size} bytes)")
        
        if voice_wav_path.exists():
            voice_wav_path.unlink()

    # Clean up temp BGM
    if bgm_10s_path.exists():
        bgm_10s_path.unlink()

    print("\n✓ All voice previews finished rendering!")

if __name__ == "__main__":
    main()
