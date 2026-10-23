import os
import sys
import time
import cv2
import torch
import numpy as np
from tqdm import tqdm

# Add video-subtitle-remover-main to path
sys.path.insert(0, os.path.abspath("video-subtitle-remover-main"))
from backend.inpaint.lama_inpaint import LamaInpaint
from remove_subtitles import auto_profile_video_layout

def run_lama_video(input_video, output_video, max_duration=10):
    print("=" * 55)
    print(" [LaMA High-Fidelity Inpainter] Starting Benchmark")
    print(f" Input Video  : {input_video}")
    print(f" Output Video : {output_video}")
    print(f" Max Duration : {max_duration} seconds")
    print("=" * 55)

    cap = cv2.VideoCapture(input_video)
    if not cap.isOpened():
        print(f"Error: Could not open {input_video}")
        return

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    orig_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    orig_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cap.release()

    # Pre-scale to 1080p if needed
    proc_video = input_video
    temp_1080 = None
    if orig_w > 1080 or orig_h > 1920:
        temp_1080 = "output/_temp_1080p_lama_bench.mp4"
        print(f"[*] Pre-scaling from {orig_w}x{orig_h} to 1080p NVENC...")
        import subprocess
        subprocess.run([
            "ffmpeg", "-y", "-i", input_video, "-t", str(max_duration),
            "-vf", "scale='if(gt(iw,ih),-2,min(1080,iw))':'if(gt(iw,ih),min(1080,ih),-2)':flags=lanczos",
            "-c:v", "hevc_nvenc", "-preset", "p4", "-b:v", "3500k", "-tag:v", "hvc1",
            "-an", temp_1080
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        proc_video = temp_1080

    # Auto detect subtitle zone
    sub_coords, wm_coords = auto_profile_video_layout(proc_video)
    if sub_coords is None:
        sub_coords = (1265, 1552, 0, 1080)
    print(f"[*] Detected Subtitle Zone: Y={sub_coords[0]} to {sub_coords[1]}")

    # Load LaMA model on GPU
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"[*] Loading big-lama.pt model on {device}...")
    model_path = os.path.join("video-subtitle-remover-main", "backend", "models", "big-lama", "big-lama.pt")
    lama = LamaInpaint(device, model_path)

    # Read video frames
    cap = cv2.VideoCapture(proc_video)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    max_frames = min(int(max_duration * fps), int(cap.get(cv2.CAP_PROP_FRAME_COUNT)))

    frames = []
    while len(frames) < max_frames:
        ret, frame = cap.read()
        if not ret:
            break
        frames.append(frame)
    cap.release()
    print(f"[*] Loaded {len(frames)} frames ({len(frames)/fps:.1f}s at {fps:.1f} FPS)")

    # Prepare mask
    s_ymin, s_ymax, s_xmin, s_xmax = sub_coords
    mask = np.zeros((h, w), dtype=np.uint8)
    mask[s_ymin:s_ymax, s_xmin:s_xmax] = 255

    # Run inpainting in batches
    print(f"[*] Inpainting {len(frames)} frames with LaMA on GPU...")
    batch_size = 16
    out_frames = []
    t_start = time.time()

    with tqdm(total=len(frames), desc="LaMA Inpainting", unit="frame") as pbar:
        for i in range(0, len(frames), batch_size):
            chunk = frames[i:i + batch_size]
            inpainted_chunk = lama(chunk, mask)
            out_frames.extend(inpainted_chunk)
            pbar.update(len(chunk))

    total_time = time.time() - t_start
    fps_speed = len(frames) / total_time
    print(f"\n[+] Inpainting finished in {total_time:.2f} seconds ({fps_speed:.2f} FPS, {total_time/len(frames)*1000:.1f} ms/frame)")

    # Write output video using NVENC HEVC
    writer_cmd = [
        "ffmpeg", "-y",
        "-f", "rawvideo",
        "-vcodec", "rawvideo",
        "-s", f"{w}x{h}",
        "-pix_fmt", "bgr24",
        "-r", str(fps),
        "-i", "-",
        "-c:v", "hevc_nvenc",
        "-preset", "p4",
        "-b:v", "3600k",
        "-tag:v", "hvc1",
        output_video
    ]
    import subprocess
    proc = subprocess.Popen(writer_cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for f in out_frames:
        proc.stdin.write(f.tobytes())
    proc.stdin.close()
    proc.wait()

    if temp_1080 and os.path.exists(temp_1080):
        try:
            os.remove(temp_1080)
        except Exception:
            pass

    out_size = os.path.getsize(output_video) / (1024 * 1024) if os.path.exists(output_video) else 0
    print(f"[+] Output Video Saved: {output_video} ({out_size:.1f} MB)")
    print(f"[*] Total Execution Time: {total_time:.1f}s for 10.0s of video")

if __name__ == "__main__":
    in_vid = "output/sample_10s.mp4"
    out_vid = "output/sample_10s_lama_clean.mp4"
    run_lama_video(in_vid, out_vid, max_duration=10)
