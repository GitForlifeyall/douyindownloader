import sys
from pathlib import Path
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, str(Path(__file__).resolve().parent))
from dubbing_studio.env_loader import configure_runtime_environment
configure_runtime_environment()
from faster_whisper import WhisperModel

model = WhisperModel('large-v3-turbo', device='cuda', compute_type='int8_float16')
s_path = 'output/audio_stems/temp_sarvam_slices/block_012.mp3'
segments, info = model.transcribe(s_path, language='hi', word_timestamps=True)
for seg in segments:
    print("Segment:", seg.text)
    for w in seg.words:
        print(f"  {w.start:.2f} - {w.end:.2f} : {w.word}")
