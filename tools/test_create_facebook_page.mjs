#!/usr/bin/env node
/**
 * tools/test_create_facebook_page.mjs
 * ===================================
 * Automates Facebook Page creation on the currently active profile:
 * 1. Opens Facebook home with persistent profile (WilsonYurcak691555).
 * 2. Waits for and clicks the 9-dots Menu icon (aria-label='Menu').
 * 3. Clicks "Page" under the Create section.
 * 4. Fills Page name (randomized brand/blog name).
 * 5. Fills Category: "Personal blog" and selects the dropdown match.
 * 6. Fills Bio: randomized engaging bio.
 * 7. Clicks "Create Page" and waits for completion.
 * 8. Captures screenshots at each step.
 */

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

const PAGE_NAMES = [
  "NovaPulse Stories",
  "CineScope Daily",
  "The Velvet Chronicles",
  "EchoSphere Media",
  "Apex Vista Hub",
  "Zenith Pulse Daily",
  "CineGlow Moments",
  "Lumina Realm"
];

const BIOS = [
  "Documenting cinematic wonders, unique stories, and everyday inspiration. Welcome to the journey!",
  "Exploring fascinating stories, cinematic scenes, and cultural deep dives.",
  "Your daily dose of captivating storytelling, film insights, and creative musings.",
  "Cinematic highlights, life stories, and curated perspectives from around the globe."
];

const randomPageName = PAGE_NAMES[crypto.randomInt(PAGE_NAMES.length)];
const randomBio = BIOS[crypto.randomInt(BIOS.length)];

