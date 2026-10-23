import cv2
import numpy as np
from PIL import Image, ImageFont, ImageDraw

frame_bgr = cv2.imread('test_user_frame_raw.png')
frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
pil_img = Image.fromarray(frame_rgb)
draw = ImageDraw.Draw(pil_img)

font_path = 'assets/fonts/Montserrat-ExtraBold.ttf'
font_size = 94
font = ImageFont.truetype(font_path, font_size)

text = "ke ped par maaro"
bbox = font.getbbox(text)
tw = bbox[2] - bbox[0]
th = bbox[3] - bbox[1]

# Position centered horizontally, and centered vertically over blur (blur y: 1472 to 1527, center = 1500)
x = (1080 - tw) // 2
y = 1500 - (th // 2) - 10 # adjust for ascent

stroke_width = 9
# Draw black outline stroke
draw.text((x, y), text, font=font, fill="white", stroke_width=stroke_width, stroke_fill="black")

res_bgr = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)
cv2.imwrite('test_overlap_proof_centered.png', res_bgr)
print(f'Rendered centered at x={x}, y={y}')
