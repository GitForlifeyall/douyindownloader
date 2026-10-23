import cv2
import numpy as np
from PIL import Image, ImageFont, ImageDraw

# Load the raw frame with the blur
frame_bgr = cv2.imread('test_user_frame_raw.png')
frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
pil_img = Image.fromarray(frame_rgb)
draw = ImageDraw.Draw(pil_img)

font_path = 'assets/fonts/Montserrat-ExtraBold.ttf'
font_size = 90
font = ImageFont.truetype(font_path, font_size)

text = "ke ped par maaro"
bbox = font.getbbox(text)
tw = bbox[2] - bbox[0]
th = bbox[3] - bbox[1]

# Position centered horizontally, and at y=1495 (center of blur)
x = (1080 - tw) // 2
y = 1495 - (th // 2)

stroke_width = 8
# Draw black outline stroke
draw.text((x, y), text, font=font, fill="white", stroke_width=stroke_width, stroke_fill="black")

# Save comparison image
res_bgr = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)
cv2.imwrite('test_overlap_proof.png', res_bgr)
print(f'Rendered "{text}" (width={tw}px) at x={x}, y={y}')
print('Blur was from x=181 to x=902 (width=721px)')
print(f'Text with stroke spans from x={x-stroke_width} to x={x+tw+stroke_width} (width={tw+2*stroke_width}px)')
print(f'Overlap on left: {181 - (x-stroke_width)}px past blur')
print(f'Overlap on right: {(x+tw+stroke_width) - 902}px past blur')
