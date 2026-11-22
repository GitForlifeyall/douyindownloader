import sys
sys.path.insert(0, '.')
from dubbing_studio.tts import load_srt_blocks, trim_audio_silence, adjust_audio_speed
from pathlib import Path
import soundfile as sf
import json

blocks = load_srt_blocks('output/subtitles/道可道 - 恭喜你成功制作出桂花蜜_hindi.srt')
sample_rate = 48000
vid_dur = 66.7
timeline_sample = int(blocks[0]['start'] * sample_rate)
min_gap_samples = int(0.08 * sample_rate)

results = []
for i, b in enumerate(blocks, 1):
    idx = b['index']
    f = Path(f'output/audio_stems/temp_sarvam_slices/block_{idx:03d}.mp3')
    audio_data, in_sr = sf.read(str(f))
    trimmed = trim_audio_silence(audio_data)
    
    if i < len(blocks):
        avail_dur = max(blocks[i]['start'] - b['start'], 0.8)
    else:
        avail_dur = max(vid_dur - b['start'] - 0.8, 1.5)
        
    raw_dur = len(trimmed) / sample_rate
    speed_factor = 1.0
    if raw_dur > avail_dur * 0.98:
        speed_factor = min(raw_dur / (avail_dur * 0.95), 1.28)
        trimmed = adjust_audio_speed(trimmed, sample_rate, speed_factor)
        
    orig_start_sample = int(b['start'] * sample_rate)
    if i == 1:
        act_start = orig_start_sample
    else:
        earliest_start = timeline_sample + min_gap_samples
        act_start = max(earliest_start, orig_start_sample)
        
    act_end = act_start + len(trimmed)
    timeline_sample = act_end
    
    res = {
        'index': idx,
        'start': round(act_start / sample_rate, 3),
        'end': round(act_end / sample_rate, 3),
        'dur': round(len(trimmed) / sample_rate, 3),
        'speed': round(speed_factor, 2),
        'text': b['text']
    }
    results.append(res)
    print(f"Block {idx:02d}: {res['start']:6.3f}s -> {res['end']:6.3f}s (dur: {res['dur']:.3f}s, speed: {res['speed']:.2f}x)")

with open('actual_block_timings.json', 'w', encoding='utf-8') as out:
    json.dump(results, out, indent=2, ensure_ascii=False)
