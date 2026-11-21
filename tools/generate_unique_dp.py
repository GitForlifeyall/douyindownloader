#!/usr/bin/env python3
"""
tools/generate_unique_dp.py
===========================
Generates perceptually and cryptographically unique image variations per account/post
to defeat Meta's Perceptual Hashing (PDQ / pHash), Blockhash, and MD5/SHA256 correlation engines.

Techniques applied:
1. Complete EXIF and metadata stripping
2. Micro-cropping (1-3% dynamic margins)
3. Fractional micro-rotation (-0.8 to +0.8 degrees with bicubic interpolation)
4. Micro-color & contrast jitter (subtle brightness, contrast, and color balance shifts)
5. Micro-noise injection (sub-perceptual Gaussian noise)
6. Dynamic JPEG compression quality (89-95)
"""

import sys
import os
import random
import numpy as np
from PIL import Image, ImageEnhance, ImageOps

def create_unique_image(input_path: str, output_path: str, target_size=None, mode="dp") -> str:
    """
    Transforms an input image into a unique variation with altered perceptual hashes.
    mode can be 'dp' (500x500 square), 'cover' (820x312), 'thumbnail' (1080x1920), or 'free' (retains aspect).
    """
    if not os.path.exists(input_path):
        return generate_geometric_avatar(output_path, target_size or (500, 500))

    img = Image.open(input_path).convert("RGB")
    w, h = img.size

    # 1. Micro-Crop (1-3% dynamic margins)
    crop_x = int(w * random.uniform(0.01, 0.03))
    crop_y = int(h * random.uniform(0.01, 0.03))
    img = img.crop((crop_x, crop_y, max(crop_x + 10, w - crop_x), max(crop_y + 10, h - crop_y)))

    # 2. Fractional Micro-Rotation (-0.8 to +0.8 deg, shifts pixel grid matrix)
    angle = random.uniform(-0.8, 0.8)
    img = img.rotate(angle, resample=Image.BICUBIC, expand=False)

    # 3. Micro-Color & Contrast Jitter (sub-perceptual ±1.5% to ±2.5%)
    img = ImageEnhance.Brightness(img).enhance(random.uniform(0.975, 1.025))
    img = ImageEnhance.Contrast(img).enhance(random.uniform(0.97, 1.03))
    img = ImageEnhance.Color(img).enhance(random.uniform(0.97, 1.03))

    # 4. Subtle Pixel Noise Injection
    arr = np.array(img, dtype=np.int16)
    noise = np.random.normal(0, random.uniform(0.6, 1.4), arr.shape)
    arr = np.clip(arr + noise, 0, 255).astype(np.uint8)
    img = Image.fromarray(arr)

    # 5. Sizing based on mode
    if target_size:
        img = ImageOps.fit(img, target_size, method=Image.LANCZOS)
    elif mode == "dp":
        img = ImageOps.fit(img, (500, 500), method=Image.LANCZOS)
    elif mode == "cover":
        img = ImageOps.fit(img, (820, 312), method=Image.LANCZOS)
    elif mode == "thumbnail":
        img = ImageOps.fit(img, (1080, 1920), method=Image.LANCZOS)

    # 6. Save without EXIF with randomized JPEG quality (breaks exact byte correlation)
    out_dir = os.path.dirname(output_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    quality = random.randint(89, 95)
    img.save(output_path, "JPEG", quality=quality, optimize=True)
    return output_path

def create_unique_dp(input_path: str, output_path: str) -> str:
    """Legacy helper maintained for backward compatibility."""
    return create_unique_image(input_path, output_path, target_size=(500, 500), mode="dp")

def generate_n_variations(input_path: str, output_dir: str, count: int = 5, mode: str = "dp") -> list:
    """Generates N unique variations of a single source image into output_dir."""
    os.makedirs(output_dir, exist_ok=True)
    generated = []
    base_name = os.path.splitext(os.path.basename(input_path))[0]
    for i in range(1, count + 1):
        out_p = os.path.join(output_dir, f"{base_name}_var_{i}.jpg")
        create_unique_image(input_path, out_p, mode=mode)
        generated.append(out_p)
    return generated

def generate_geometric_avatar(output_path: str, size=(500, 500)) -> str:
    """Fallback generator: creates a clean modern gradient avatar with initials or shapes."""
    bg_colors = [
        ((35, 39, 47), (80, 88, 108)),
        ((40, 20, 60), (95, 45, 120)),
        ((20, 45, 60), (45, 105, 135)),
        ((60, 30, 25), (140, 65, 55)),
        ((25, 50, 40), (55, 115, 90)),
    ]
    c1, c2 = random.choice(bg_colors)
    arr = np.zeros((size[1], size[0], 3), dtype=np.uint8)
    for y in range(size[1]):
        ratio = y / size[1]
        r = int(c1[0] * (1 - ratio) + c2[0] * ratio)
        g = int(c1[1] * (1 - ratio) + c2[1] * ratio)
        b = int(c1[2] * (1 - ratio) + c2[2] * ratio)
        arr[y, :] = [r, g, b]

    img = Image.fromarray(arr)
    out_dir = os.path.dirname(output_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    img.save(output_path, "JPEG", quality=92, optimize=True)
    return output_path

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: generate_unique_dp.py <input_image> <output_image> [mode]")
        sys.exit(1)

    inp = sys.argv[1]
    out = sys.argv[2]
    m = sys.argv[3] if len(sys.argv) > 3 else "dp"
    result = create_unique_image(inp, out, mode=m)
    print(f"UNIQUE_IMAGE_SAVED: {result}")
