#!/usr/bin/env node
/**
 * tools/open_fb_profile.mjs
 * =========================
 * Opens an existing Facebook profile in a visible Camoufox browser with proxy,
 * WebRTC protection, frozen persona seeds, and full frozen fingerprint.
 *
 * Usage:
 *   node tools/open_fb_profile.mjs
 *   node tools/open_fb_profile.mjs --profile BurleighVandall804767
 *   node tools/open_fb_profile.mjs --email BurleighVandall804767@outlook.in
 */

import fs from "node:fs";
import path from "node:path";
import crypto from "node:crypto";
import { execFileSync } from "node:child_process";

const CAMOUFOX_PATH = "file:///C:/Users/rudra/AppData/Roaming/npm/node_modules/camoufox-cli/node_modules/camoufox-js/dist/index.js";
const { Camoufox } = await import(CAMOUFOX_PATH);

const FP_GENERATOR_PATH = "file:///C:/Users/rudra/AppData/Roaming/npm/node_modules/camoufox-cli/node_modules/fingerprint-generator/index.mjs";
const { FingerprintGenerator } = await import(FP_GENERATOR_PATH);
const FP_GENERATOR = new FingerprintGenerator({ browsers: ["firefox"], operatingSystems: ["windows"] });

const CAMOUFOX_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:158.0) Gecko/20100101 Firefox/158.0";

// Verified Camoufox Windows GPU pool (from camoufox-js webgl_data.db)
const GPU_CONFIGURATIONS = [
  ["Google Inc. (NVIDIA)", "ANGLE (NVIDIA, NVIDIA GeForce GTX 980 Direct3D11 vs_5_0 ps_5_0), or similar"],
  ["Google Inc. (NVIDIA)", "ANGLE (NVIDIA, NVIDIA GeForce GTX 980 Direct3D11 vs_5_0 ps_5_0)"],
  ["Google Inc. (NVIDIA)", "ANGLE (NVIDIA, NVIDIA GeForce GTX 480 Direct3D11 vs_5_0 ps_5_0), or similar"],
  ["Google Inc. (NVIDIA)", "ANGLE (NVIDIA, NVIDIA GeForce GTX 480 Direct3D11 vs_5_0 ps_5_0)"],
  ["Google Inc. (NVIDIA)", "ANGLE (NVIDIA, NVIDIA GeForce 8800 GTX Direct3D11 vs_4_0 ps_4_0)"],
  ["Google Inc. (AMD)", "ANGLE (AMD, Radeon R9 200 Series Direct3D11 vs_5_0 ps_5_0), or similar"],
  ["Google Inc. (AMD)", "ANGLE (AMD, Radeon R9 200 Series Direct3D11 vs_5_0 ps_5_0)"],
  ["Google Inc. (AMD)", "ANGLE (AMD, Radeon HD 3200 Graphics Direct3D11 vs_5_0 ps_5_0), or similar"],
  ["Google Inc. (Intel)", "ANGLE (Intel, Intel(R) HD Graphics Direct3D11 vs_5_0 ps_5_0), or similar"],
  ["Google Inc. (Intel)", "ANGLE (Intel, Intel(R) HD Graphics Direct3D11 vs_5_0 ps_5_0)"],
  ["Google Inc. (Intel)", "ANGLE (Intel, Intel(R) HD Graphics 400 Direct3D11 vs_5_0 ps_5_0), or similar"],
  ["Google Inc. (Intel)", "ANGLE (Intel, Intel(R) HD Graphics Direct3D11 vs_4_1 ps_4_1), or similar"],
  ["Google Inc. (Intel)", "ANGLE (Intel, Intel(R) HD Graphics Direct3D11 vs_4_1 ps_4_1)"],
  ["Google Inc. (Intel)", "ANGLE (Intel, Intel(R) HD Graphics Direct3D11 vs_4_0 ps_4_0)"],
  ["Google Inc. (Intel)", "ANGLE (Intel, Intel 945GM Direct3D11 vs_4_0 ps_4_0)"],
];

const SCREEN_RESOLUTIONS = [
  { width: 1920, height: 1080 },
  { width: 1536, height: 864 },
  { width: 1440, height: 900 },
];

const args = process.argv.slice(2);
function getArg(name, def = null) {
  const i = args.indexOf(name);
  return i >= 0 && i + 1 < args.length ? args[i + 1] : def;
}

