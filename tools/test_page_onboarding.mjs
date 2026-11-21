#!/usr/bin/env node
/**
 * tools/test_page_onboarding.mjs
 * ==============================
 * Tests the post-creation Facebook Page Onboarding steps:
 * - Handle input matching Page Name
 * - Profile Picture & Cover Photo upload
 * - "Open at selected hours" selection
 * - WhatsApp prompt "Skip"
 * - "Next" and "Done" navigation
 * Handles both the 3-Step Creator flow and the 5-Step Customise Page flow.
 */

import fs from "node:fs";
import path from "node:path";
import crypto from "node:crypto";

const CAMOUFOX_PATH = "file:///C:/Users/rudra/AppData/Roaming/npm/node_modules/camoufox-cli/node_modules/camoufox-js/dist/index.js";
const { Camoufox } = await import(CAMOUFOX_PATH);

const DEFAULT_PROXY = process.env.OXYLABS_PROXY || "";
const profileDir = path.resolve("output", "profiles facebook", "WilsonYurcak691555");

function parseProxy(proxyStr) {
  if (!proxyStr) return null;
  let clean = proxyStr.replace(/^https?:\/\//i, "");
  if (clean.includes("@")) {
    const [auth, hostPort] = clean.split("@");
    const [username, password] = auth.split(":");
    return {
      server: `http://${hostPort}`,
      username: decodeURIComponent(username),
      password: decodeURIComponent(password),
    };
  }
  return { server: `http://${clean}` };
}

export async function completePageOnboarding(page, pageName = "NovaPulse Media") {
  console.log("============================================================");
  console.log(`[Facebook Onboarding] Running wizard setup for: "${pageName}"`);
  console.log("============================================================");

  const profilePhotoPath = path.resolve("tests", "test_artifacts", "test_thumb_vertical.jpg");
  const coverPhotoPath = path.resolve("tests", "test_artifacts", "test_thumb_horizontal.jpg");
  const cleanHandle = pageName.toLowerCase().replace(/[^a-z0-9]/g, "").slice(0, 30);

  for (let step = 1; step <= 8; step++) {
    await page.waitForTimeout(3000);
    const url = page.url();
    const bodyText = await page.evaluate(() => (document.body ? document.body.innerText : ""));
    console.log(`[Facebook Onboarding] Step ${step} | URL: ${url}`);

    await page.screenshot({ path: `tests/test_artifacts/fb_onboard_step_${step}.png` });

    // Check if finished / on Page Home
    if (bodyText.includes("Welcome to your new Page") || bodyText.includes("Switch into") || bodyText.includes("Manage Page") || bodyText.includes("What's on your mind?")) {
      console.log("[Facebook Onboarding] Reached finished Page state!");
      break;
    }

    // 1. Choose Page Type screen (Business vs Creator) -> Image 1
    if (bodyText.includes("Choose Page type") || bodyText.includes("Your Page is created! Choose your Page type")) {
      console.log("[Facebook Onboarding] Detected: 'Choose Page type'. Selecting 'Creator'...");
      const creatorOption = page.locator("div:has-text('Creator'), label:has-text('Creator')").filter({ hasText: /monetize original content/i }).first();
      if ((await creatorOption.count()) > 0) {
        await creatorOption.click().catch(() => {});
        await page.waitForTimeout(500);
      }
      const nextBtn = page.locator("button:has-text('Next'), [role='button']:has-text('Next')").first();
      if ((await nextBtn.count()) > 0) {
        await nextBtn.click();
        console.log("[Facebook Onboarding] Clicked 'Next' on Choose Page type.");
        await page.waitForTimeout(3000);
        continue;
      }
    }

    // 2. Handle input (Step 1 of 3: Page details) -> Image 2
    const handleInput = page.locator("input[placeholder*='handle' i], input[aria-label*='handle' i], label:has-text('Handle') input, div:has-text('Handle') input").first();
    if ((await handleInput.count()) > 0 && (await handleInput.isVisible())) {
      console.log(`[Facebook Onboarding] Detected: 'Handle' input. Entering: '${cleanHandle}'...`);
      await handleInput.click();
      await handleInput.pressSequentially(cleanHandle, { delay: 50 });
      await page.waitForTimeout(500);

      // Upload photo if available on this step
      const fileInputs = page.locator("input[type='file']");
      if ((await fileInputs.count()) > 0 && fs.existsSync(profilePhotoPath)) {
        console.log(`[Facebook Onboarding] Uploading photo to Step 1: ${profilePhotoPath}...`);
        await fileInputs.first().setInputFiles(profilePhotoPath).catch(() => {});
        await page.waitForTimeout(2000);
      }

      const nextBtn = page.locator("button:has-text('Next'), [role='button']:has-text('Next')").first();
      if ((await nextBtn.count()) > 0) {
        await nextBtn.click();
        console.log("[Facebook Onboarding] Clicked 'Next' on Page details.");
        await page.waitForTimeout(3000);
        continue;
      }
    }

    // 3. Step 1 of 5: "Finish setting up your Page" (Hours: Open at selected hours) -> Image 3
    if (bodyText.includes("Finish setting up your Page") || bodyText.includes("location's hours") || bodyText.includes("Open at selected hours")) {
      console.log("[Facebook Onboarding] Detected: 'Finish setting up your Page'. Selecting 'Open at selected hours'...");
      const hoursRadio = page.locator("label:has-text('Open at selected hours'), div:has-text('Open at selected hours'), input[value*='selected']").first();
      if ((await hoursRadio.count()) > 0) {
        await hoursRadio.click().catch(() => {});
        await page.waitForTimeout(500);
      } else {
        const alwaysOpen = page.locator("label:has-text('Always open'), div:has-text('Always open')").first();
        if ((await alwaysOpen.count()) > 0) await alwaysOpen.click().catch(() => {});
      }

      const nextBtn = page.locator("button:has-text('Next'), [role='button']:has-text('Next')").first();
      if ((await nextBtn.count()) > 0) {
        await nextBtn.click();
        console.log("[Facebook Onboarding] Clicked 'Next' on Finish setting up your Page.");
        await page.waitForTimeout(3000);
        continue;
      }
    }

    // 4. Step 2 of 5: "Customise your Page" (Profile Picture & Cover Photo) -> Image 4
    if (bodyText.includes("Customise your Page") || bodyText.includes("Customize your Page") || bodyText.includes("Add Profile Picture") || bodyText.includes("Add Cover Photo")) {
      console.log("[Facebook Onboarding] Detected: 'Customise your Page'. Uploading Profile Picture and Cover Photo...");
      const fileInputs = page.locator("input[type='file']");
      const fileCount = await fileInputs.count();
      console.log(`[Facebook Onboarding] Found ${fileCount} file input(s).`);

      if (fileCount >= 1 && fs.existsSync(profilePhotoPath)) {
        console.log(`[Facebook Onboarding] Uploading Profile Picture: ${profilePhotoPath}...`);
        await fileInputs.nth(0).setInputFiles(profilePhotoPath).catch(() => {});
        await page.waitForTimeout(2000);
      }
      if (fileCount >= 2 && fs.existsSync(coverPhotoPath)) {
        console.log(`[Facebook Onboarding] Uploading Cover Photo: ${coverPhotoPath}...`);
        await fileInputs.nth(1).setInputFiles(coverPhotoPath).catch(() => {});
        await page.waitForTimeout(2000);
      }

      const nextBtn = page.locator("button:has-text('Next'), [role='button']:has-text('Next')").first();
      if ((await nextBtn.count()) > 0) {
        await nextBtn.click();
        console.log("[Facebook Onboarding] Clicked 'Next' on Customise your Page.");
        await page.waitForTimeout(3000);
        continue;
      }
    }

    // 5. Connect WhatsApp -> Image 5: click "Skip"
    if (bodyText.includes("Connect WhatsApp") || bodyText.includes("WhatsApp number") || bodyText.includes("send you a code on WhatsApp")) {
      console.log("[Facebook Onboarding] Detected: 'Connect WhatsApp'. Clicking 'Skip'...");
      const skipBtn = page.locator("button:has-text('Skip'), [role='button']:has-text('Skip')").first();
      if ((await skipBtn.count()) > 0 && (await skipBtn.isVisible())) {
        await skipBtn.click();
        console.log("[Facebook Onboarding] Clicked 'Skip' on WhatsApp prompt.");
        await page.waitForTimeout(3000);
        continue;
      }
    }

    // 6. Check for "Done" button (Final step)
    const doneBtn = page.locator("button:has-text('Done'), [role='button']:has-text('Done'), [aria-label='Done']").first();
    if ((await doneBtn.count()) > 0 && (await doneBtn.isVisible())) {
      console.log("[Facebook Onboarding] Clicked 'Done' button!");
      await doneBtn.click();
      await page.waitForTimeout(5000);
      break;
    }

    // 7. Generic "Next" fallback
    const genericNext = page.locator("button:has-text('Next'), [role='button']:has-text('Next')").first();
    if ((await genericNext.count()) > 0 && (await genericNext.isVisible())) {
      console.log("[Facebook Onboarding] Clicking generic 'Next' button...");
      await genericNext.click();
      await page.waitForTimeout(3000);
      continue;
    }

    console.log("[Facebook Onboarding] No active onboarding modal detected on current screen.");
    break;
  }

  await page.screenshot({ path: "tests/test_artifacts/fb_onboard_final.png", fullPage: true });
  console.log("[Facebook Onboarding] Saved final onboarding screenshot to tests/test_artifacts/fb_onboard_final.png");
}

async function run() {
  const browser = await Camoufox({
    user_data_dir: profileDir,
    headless: false,
    proxy: parseProxy(DEFAULT_PROXY),
    geoip: false,
  });

  const page = (browser.pages && browser.pages().length > 0) ? browser.pages()[0] : await browser.newPage();
  console.log("[Facebook] Navigating to https://www.facebook.com/pages/?category=your_pages...");
  await page.goto("https://www.facebook.com/pages/?category=your_pages", { waitUntil: "domcontentloaded", timeout: 35000 });
  await page.waitForTimeout(4000);

  // If there is an existing page under manage (e.g. Dsds), click into it
  const pageLink = page.locator("a:has-text('Dsds'), [role='link']:has-text('Dsds'), div:has-text('Dsds')").first();
  if ((await pageLink.count()) > 0) {
    console.log("[Facebook] Opening page 'Dsds' to check/complete onboarding...");
    await pageLink.click();
    await page.waitForTimeout(4000);
  }

  await completePageOnboarding(page, "Dsds");

  await browser.close();
}

if (process.argv[1]?.endsWith("test_page_onboarding.mjs")) {
  run().catch(console.error);
}
