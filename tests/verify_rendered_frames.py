import cv2
from pathlib import Path

video_path = 'output/final_videos/道可道 - 恭喜你成功制作出桂花蜜_hindi_sarvam_dubbed_captioned.mp4'
cap = cv2.VideoCapture(video_path)
fps = cap.get(cv2.CAP_PROP_FPS)

test_times = [
    (1.2, "frame_1_2s_kick"),
    (8.0, "frame_8_0s_golden"),
    (16.8, "frame_16_8s_glassjar"),
    (26.5, "frame_26_5s_sugardaal"),
    (62.5, "frame_62_5s_tasty")
]

for t, name in test_times:
    frame_no = int(t * fps)
    cap.set(cv2.CAP_PROP_POS_FRAMES, frame_no)
    ret, frame = cap.read()
    if ret:
        # Full frame
        cv2.imwrite(f"{name}_full.png", frame)
        # Subtitle region crop (y=1380 to 1620, x=80 to 1000)
        crop = frame[1380:1620, 80:1000]
        cv2.imwrite(f"{name}_crop.png", crop)
        print(f"Extracted {name}_crop.png at t={t}s")

cap.release()
print("All verification frames extracted successfully!")
