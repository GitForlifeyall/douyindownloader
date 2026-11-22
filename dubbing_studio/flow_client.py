"""
Google Flow Automated Headless Client for AI Thumbnail Generation.

Uses Playwright with persistent Chrome profile:
1. Launches Chrome headless with C:\\Users\\rudra\\.flowkit_chrome_profile
2. Navigates directly to your active Google Flow project
3. Inputs the cinematic prompt into ProseMirror
4. Submits generation and extracts the resulting high-res image (16:9 or 9:16)
"""

import base64
import logging
import os
import time
from pathlib import Path
from typing import Optional

from playwright.sync_api import sync_playwright

logger = logging.getLogger(__name__)

def get_default_flow_profile() -> Path:
    """Find the active FlowKit Chrome profile directory."""
    candidate = Path(__file__).resolve().parent.parent / "output" / "flow_profiles" / "account_1"
    if candidate.exists():
        return candidate
    return Path.home() / ".flowkit_chrome_profile"

DEFAULT_FLOW_PROFILE = get_default_flow_profile()
DEFAULT_PROJECT_URL = "https://flow.google.com/project/25d03787-2b4b-4bbe-86fa-54e2e10ca517"


def generate_flow_image(
    prompt: str,
    output_path: Path,
    project_url: str = DEFAULT_PROJECT_URL,
    profile_path: Path = DEFAULT_FLOW_PROFILE,
    timeout_seconds: int = 40,
) -> Optional[Path]:
    """
    Submits prompt to Google Flow (Nano Banana 2.1) and extracts the high-res image plate.
    Returns output_path on success, or None on failure.
    """
    if not profile_path.exists():
        logger.warning(f"[FlowClient] Chrome profile not found at {profile_path}")
        return None

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch_persistent_context(
                user_data_dir=str(profile_path),
                headless=True,
                channel="chrome",
                args=["--disable-blink-features=AutomationControlled"],
            )
            page = browser.pages[0] if browser.pages else browser.new_page()
            page.goto(project_url, wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(3000)

            initial_tiles = page.locator("flow-grid-tile-container").count()

            # Locate the Flow prompt editor
            prompt_box = page.locator('div.ProseMirror[contenteditable="true"]')
            if prompt_box.count() == 0:
                logger.warning("[FlowClient] Could not locate Google Flow prompt bar.")
                browser.close()
                return None

            prompt_box.click()
            page.wait_for_timeout(200)
            page.keyboard.press("Control+A")
            page.keyboard.press("Backspace")
            page.wait_for_timeout(200)
            prompt_box.fill(prompt)
            page.wait_for_timeout(800)

            # Submit generation
            submit_btn = page.locator('button[aria-label="Start generation"]')
            if submit_btn.count() > 0 and submit_btn.first.is_enabled():
                submit_btn.first.click()
            else:
                prompt_box.press("Enter")

            # Wait for new tile to appear
            t0 = time.time()
            generated = False
            while time.time() - t0 < timeout_seconds:
                page.wait_for_timeout(1500)
                curr_tiles = page.locator("flow-grid-tile-container").count()
                if curr_tiles > initial_tiles:
                    page.wait_for_timeout(4000)
                    generated = True
                    break

            if not generated:
                logger.warning("[FlowClient] Generation timed out waiting for new tile.")
                browser.close()
                return None

            # Extract high-res image (=s1920-rw) from newest tile
            data = page.evaluate("""() => {
                return new Promise((resolve) => {
                    const tiles = Array.from(document.querySelectorAll('flow-grid-tile-container'));
                    if (tiles.length === 0) return resolve(null);
                    const tileImg = tiles[0].querySelector('img');
                    if (!tileImg) return resolve(null);

                    const hiResSrc = tileImg.src.replace(/=s\\d+-rw/, '=s1920-rw');
                    const fullImg = new Image();
                    fullImg.crossOrigin = 'anonymous';
                    fullImg.onload = () => {
                        const canvas = document.createElement('canvas');
                        canvas.width = fullImg.naturalWidth;
                        canvas.height = fullImg.naturalHeight;
                        const ctx = canvas.getContext('2d');
                        ctx.drawImage(fullImg, 0, 0);
                        resolve({
                            width: fullImg.naturalWidth,
                            height: fullImg.naturalHeight,
                            dataUrl: canvas.toDataURL('image/jpeg', 0.96)
                        });
                    };
                    fullImg.onerror = () => resolve(null);
                    fullImg.src = hiResSrc;
                });
            }""")

            browser.close()

            if data and data.get("dataUrl") and "," in data["dataUrl"]:
                raw_bytes = base64.b64decode(data["dataUrl"].split(",", 1)[1])
                output_path.write_bytes(raw_bytes)
                logger.info(f"[FlowClient] Successfully saved AI image ({data['width']}x{data['height']}, {len(raw_bytes)} bytes) to {output_path}")
                return output_path

    except Exception as e:
        logger.warning(f"[FlowClient] Headless Google Flow generation encountered an error: {e}")

    return None
