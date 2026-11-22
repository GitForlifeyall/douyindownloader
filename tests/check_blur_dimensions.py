import cv2, glob
from blur_subtitles import detect_exact_subtitle_box

orig_paths = glob.glob('TikTokDownloader/Volume/Download/*桂花蜜*.mp4')
if not orig_paths:
    print('Not found')
    exit()
orig_path = orig_paths[0]

cap = cv2.VideoCapture(orig_path)
total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
fps = cap.get(cv2.CAP_PROP_FPS)

boxes = []
frame_idx = 0
while True:
    ret, frame = cap.read()
    if not ret:
        break
    if frame_idx % 10 == 0:  # sample every 10 frames
        box = detect_exact_subtitle_box(frame)
        if box is not None:
            bx, by, bw, bh = box
            # with blur margin=10
            x1 = max(0, bx - 10)
            x2 = min(frame.shape[1], bx + bw + 10)
            y1 = max(0, by - 10)
            y2 = min(frame.shape[0], by + bh + 10)
            w_blur = x2 - x1
            h_blur = y2 - y1
            boxes.append((frame_idx / fps, bx, by, bw, bh, x1, x2, y1, y2, w_blur, h_blur))
    frame_idx += 1
cap.release()

if boxes:
    widths = [b[9] for b in boxes]
    heights = [b[10] for b in boxes]
    y_centers = [(b[7] + b[8]) / 2 for b in boxes]
    x_centers = [(b[5] + b[6]) / 2 for b in boxes]
    print(f'Detected {len(boxes)} subtitle samples across video.')
    print(f'Blur Width min: {min(widths)} px, max: {max(widths)} px, avg: {sum(widths)/len(widths):.1f} px')
    print(f'Blur Height min: {min(heights)} px, max: {max(heights)} px, avg: {sum(heights)/len(heights):.1f} px')
    print(f'Horizontal Center: min {min(x_centers):.1f}, max {max(x_centers):.1f}, avg {sum(x_centers)/len(x_centers):.1f} (Video width is 1080)')
    print(f'Vertical Center: min {min(y_centers):.1f}, max {max(y_centers):.1f}, avg {sum(y_centers)/len(y_centers):.1f} (Video height is 1920)')
    print('\nDistribution of blur widths:')
    import collections
    buckets = collections.defaultdict(int)
    for w in widths:
        b_key = f"{(w // 50) * 50}-{(w // 50) * 50 + 49}"
        buckets[b_key] += 1
    for k in sorted(buckets.keys()):
        print(f'  {k} px: {buckets[k]} frames')
