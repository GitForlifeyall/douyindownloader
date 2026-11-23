#!/usr/bin/env node
/**
 * tools/douyin_login_cookie.mjs
 * =============================
 * Spawns a persistent anti-detect browser session for Douyin (抖音),
 * allowing you to log in, solve captchas, and automatically captures
 * and syncs your Douyin cookies directly into TikTokDownloader/Volume/settings.json.
 */

import fs from "node:fs";
import path from "node:path";
import readline from "node:readline";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const PROJECT_ROOT = path.resolve(__dirname, "..");
const PROFILE_DIR = path.resolve(PROJECT_ROOT, "output", "profiles", "douyin");
const SETTINGS_JSON = path.resolve(PROJECT_ROOT, "TikTokDownloader", "Volume", "settings.json");

// Import Camoufox
import { Camoufox } from "./node_modules/camoufox-js/dist/index.js";

async function main() {
  console.log("=".repeat(65));
  console.log("       DOUYIN PERSISTENT LOGIN & COOKIE SYNC TOOL");
  console.log("=".repeat(65));
  console.log(`[Profile] Storing browser session in: ${PROFILE_DIR}`);

  fs.mkdirSync(PROFILE_DIR, { recursive: true });

  // Clean stale lock files
  for (const lock of ["parent.lock", "lock", ".parentlock"]) {
    try {
      const p = path.join(PROFILE_DIR, lock);
      if (fs.existsSync(p)) fs.unlinkSync(p);
    } catch (e) { }
  }

  console.log("[Browser] Launching browser window for https://www.douyin.com/ ...");
  const context = await Camoufox({
    user_data_dir: PROFILE_DIR,
    headless: false,
    os: "windows",
    locale: "zh-CN",
    humanize: false,
    block_webrtc: false,
    i_know_what_im_doing: true,
    firefox_user_prefs: {
      "gfx.webrender.program-binary-disk": false,
      "intl.accept_languages": "zh-CN, zh, en-US, en",
      "browser.toolbars.bookmarks.visibility": "always",
    },
  });

  const page = (context.pages && context.pages().length > 0) ? context.pages()[0] : await context.newPage();
  await page.setViewportSize({ width: 1280, height: 850 }).catch(() => {});

  console.log("[Browser] Navigating to Douyin...");
  await page.goto("https://www.douyin.com/", { waitUntil: "domcontentloaded", timeout: 45000 }).catch(err => {
    console.warn(`[Navigation] Initial load note: ${err.message}`);
  });

  console.log("\n" + "=".repeat(65));
  console.log(">> PLEASE COMPLETE LOGIN ON THE BROWSER WINDOW <<");
  console.log("   - Log in using QR Code, SMS, or Password if required.");
  console.log("   - If you are already logged in or browse successfully,");
  console.log("     press ENTER in this terminal when ready to save cookies!");
  console.log("=".repeat(65) + "\n");

  const rl = readline.createInterface({
    input: process.stdin,
    output: process.stdout,
  });

  await new Promise(resolve => {
    rl.question("Press ENTER once you are logged in (or press Ctrl+C to abort)... ", () => {
      rl.close();
      resolve();
    });
  });

  console.log("\n[Cookies] Extracting Douyin cookies from browser session...");
  const cookies = await context.cookies([
    "https://www.douyin.com",
    "https://douyin.com",
    "https://live.douyin.com",
    "https://sso.douyin.com",
  ]);

  if (!cookies || cookies.length === 0) {
    console.error("[Cookies Error] No cookies detected! Please make sure the page loaded properly.");
    await context.close();
    process.exit(1);
  }

  // Filter cookies for douyin.com domains
  const douyinCookies = cookies.filter(c => c.domain.includes("douyin.com"));
  const cookieString = douyinCookies.map(c => `${c.name}=${c.value}`).join("; ");

  console.log(`[Cookies] Successfully captured ${douyinCookies.length} cookies.`);
  const keyTokens = ["passport_csrf_token", "ttwid", "sessionid", "sessionid_ss", "msToken", "odin_tt"];
  const foundTokens = keyTokens.filter(k => cookieString.includes(k));
  console.log(`[Cookies] Key tokens present: ${foundTokens.join(", ") || "None"}`);

  // Backup to JSON
  const backupJson = path.join(PROFILE_DIR, "cookies.json");
  fs.writeFileSync(backupJson, JSON.stringify(douyinCookies, null, 2), "utf-8");
  console.log(`[Cookies] Saved backup to: ${backupJson}`);

  // Write directly into TikTokDownloader/Volume/settings.json
  if (fs.existsSync(SETTINGS_JSON)) {
    try {
      const settings = JSON.parse(fs.readFileSync(SETTINGS_JSON, "utf-8"));
      settings.cookie = cookieString;
      fs.writeFileSync(SETTINGS_JSON, JSON.stringify(settings, null, 4), "utf-8");
      console.log(`[Settings] SUCCESS! Updated 'cookie' in ${SETTINGS_JSON}`);
    } catch (err) {
      console.error(`[Settings Error] Failed to write to settings.json: ${err.message}`);
    }
  } else {
    console.warn(`[Settings Warning] ${SETTINGS_JSON} not found. Saved to backup JSON only.`);
  }

  console.log("\n" + "=".repeat(65));
  console.log("✅ Douyin session and cookies successfully synced!");
  console.log("   You can now run: .\\.venv\\Scripts\\python.exe pipeline.py --url <douyin_url>");
  console.log("=".repeat(65) + "\n");

  await context.close();
}

main().catch(err => {
  console.error("FATAL ERROR:", err);
  process.exit(1);
});