// Determine default profile from master Facebook accounts registry
let defaultProfile = "BurleighVandall804767";
const accountsFile = path.resolve("output", "facebook_registered_accounts.json");
if (fs.existsSync(accountsFile)) {
  try {
    const list = JSON.parse(fs.readFileSync(accountsFile, "utf-8"));
    if (Array.isArray(list) && list.length > 0) {
      const latest = list[list.length - 1];
      defaultProfile = latest.email ? latest.email.split("@")[0] : latest.username || defaultProfile;
    }
  } catch (e) { }
}

const rawProfile = getArg("--profile") || getArg("--email", defaultProfile);
const profileName = (rawProfile.includes("@") ? rawProfile.split("@")[0] : rawProfile).replace(/[^A-Za-z0-9._-]/g, "");
if (!profileName || profileName === "." || profileName === "..") {
  console.error(`[Facebook] Invalid profile name: ${rawProfile}`);
  process.exit(1);
}

const DEFAULT_PROXY = "customer-resi_c069a2c2-cc-in:15b+9UHzDZf+@pr.oxylabs.io:7777";
let proxyStr = getArg("--proxy");

function ensureStickyProxy(pStr, seed = null) {
  if (!pStr) return pStr;
  let clean = String(pStr).trim().replace(/^https?:\/\//i, "");
  if (!clean.includes("@")) return `http://${clean}`;
  const [auth, hostPort] = clean.split("@");
  let [username, password] = auth.split(":");
  if (!username) return `http://${clean}`;

  if (hostPort.includes("oxylabs.io") || username.startsWith("customer-")) {
    if (!username.includes("sessid") && !username.includes("session")) {
      const sessId = seed
        ? crypto.createHash("md5").update(String(seed)).digest("hex").slice(0, 8)
        : crypto.randomBytes(4).toString("hex");
      username = `${username}-sessid-${sessId}-sesstime-30`;
    }
  }
  return `http://${username}:${password}@${hostPort}`;
}

function parseProxy(str) {
  if (!str) return null;
  const clean = str.replace(/^https?:\/\//i, "");
  if (clean.includes("@")) {
    const [auth, hostPort] = clean.split("@");
    const [u, pass] = auth.split(":");
    return {
      server: `http://${hostPort}`,
      username: decodeURIComponent(u),
      password: decodeURIComponent(pass),
    };
  }
  return { server: `http://${clean}` };
}

const profilesRoot = path.resolve("output", "profiles facebook");
const profileDir = path.resolve(profilesRoot, profileName);
fs.mkdirSync(profileDir, { recursive: true });

// Check saved proxy in account_info.json or registry
if (!proxyStr) {
  const infoPath = path.join(profileDir, "account_info.json");
  if (fs.existsSync(infoPath)) {
    try {
      const info = JSON.parse(fs.readFileSync(infoPath, "utf-8"));
      if (typeof info.proxy_used === "string" && info.proxy_used.trim()) {
        proxyStr = info.proxy_used.trim();
        console.log(`[Facebook] Reusing proxy from account_info.json: ${proxyStr.replace(/^.*@/, "***@")}`);
      }
    } catch (e) { }
  }
}

if (!proxyStr && fs.existsSync(accountsFile)) {
  try {
    const list = JSON.parse(fs.readFileSync(accountsFile, "utf-8"));
    if (Array.isArray(list)) {
      const record = list.find((a) => {
        const stem = String(a && a.email ? a.email : "").split("@")[0].replace(/[^A-Za-z0-9._-]/g, "");
        return stem === profileName;
      });
      if (record && typeof record.proxy_used === "string" && record.proxy_used.trim()) {
        proxyStr = record.proxy_used.trim();
        console.log(`[Facebook] Reusing proxy from accounts registry: ${proxyStr.replace(/^.*@/, "***@")}`);
      }
    }
  } catch (e) { }
}

if (!proxyStr) {
  proxyStr = DEFAULT_PROXY;
}

const personaPath = path.join(profileDir, "persona.json");
let persona = null;
if (fs.existsSync(personaPath)) {
  try {
    persona = JSON.parse(fs.readFileSync(personaPath, "utf-8"));
  } catch (e) { }
}

const isGpuValid = Boolean(persona?.webgl_config) && GPU_CONFIGURATIONS.some(
  ([vendor, renderer]) => vendor === persona.webgl_config[0] && renderer === persona.webgl_config[1]
);

if (!persona || !persona["canvas:seed"] || !isGpuValid) {
  const previous = persona || {};
  const chosenGpu = isGpuValid ? previous.webgl_config : GPU_CONFIGURATIONS[crypto.randomInt(GPU_CONFIGURATIONS.length)];
  const chosenRes = previous.screen_resolution || SCREEN_RESOLUTIONS[crypto.randomInt(SCREEN_RESOLUTIONS.length)];
  persona = {
    "canvas:seed": previous["canvas:seed"] || crypto.randomInt(1, 4000000000),
    "audio:seed": previous["audio:seed"] || crypto.randomInt(1, 4000000000),
    "fonts:spacing_seed": previous["fonts:spacing_seed"] || crypto.randomInt(1, 4000000000),
    webgl_config: chosenGpu,
    screen_resolution: chosenRes,
  };
  fs.writeFileSync(personaPath, JSON.stringify(persona, null, 2));
}

const fingerprintPath = path.join(profileDir, "fingerprint.json");
let fingerprint = null;
if (fs.existsSync(fingerprintPath)) {
  try {
    const fp = JSON.parse(fs.readFileSync(fingerprintPath, "utf-8"));
    if (fp && fp.navigator && fp.screen) fingerprint = fp;
  } catch (e) { }
}
if (!fingerprint) {
  const scr = persona.screen_resolution;
  let generated = null;
  try {
    generated = FP_GENERATOR.getFingerprint({
      screen: { minWidth: scr.width, maxWidth: scr.width, minHeight: scr.height, maxHeight: scr.height },
      operatingSystems: ["windows"],
    }).fingerprint;
  } catch (e) { }
  if (!generated) {
    generated = FP_GENERATOR.getFingerprint({ operatingSystems: ["windows"] }).fingerprint;
  }
  fingerprint = generated;
  fs.writeFileSync(fingerprintPath, JSON.stringify(fingerprint, null, 2));
}

if (fingerprint && fingerprint.navigator) {
  fingerprint.navigator.userAgent = CAMOUFOX_UA;
  fingerprint.navigator.appVersion = "5.0 (Windows)";
}

const scr = persona.screen_resolution || fingerprint.screen || { width: 1920, height: 1080 };

console.log("============================================================");
console.log(`LAUNCHING FACEBOOK PROFILE: ${profileName}`);
console.log(`Profile Directory: ${profileDir}`);
console.log(`Frozen Persona:    Loaded (${personaPath})`);
console.log(`Frozen Fingerprint: Loaded (${fingerprintPath})`);
console.log(`WebRTC Protection: Active`);
console.log("============================================================");

if (fingerprint && fingerprint.headers) {
  fingerprint.headers["accept-language"] = "en-US,en;q=0.9";
}

// Seed Profile Aging: Bookmarks Toolbar, browsing history & visible UI
try {
  const agingScript = path.resolve("tools", "profile_aging.py");
  execFileSync("python", [agingScript, profileDir], { timeout: 10000 });
} catch (e) { }

const browserConfig = {
  user_data_dir: profileDir,
  headless: false,
  os: "windows",
  humanize: 0.85,
  block_webrtc: true,
  exclude_addons: ["UBO"],
  screen: { maxWidth: scr.width, maxHeight: scr.height },
  webgl_config: persona.webgl_config || undefined,
  proxy: parseProxy(ensureStickyProxy(proxyStr, profileName)),
  locale: "en-US",
  firefox_user_prefs: {
    "intl.accept_languages": "en-US, en",
    "javascript.use_us_english_locale": true,
    "browser.toolbars.bookmarks.visibility": "always",
    "browser.urlbar.suggest.bookmark": true,
    "browser.urlbar.suggest.history": true,
    "browser.urlbar.suggest.topsites": true,
  },
  geoip: true,
  fingerprint,
  i_know_what_im_doing: true,
  config: {
    "canvas:seed": persona["canvas:seed"],
    "audio:seed": persona["audio:seed"],
    "fonts:spacing_seed": persona["fonts:spacing_seed"],
    timezone: persona.timezone || "America/Chicago",
    "locale:region": "US",
    "locale:language": "en",
    "locale:all": "en-US, en",
  },
};

const browser = await Camoufox(browserConfig);
const context = (browser.contexts && browser.contexts().length > 0) ? browser.contexts()[0] : null;
if (context) {
  await context.addCookies([
    {
      name: "locale",
      value: "en_US",
      domain: ".facebook.com",
      path: "/",
    },
  ]).catch(() => {});
}
const page = (browser.pages && browser.pages().length > 0) ? browser.pages()[0] : await browser.newPage();
async function isFacebookSuspendedScreen(page) {
  try {
    const curUrl = page.url() || "";
    if (
      curUrl.includes("checkpoint/1501092823525282") ||
      curUrl.includes("/checkpoint/1501092823525282/") ||
      curUrl.includes("suspended")
    ) {
      return { isSuspended: true, url: curUrl, reason: "checkpoint_1501092823525282" };
    }
    const pageText = await page.evaluate(() => {
      const b = document.body;
      return b ? (b.innerText || "").slice(0, 4000).toLowerCase() : "";
    }).catch(() => "");
    if (
      pageText.includes("we suspended your account") ||
      pageText.includes("your account has been suspended") ||
      pageText.includes("you have 180 days to disagree") ||
      pageText.includes("account was suspended") ||
      pageText.includes("we disabled your account") ||
      pageText.includes("your account has been disabled") ||
      pageText.includes("account disabled") ||
      pageText.includes("disagree with decision")
    ) {
      return { isSuspended: true, url: curUrl, reason: "suspension_text_match" };
    }
  } catch (e) {}
  return { isSuspended: false, url: null, reason: null };
}

function markFacebookAccountSuspended(profileName, url, profileDir) {
  try {
    const regFile = path.resolve("output", "facebook_registered_accounts.json");
    if (fs.existsSync(regFile)) {
      const existing = JSON.parse(fs.readFileSync(regFile, "utf-8"));
      const target = (profileName || "").toLowerCase();
      const idx = existing.findIndex((item) => {
        const em = (item && item.email ? item.email : "").toLowerCase();
        const fn = (item && item.fullname ? item.fullname : "").toLowerCase();
        return em === target || fn === target;
      });
      if (idx >= 0) {
        existing[idx].status = "SUSPENDED";
        existing[idx].is_suspended = true;
        existing[idx].suspended_at = new Date().toISOString();
        existing[idx].suspension_url = url;
        fs.writeFileSync(regFile, JSON.stringify(existing, null, 2), "utf-8");
        console.log(`[Database] Updated account ${profileName} status to SUSPENDED in ${regFile}`);
      }
    }
    const infoPath = path.join(profileDir, "account_info.json");
    let info = {};
    if (fs.existsSync(infoPath)) {
      try { info = JSON.parse(fs.readFileSync(infoPath, "utf-8")); } catch (e) {}
    }
    info.status = "SUSPENDED";
    info.is_suspended = true;
    info.suspended_at = new Date().toISOString();
    info.suspension_url = url;
    fs.writeFileSync(infoPath, JSON.stringify(info, null, 2), "utf-8");
    console.log(`[Profile] Saved SUSPENDED state in ${infoPath}`);
  } catch (err) {
    console.warn(`[Database] Error updating suspended status: ${err.message}`);
  }
}

try {
  await page.goto("https://www.facebook.com/?locale=en_US", { waitUntil: "domcontentloaded", timeout: 45000 });
} catch (err) {
  console.warn(`[Navigation] Initial load note: ${err.message}. Retrying...`);
  await page.goto("https://www.facebook.com/?locale=en_US", { waitUntil: "domcontentloaded", timeout: 45000 }).catch(() => { });
}
await page.bringToFront().catch(() => { });

await page.waitForTimeout(2000);
const suspCheck = await isFacebookSuspendedScreen(page);
if (suspCheck.isSuspended) {
  console.error("=".repeat(65));
  console.error(`[Facebook] ⚠️ ACCOUNT SUSPENDED: Facebook is on suspension checkpoint ${suspCheck.url}`);
  console.error("=".repeat(65));
  markFacebookAccountSuspended(profileName, suspCheck.url, profileDir);
}

console.log("[Facebook] Profile is loaded and live on your screen.");
console.log("[Facebook] Close the browser window when you are done.");

await new Promise((resolve) => browser.on("close", resolve));
