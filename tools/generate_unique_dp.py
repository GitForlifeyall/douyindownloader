#!/usr/bin/env python3
"""
tools/generate_unique_dp.py
===========================
Generates a perceptually unique Profile Picture (DP) per account
to defeat Meta's Perceptual Hashing (PDQ / pHash) and MD5/SHA256 correlation engines.

Techniques applied:
1. Micro-cropping (1-4% dynamic margins)
2. Micro-rotation (-1.5 to +1.5 degrees with bicubic interpolation)
3. Micro-color jitter (subtle brightness, contrast, and color balance jitter)
4. Micro-noise injection (sub-perceptual Gaussian noise)
5. Complete EXIF and metadata stripping
6. Dynamic JPEG compression quality (88-95)
"""

import sys
import os
import random
import numpy as np
from PIL import Image, ImageEnhance, ImageOps

def create_unique_dp(input_path: str, output_path: str) -> str:
    if not os.path.exists(input_path):
        # If input path does not exist, generate a stylized graphic avatar
        return generate_geometric_avatar(output_path)

    img = Image.open(input_path).convert("RGB")
    w, h = img.size

    # 1. Micro-Crop (1-4%)
    crop_x = int(w * random.uniform(0.01, 0.04))
    crop_y = int(h * random.uniform(0.01, 0.04))
    img = img.crop((crop_x, crop_y, w - crop_x, h - crop_y))

    # 2. Micro-Rotation (-1.2 to +1.2 deg)
    angle = random.uniform(-1.2, 1.2)
    img = img.rotate(angle, resample=Image.BICUBIC, expand=False)

    # 3. Micro-Color & Contrast Jitter (sub-perceptual)
    img = ImageEnhance.Brightness(img).enhance(random.uniform(0.96, 1.04))
    img = ImageEnhance.Contrast(img).enhance(random.uniform(0.95, 1.05))
    img = ImageEnhance.Color(img).enhance(random.uniform(0.95, 1.05))

    # 4. Subtle Pixel Noise Injection
    arr = np.array(img, dtype=np.int16)
    noise = np.random.normal(0, random.uniform(0.8, 1.6), arr.shape)
    arr = np.clip(arr + noise, 0, 255).astype(np.uint8)
    img = Image.fromarray(arr)

    # 5. Resize to standard 500x500 square for Instagram DP
    img = ImageOps.fit(img, (500, 500), method=Image.LANCZOS)

    # 6. Save without EXIF with randomized JPEG quality
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    quality = random.randint(89, 95)
    img.save(output_path, "JPEG", quality=quality, optimize=True)
    return output_path

def generate_geometric_avatar(output_path: str) -> str:
    """Fallback generator: creates a clean modern gradient avatar with initials or shapes."""
    size = (500, 500)
    bg_colors = [
        ((35, 39, 47), (80, 88, 108)),
        ((40, 20, 60), (95, 45, 120)),
        ((20, 45, 60), (45, 105, 135)),
        ((60, 30, 25), (140, 65, 55)),
        ((25, 50, 40), (55, 115, 90)),
    ]
    c1, c2 = random.choice(bg_colors)
    base = Image.new("RGB", size, c1)
    
    # Simple vertical gradient
    arr = np.zeros((size[1], size[0], 3), dtype=np.uint8)
    for y in range(size[1]):
        ratio = y / size[1]
        r = int(c1[0] * (1 - ratio) + c2[0] * ratio)
        g = int(c1[1] * (1 - ratio) + c2[1] * ratio)
        b = int(c1[2] * (1 - ratio) + c2[2] * ratio)
        arr[y, :] = [r, g, b]
    
    img = Image.fromarray(arr)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    img.save(output_path, "JPEG", quality=92, optimize=True)
    return output_path

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: generate_unique_dp.py <input_image> <output_image>")
        sys.exit(1)
    
    inp = sys.argv[1]
    out = sys.argv[2]
    result = create_unique_dp(inp, out)
    print(f"UNIQUE_DP_SAVED: {result}")