export async function createFacebookPage(page, pageName = randomPageName, bio = randomBio) {
  console.log("============================================================");
  console.log(`CREATING FACEBOOK PAGE: "${pageName}"`);
  console.log(`Category:  Personal blog`);
  console.log(`Bio:       ${bio}`);
  console.log("============================================================");

  // 1. Wait for Home page to load
  console.log("[Facebook] Waiting for home page navigation...");
  await page.waitForTimeout(3000);

  // Dismiss any "Remember Password" or dialog popups if present
  try {
    const notNowBtn = page.locator("button:has-text('Not Now'), [role='button']:has-text('Not Now'), [aria-label='Close'], [aria-label='बंद करें']");
    if ((await notNowBtn.count()) > 0 && (await notNowBtn.first().isVisible())) {
      console.log("[Facebook] Dismissing popup dialog...");
      await notNowBtn.first().click().catch(() => {});
      await page.waitForTimeout(1000);
    }
  } catch (e) {}

  // 2. Wait for 9-dots Menu icon to load
  console.log("[Facebook] Waiting for 9-dots Menu element to appear in top bar...");
  const menuLocator = page.locator("[aria-label='Menu'], [aria-label*='मेनू' i], [role='button'][aria-label='Menu'], [role='button'][aria-label*='मेनू' i]");
  
  await menuLocator.first().waitFor({ state: "visible", timeout: 20000 }).catch(() => {
    console.log("[Facebook] Menu locator wait timed out, proceeding to inspect header...");
  });

  // Log all header buttons for clarity
  const topButtons = await page.evaluate(() => {
    const btns = Array.from(document.querySelectorAll("div[role='banner'] [role='button'], div[role='navigation'] [role='button'], [aria-label]"));
    return btns.map((b) => ({
      ariaLabel: b.getAttribute("aria-label"),
      text: (b.innerText || "").trim(),
      role: b.getAttribute("role")
    })).filter((b) => b.ariaLabel).slice(0, 10);
  });
  console.log("[Facebook] Top Bar Elements:", JSON.stringify(topButtons));

  // Click 9-dots Menu button
  if ((await menuLocator.count()) > 0 && (await menuLocator.first().isVisible())) {
    console.log("[Facebook] Clicking 9-dots Menu icon...");
    await menuLocator.first().click();
    await page.waitForTimeout(2500);
  } else {
    // Fallback: Click the button that contains the 9 dots SVG
    console.log("[Facebook] Attempting fallback click for 9-dots icon...");
    await page.evaluate(() => {
      const allBtns = Array.from(document.querySelectorAll("[role='button']"));
      const menuBtn = allBtns.find((b) => {
        const l = (b.getAttribute("aria-label") || "").toLowerCase();
        return l === "menu" || l.includes("मेनू");
      });
      if (menuBtn) menuBtn.click();
    });
    await page.waitForTimeout(2500);
  }

  // Screenshot with Menu opened
  await page.screenshot({ path: "tests/test_artifacts/fb_menu_opened.png" });
  console.log("[Facebook] Saved menu screenshot to tests/test_artifacts/fb_menu_opened.png");

  // 3. Locate and click "Page" under Create section
  console.log("[Facebook] Locating 'Page' under Create menu...");
  // Look for exact "Page" text under the menu (singular, distinct from "Pages" under Social)
  const createPageOption = page.locator("div[role='dialog'] [role='button'], [role='menu'] [role='button'], [role='menuitem'], a, div").filter({
    hasText: /^Page$/
  }).first();

  if ((await createPageOption.count()) > 0 && (await createPageOption.isVisible())) {
    console.log("[Facebook] Found 'Page' option under Create section! Clicking...");
    await createPageOption.click();
    await page.waitForTimeout(4000);
  } else {
    console.log("[Facebook] Direct click on 'Page' item...");
    const altPageClick = await page.evaluate(() => {
      const elements = Array.from(document.querySelectorAll("div[role='dialog'] span, div[role='dialog'] div, [role='menu'] span"));
      const target = elements.find((el) => (el.innerText || "").trim() === "Page");
      if (target) {
        target.click();
        return true;
      }
      return false;
    });

    if (altPageClick) {
      console.log("[Facebook] Clicked 'Page' via DOM lookup.");
      await page.waitForTimeout(4000);
    } else {
      console.log("[Facebook] Navigating to https://www.facebook.com/pages/create/...");
      await page.goto("https://www.facebook.com/pages/create/", { waitUntil: "domcontentloaded" });
      await page.waitForTimeout(4000);
    }
  }

  console.log(`[Facebook] Current URL: ${page.url()} | Title: '${await page.title()}'`);
  await page.screenshot({ path: "tests/test_artifacts/fb_page_create_screen.png", fullPage: true });

  // 4. Fill "Page name (required)"
  console.log(`[Facebook] Typing Page Name: "${pageName}"...`);
  const nameInput = page.locator("input[aria-label*='Page name' i], input[aria-label*='पेज का नाम' i], label:has-text('Page name') input, input[type='text']").first();
  await nameInput.waitFor({ state: "visible", timeout: 15000 });
  await nameInput.click();
  await nameInput.pressSequentially(pageName, { delay: 60 });
  await page.waitForTimeout(1000);

  // 5. Fill "Category (required)": "Personal blog"
  console.log("[Facebook] Typing Category: 'Personal blog'...");
  const catInput = page.locator("input[aria-label*='Category' i], input[aria-label*='श्रेणी' i], label:has-text('Category') input").first();
  await catInput.click();
  await catInput.pressSequentially("Personal blog", { delay: 60 });
  await page.waitForTimeout(2000);

  // Wait for dropdown option "Personal blog" and click it
  console.log("[Facebook] Selecting 'Personal blog' from dropdown...");
  const catOption = page.locator("[role='listbox'] [role='option'], [role='option']").filter({
    hasText: /^Personal blog$/i
  }).first();

  if ((await catOption.count()) > 0 && (await catOption.isVisible())) {
    await catOption.click();
    console.log("[Facebook] Successfully selected 'Personal blog'!");
  } else {
    console.log("[Facebook] Listbox filter not matching exact, trying first option or Enter key...");
    const firstOpt = page.locator("[role='listbox'] [role='option'], [role='option']").first();
    if ((await firstOpt.count()) > 0 && (await firstOpt.isVisible())) {
      await firstOpt.click();
    } else {
      await page.keyboard.press("ArrowDown");
      await page.waitForTimeout(400);
      await page.keyboard.press("Enter");
    }
  }
  await page.waitForTimeout(1000);

  // 6. Fill "Bio (optional)"
  console.log(`[Facebook] Typing Bio: "${bio}"...`);
  const bioInput = page.locator("textarea[aria-label*='Bio' i], textarea").first();
  if ((await bioInput.count()) > 0 && (await bioInput.isVisible())) {
    await bioInput.click();
    await bioInput.pressSequentially(bio, { delay: 35 });
    await page.waitForTimeout(1000);
  }

  // Pre-creation screenshot
  await page.screenshot({ path: "tests/test_artifacts/fb_page_filled.png", fullPage: true });
  console.log("[Facebook] Saved pre-creation screenshot to tests/test_artifacts/fb_page_filled.png");

  // 7. Click "Create Page" button
  console.log("[Facebook] Submitting page creation ('Create Page')...");
  const createBtn = page.locator("button:has-text('Create Page'), [role='button']:has-text('Create Page'), button:has-text('पेज बनाएँ')").first();
  await createBtn.scrollIntoViewIfNeeded().catch(() => {});
  await createBtn.click();

  console.log("[Facebook] Clicked 'Create Page'. Waiting 12s for Facebook to process...");
  await page.waitForTimeout(12000);

  const postCreateUrl = page.url();
  const postCreateTitle = await page.title();
  console.log(`[Facebook] Post-creation URL: ${postCreateUrl} | Title: '${postCreateTitle}'`);

  await page.screenshot({ path: "tests/test_artifacts/fb_page_created.png", fullPage: true });
  console.log("[Facebook] Saved final screenshot to tests/test_artifacts/fb_page_created.png");

  return {
    pageName,
    category: "Personal blog",
    bio,
    url: postCreateUrl,
    title: postCreateTitle
  };
}

async function main() {
  const parsedProxy = parseProxy(DEFAULT_PROXY);

  console.log("[Camoufox] Launching Camoufox with profile WilsonYurcak691555...");
  const browser = await Camoufox({
    user_data_dir: profileDir,
    headless: false,
    os: "windows",
    humanize: true,
    proxy: parsedProxy,
    geoip: false,
  });

  const page = (browser.pages && browser.pages().length > 0) ? browser.pages()[0] : await browser.newPage();
  
  console.log("[Facebook] Navigating to https://www.facebook.com/...");
  await page.goto("https://www.facebook.com/", { waitUntil: "domcontentloaded", timeout: 35000 });

  const result = await createFacebookPage(page, randomPageName, randomBio);
  console.log("============================================================");
  console.log("PAGE CREATION FINISHED SUCCESSFULLY:");
  console.log(JSON.stringify(result, null, 2));
  console.log("============================================================");

  // Keep open for 5 minutes for user inspection
  await page.waitForTimeout(300000);
}

main().catch((err) => {
  console.error(`[Fatal Error]: ${err.stack || err}`);
  process.exit(1);
});
