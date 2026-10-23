import sys
from pathlib import Path
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, str(Path(__file__).resolve().parent))
import soundfile as sf
import numpy as np
from dubbing_studio.tts import load_srt_blocks, trim_audio_silence, adjust_audio_speed

srt_path = Path("output/subtitles/见微知古 - 河中不建桥墩古人靠木头怎么把桥_hindi.srt")
vid_path = Path("output/clean_videos/见微知古 - 河中不建桥墩古人靠木头怎么把桥_clean.mp4")
slice_dir = Path("output/audio_stems/temp_sarvam_slices")
sample_rate = 48000
vid_dur = 87.47

blocks = load_srt_blocks(srt_path)
timeline_sample = int(blocks[0]["start"] * sample_rate)
min_gap_samples = int(0.08 * sample_rate)

block_placements = []

for i, b in enumerate(blocks, 1):
    slice_mp3 = slice_dir / f"block_{b['index']:03d}.mp3"
    audio_data, in_sr = sf.read(str(slice_mp3))
    if len(audio_data.shape) > 1:
        audio_data = np.mean(audio_data, axis=1)

    # find how much silence was trimmed at the start
    # trim_audio_silence removes samples < threshold
    # let's inspect trim_audio_silence behavior
    trimmed = trim_audio_silence(audio_data)
    
    orig_start_sample = int(b["start"] * sample_rate)
    if i < len(blocks):
        avail_dur = max(blocks[i]["start"] - b["start"], 0.8)
    else:
        avail_dur = max(vid_dur - b["start"] - 0.8, 1.5)

    raw_dur = len(trimmed) / sample_rate
    speed_factor = 1.0
    if raw_dur > avail_dur * 0.98:
        speed_factor = min(raw_dur / (avail_dur * 0.95), 1.28)
        trimmed = adjust_audio_speed(trimmed, sample_rate, speed_factor)

    if i == 1:
        act_start = orig_start_sample
    else:
        earliest_start = timeline_sample + min_gap_samples
        act_start = max(earliest_start, orig_start_sample)

    act_end = act_start + len(trimmed)
    timeline_sample = act_end
    
    start_sec = act_start / sample_rate
    end_sec = act_end / sample_rate
    block_placements.append({
        "index": b["index"],
        "start_sec": start_sec,
        "end_sec": end_sec,
        "dur_sec": end_sec - start_sec,
        "speed_factor": speed_factor,
        "raw_dur": raw_dur,
        "text": b["text"]
    })
    print(f"Block #{b['index']:02d}: start={start_sec:6.2f}s, end={end_sec:6.2f}s, speed={speed_factor:.2f}x")

