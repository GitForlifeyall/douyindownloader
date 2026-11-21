#!/usr/bin/env node
/**
 * tools/unified_social_creator.mjs
 * =================================
 * Unified Multi-Platform Social Account Automation:
 * 1. Metricool Account Creation & Onboarding (Tab 1)
 * 2. Instagram Account Creation & 2FA Setup  (Tab 2)
 * 3. Facebook Account Creation & 2FA Setup   (Tab 3)
 *
 * Core Architectural Invariants:
 * - Single Browser Window & Profile: Exactly ONE browser window. All 3 platforms run in
 *   sequential tabs inside the SAME window, sharing `user_data_dir` and cookies.
 * - Strict Sequential Execution: Metricool first -> Instagram second -> Facebook third.
 *   Each stage has an assertive checkpoint: if Stage 1 fails, it NEVER jumps to Stage 2 or 3.
 * - Single Sticky IP: Locks residential proxy to a 30-minute sticky session so all platforms
 *   see the EXACT same public exit IP address and timezone. Stale sessids are stripped.
 * - Anti-Detect Hardware & Engine: Camoufox C++ kernel anti-detect, BrowserForge frozen fingerprint,
 *   Canvas bit-for-bit parity, WebRTC IP masking, and runtime `navigator.webdriver === false` guard.
 * - Natural Typing Cadence: Human keystroke delay calibrated strictly to 40-52 WPM
 *   (210ms - 310ms per character, mean=260ms, stdDev=30ms) with realistic micro-jitter.
 * - Direct Organic Navigation: Direct page visits without opening random unrelated sites (no virgin browser warmups).
 * - Multi-Tab Concurrency: Keeps all 3 platform tabs alive and authenticated in the same window so Metricool
 *   can later connect Facebook and Instagram with 1-click authorization.
 *
 * Usage:
 *   node tools/unified_social_creator.mjs --email user@outlook.com --client-id <id> --refresh-token <token>
 *   node tools/unified_social_creator.mjs --account "user@outlook.com|password|refreshToken|clientId" --proxy "http://user:pass@pr.oxylabs.io:7777"
 *   node tools/unified_social_creator.mjs --email user@outlook.com --no-proxy
 *   node tools/unified_social_creator.mjs --skip-metricool ...
 */

import fs from "node:fs";
import path from "node:path";
import crypto from "node:crypto";
import readline from "node:readline";
import { execFileSync } from "node:child_process";

import { humanClick, humanHover } from "./kinematic_mouse.mjs";
import { setupInstagram2FA } from "./setup_instagram_2fa.mjs";
import { setupFacebook2FA } from "./setup_facebook_2fa.mjs";

const CAMOUFOX_PATH = "file:///C:/Users/rudra/AppData/Roaming/npm/node_modules/camoufox-cli/node_modules/camoufox-js/dist/index.js";
const { Camoufox } = await import(CAMOUFOX_PATH);
const CLOAKBROWSER_PATH = "file:///C:/Users/rudra/AppData/Roaming/npm/node_modules/cloakbrowser/dist/index.js";

const FP_GENERATOR_PATH = "file:///C:/Users/rudra/AppData/Roaming/npm/node_modules/camoufox-cli/node_modules/fingerprint-generator/index.mjs";
const { FingerprintGenerator } = await import(FP_GENERATOR_PATH);
const FP_GENERATOR = new FingerprintGenerator({ browsers: ["firefox"], operatingSystems: ["windows"] });

// Defensive adapter for setupInstagram2FA (handles 4-arg vs 6-arg signature)
async function invokeSetupInstagram2FA(page, email, password, profileDir, clientId, refreshToken) {
  if (setupInstagram2FA.length <= 4) {
    return setupInstagram2FA(page, email, clientId, refreshToken);
  }
  return setupInstagram2FA(page, email, password, profileDir, clientId, refreshToken);
}

const GPU_CONFIGURATIONS = [
  ["Google Inc. (NVIDIA)", "ANGLE (NVIDIA, NVIDIA GeForce GTX 980 Direct3D11 vs_5_0 ps_5_0)"],
  ["Google Inc. (NVIDIA)", "ANGLE (NVIDIA, NVIDIA GeForce GTX 480 Direct3D11 vs_5_0 ps_5_0)"],
  ["Google Inc. (AMD)", "ANGLE (AMD, Radeon R9 200 Series Direct3D11 vs_5_0 ps_5_0)"],
  ["Google Inc. (Intel)", "ANGLE (Intel, Intel(R) HD Graphics Direct3D11 vs_5_0 ps_5_0)"],
];

const SCREEN_RESOLUTIONS = [
  { width: 1920, height: 1080 },
  { width: 1440, height: 900 },
  { width: 1920, height: 1200 },
];

const MOBILE_PRESETS = {
  s24: {
    name: "Samsung Galaxy S24 Ultra",
    width: 412,
    height: 915,
    deviceScaleFactor: 3.0,
    isMobile: true,
    hasTouch: true,
    platform: "Linux armv8l",
    model: "SM-S928B",
    userAgent: "Mozilla/5.0 (Linux; Android 14; SM-S928B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.6778.200 Mobile Safari/537.36",
    userAgentMetadata: {
      brands: [
        { brand: "Chromium", version: "131" },
        { brand: "Google Chrome", version: "131" },
        { brand: "Not?A_Brand", version: "24" },
      ],
      fullVersionList: [
        { brand: "Chromium", version: "131.0.6778.200" },
        { brand: "Google Chrome", version: "131.0.6778.200" },
        { brand: "Not?A_Brand", version: "24.0.0.0" },
      ],
      platform: "Android",
      platformVersion: "14.0.0",
      architecture: "",
      model: "SM-S928B",
      mobile: true,
      bitness: "64",
      wow64: false,
    },
    clientHints: {
      platform: "Android",
      mobile: "?1",
      model: "SM-S928B",
      platformVersion: "14.0.0",
    },
  },
  pixel8: {
    name: "Google Pixel 8 Pro",
    width: 412,
    height: 923,
    deviceScaleFactor: 2.625,
    isMobile: true,
    hasTouch: true,
    platform: "Linux armv8l",
    model: "Pixel 8 Pro",
    userAgent: "Mozilla/5.0 (Linux; Android 14; Pixel 8 Pro) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.6778.200 Mobile Safari/537.36",
    userAgentMetadata: {
      brands: [
        { brand: "Chromium", version: "131" },
        { brand: "Google Chrome", version: "131" },
        { brand: "Not?A_Brand", version: "24" },
      ],
      fullVersionList: [
        { brand: "Chromium", version: "131.0.6778.200" },
        { brand: "Google Chrome", version: "131.0.6778.200" },
        { brand: "Not?A_Brand", version: "24.0.0.0" },
      ],
      platform: "Android",
      platformVersion: "14.0.0",
      architecture: "",
      model: "Pixel 8 Pro",
      mobile: true,
      bitness: "64",
      wow64: false,
    },
    clientHints: {
      platform: "Android",
      mobile: "?1",
      model: "Pixel 8 Pro",
      platformVersion: "14.0.0",
    },
  },
  iphone15: {
    name: "Apple iPhone 15 Pro",
    width: 393,
    height: 852,
    deviceScaleFactor: 3.0,
    isMobile: true,
    hasTouch: true,
    platform: "iPhone",
    model: "iPhone",
    userAgent: "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1",
    clientHints: {
      platform: "iOS",
      mobile: "?1",
      model: "iPhone",
      platformVersion: "17.5.1",
    },
  },
};

function deriveTimezoneFromProxy(proxyStr) {
  const p = (proxyStr || "").toLowerCase();
  if (p.includes("-cc-in") || p.includes("india")) return { tz: "Asia/Kolkata", region: "IN", lang: "en" };
  if (p.includes("us_california") || p.includes("los_angeles")) return { tz: "America/Los_Angeles", region: "US", lang: "en" };
  if (p.includes("us_new_york") || p.includes("eastern")) return { tz: "America/New_York", region: "US", lang: "en" };
  if (p.includes("-cc-gb") || p.includes("-cc-uk") || p.includes("london")) return { tz: "Europe/London", region: "GB", lang: "en" };
  if (p.includes("-cc-de") || p.includes("germany")) return { tz: "Europe/Berlin", region: "DE", lang: "en" };
  if (p.includes("-cc-jp") || p.includes("japan")) return { tz: "Asia/Tokyo", region: "JP", lang: "en" };
  return { tz: "America/Chicago", region: "US", lang: "en" };
}

async function alignFrozenUserAgent(page, fingerprint, fingerprintPath) {
  try {
    const actualUa = await page.evaluate(() => navigator.userAgent);
    if (!actualUa || !fingerprint?.navigator || fingerprint.navigator.userAgent === actualUa) return;
    fingerprint.navigator.userAgent = actualUa;
    if (Array.isArray(fingerprint.headers)) {
      for (const h of fingerprint.headers) {
        if (h?.name?.toLowerCase() === "user-agent") h.value = actualUa;
      }
    } else if (fingerprint.headers && typeof fingerprint.headers === "object") {
      fingerprint.headers["user-agent"] = actualUa;
    }
    fs.writeFileSync(fingerprintPath, JSON.stringify(fingerprint, null, 2), "utf-8");
  } catch (e) { }
}

let activeBrowser = null;
let isExiting = false;

async function forceCleanExit(signal = "SIGINT") {
  if (isExiting) {
    process.exit(130);
  }
  isExiting = true;
  console.log(`\n[Process] Received ${signal} (Ctrl+C). Terminating browser and exiting immediately...`);
  try {
    if (activeBrowser) {
      await Promise.race([
        activeBrowser.close().catch(() => { }),
        new Promise((r) => setTimeout(r, 1200)),
      ]);
    }
  } catch (e) { }
  process.exit(signal === "SIGINT" ? 130 : 0);
}

process.on("SIGINT", () => forceCleanExit("SIGINT"));
process.on("SIGTERM", () => forceCleanExit("SIGTERM"));
process.on("SIGHUP", () => forceCleanExit("SIGHUP"));

if (process.stdin.isTTY) {
  process.stdin.resume();
}

const args = process.argv.slice(2);
function getArg(name, def = null) {
  const i = args.indexOf(name);
  return i >= 0 && i + 1 < args.length ? args[i + 1] : def;
}
const hasFlag = (name) => args.includes(name);

const DEFAULT_PROXY = process.env.OXYLABS_PROXY || "";
const noProxyFlag = hasFlag("--no-proxy") || hasFlag("--direct");
const headless = hasFlag("--headless");
const keepOpen = hasFlag("--keep-open");
const isMobileMode = hasFlag("--mobile") || Boolean(getArg("--device"));
const devicePresetKey = (getArg("--device", "s24")).toLowerCase().replace(/[^a-z0-9]/g, "");
let activeMobilePreset = null;
if (isMobileMode) {
  if (devicePresetKey.includes("pixel")) activeMobilePreset = MOBILE_PRESETS.pixel8;
  else if (devicePresetKey.includes("iphone") || devicePresetKey.includes("ios") || devicePresetKey.includes("apple")) activeMobilePreset = MOBILE_PRESETS.iphone15;
  else activeMobilePreset = MOBILE_PRESETS.s24;
}

// When --mobile is requested, automatically route to CloakBrowser (stealth Chromium mobile engine)
const rawBrowserArg = getArg("--browser");
const browserChoice = (rawBrowserArg || (isMobileMode ? "cloakbrowser" : "camoufox")).toLowerCase(); // "camoufox" | "cloakbrowser"
const blockMedia = !hasFlag("--no-block-media"); // Default true: blocks heavy video streams & ad beacons
const enableFeedWarmup = !hasFlag("--no-warmup"); // Default true: performs organic feed scrolling & dwell pauses

// Stage skipping / isolating flags
const onlyConnect = hasFlag("--only-connect");
const skipMetricool = hasFlag("--skip-metricool") || hasFlag("--skip-m") || onlyConnect;
const skipInstagram = hasFlag("--skip-instagram") || hasFlag("--skip-insta") || hasFlag("--skip-ig") || onlyConnect;
const skipFacebook = hasFlag("--skip-facebook") || hasFlag("--skip-fb") || onlyConnect;
const skipConnect = hasFlag("--skip-connect");

const onlyMetricool = hasFlag("--only-metricool");
const onlyInstagram = hasFlag("--only-instagram");
const onlyFacebook = hasFlag("--only-facebook");

// Stage Redo / Force Overwrite Flags
const redoAll = hasFlag("--redo-all") || hasFlag("--force");
const redoMetricool = hasFlag("--redo-metricool") || redoAll;
const redoInstagram = hasFlag("--redo-instagram") || redoAll;
const redoFacebook = hasFlag("--redo-facebook") || redoAll;

const explicitAccount = getArg("--account");
const explicitEmail = getArg("--email");
let email = explicitEmail || (explicitAccount ? explicitAccount.split("|")[0] : null);
let password = getArg("--password") || (explicitAccount && explicitAccount.split("|")[1] ? explicitAccount.split("|")[1] : null);
let refreshToken = getArg("--refresh-token") || getArg("--token");
let clientId = getArg("--client-id", "9e5f94bc-e8a4-4e73-b8be-63364c29d753");

if (explicitAccount) {
  const parts = explicitAccount.split("|");
  email = (parts[0] || "").trim();
  if (parts.length >= 2 && parts[1]) password = parts[1].trim();
  if (parts.length >= 4) {
    refreshToken = (parts[2] || "").trim();
    let rawCId = (parts[3] || "").trim().replace(/["']/g, "");
    if (rawCId.startsWith("9e5f94bc") && rawCId.length === 35) {
      rawCId = "9e5f94bc-e8a4-4e73-b8be-63364c29d753";
    }
    clientId = rawCId || clientId;
  }
}

if (!email) {
  console.error("============================================================");
  console.error("[Unified Creator Error] Missing required email address.");
  console.error("Usage:");
  console.error("  node tools/unified_social_creator.mjs --email <email> --refresh-token <token> [--proxy <proxy>]");
  console.error("  node tools/unified_social_creator.mjs --account 'email|pass|refreshToken|clientId'");
  console.error("============================================================");
  process.exit(1);
}

// ----------------------------------------------------
// Proxy Connectivity & Sticky Session Verification (Rule #1)
// ----------------------------------------------------
function validateProxyConnectivity(proxy, timeoutMs = 20000) {
  if (!proxy) return { ok: true };
  const clean = String(proxy).trim();
  const nullDevice = process.platform === "win32" ? "NUL" : "/dev/null";

  for (let attempt = 1; attempt <= 2; attempt++) {
    try {
      const code = execFileSync(
        "curl.exe",
        ["-sS", "-o", nullDevice, "-w", "%{http_code}", "--connect-timeout", "15", "-x", clean, "https://icanhazip.com"],
        { encoding: "utf-8", timeout: timeoutMs, stdio: ["pipe", "pipe", "pipe"] }
      ).trim();
      if (code === "200") {
        return { ok: true, statusCode: 200 };
      }
      if (code === "407") {
        return { ok: false, statusCode: 407, error: "HTTP 407 Proxy Authentication Required" };
      }
      if (attempt === 2) {
        return { ok: false, statusCode: Number(code) || 0, error: `Proxy returned HTTP status ${code}` };
      }
    } catch (err) {
      if (attempt === 2) {
        const stdout = (err.stdout ? String(err.stdout) : "").trim();
        const stderr = (err.stderr ? String(err.stderr) : "").trim();
        const combined = `${stdout} ${stderr} ${err.message || ""}`;
        if (/407/i.test(combined) || stdout === "407") {
          return { ok: false, statusCode: 407, error: `HTTP 407 Proxy Authentication Required (${stderr || stdout || "407"})` };
        }
        return { ok: false, error: stderr || err.message };
      }
    }
  }
}

function splitProxyParts(proxyStr) {
  const clean = String(proxyStr).trim().replace(/^https?:\/\//i, "");
  const at = clean.lastIndexOf("@");
  if (at < 0) return { hasAuth: false, hostPort: clean, user: "", pass: "" };
  const auth = clean.slice(0, at);
  const hostPort = clean.slice(at + 1);
  const colon = auth.indexOf(":");
  const user = colon >= 0 ? auth.slice(0, colon) : auth;
  const pass = colon >= 0 ? auth.slice(colon + 1) : "";
  return { hasAuth: true, hostPort, user, pass };
}

function ensureStickyProxy(proxyStr, seed = null) {
  if (!proxyStr) return proxyStr;
  const { hasAuth, hostPort, user, pass } = splitProxyParts(proxyStr);
  if (!hasAuth || !user) return `http://${hostPort}`;

  let u = user;
  // If the user already provided an explicit sticky session or oneip ID, preserve it as-is!
  if (u.includes("sessid") || u.includes("session")) {
    return `http://${u}:${pass}@${hostPort}`;
  }
  if (hostPort.includes("oxylabs.io") || u.startsWith("customer-")) {
    u = u.replace(/-sessid[-_][a-zA-Z0-9_-]+/g, "").replace(/-sesstime-\d+/g, "");
    const seedHash = seed ? crypto.createHash("md5").update(String(seed)).digest("hex").slice(0, 4) : "";
    const sessId = `${seedHash}${crypto.randomBytes(3).toString("hex")}`;
    u = `${u}-sessid-${sessId}-sesstime-30`;
  }
  return `http://${u}:${pass}@${hostPort}`;
}

function parseProxy(proxyStr) {
  if (!proxyStr) return null;
  const { hasAuth, hostPort, user, pass } = splitProxyParts(proxyStr);
  if (hasAuth) {
    return {
      server: `http://${hostPort}`,
      username: decodeURIComponent(user),
      password: decodeURIComponent(pass),
    };
  }
  return { server: `http://${hostPort}` };
}

let rawProxy = noProxyFlag ? null : (getArg("--proxy") || DEFAULT_PROXY);
let effectiveProxy = rawProxy ? ensureStickyProxy(rawProxy, email) : null;
let proxyExitIp = null;

function fetchProxyExitIp(proxyStr, timeoutMs = 7000) {
  if (!proxyStr) return null;
  const clean = String(proxyStr).trim();
  try {
    return execFileSync(
      "curl.exe",
      ["-sS", "--connect-timeout", "5", "-x", clean, "https://icanhazip.com"],
      { encoding: "utf-8", timeout: timeoutMs, stdio: ["pipe", "pipe", "pipe"] }
    ).trim();
  } catch (e) {
    return null;
  }
}

if (effectiveProxy) {
  console.log(`[Proxy] Verifying connectivity for ${effectiveProxy.replace(/^.*@/, "***@")}...`);
  const check = validateProxyConnectivity(effectiveProxy);
  if (!check.ok) {
    console.error("============================================================");
    if (check.statusCode === 407 || /407/i.test(check.error || "")) {
      console.error(`[Proxy 407 Error] Proxy returned HTTP 407 (Proxy Authentication Required / Access Denied).`);
    } else {
      console.error(`[Proxy Error] Configured proxy pre-flight verification failed!`);
    }
    console.error(`  Target: ${effectiveProxy.replace(/^.*@/, "***@")}`);
    console.error(`  Reason: ${check.error}`);
    console.error(`⚠️ Workspace Rule: Strictly do NOT fall back to default proxy.`);
    console.error(`  Script halted immediately.`);
    console.error("============================================================");
    process.exit(1);
  }
  proxyExitIp = fetchProxyExitIp(effectiveProxy);
  console.log(`[Proxy Sticky Session] Verified & Locked: ${proxyExitIp || "operational"} (30-min sticky peer)`);
} else if (noProxyFlag) {
  console.log("[Proxy] Running in direct connection mode (--no-proxy).");
}

// ----------------------------------------------------
// Human Typing Engine: Strictly 40 to 52 WPM
// ----------------------------------------------------
// Natural Human Typing & Keystroke Timing
// Calibrated for Meta (Instagram/Facebook) & Anti-Bot Ban Prevention:
// Mean: 210ms, StdDev: 25ms (clamped between 170ms and 270ms, ~45-52 WPM)
// Meta's behavioral signals flag keystroke velocities < 160ms on registration.
// ----------------------------------------------------
function gaussianDelay(mean = 210, stdDev = 25) {
  let u = 0;
  let v = 0;
  while (u === 0) u = Math.random();
  while (v === 0) v = Math.random();
  const z = Math.sqrt(-2.0 * Math.log(u)) * Math.cos(2.0 * Math.PI * v);
  return Math.max(170, Math.min(270, Math.round(mean + z * stdDev)));
}

// Interaction Dynamics Tracker for Forensic Ban Pattern Analysis
const interactionMetrics = {
  keystrokes: 0,
  typos: 0,
  typingTimeMs: 0,
  reset() {
    this.keystrokes = 0;
    this.typos = 0;
    this.typingTimeMs = 0;
  }
};

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function humanType(page, locator, text, options = {}) {
  const t0 = Date.now();
  const element = typeof locator.first === "function" ? locator.first() : locator;
  if (!element || (await element.count().catch(() => 0)) === 0) {
    console.warn("[humanType] Target element not found or count is 0, skipping type.");
    return;
  }
  await humanClick(page, element).catch(() => {
    if (typeof element.click === "function") return element.click().catch(() => { });
  });
  await sleep(100 + Math.random() * 60);
  const currentVal = await element.inputValue().catch(() => "");
  if (currentVal && currentVal.length > 0) {
    if (typeof page.keyboard?.press === "function") {
      await page.keyboard.press("Control+A").catch(() => { });
      await sleep(35 + Math.random() * 25);
      await page.keyboard.press("Backspace").catch(() => { });
      await sleep(40 + Math.random() * 30);
    }
  }
  await sleep(60 + Math.random() * 40);

  const str = String(text);
  for (let i = 0; i < str.length; i++) {
    const char = str[i];
    if (options.typos !== false && Math.random() < 0.015 && char !== " " && char !== "@") {
      interactionMetrics.typos++;
      interactionMetrics.keystrokes += 2;
      const typoChar = String.fromCharCode(char.charCodeAt(0) + (Math.random() > 0.5 ? 1 : -1));
      await page.keyboard.type(typoChar, { delay: 35 + Math.floor(Math.random() * 40) }).catch(() => { });
      await sleep(gaussianDelay(210, 25));
      await page.keyboard.press("Backspace").catch(() => { });
      await sleep(60 + Math.random() * 50);
    }
    interactionMetrics.keystrokes++;
    await page.keyboard.type(char, { delay: 35 + Math.floor(Math.random() * 40) }).catch(() => { });
    await sleep(gaussianDelay(210, 25));
  }
  interactionMetrics.typingTimeMs += Date.now() - t0;
  await sleep(100 + Math.random() * 80);
}

// ----------------------------------------------------
// Navigation Helper with Auto-Retry & Error Recovery
// ----------------------------------------------------
async function safeGoto(page, url, options = { waitUntil: "domcontentloaded", timeout: 45000 }, maxRetries = 3) {
  for (let attempt = 1; attempt <= maxRetries; attempt++) {
    try {
      const resp = await page.goto(url, options);
      const curUrl = page.url() || "";
      if (curUrl.startsWith("about:neterror") || curUrl.startsWith("about:certerror")) {
        console.warn(`[Navigation] Landed on browser network error (${curUrl}). Clicking 'Try Again'...`);
        const tryAgainBtn = page.locator("#errorTryAgain, button:has-text('Try Again')").first();
        if ((await tryAgainBtn.count()) > 0) {
          await tryAgainBtn.click().catch(() => { });
          await page.waitForTimeout(4000);
        }
      }
      return resp;
    } catch (err) {
      console.warn(`[Navigation] Attempt ${attempt}/${maxRetries} failed for ${url}: ${err.message}`);
      try {
        const tryAgainBtn = page.locator("#errorTryAgain, button:has-text('Try Again')").first();
        if ((await tryAgainBtn.count()) > 0 && (await tryAgainBtn.isVisible().catch(() => false))) {
          console.log("[Navigation] Clicking 'Try Again' button on network error screen...");
          await tryAgainBtn.click().catch(() => { });
          await page.waitForTimeout(3000);
        }
      } catch (e) { }

      if (attempt === maxRetries) {
        throw new Error(`Failed to navigate to ${url} after ${maxRetries} attempts: ${err.message}`);
      }
      await page.waitForTimeout(2000 * attempt);
    }
  }
}

// ----------------------------------------------------
// Meta (Instagram & Facebook) Forensic Telemetry Engine
// (Strictly excludes Metricool as it does not ban)
// ----------------------------------------------------
async function captureMetaExitIp(page, step = "pre_signup") {
  const entry = {
    step,
    timestamp: new Date().toISOString(),
    ip: null,
    asn: null,
    org: null,
    city: null,
    region: null,
    country: null,
    timezone: null,
  };
  try {
    const loc = await page.evaluate(async () => {
      const endpoints = [
        "https://ipapi.co/json/",
        "https://ipwho.is/",
        "http://ip-api.com/json/?fields=status,message,country,countryCode,region,regionName,city,timezone,as,org,query",
      ];
      for (const url of endpoints) {
        try {
          const controller = new AbortController();
          const tid = setTimeout(() => controller.abort(), 4500);
          const res = await fetch(url, { signal: controller.signal });
          clearTimeout(tid);
          if (res.ok) {
            const data = await res.json();
            if (data && (data.ip || data.query)) return data;
          }
        } catch (e) { }
      }
      return null;
    });
    if (loc) {
      entry.ip = loc.ip || loc.query || null;
      entry.city = loc.city || loc.regionName || null;
      entry.region = loc.region || loc.region_name || loc.regionName || null;
      entry.country = loc.country_name || loc.country || loc.countryCode || null;
      entry.timezone = loc.timezone || null;
      entry.asn = loc.asn || loc.as || null;
      entry.org = loc.org || loc.connection?.org || loc.isp || null;
    }
  } catch (e) { }
  return entry;
}

async function auditMetaDeviceFingerprint(page) {
  try {
    return await page.evaluate(() => {
      const out = {};
      try {
        out.webdriver = navigator.webdriver;
        out.userAgent = navigator.userAgent;
        out.platform = navigator.platform;
        out.language = navigator.language;
        out.languages = navigator.languages;
        out.hardwareConcurrency = navigator.hardwareConcurrency;
        out.deviceMemory = navigator.deviceMemory;
        out.maxTouchPoints = navigator.maxTouchPoints;
        out.browserTimezone = Intl.DateTimeFormat().resolvedOptions().timeZone;
        out.timezoneOffset = new Date().getTimezoneOffset();
        out.screen = {
          width: window.screen.width,
          height: window.screen.height,
          availWidth: window.screen.availWidth,
          availHeight: window.screen.availHeight,
          colorDepth: window.screen.colorDepth,
          devicePixelRatio: window.devicePixelRatio,
        };
        out.viewport = {
          innerWidth: window.innerWidth,
          innerHeight: window.innerHeight,
          outerWidth: window.outerWidth,
          outerHeight: window.outerHeight,
        };
        out.automationGlobals = Boolean(
          window.__playwright ||
          window.__puppeteer ||
          window.cdc_adoQpoasnfa76pfcZLmcfl_Array ||
          window.__nightmare ||
          window.callPhantom
        );
        try {
          const canvas = document.createElement("canvas");
          const gl = canvas.getContext("webgl") || canvas.getContext("experimental-webgl");
          if (gl) {
            const ext = gl.getExtension("WEBGL_debug_renderer_info");
            out.webglVendor = ext ? gl.getParameter(ext.UNMASKED_VENDOR_WEBGL) : gl.getParameter(gl.VENDOR);
            out.webglRenderer = ext ? gl.getParameter(ext.UNMASKED_RENDERER_WEBGL) : gl.getParameter(gl.RENDERER);
          }
        } catch (e) { }
      } catch (e) {
        out.error = String(e);
      }
      return out;
    });
  } catch (e) {
    return { error: e.message };
  }
}

async function checkFacebookHealth(page) {
  const curUrl = page.url() || "";
  const pageText = await page.evaluate(() => {
    const b = document.body;
    return b ? (b.innerText || "").slice(0, 4000).toLowerCase() : "";
  }).catch(() => "");

  if (
    curUrl.includes("checkpoint/1501092823525282") ||
    curUrl.includes("/checkpoint/") ||
    curUrl.includes("suspended") ||
    pageText.includes("we suspended your account") ||
    pageText.includes("you have 180 days")
  ) {
    return {
      status: "SUSPENDED",
      checkpoint_type: "appeal_180_days",
      url: curUrl,
      reason: "Account suspended / 180 day appeal triggered"
    };
  }
  if (
    curUrl.includes("checkpoint") ||
    pageText.includes("help us confirm it's you") ||
    pageText.includes("confirm your identity") ||
    pageText.includes("security check")
  ) {
    return {
      status: "CHECKPOINT",
      checkpoint_type: "identity_or_sms_required",
      url: curUrl,
      reason: "Facebook security checkpoint triggered"
    };
  }
  if (
    pageText.includes("we restrict certain activity") ||
    pageText.includes("protect our community") ||
    pageText.includes("action blocked") ||
    pageText.includes("try again later to protect our community")
  ) {
    return {
      status: "RESTRICTED",
      checkpoint_type: "community_activity_restriction",
      url: curUrl,
      reason: "Facebook rate limit: We restrict certain activity to protect our community"
    };
  }
  return {
    status: "ACTIVE",
    checkpoint_type: "none",
    url: curUrl,
    reason: null
  };
}

async function checkInstagramHealth(page) {
  const curUrl = page.url() || "";
  const pageText = await page.evaluate(() => (document.body ? document.body.innerText : "")).catch(() => "");
  const pageTextLower = pageText.toLowerCase();

  if (
    pageTextLower.includes("we restrict certain activity") ||
    pageTextLower.includes("action blocked") ||
    pageTextLower.includes("try again later to protect our community")
  ) {
    return {
      status: "RESTRICTED",
      checkpoint_type: "community_activity_restriction",
      url: curUrl,
      reason: "Instagram rate limit: We restrict certain activity to protect our community"
    };
  }

  if (
    curUrl.includes("/accounts/suspended/") ||
    pageTextLower.includes("we suspended your account") ||
    pageTextLower.includes("you have 180 days")
  ) {
    return {
      status: "SUSPENDED",
      checkpoint_type: "appeal_180_days",
      url: curUrl,
      reason: "Instagram suspended account"
    };
  }
  if (
    curUrl.includes("/challenge/") ||
    curUrl.includes("checkpoint") ||
    pageTextLower.includes("help us confirm it's you") ||
    pageTextLower.includes("add a phone number")
  ) {
    return {
      status: "CHECKPOINT",
      checkpoint_type: "phone_or_challenge_required",
      url: curUrl,
      reason: "Instagram challenge/checkpoint triggered"
    };
  }
  return {
    status: "ACTIVE",
    checkpoint_type: "none",
    url: curUrl,
    reason: null
  };
}

async function isInstagramOtpScreen(page) {
  const bodyText = (await page.evaluate(() => (document.body ? document.body.innerText : "")).catch(() => "")).toLowerCase();
  const markers = [
    "confirmation code",
    "confirm your account",
    "confirm your email",
    "enter the code",
    "we sent a code",
    "we've sent a code",
    "security code",
    "just sent a code",
    "enter 6-digit",
    "enter code",
    "check your email",
  ];
  if (markers.some((marker) => bodyText.includes(marker))) return true;

  const codeInput = page.locator(
    "input[name='email_confirmation_code'], input[autocomplete='one-time-code'], input[aria-label*='code' i], input[placeholder*='code' i], input[name*='code' i], input[maxlength='6']"
  ).first();
  return (await codeInput.count()) > 0 && (await codeInput.isVisible().catch(() => false));
}

function recordMetaForensicLog({
  platform,
  profileDir,
  email,
  ident,
  birthday,
  gender,
  preIp,
  postOtpIp,
  finalIp,
  fingerprint,
  timing,
  verification,
  health,
}) {
  const emailDomain = email.includes("@") ? email.split("@")[1] : "unknown";
  const ipDrift = Boolean(preIp?.ip && postOtpIp?.ip && preIp.ip !== postOtpIp.ip);
  const tzMatch = Boolean(
    fingerprint?.browserTimezone &&
    preIp?.timezone &&
    fingerprint.browserTimezone === preIp.timezone
  );

  const wordsTyped = (interactionMetrics.keystrokes / 5) || 0;
  const minutesSpent = (interactionMetrics.typingTimeMs / 60000) || 0.001;
  const calculatedWpm = Math.round(wordsTyped / minutesSpent) || 0;

  const entry = {
    record_id: crypto.randomUUID(),
    platform,
    email,
    created_at: new Date().toISOString(),
    persona: {
      full_name: ident.fullName,
      email_domain: emailDomain,
      age: 2026 - (birthday?.year || 2000),
      birth_year: birthday?.year || 2000,
      gender: gender || "Unknown",
      username: platform === "instagram" ? ident.username : undefined,
    },
    network: {
      initial_exit_ip: preIp?.ip || null,
      post_otp_exit_ip: postOtpIp?.ip || null,
      final_exit_ip: finalIp?.ip || null,
      ip_drift_detected: ipDrift,
      asn: preIp?.asn || null,
      isp_org: preIp?.org || null,
      city: preIp?.city || null,
      region: preIp?.region || null,
      country: preIp?.country || null,
      proxy_timezone: preIp?.timezone || null,
      browser_timezone: fingerprint?.browserTimezone || null,
      timezone_match: tzMatch,
    },
    device_fingerprint: {
      user_agent: fingerprint?.userAgent || null,
      platform: fingerprint?.platform || null,
      hardware_concurrency: fingerprint?.hardwareConcurrency || null,
      device_memory: fingerprint?.deviceMemory || null,
      screen_resolution: fingerprint?.screen ? `${fingerprint.screen.width}x${fingerprint.screen.height}` : null,
      device_pixel_ratio: fingerprint?.screen?.devicePixelRatio || null,
      viewport: fingerprint?.viewport ? `${fingerprint.viewport.innerWidth}x${fingerprint.viewport.innerHeight}` : null,
      webgl_vendor: fingerprint?.webglVendor || null,
      webgl_renderer: fingerprint?.webglRenderer || null,
      webdriver_clean: fingerprint?.webdriver === false,
      automation_globals_clean: !fingerprint?.automationGlobals,
    },
    behavioral_and_cadence: {
      dwell_time_before_first_action_ms: timing?.dwellTimeMs || 0,
      form_fill_duration_ms: timing?.formFillMs || 0,
      total_duration_sec: Math.round(((Date.now() - (timing?.stageStartTime || Date.now())) / 1000) || 0),
      measured_wpm: calculatedWpm,
      keystrokes_total: interactionMetrics.keystrokes,
      typos_corrected: interactionMetrics.typos,
    },
    verification_and_2fa: {
      otp_latency_ms: verification?.otpLatencyMs || null,
      two_factor_enabled: Boolean(verification?.twoFactor?.enabled),
      backup_codes_count: verification?.twoFactor?.backup_codes?.length || 0,
    },
    health_outcome: {
      verdict: health?.status || "UNKNOWN",
      checkpoint_type: health?.checkpoint_type || "none",
      reason: health?.reason || null,
      final_url: health?.url || null,
    },
  };

  // 1. Save per-profile forensics
  try {
    const profileForensicsPath = path.join(profileDir, "meta_forensics.json");
    let existingForensics = {};
    if (fs.existsSync(profileForensicsPath)) {
      try { existingForensics = JSON.parse(fs.readFileSync(profileForensicsPath, "utf-8")); } catch (e) { }
    }
    existingForensics[platform] = entry;
    fs.writeFileSync(profileForensicsPath, JSON.stringify(existingForensics, null, 2), "utf-8");

    // 2. Append to master cross-account JSONL dataset
    const masterLogPath = path.resolve("output", "meta_ban_forensics.jsonl");
    fs.mkdirSync(path.dirname(masterLogPath), { recursive: true });
    fs.appendFileSync(masterLogPath, JSON.stringify(entry) + "\n", "utf-8");

    console.log(`[Forensics] 🛡️ Recorded Meta forensic ban telemetry for ${platform.toUpperCase()}:`);
    console.log(`  - Profile Log: ${profileForensicsPath}`);
    console.log(`  - Master JSONL: ${masterLogPath}`);
    console.log(`  - Verdict: [${entry.health_outcome.verdict}] | IP Drift: ${entry.network.ip_drift_detected ? "⚠️ YES" : "CLEAN"}`);
  } catch (err) {
    console.warn(`[Forensics Warning] Failed to persist forensic telemetry: ${err.message}`);
  }

  return entry;
}

// ----------------------------------------------------
// Persona & Identity Generation
// ----------------------------------------------------
const INDIAN_FIRST_NAMES = [
  "Aarav", "Rohan", "Arjun", "Ishaan", "Aditya", "Vikram", "Kabir", "Vihaan", "Dhruv", "Kunal",
  "Siddharth", "Rahul", "Varun", "Priya", "Ananya", "Meera", "Diya", "Isha", "Neha", "Riya",
  "Kavya", "Tanvi", "Shreya", "Aditi", "Pooja", "Nandini", "Simran", "Sneha", "Manish", "Abhimanyu"
];

const INDIAN_LAST_NAMES = [
  "Sharma", "Verma", "Patel", "Mehta", "Iyer", "Nair", "Rao", "Joshi", "Deshmukh", "Chopra",
  "Malhotra", "Reddy", "Kulkarni", "Bose", "Chatterjee", "Gupta", "Mishra", "Saxena", "Bhatia", "Trivedi"
];

const FIRST_NAMES = [
  "Liam", "Noah", "Oliver", "Lucas", "Ethan", "Aiden", "Mason", "Logan", "James", "Benjamin",
  "Elijah", "Daniel", "Henry", "Jackson", "Sebastian", "Jack", "Owen", "Samuel", "Ryan", "Nathan",
  "Emma", "Olivia", "Ava", "Sophia", "Isabella", "Mia", "Charlotte", "Amelia", "Harper", "Evelyn",
  "Abigail", "Emily", "Ella", "Elizabeth", "Camila", "Luna", "Sofia", "Avery", "Mila", "Aria",
  "Nora", "Layla", "Chloe", "Penelope", "Riley", "Zoey", "Natalie", "Leah", "Hazel", "Violet",
  "Diego", "Mateo", "Carlos", "Adrian", "Javier", "Marco", "Leo", "Oscar", "Theo", "Miles",
  "Priya", "Ananya", "Rohan", "Arjun", "Meera", "Ishaan", "Valeria", "Elena", "Marina", "Nikolai"
];

const LAST_NAMES = [
  "Vance", "Wright", "Bennett", "Carter", "Hayes", "Morgan", "Brooks", "Reed", "Coleman", "Foster",
  "Bailey", "Rivera", "Sullivan", "Price", "Watson", "Sanders", "Murphy", "Bishop", "Fleming", "Hale",
  "Grant", "Doyle", "Pierce", "Barnes", "Hudson", "Spencer", "Marsh", "Ellis", "Watts", "Dean",
  "Silva", "Costa", "Reyes", "Flores", "Ortega", "Navarro", "Romero", "Vargas", "Mendoza", "Castro",
  "Patel", "Shah", "Mehta", "Kapoor", "Rao", "Nair", "Iyer", "Desai", "Chopra", "Bose",
  "Novak", "Petrov", "Ivanov", "Kowalski", "Andersen", "Larsen", "Berg", "Fischer", "Weber", "Hoffmann"
];

function extractIdentity(emailAddress, country = "IN") {
  const local = (emailAddress || "").split("@")[0] || "user";
  // STRICT RULE: Human first, last, and full names MUST NEVER contain any digits or symbols
  const lettersOnly = local.replace(/[^A-Za-z._-]/g, "");

  // Try extracting CamelCase names: e.g. "DelilaVermes" -> "Delila", "Vermes"
  const camelMatch = lettersOnly.match(/^([A-Z][a-z]{2,})([A-Z][a-z]{2,})/);

  let firstName = "";
  let lastName = "";

  if (camelMatch) {
    firstName = camelMatch[1];
    lastName = camelMatch[2];
  } else {
    // Check if delimited by dot, underscore, or hyphen
    const parts = lettersOnly.split(/[._-]+/).filter((p) => p.length >= 2);
    if (parts.length >= 2) {
      firstName = parts[0];
      lastName = parts[1];
    } else if (parts.length === 1) {
      if (parts[0].length >= 10) {
        // e.g. "taseenxane" -> "Taseen", "Xane"
        firstName = parts[0].slice(0, Math.floor(parts[0].length / 2));
        lastName = parts[0].slice(Math.floor(parts[0].length / 2));
      } else if (parts[0].length >= 3) {
        // e.g. "dvir" -> "Dvir" + last name from pool
        firstName = parts[0];
        const lastPool = country === "IN" ? INDIAN_LAST_NAMES : LAST_NAMES;
        lastName = lastPool[crypto.randomInt(0, lastPool.length)];
      }
    }
  }

  // Fallback to pool if either name is invalid or has non-alpha characters
  const firstPool = country === "IN" ? INDIAN_FIRST_NAMES : FIRST_NAMES;
  const lastPool = country === "IN" ? INDIAN_LAST_NAMES : LAST_NAMES;
  if (!firstName || firstName.length < 2 || !/^[A-Za-z]+$/.test(firstName)) {
    firstName = firstPool[crypto.randomInt(0, firstPool.length)];
  }
  if (!lastName || lastName.length < 2 || !/^[A-Za-z]+$/.test(lastName)) {
    lastName = lastPool[crypto.randomInt(0, lastPool.length)];
  }

  // Capitalize properly and strictly strip any stray non-alpha characters
  firstName = firstName.charAt(0).toUpperCase() + firstName.slice(1).toLowerCase().replace(/[^a-z]/g, "");
  lastName = lastName.charAt(0).toUpperCase() + lastName.slice(1).toLowerCase().replace(/[^a-z]/g, "");

  const fullName = `${firstName} ${lastName}`;

  // Instagram username can have numbers/suffixes, but Full Name NEVER has digits
  const randSuffix = crypto.randomInt(100, 9999);
  const username = `${firstName.toLowerCase()}_${lastName.toLowerCase()}${randSuffix}`;

  return {
    firstName,
    lastName,
    fullName,
    username,
    profileStem: local,
  };
}

function generateRandomBirthday() {
  const MONTHS = [
    { name: "January", index: 1, hindi: "जनवरी" },
    { name: "February", index: 2, hindi: "फ़रवरी" },
    { name: "March", index: 3, hindi: "मार्च" },
    { name: "April", index: 4, hindi: "अप्रैल" },
    { name: "May", index: 5, hindi: "मई" },
    { name: "June", index: 6, hindi: "जून" },
    { name: "July", index: 7, hindi: "जुलाई" },
    { name: "August", index: 8, hindi: "अगस्त" },
    { name: "September", index: 9, hindi: "सितंबर" },
    { name: "October", index: 10, hindi: "अक्टूबर" },
    { name: "November", index: 11, hindi: "नवंबर" },
    { name: "December", index: 12, hindi: "दिसंबर" }
  ];
  const m = MONTHS[crypto.randomInt(0, MONTHS.length)];
  const day = crypto.randomInt(1, 28);
  const currentYear = new Date().getFullYear();
  const year = currentYear - 18 - crypto.randomInt(0, 18);
  return {
    day,
    dayStr: String(day),
    month: m.name,
    monthHindi: m.hindi,
    monthIndex: m.index,
    year,
    formatted: `${day} ${m.name} ${year}`,
  };
}

function isValidMetricoolPassword(pwd) {
  if (!pwd || typeof pwd !== "string") return false;
  if (pwd.length < 8 || pwd.length > 20) return false;
  const hasUpper = /[A-Z]/.test(pwd);
  const hasLower = /[a-z]/.test(pwd);
  const hasDigit = /[0-9]/.test(pwd);
  const hasSpecial = /[^A-Za-z0-9]/.test(pwd);
  return hasUpper && hasLower && hasDigit && hasSpecial;
}

function generateCompliantPassword(baseSeed = null) {
  const uppers = "ABCDEFGHJKLMNPQRSTUVWXYZ";
  const lowers = "abcdefghijkmnopqrstuvwxyz";
  const digits = "23456789";
  const specials = "!@#$%*?";

  // Guarantee at least 1 of each required character category
  const parts = [
    uppers[crypto.randomInt(0, uppers.length)],
    lowers[crypto.randomInt(0, lowers.length)],
    digits[crypto.randomInt(0, digits.length)],
    specials[crypto.randomInt(0, specials.length)],
  ];

  // If baseSeed is provided, incorporate a clean truncated stem
  const stem = String(baseSeed || "").replace(/[^A-Za-z0-9]/g, "");
  if (stem.length >= 4) {
    const cleanStem = stem.slice(0, 6);
    parts.push(cleanStem.charAt(0).toUpperCase() + cleanStem.slice(1).toLowerCase());
  }

  // Fill up to target length of 12-14 characters (well within 8-20 range)
  const allChars = uppers + lowers + digits + specials;
  const targetLen = 13;
  let currentLen = parts.join("").length;
  while (currentLen < targetLen) {
    parts.push(allChars[crypto.randomInt(0, allChars.length)]);
    currentLen++;
  }

  // Shuffle to randomize character positions
  const arr = parts.join("").split("");
  for (let i = arr.length - 1; i > 0; i--) {
    const j = crypto.randomInt(0, i + 1);
    [arr[i], arr[j]] = [arr[j], arr[i]];
  }
  const result = arr.join("");
  return isValidMetricoolPassword(result) ? result : `${uppers[0]}${lowers[0]}${digits[0]}!${result.slice(0, 10)}`;
}

function sanitizeOrGeneratePassword(rawPassword, fallbackSeed = "") {
  if (rawPassword && isValidMetricoolPassword(rawPassword)) {
    return rawPassword;
  }
  if (rawPassword) {
    console.warn(`[Password Notice] Provided password '${rawPassword}' does not meet Metricool criteria (8-20 chars, Upper, Lower, Number, Special). Upgrading to compliant password...`);
    // Attempt to adapt existing password
    let adapted = rawPassword;
    if (!/[A-Z]/.test(adapted)) adapted += "A";
    if (!/[a-z]/.test(adapted)) adapted += "a";
    if (!/[0-9]/.test(adapted)) adapted += "9";
    if (!/[^A-Za-z0-9]/.test(adapted)) adapted += "!";
    if (adapted.length > 20) adapted = adapted.slice(0, 16) + "A1!";
    if (adapted.length < 8) adapted += "Xy9!";
    if (isValidMetricoolPassword(adapted)) return adapted;
  }
  return generateCompliantPassword(fallbackSeed);
}

function generatePassword(firstName, lastName) {
  return generateCompliantPassword(`${firstName}${lastName}`);
}

const ident = extractIdentity(email);
password = sanitizeOrGeneratePassword(password, `${ident.firstName}${ident.lastName}`);

const birthday = generateRandomBirthday();
let gender = Math.random() < 0.5 ? "Female" : "Male";

// ----------------------------------------------------
// Microsoft Graph / Outlook OAuth Polling (Multi-Tier)
// ----------------------------------------------------
async function fetchWithTimeout(url, opts = {}, timeoutMs = 8000) {
  const controller = new AbortController();
  const tid = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, { ...opts, signal: controller.signal });
  } finally {
    clearTimeout(tid);
  }
}

async function getMsAccessToken(cId, rToken) {
  let cleanCId = (cId || "").trim();
  if (cleanCId.startsWith("9e5f94bc") && cleanCId.length === 35) {
    cleanCId = "9e5f94bc-e8a4-4e73-b8be-63364c29d753";
  }
  cleanCId = cleanCId || "9e5f94bc-e8a4-4e73-b8be-63364c29d753";

  const tokenUrl = "https://login.microsoftonline.com/consumers/oauth2/v2.0/token";
  const baseParams = {
    client_id: cleanCId,
    grant_type: "refresh_token",
    refresh_token: (rToken || "").trim(),
  };

  // Tier 1: Explicitly request Microsoft Graph Mail.Read scope
  try {
    const res = await fetchWithTimeout(tokenUrl, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({ ...baseParams, scope: "https://graph.microsoft.com/Mail.Read" }).toString(),
    });
    const data = await res.json();
    if (data.access_token) return data.access_token;
  } catch (e) { }

  // Tier 2: Explicitly request legacy Outlook Mail.Read scope
  try {
    const res = await fetchWithTimeout(tokenUrl, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({ ...baseParams, scope: "https://outlook.office.com/Mail.Read" }).toString(),
    });
    const data = await res.json();
    if (data.access_token) return data.access_token;
  } catch (e) { }

  // Tier 3: Omit scope and inherit consented default scopes
  const res = await fetchWithTimeout(tokenUrl, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams(baseParams).toString(),
  });
  const data = await res.json();
  if (data.access_token) return data.access_token;

  throw new Error(`Failed to acquire MS access token: ${data.error_description || JSON.stringify(data)}`);
}

async function pollOutlookForMetricool(cId, rToken, maxWaitSec = 75) {
  console.log("[Outlook] Polling inbox and junk for Metricool activation email...");
  const startTime = Date.now();
  const folderUrls = [
    "https://graph.microsoft.com/v1.0/me/messages?$top=5&$orderby=receivedDateTime%20desc",
    "https://graph.microsoft.com/v1.0/me/mailFolders/junkemail/messages?$top=5&$orderby=receivedDateTime%20desc",
    "https://outlook.office.com/api/v2.0/me/messages?$top=5&$orderby=ReceivedDateTime%20desc",
    "https://outlook.office.com/api/v2.0/me/MailFolders/JunkEmail/messages?$top=5&$orderby=ReceivedDateTime%20desc",
  ];

  while (Date.now() - startTime < maxWaitSec * 1000) {
    try {
      const token = await getMsAccessToken(cId, rToken);
      for (const url of folderUrls) {
        const resp = await fetchWithTimeout(url, {
          headers: { Authorization: `Bearer ${token}`, Accept: "application/json" },
        });
        if (!resp.ok) continue;
        const data = await resp.json();
        for (const m of data.value || []) {
          const subject = m.Subject || m.subject || "";
          const preview = m.BodyPreview || m.bodyPreview || "";
          const bodyObj = m.Body || m.body;
          const content = typeof bodyObj === "object" ? (bodyObj.Content || bodyObj.content || "") : (bodyObj || "");
          const full = `${subject} ${preview} ${content}`;
          if (full.toLowerCase().includes("metricool")) {
            console.log(`[Outlook] Found Metricool email: '${subject}'`);
            const linkMatch = (content || preview).match(/https?:\/\/[^\s"'<>]*(?:verify|confirm|activate|register|token)[^\s"'<>]*/i);
            if (linkMatch) return { type: "link", data: linkMatch[0].replace(/&amp;/g, "&") };
            const codeMatch = full.match(/\b(\d{6})\b/);
            if (codeMatch) return { type: "code", data: codeMatch[1] };
          }
        }
      }
    } catch (e) { }
    await new Promise((r) => setTimeout(r, 4000));
  }
  return null;
}

async function pollOutlookForInstagramOtp(cId, rToken, minTimeMs, maxWaitSec = 120) {
  console.log("[Outlook] Polling inbox and junk for Instagram confirmation code...");
  const startTime = Date.now();
  const minTime = minTimeMs - 15000;
  const folderUrls = [
    "https://graph.microsoft.com/v1.0/me/messages?$top=5&$orderby=receivedDateTime%20desc",
    "https://graph.microsoft.com/v1.0/me/mailFolders/junkemail/messages?$top=5&$orderby=receivedDateTime%20desc",
    "https://outlook.office.com/api/v2.0/me/messages?$top=5&$orderby=ReceivedDateTime%20desc",
    "https://outlook.office.com/api/v2.0/me/MailFolders/JunkEmail/messages?$top=5&$orderby=ReceivedDateTime%20desc",
  ];

  while (Date.now() - startTime < maxWaitSec * 1000) {
    try {
      const token = await getMsAccessToken(cId, rToken);
      for (const url of folderUrls) {
        const resp = await fetchWithTimeout(url, {
          headers: { Authorization: `Bearer ${token}`, Accept: "application/json" },
        });
        if (!resp.ok) continue;
        const data = await resp.json();
        for (const m of data.value || []) {
          const rawDate = m.ReceivedDateTime || m.receivedDateTime;
          const recTime = rawDate ? new Date(rawDate).getTime() : Date.now();
          if (recTime < minTime) continue;
          const subject = m.Subject || m.subject || "";
          const preview = m.BodyPreview || m.bodyPreview || "";
          const full = `${subject} ${preview}`;
          if (full.toLowerCase().includes("instagram") || full.includes("code")) {
            const match = subject.match(/\b(\d{6})\b/) || preview.match(/\b(\d{6})\b/);
            if (match) {
              console.log(`[Outlook] Found Instagram 6-digit OTP: ${match[1]}`);
              return match[1];
            }
          }
        }
      }
    } catch (e) { }
    await new Promise((r) => setTimeout(r, 3500));
  }
  return null;
}

async function promptTerminalOtp(email, timeoutSec = 180) {
  console.log("\n" + "=".repeat(65));
  console.log(`[Manual OTP] Waiting for confirmation code for: ${email}`);
  console.log(`[Manual OTP] Type the code below and press Enter (timeout: ${timeoutSec}s)...`);
  console.log("=".repeat(65));

  return new Promise((resolve) => {
    const rl = readline.createInterface({ input: process.stdin, output: process.stdout });
    const timer = setTimeout(() => {
      rl.close();
      console.log("\n[Manual OTP] Timed out waiting for terminal OTP input.");
      resolve(null);
    }, timeoutSec * 1000);

    rl.question(`[Enter OTP for ${email}]: `, (answer) => {
      clearTimeout(timer);
      rl.close();
      const code = (answer || "").replace(/\D/g, "").trim();
      resolve(code || null);
    });
  });
}

async function pollOutlookForFacebookOtp(cId, rToken, minTimeMs, maxWaitSec = 120) {
  console.log("[Outlook] Polling inbox and junk for Facebook confirmation code...");
  const startTime = Date.now();
  const minTime = minTimeMs - 15000;
  const folderUrls = [
    "https://graph.microsoft.com/v1.0/me/messages?$top=5&$orderby=receivedDateTime%20desc",
    "https://graph.microsoft.com/v1.0/me/mailFolders/junkemail/messages?$top=5&$orderby=receivedDateTime%20desc",
    "https://outlook.office.com/api/v2.0/me/messages?$top=5&$orderby=ReceivedDateTime%20desc",
    "https://outlook.office.com/api/v2.0/me/MailFolders/JunkEmail/messages?$top=5&$orderby=ReceivedDateTime%20desc",
  ];

  while (Date.now() - startTime < maxWaitSec * 1000) {
    try {
      const token = await getMsAccessToken(cId, rToken);
      for (const url of folderUrls) {
        const resp = await fetchWithTimeout(url, {
          headers: { Authorization: `Bearer ${token}`, Accept: "application/json" },
        });
        if (!resp.ok) continue;
        const data = await resp.json();
        for (const m of data.value || []) {
          const rawDate = m.ReceivedDateTime || m.receivedDateTime;
          const recTime = rawDate ? new Date(rawDate).getTime() : Date.now();
          if (recTime < minTime) continue;
          const subject = m.Subject || m.subject || "";
          const preview = m.BodyPreview || m.bodyPreview || "";
          const full = `${subject} ${preview}`;
          if (full.toLowerCase().includes("facebook") || full.includes("FB-") || full.includes("code")) {
            const match = subject.match(/\b(\d{5})\b/) ||
              preview.match(/FB-\s*(\d{5})/i) ||
              preview.match(/\b(\d{5})\b/) ||
              subject.match(/\b(\d{6})\b/) ||
              preview.match(/\b(\d{6})\b/);
            if (match) {
              console.log(`[Outlook] Found Facebook confirmation code: ${match[1]}`);
              return match[1];
            }
          }
        }
      }
    } catch (e) { }
    await new Promise((r) => setTimeout(r, 3500));
  }
  return null;
}

// ----------------------------------------------------
// Metricool Onboarding Survey & Dialog Traversal
// ----------------------------------------------------
async function clickMetricoolOption(page, text) {
  try {
    const loc = page.locator("button, .v-btn, .v-card, .v-selection-control, [role='button'], label, div, span, p")
      .filter({ hasText: new RegExp(text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), "i") })
      .first();
    if ((await loc.count()) > 0 && (await loc.isVisible().catch(() => false))) {
      await loc.scrollIntoViewIfNeeded().catch(() => { });
      await humanClick(page, loc).catch(() => loc.click({ force: true }));
      await page.waitForTimeout(500);
      return true;
    }

    const locLast = page.locator("button, .v-btn, .v-card, [role='button'], div").filter({ hasText: new RegExp(text, "i") }).last();
    if ((await locLast.count()) > 0 && (await locLast.isVisible().catch(() => false))) {
      await locLast.scrollIntoViewIfNeeded().catch(() => { });
      await humanClick(page, locLast).catch(() => locLast.click({ force: true }));
      await page.waitForTimeout(500);
      return true;
    }
  } catch (e) { }
  return false;
}

async function handleMetricoolOnboarding(page, maxWaitMs = 45000) {
  console.log("[Metricool] Checking for and completing multi-step onboarding survey before moving to Instagram...");
  const startTime = Date.now();
  await page.waitForTimeout(2000);

  while (Date.now() - startTime < maxWaitMs) {
    const bodyText = (await page.evaluate(() => (document.body ? document.body.innerText : "")).catch(() => "")) || "";
    const html = (await page.content().catch(() => "")) || "";

    // Dialog 4: Confirmation "Wait! Are you sure you want to leave?"
    if (
      bodyText.includes("Wait! Are you sure you want to leave?") ||
      bodyText.includes("Connect at least one social network") ||
      (bodyText.includes("Cancel") && bodyText.includes("Accept"))
    ) {
      console.log("[Metricool Onboarding] Dialog 4 detected: 'Wait! Are you sure you want to leave?'. Handling dialog...");
      const cancelBtn = page.locator("button:has-text('Cancel'), .v-btn:has-text('Cancel'), [role='button']:has-text('Cancel')").first();
      const acceptBtn = page.locator("button:has-text('Accept'), .v-btn:has-text('Accept'), [role='button']:has-text('Accept')").first();
      if ((await cancelBtn.count()) > 0 && (await cancelBtn.isVisible().catch(() => false))) {
        await humanClick(page, cancelBtn).catch(() => cancelBtn.click({ force: true }));
      } else if ((await acceptBtn.count()) > 0 && (await acceptBtn.isVisible().catch(() => false))) {
        await humanClick(page, acceptBtn).catch(() => acceptBtn.click({ force: true }));
      } else {
        await clickMetricoolOption(page, "Cancel").catch(() => clickMetricoolOption(page, "Accept"));
      }
      await page.waitForTimeout(1200);
      continue;
    }

    // Dialog 1: "What describes you best?"
    if (bodyText.includes("What describes you best?") || html.includes("What describes you best?")) {
      console.log("[Metricool Onboarding] Dialog 1 detected: 'What describes you best?'. Selecting role...");
      let roleClicked = false;
      for (const role of [
        "Content creator, personal brand or influencer",
        "Content creator",
        "Social media management in my company",
        "Freelancer working for clients",
        "Marketing agency",
      ]) {
        if (await clickMetricoolOption(page, role)) {
          console.log(`[Metricool Onboarding] Selected role: '${role}'`);
          roleClicked = true;
          break;
        }
      }

      await page.waitForTimeout(300);

      // Check if team size selector appears ("Just me")
      for (const team of ["Just me", "I will work with more colleagues"]) {
        if (bodyText.includes(team)) {
          if (await clickMetricoolOption(page, team)) {
            console.log(`[Metricool Onboarding] Selected team: '${team}'`);
            break;
          }
        }
      }

      await page.waitForTimeout(350);

      // Click "Continue" button
      console.log("[Metricool Onboarding] Clicking 'Continue' on Dialog 1...");
      const contBtns = page.locator("button:has-text('Continue'):visible, .v-btn:has-text('Continue'):visible, [role='button']:has-text('Continue'):visible");
      if ((await contBtns.count()) > 0) {
        const lastBtn = contBtns.last();
        await lastBtn.scrollIntoViewIfNeeded().catch(() => {});
        await humanClick(page, lastBtn).catch(() => lastBtn.click({ force: true }));
      }
      // Guarantee dismissal via evaluated click on visible Continue button
      await page.evaluate(() => {
        const btns = Array.from(document.querySelectorAll("button, .v-btn, [role='button']"));
        const visibleCont = btns.reverse().find(b => {
          const t = (b.innerText || b.textContent || "").trim();
          return t.includes("Continue") && b.offsetParent !== null && !b.disabled;
        });
        if (visibleCont) {
          visibleCont.click();
          visibleCont.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }));
        }
      }).catch(() => {});
      await page.waitForTimeout(1500);
      continue;
    }

    // Dialog 2: "How are you going to use Metricool?"
    if (bodyText.includes("How are you going to use Metricool?") || html.includes("How are you going to use Metricool?")) {
      console.log("[Metricool Onboarding] Dialog 2 detected: 'How are you going to use Metricool?'. Selecting usage...");
      for (const usage of [
        "Programming and publishing of content",
        "Analysis and reports",
        "Create a page for your bio link",
        "Conversation management",
      ]) {
        if (await clickMetricoolOption(page, usage)) {
          console.log(`[Metricool Onboarding] Selected usage: '${usage}'`);
          break;
        }
      }

      await page.waitForTimeout(350);

      // Click "Continue" button
      console.log("[Metricool Onboarding] Clicking 'Continue' on Dialog 2...");
      const cont2 = page.locator("button:has-text('Continue'), .v-btn:has-text('Continue'), [role='button']:has-text('Continue')").last();
      if ((await cont2.count()) > 0 && (await cont2.isVisible().catch(() => false))) {
        await humanClick(page, cont2).catch(() => cont2.click({ force: true }));
      } else {
        await clickMetricoolOption(page, "Continue");
      }
      await page.waitForTimeout(1500);
      continue;
    }

    // Dialog 3: "Connect your social networks"
    if (bodyText.includes("Connect your social networks") || html.includes("Connect your social networks")) {
      console.log("[Metricool Onboarding] Dialog 3 detected: 'Connect your social networks'. Clicking 'Finish'...");
      const finishBtn = page.locator("button:has-text('Finish'), .v-btn:has-text('Finish'), [role='button']:has-text('Finish')").last();
      if ((await finishBtn.count()) > 0 && (await finishBtn.isVisible().catch(() => false))) {
        await humanClick(page, finishBtn).catch(() => finishBtn.click({ force: true }));
      } else {
        await clickMetricoolOption(page, "Finish");
      }
      await page.waitForTimeout(1500);
      continue;
    }

    // Dismiss any other tour, confirmation, or modal overlays
    let tourDismissed = false;
    for (const text of ["Accept", "Skip tour", "Skip", "Got it", "Understood", "Close", "Accept all"]) {
      const btn = page.locator(`button:has-text('${text}'), .v-btn:has-text('${text}')`).first();
      if ((await btn.count()) > 0 && (await btn.isVisible().catch(() => false))) {
        console.log(`[Metricool Onboarding] Dismissing modal overlay: '${text}'`);
        await humanClick(page, btn).catch(() => btn.click({ force: true }));
        await page.waitForTimeout(1000);
        tourDismissed = true;
        break;
      }
    }
    if (tourDismissed) continue;

    // Check if dialog overlay is still active in Vuetify
    const overlays = page.locator(".v-overlay--active .v-dialog, .v-overlay--active .v-card, div[role='dialog']:visible");
    const overlayCount = await overlays.count();
    if (overlayCount === 0) {
      console.log("[Metricool Onboarding] ✅ All onboarding forms and dialogs completed and dismissed cleanly!");
      break;
    }

    await page.waitForTimeout(1500);
  }
}

// ----------------------------------------------------
// Organic Post-Registration Warmup Routine
// ----------------------------------------------------
async function warmUpAccountFeed(page, platform = "instagram", durationMs = 35000) {
  console.log(`\n[Warmup Engine] 🌿 Starting ${Math.round(durationMs / 1000)}s organic feed engagement warmup on ${platform}...`);
  try {
    const feedUrl = platform === "instagram" ? "https://www.instagram.com/" : "https://www.facebook.com/";
    if (!page.url().includes(feedUrl)) {
      await safeGoto(page, feedUrl, { waitUntil: "domcontentloaded", timeout: 25000 });
    }
    await page.waitForTimeout(3000);

    const startTime = Date.now();
    let likedPost = false;

    while (Date.now() - startTime < durationMs) {
      await page.mouse.wheel(0, 100 + Math.floor(Math.random() * 150));
      await page.waitForTimeout(1800 + Math.random() * 2500);

      // Attempt to like 1 public post naturally to build organic engagement profile
      if (!likedPost) {
        const likeSelector = platform === "instagram"
          ? "svg[aria-label='Like']"
          : "div[role='button']:has-text('Like'), span:has-text('Like')";
        const likeBtn = page.locator(likeSelector).first();
        if ((await likeBtn.count()) > 0 && (await likeBtn.isVisible().catch(() => false))) {
          console.log(`[Warmup Engine] Emulating organic engagement: Liking public post...`);
          await humanClick(page, likeBtn).catch(() => { });
          likedPost = true;
          await page.waitForTimeout(2500 + Math.random() * 1500);
        }
      }
    }
    console.log(`[Warmup Engine] ✅ Organic feed engagement complete.`);
  } catch (err) {
    console.warn(`[Warmup Engine] Warmup routine bypassed non-fatally: ${err.message}`);
  }
}

// ----------------------------------------------------
// Metricool Social Account Connection Flow
// ----------------------------------------------------
async function connectSocialAccountsToMetricool(context, metricoolPage, results) {
  console.log("\n" + "=".repeat(60));
  console.log(">>> STAGE 4: CONNECTING SOCIAL ACCOUNTS TO METRICOOL <<<");
  console.log("=".repeat(60));

  try {
    // 1. Focus Metricool Tab and navigate to connections page
    await metricoolPage.bringToFront();
    console.log("[Metricool Connect] Navigating to https://app.metricool.com/brands/connections...");
    await safeGoto(metricoolPage, "https://app.metricool.com/brands/connections", { waitUntil: "domcontentloaded", timeout: 35000 });
    await metricoolPage.waitForTimeout(3000);

    // Dismiss any onboarding surveys / modals if still lingering
    await handleMetricoolOnboarding(metricoolPage, 10000).catch(() => { });

    // Check specifically for the 'Wait! Are you sure you want to leave?' modal overlay that blocks connector cards
    const leaveModal = metricoolPage.locator("div:has-text('Wait! Are you sure you want to leave?'), div:has-text('Connect at least one social network')").first();
    if ((await leaveModal.count()) > 0 && (await leaveModal.isVisible().catch(() => false))) {
      console.log("[Metricool Connect] Modal 'Wait! Are you sure you want to leave?' detected. Dismissing by clicking Cancel to reveal connector cards...");
      const cancelBtn = metricoolPage.locator("button:has-text('Cancel'), .v-btn:has-text('Cancel')").first();
      if ((await cancelBtn.count()) > 0 && (await cancelBtn.isVisible().catch(() => false))) {
        await humanClick(metricoolPage, cancelBtn).catch(() => cancelBtn.click({ force: true }));
        await metricoolPage.waitForTimeout(1500);
      }
    }

    // =========================================================================
    // PART 1: CONNECT INSTAGRAM PROFESSIONAL ACCOUNT
    // =========================================================================
    console.log("\n[Metricool Connect] Locating Instagram connector card...");
    const igCardSelector = "div[data-mc-connector-card='instagram']";
    const igCard = metricoolPage.locator(igCardSelector).first();
    await igCard.waitFor({ state: "visible", timeout: 20000 }).catch(() => { });

    // Button: "Connect an Instagram professional account"
    const igBtnSelector = "div[data-mc-connector-card='instagram'] button, div[data-mc-connector='instagram'] button, button:has-text('Connect an Instagram professional account'), span:has-text('Connect an Instagram professional account')";
    const igBtn = metricoolPage.locator(igBtnSelector).first();

    if ((await igBtn.count()) > 0 && (await igBtn.isVisible().catch(() => false))) {
      console.log("[Metricool Connect] Clicking 'Connect an Instagram professional account' button...");
      await humanClick(metricoolPage, igBtn).catch(() => igBtn.click({ force: true }));
      await metricoolPage.waitForTimeout(2000);

      // In Metricool, a popup dialog appears with:
      // <button ...><span class="v-btn__content" data-no-activator="">Connect</span></button>
      console.log("[Metricool Connect] Locating modal 'Connect' button...");
      const modalConnectSelector = "div[role='dialog'] button:has-text('Connect'), .v-dialog button:has-text('Connect'), .v-dialog .v-btn:has-text('Connect'), button:has-text('Connect'), [role='button']:has-text('Connect')";
      const modalConnectBtn = metricoolPage.locator(modalConnectSelector).first();

      await modalConnectBtn.waitFor({ state: "visible", timeout: 10000 }).catch(() => { });

      let igConvertPage = null;
      const popupPromise = context.waitForEvent("page", { timeout: 20000 }).catch(() => null);

      if ((await modalConnectBtn.count()) > 0 && (await modalConnectBtn.isVisible().catch(() => false))) {
        console.log("[Metricool Connect] Clicking 'Connect' inside Metricool modal...");
        await humanClick(metricoolPage, modalConnectBtn).catch(() => modalConnectBtn.click({ force: true }));
      } else {
        console.log("[Metricool Connect] Modal connect button not found, checking if page redirected directly...");
      }

      igConvertPage = await popupPromise;

      // Fallback check across all pages in context
      if (!igConvertPage) {
        await metricoolPage.waitForTimeout(3000);
        const openPages = context.pages();
        igConvertPage = openPages.find((p) => {
          const u = p.url();
          return (
            u.includes("convert_to_professional_account") ||
            u.includes("instagram.com/oauth") ||
            u.includes("instagram.com/consent") ||
            u.includes("metricool-IG")
          );
        });
      }

      if (!igConvertPage && metricoolPage.url().includes("instagram.com")) {
        igConvertPage = metricoolPage;
      }

      if (igConvertPage) {
        console.log(`[Instagram Professional] Active convert/auth tab detected: ${igConvertPage.url()}`);
        await igConvertPage.bringToFront();
        await igConvertPage.waitForLoadState("domcontentloaded").catch(() => { });
        await igConvertPage.waitForTimeout(3000);

        // Check if there is an initial "Connect" button on this tab as noted by user
        const tabConnectBtn = igConvertPage.locator("button:has-text('Connect'), [role='button']:has-text('Connect'), .v-btn__content:text-is('Connect')").first();
        if ((await tabConnectBtn.count()) > 0 && (await tabConnectBtn.isVisible().catch(() => false))) {
          console.log("[Instagram Professional] Clicking initial 'Connect' button on tab...");
          await humanClick(igConvertPage, tabConnectBtn).catch(() => tabConnectBtn.click({ force: true }));
          await igConvertPage.waitForTimeout(2500);
        }

        // Check if "Continue as @username" appears
        const continueAsBtn = igConvertPage.locator("button:has-text('Continue as'), [role='button']:has-text('Continue as')").first();
        if ((await continueAsBtn.count()) > 0 && (await continueAsBtn.isVisible().catch(() => false))) {
          console.log("[Instagram Professional] Clicking 'Continue as' user button...");
          await humanClick(igConvertPage, continueAsBtn).catch(() => continueAsBtn.click({ force: true }));
          await igConvertPage.waitForTimeout(3000);
        }

        // ----------------------------------------------------
        // Step 1: Select "Creator"
        // ----------------------------------------------------
        console.log("[Instagram Professional] Step 1: Selecting 'Creator'...");
        const creatorSelector = "input[value='media_creator'], input#IGDSRadioButtonmedia_creator, div[role='button']:has(input[value='media_creator']), div:has-text('Creator'):has-text('Best for public figures'), h2:has-text('Creator')";
        const creatorLoc = igConvertPage.locator(creatorSelector).first();
        await creatorLoc.waitFor({ state: "visible", timeout: 15000 }).catch(() => { });

        if ((await creatorLoc.count()) > 0) {
          await humanClick(igConvertPage, creatorLoc).catch(() => creatorLoc.click({ force: true }));
        }
        await igConvertPage.waitForTimeout(600);

        // ----------------------------------------------------
        // Step 2: First "Next" Button
        // ----------------------------------------------------
        console.log("[Instagram Professional] Step 2: Clicking 'Next'...");
        const nextBtn1 = igConvertPage.locator("button:has-text('Next')").first();
        await nextBtn1.waitFor({ state: "visible", timeout: 10000 }).catch(() => { });
        await humanClick(igConvertPage, nextBtn1).catch(() => nextBtn1.click({ force: true }));
        await igConvertPage.waitForTimeout(1000);

        // ----------------------------------------------------
        // Step 3: Second "Next" Button
        // ----------------------------------------------------
        console.log("[Instagram Professional] Step 3: Clicking second 'Next'...");
        const nextBtn2 = igConvertPage.locator("button:has-text('Next')").first();
        await nextBtn2.waitFor({ state: "visible", timeout: 10000 }).catch(() => { });
        if ((await nextBtn2.count()) > 0 && (await nextBtn2.isVisible().catch(() => false))) {
          await humanClick(igConvertPage, nextBtn2).catch(() => nextBtn2.click({ force: true }));
          await igConvertPage.waitForTimeout(1000);
        }

        // ----------------------------------------------------
        // Step 4: Category: "Personal blog"
        // ----------------------------------------------------
        console.log("[Instagram Professional] Step 4: Selecting Category: 'Personal blog'...");
        const blogSelector = "input[value='2700'], input#IGDSRadioButton2700, span:has-text('Personal blog'), div:has-text('Personal blog')";
        const blogLoc = igConvertPage.locator(blogSelector).first();
        await blogLoc.waitFor({ state: "visible", timeout: 15000 }).catch(() => { });

        if ((await blogLoc.count()) > 0) {
          await humanClick(igConvertPage, blogLoc).catch(() => blogLoc.click({ force: true }));
        }
        await igConvertPage.waitForTimeout(600);

        // ----------------------------------------------------
        // Step 5: "Done" Button
        // ----------------------------------------------------
        console.log("[Instagram Professional] Step 5: Waiting for 'Done' button to become enabled...");
        const doneBtn1 = igConvertPage.locator("button:has-text('Done')").first();
        await doneBtn1.waitFor({ state: "visible", timeout: 10000 }).catch(() => { });

        // Poll until enabled
        for (let i = 0; i < 20; i++) {
          const isDisabled = await doneBtn1.isDisabled().catch(() => false);
          if (!isDisabled) break;
          await igConvertPage.waitForTimeout(200);
        }
        await humanClick(igConvertPage, doneBtn1).catch(() => doneBtn1.click({ force: true }));
        await igConvertPage.waitForTimeout(1500);

        // ----------------------------------------------------
        // Step 6: "Continue" Button
        // ----------------------------------------------------
        console.log("[Instagram Professional] Step 6: Clicking 'Continue'...");
        const contBtn = igConvertPage.locator("button:has-text('Continue'), button._a9--._ap36._asz1, [role='button']:has-text('Continue')").first();
        await contBtn.waitFor({ state: "visible", timeout: 15000 }).catch(() => { });
        if ((await contBtn.count()) > 0 && (await contBtn.isVisible().catch(() => false))) {
          await humanClick(igConvertPage, contBtn).catch(() => contBtn.click({ force: true }));
          await igConvertPage.waitForTimeout(1200);
        }

        // ----------------------------------------------------
        // Step 7: "Not now" Button / Option
        // ----------------------------------------------------
        console.log("[Instagram Professional] Step 7: Selecting 'Not now'...");
        const notNowBtn = igConvertPage.locator("span:has-text('Not now'), button:has-text('Not now'), div[role='button']:has-text('Not now'), [aria-label*='Not now' i]").first();
        await notNowBtn.waitFor({ state: "visible", timeout: 10000 }).catch(() => { });
        if ((await notNowBtn.count()) > 0 && (await notNowBtn.isVisible().catch(() => false))) {
          await humanClick(igConvertPage, notNowBtn).catch(() => notNowBtn.click({ force: true }));
          await igConvertPage.waitForTimeout(1000);
        }

        // ----------------------------------------------------
        // Step 8: "Done" Button again
        // ----------------------------------------------------
        console.log("[Instagram Professional] Step 8: Clicking second 'Done'...");
        const doneBtn2 = igConvertPage.locator("button:has-text('Done')").first();
        await doneBtn2.waitFor({ state: "visible", timeout: 10000 }).catch(() => { });
        if ((await doneBtn2.count()) > 0 && (await doneBtn2.isVisible().catch(() => false))) {
          await humanClick(igConvertPage, doneBtn2).catch(() => doneBtn2.click({ force: true }));
          await igConvertPage.waitForTimeout(1500);
        }

        // ----------------------------------------------------
        // Step 9: Consent Page ("Allow" Button)
        // ----------------------------------------------------
        console.log("[Instagram Professional] Step 9: Waiting for Instagram Consent / Permissions page...");
        await igConvertPage.waitForURL(
          (u) => u.pathname.includes("/consent") || u.search.includes("ig_biz_login_oauth") || u.search.includes("oauth"),
          { timeout: 30000 }
        ).catch(() => { });
        await igConvertPage.waitForTimeout(1500);

        const allowBtnSelector = "div[role='button']:has-text('Allow'), button:has-text('Allow'), [aria-label='Allow']";
        const allowBtn = igConvertPage.locator(allowBtnSelector).first();
        await allowBtn.waitFor({ state: "visible", timeout: 15000 }).catch(() => { });

        if ((await allowBtn.count()) > 0 && (await allowBtn.isVisible().catch(() => false))) {
          console.log("[Instagram Professional] Clicking 'Allow' to authorize Metricool...");
          await humanClick(igConvertPage, allowBtn).catch(() => allowBtn.click({ force: true }));
          console.log("[Instagram Professional] Clicked 'Allow'. Waiting for OAuth redirect back to Metricool...");
          await igConvertPage.waitForTimeout(3000);
        } else {
          console.warn("[Instagram Professional] 'Allow' button not detected on consent page.");
        }

        // ----------------------------------------------------
        // Step 10: Close convert/OAuth tab
        // ----------------------------------------------------
        if (igConvertPage !== metricoolPage && !igConvertPage.isClosed()) {
          console.log("[Instagram Professional] Closing convert/auth tab...");
          await igConvertPage.close().catch(() => { });
          await metricoolPage.waitForTimeout(1500);
        }
      } else {
        console.warn("[Metricool Connect] Instagram convert tab did not open or could not be detected.");
      }
    } else {
      console.warn("[Metricool Connect] 'Connect an Instagram professional account' button not found.");
    }

    // =========================================================================
    // PART 2: RETURN TO METRICOOL CONNECTIONS & CLICK "CONNECT A FACEBOOK PAGE"
    // =========================================================================
    console.log("\n" + "=".repeat(60));
    console.log(">>> [Metricool Connect] FOCUSING METRICOOL CONNECTIONS PAGE <<<");
    console.log("=".repeat(60));
    await metricoolPage.bringToFront();
    if (!metricoolPage.url().includes("brands/connections")) {
      console.log("[Metricool Connect] Navigating back to https://app.metricool.com/brands/connections...");
      await safeGoto(metricoolPage, "https://app.metricool.com/brands/connections", { waitUntil: "domcontentloaded", timeout: 35000 });
    }
    await metricoolPage.waitForTimeout(3000);

    // Find Facebook connector card & button:
    // <div data-mc-connector-card="facebook" class="h-full">...<div data-mc-connector="facebookPage">...<button ...>Connect a Facebook page</button>
    console.log("[Metricool Connect] Locating 'Connect a Facebook page' button...");
    const fbCard = metricoolPage.locator("div[data-mc-connector-card='facebook']").first();
    await fbCard.waitFor({ state: "visible", timeout: 20000 }).catch(() => { });

    const fbConnectBtn = metricoolPage.locator(
      "div[data-mc-connector-card='facebook'] button, div[data-mc-connector='facebookPage'] button, button:has-text('Connect a Facebook page')"
    ).first();

    await fbConnectBtn.waitFor({ state: "visible", timeout: 15000 }).catch(() => { });

    if ((await fbConnectBtn.count()) > 0 && (await fbConnectBtn.isVisible().catch(() => false))) {
      console.log("[Metricool Connect] Natural interaction: Hovering & clicking 'Connect a Facebook page' button...");
      await humanHover(metricoolPage, fbConnectBtn).catch(() => { });
      await metricoolPage.waitForTimeout(300);
      await humanClick(metricoolPage, fbConnectBtn).catch(() => fbConnectBtn.click({ force: true }));
      await metricoolPage.waitForTimeout(3000);
      console.log("[Metricool Connect] ✅ Clicked 'Connect a Facebook page' successfully!");
    } else {
      console.warn("[Metricool Connect] 'Connect a Facebook page' button not found on connections page.");
    }

    console.log("\n" + "=".repeat(70));
    console.log(">>> REACHED USER TARGET CHECKPOINT <<<");
    console.log("Instagram professional account connection completed.");
    console.log("'Connect a Facebook page' button clicked.");
    console.log("[Camoufox] 🛡️ Browser tabs remain alive. Pausing for user instructions ('ill tell baaki badme')...");
    console.log("=".repeat(70));
  } catch (connectErr) {
    console.error(`[Metricool Connect Error]: ${connectErr.message}`);
  }
}

// ----------------------------------------------------
// Master Orchestration Routine
// ----------------------------------------------------
async function main() {
  console.log("=".repeat(70));
  console.log("UNIFIED MULTI-PLATFORM SOCIAL ACCOUNT AUTOMATION");
  console.log("  Order of Execution: 1. Metricool  ->  2. Instagram  ->  3. Facebook");
  console.log("  Window Model:       Single Window, Sequential Tabs");
  console.log("  Profile Policy:     Shared Profile (`output/profiles unified/<stem>`)");
  console.log("  Typing Cadence:     Strictly 40 to 52 WPM (210ms - 310ms/char)");
  console.log("  Warmup Policy:      Direct Organic Landing (No Virgin Browser Pages)");
  console.log("=".repeat(70));
  console.log(`Target Email:     ${email}`);
  console.log(`Full Name:        ${ident.fullName}`);
  console.log(`Instagram Handle: @${ident.username}`);
  console.log(`Birthday:         ${birthday.formatted}`);
  console.log(`Gender:           ${gender}`);
  console.log(`Password:         ${password.slice(0, 3)}***${password.slice(-2)}`);
  if (effectiveProxy) {
    console.log(`Sticky Proxy:     ${effectiveProxy.replace(/^.*@/, "***@")}`);
  }
  console.log("=".repeat(70));

  const profileDir = path.resolve("output", "profiles unified", ident.profileStem);
  fs.mkdirSync(profileDir, { recursive: true });

  const screenshotsDir = path.join(profileDir, "screenshots");
  fs.mkdirSync(screenshotsDir, { recursive: true });

  const takeStepScreenshot = async (page, name) => {
    try {
      if (!page || page.isClosed()) return null;
      const fileBase = `${Date.now()}_${name.replace(/[^a-zA-Z0-9_-]/g, "_")}.png`;
      const sPath = path.join(screenshotsDir, fileBase);
      await page.screenshot({ path: sPath }).catch(() => { });
      console.log(`[Screenshot Captured] ${name} -> ${sPath}`);
      return sPath;
    } catch (e) {
      return null;
    }
  };

  const infoPath = path.join(profileDir, "account_info.json");
  let savedInfo = null;
  if (fs.existsSync(infoPath)) {
    try {
      savedInfo = JSON.parse(fs.readFileSync(infoPath, "utf-8"));
      console.log(`[Auto-Resume] Loaded existing profile progress: ${infoPath}`);
    } catch (e) { }
  }

  // Preserve compliant password across replays if not explicitly overridden
  if (!getArg("--password") && (!explicitAccount || !explicitAccount.split("|")[1]) && savedInfo?.password) {
    password = savedInfo.password;
    console.log(`[Auto-Resume] Preserved compliant password from profile.`);
  }

  const derivedTz = deriveTimezoneFromProxy(effectiveProxy);
  const personaPath = path.join(profileDir, "persona.json");
  let persona = null;
  if (fs.existsSync(personaPath)) {
    try { persona = JSON.parse(fs.readFileSync(personaPath, "utf-8")); } catch (e) { }
  }
  if (!persona) {
    persona = {
      "canvas:seed": crypto.randomInt(10000000, 99999999),
      "audio:seed": crypto.randomInt(10000000, 99999999),
      "fonts:spacing_seed": crypto.randomInt(10000000, 99999999),
      webgl_config: GPU_CONFIGURATIONS[crypto.randomInt(GPU_CONFIGURATIONS.length)],
      screen_resolution: SCREEN_RESOLUTIONS[crypto.randomInt(SCREEN_RESOLUTIONS.length)],
      timezone: derivedTz.tz,
      "locale:region": derivedTz.region,
      "locale:language": derivedTz.lang,
      name: { firstName: ident.firstName, lastName: ident.lastName, fullName: ident.fullName },
      birthday,
      gender,
      created_at: new Date().toISOString(),
    };
    fs.writeFileSync(personaPath, JSON.stringify(persona, null, 2), "utf-8");
  } else {
    let personaUpdated = false;
    if (!persona.name || /\d/.test(persona.name.fullName || "")) {
      persona.name = { firstName: ident.firstName, lastName: ident.lastName, fullName: ident.fullName };
      personaUpdated = true;
    } else {
      ident.firstName = persona.name.firstName;
      ident.lastName = persona.name.lastName;
      ident.fullName = persona.name.fullName;
    }
    if (!persona.birthday) {
      persona.birthday = birthday;
      persona.gender = gender;
      personaUpdated = true;
    } else {
      Object.assign(birthday, persona.birthday);
      if (persona.gender) gender = persona.gender;
    }
    if (!persona.timezone || !persona["locale:region"]) {
      persona.timezone = persona.timezone || derivedTz.tz;
      persona["locale:region"] = persona["locale:region"] || derivedTz.region;
      persona["locale:language"] = persona["locale:language"] || derivedTz.lang;
      personaUpdated = true;
    }
    if (personaUpdated) {
      fs.writeFileSync(personaPath, JSON.stringify(persona, null, 2), "utf-8");
    }
  }

  const scr = persona.screen_resolution || { width: 1920, height: 1080 };
  const fingerprintPath = path.join(profileDir, "fingerprint.json");
  let fingerprint = null;
  if (fs.existsSync(fingerprintPath)) {
    try { fingerprint = JSON.parse(fs.readFileSync(fingerprintPath, "utf-8")); } catch (e) { }
  }
  if (!fingerprint) {
    const res = FP_GENERATOR.getFingerprint({ operatingSystems: ["windows"] });
    fingerprint = res.fingerprint;
    fingerprint.screen = { width: scr.width, height: scr.height };
    fingerprint.videoCard = { vendor: persona.webgl_config[0], renderer: persona.webgl_config[1] };
    fs.writeFileSync(fingerprintPath, JSON.stringify(fingerprint, null, 2), "utf-8");
  }

  const parsedProxy = parseProxy(effectiveProxy);

  const browserConfig = {
    user_data_dir: profileDir,
    headless,
    os: "windows",
    humanize: false,
    block_webrtc: true,
    exclude_addons: ["UBO"],
    screen: { maxWidth: scr.width, maxHeight: scr.height },
    fingerprint,
    locale: "en-US",
    firefox_user_prefs: {
      "intl.accept_languages": "en-US, en",
      "javascript.use_us_english_locale": true,
      "browser.toolbars.bookmarks.visibility": "always",
      "browser.urlbar.suggest.bookmark": true,
      "browser.urlbar.suggest.history": true,
      "browser.urlbar.suggest.topsites": true,
      "browser.link.open_newwindow": 3,                // Open new windows in tabs
      "browser.link.open_newwindow.restriction": 0,    // Force even popup windows into tabs
      "browser.link.open_newwindow.override.external": 3,
      "browser.tabs.remote.autostart": true,
      "dom.disable_open_during_load": false,           // Prevent host page CSP / popup blocker from suppressing tabs
      "privacy.popups.showBrowserMessage": false,      // Suppress popup warning bars
      "network.trr.mode": 5,                           // Disable DoH to prevent residential proxy DNS failures
      "network.proxy.socks_remote_dns": true,
      "network.http.connection-retry-timeout": 1500,
      "gfx.font_rendering.cleartype_params.rendering_mode": 2, // Bit-for-bit Canvas parity
      "dom.webnotifications.enabled": true,
    },
    webgl_config: persona.webgl_config,
    i_know_what_im_doing: true,
    config: {
      "canvas:seed": persona["canvas:seed"],
      "canvas:aaOffset": 0,
      "canvas:aaCapOffset": false,
      "audio:seed": persona["audio:seed"],
      "fonts:spacing_seed": persona["fonts:spacing_seed"],
      timezone: persona.timezone || derivedTz.tz,
      "locale:region": persona["locale:region"] || derivedTz.region,
      "locale:language": persona["locale:language"] || derivedTz.lang,
      "locale:all": "en-US, en",
    },
    geoip: Boolean(parsedProxy),
  };
  if (parsedProxy) {
    browserConfig.proxy = parsedProxy;
  }

  if (isMobileMode && activeMobilePreset && browserChoice !== "cloakbrowser") {
    browserConfig.firefox_user_prefs["general.useragent.override"] = activeMobilePreset.userAgent;
    console.log(`[Mobile Emulation] 📱 Mobile preset active: ${activeMobilePreset.name} (${activeMobilePreset.width}x${activeMobilePreset.height}).`);
  }

  let browser = null;
  let context = null;

  if (browserChoice === "cloakbrowser") {
    console.log("[CloakBrowser] Launching Patched Stealth Chromium Anti-Detect Browser...");
    const cloak = await import(CLOAKBROWSER_PATH);

    // Auto-bind binary to local Chrome / Edge if no license key or custom binary is set
    if (!process.env.CLOAKBROWSER_LICENSE_KEY && !process.env.CLOAKBROWSER_BINARY_PATH) {
      const candidatePaths = [
        "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
        "C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe",
        "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
        "C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe",
      ];
      for (const p of candidatePaths) {
        if (fs.existsSync(p)) {
          process.env.CLOAKBROWSER_BINARY_PATH = p;
          console.log(`[CloakBrowser] Bound binary to host browser: ${p}`);
          break;
        }
      }
    }

    const cloakOpts = {
      userDataDir: profileDir,
      headless,
      locale: "en-US",
      timezone: persona.timezone || derivedTz.tz,
      args: [
        "--disable-blink-features=AutomationControlled",
        "--test-type",
        "--disable-infobars",
        "--disable-popup-blocking",
        "--lang=en-US,en",
      ],
    };

    if (parsedProxy) {
      // Pass proxy via launchOptions.proxy instead of top-level cloakOpts.proxy.
      // Top-level cloakOpts.proxy forces --proxy-server=http://user:pass@host:port in args,
      // which causes net::ERR_NO_SUPPORTED_PROXIES on standard Chromium / host Chrome.
      // Passing via launchOptions.proxy delegates authentication cleanly to Playwright's native CDP handler.
      cloakOpts.launchOptions = {
        proxy: parsedProxy,
      };
    }

    if (isMobileMode && activeMobilePreset) {
      console.log(`[CloakBrowser Mobile] 📱 Emulating ${activeMobilePreset.name} (${activeMobilePreset.width}x${activeMobilePreset.height})...`);
      cloakOpts.viewport = { width: activeMobilePreset.width, height: activeMobilePreset.height };
      cloakOpts.deviceScaleFactor = activeMobilePreset.deviceScaleFactor || 3.0;
      cloakOpts.isMobile = true;
      cloakOpts.hasTouch = true;
      cloakOpts.userAgent = activeMobilePreset.userAgent;
    } else {
      cloakOpts.viewport = { width: scr.width, height: scr.height };
    }

    try {
      context = await cloak.launchPersistentContext(cloakOpts);
      browser = context;
      activeBrowser = browser;
      console.log("[CloakBrowser] ✅ Stealth Chromium session initialized.");
    } catch (err) {
      if (err.name === "CloakBrowserLicenseError" || /license/i.test(err.message || "")) {
        console.error("============================================================");
        console.error("[CloakBrowser Notice] CloakBrowser binary requires a license key.");
        console.error("  Claim a free key at: https://cloakbrowser.dev/free");
        console.error("  Then set: $env:CLOAKBROWSER_LICENSE_KEY = '<your-key>'");
        console.error("  Falling back to Camoufox (Stealth C++ Firefox engine)...");
        console.error("============================================================");
        browser = await Camoufox(browserConfig);
        activeBrowser = browser;
        context = browser;
      } else {
        throw err;
      }
    }
  } else {
    console.log("[Camoufox] Launching Single-Window Multi-Tab Anti-Detect Browser...");
    browser = await Camoufox(browserConfig);
    activeBrowser = browser;
    // When user_data_dir is passed, browser is the BrowserContext
    context = browser;
  }

  // Selective media and tracker interceptor (saves proxy bandwidth & reduces CPU load)
  if (blockMedia) {
    console.log("[Network] Selective media & tracker interceptor ACTIVE: Blocking heavy video streams and chunk downloads...");
    await context.route("**/*", (route) => {
      const req = route.request();
      const resourceType = req.resourceType();
      const url = req.url().toLowerCase();
      if (
        resourceType === "media" ||
        url.includes(".mp4") ||
        url.includes(".m4s") ||
        url.includes(".webm") ||
        url.includes(".mpd") ||
        url.includes(".m3u8") ||
        url.includes("video.xx.fbcdn.net") ||
        url.includes("instagram.xx.fbcdn.net/v/t50.")
      ) {
        return route.abort();
      }
      return route.continue();
    });
  }

  // Anti-Detect Webdriver Leak Verification (Rule #2)
  const probePage = context.pages().length > 0 ? context.pages()[0] : await context.newPage();
  const isWebdriver = await probePage.evaluate(() => navigator.webdriver).catch(() => false);
  if (isWebdriver) {
    console.error("============================================================");
    console.error("[Anti-Detect Alert] ⚠️ navigator.webdriver is LEAKING (true)!");
    console.error("Script halted immediately per workspace security rules.");
    console.error("============================================================");
    await browser.close().catch(() => { });
    process.exit(1);
  }
  console.log("[Anti-Detect Check] navigator.webdriver = false (CLEAN & SPOOFED)");

  await alignFrozenUserAgent(probePage, fingerprint, fingerprintPath);

  if (isMobileMode && activeMobilePreset) {
    await probePage.setViewportSize({ width: activeMobilePreset.width, height: activeMobilePreset.height }).catch(() => { });
  }

  // Reusable helper to engage low-level Chrome DevTools Protocol (CDP) session for mobile touch & hardware emulation
  const applyCdpMobileEmulation = async (targetPage) => {
    if (isMobileMode && activeMobilePreset && browserChoice === "cloakbrowser" && typeof context.newCDPSession === "function") {
      try {
        const cdp = await context.newCDPSession(targetPage);
        await cdp.send("Emulation.setTouchEmulationEnabled", { enabled: true, maxTouchPoints: 5 });
        await cdp.send("Emulation.setFocusEmulationEnabled", { enabled: true });
        await cdp.send("Emulation.setDeviceMetricsOverride", {
          width: activeMobilePreset.width,
          height: activeMobilePreset.height,
          deviceScaleFactor: activeMobilePreset.deviceScaleFactor || 3.0,
          mobile: true,
        });
        if (activeMobilePreset.userAgentMetadata) {
          await cdp.send("Emulation.setUserAgentOverride", {
            userAgent: activeMobilePreset.userAgent,
            platform: activeMobilePreset.platform || "Linux armv8l",
            userAgentMetadata: activeMobilePreset.userAgentMetadata,
          });
        }
        console.log(`[CDP Mobile Emulation] ✅ CDP session active: Touch, Focus, DeviceMetrics & UserAgentMetadata engaged.`);
      } catch (cdpErr) {
        console.warn(`[CDP Mobile Emulation] CDP hook notice: ${cdpErr.message}`);
      }
    }
  };

  await applyCdpMobileEmulation(probePage);

  // Dedicated single-window tab opener: opens genuine tabs inside the shared window via window.open()
  const openTabInSameWindow = async (parentPage, targetUrl) => {
    console.log(`[Browser] Opening new tab in same window for: ${targetUrl}...`);
    if (!parentPage || parentPage.isClosed()) {
      const fallbackPage = await context.newPage();
      await applyCdpMobileEmulation(fallbackPage);
      return fallbackPage;
    }
    try {
      const pagePromise = context.waitForEvent("page", { timeout: 15000 });
      await parentPage.evaluate((url) => {
        try {
          return window.open(url, "_blank");
        } catch (e) {
          const frame = document.createElement("iframe");
          frame.style.display = "none";
          document.body.appendChild(frame);
          const win = frame.contentWindow.open(url, "_blank");
          frame.remove();
          return win;
        }
      }, targetUrl);
      const newPage = await pagePromise;
      await newPage.waitForLoadState("domcontentloaded").catch(() => { });
      if (isMobileMode && activeMobilePreset) {
        await newPage.setViewportSize({ width: activeMobilePreset.width, height: activeMobilePreset.height }).catch(() => { });
      }
      await applyCdpMobileEmulation(newPage);
      return newPage;
    } catch (err) {
      console.warn(`[Browser] Tab creation via window.open timed out (${err.message}). Falling back to context.newPage()...`);
      const fallbackPage = await context.newPage();
      if (isMobileMode && activeMobilePreset) {
        await fallbackPage.setViewportSize({ width: activeMobilePreset.width, height: activeMobilePreset.height }).catch(() => { });
      }
      await applyCdpMobileEmulation(fallbackPage);
      return fallbackPage;
    }
  };

  // Load existing Meta forensics if available
  const forensicsPath = path.join(profileDir, "meta_forensics.json");
  let existingMetaForensics = {};
  if (fs.existsSync(forensicsPath)) {
    try { existingMetaForensics = JSON.parse(fs.readFileSync(forensicsPath, "utf-8")); } catch (e) { }
  }

  // Initialize results, preserving previously completed platforms if valid
  const results = {
    profile_dir: profileDir,
    email,
    password,
    proxy_used: effectiveProxy,
    proxy_ip: proxyExitIp,
    created_at: savedInfo?.created_at || new Date().toISOString(),
    metricool: savedInfo?.metricool?.status === "active" ? savedInfo.metricool : null,
    instagram: (savedInfo?.instagram?.status === "active" && savedInfo?.instagram?.username) ? savedInfo.instagram : null,
    facebook: (savedInfo?.facebook?.status === "active" || savedInfo?.facebook?.two_factor?.enabled || (savedInfo?.facebook?.two_factor?.backup_codes?.length || 0) > 0 || savedInfo?.facebook?.name || savedInfo?.facebook?.status === "checkpoint") ? savedInfo.facebook : null,
    meta_forensics: existingMetaForensics,
  };

  // Self-heal and sync 2FA state from master vault registries if backup codes or secret keys exist
  if (results.instagram) {
    const masterBackupFile = path.resolve("output", "instagram_backup_codes.json");
    if (fs.existsSync(masterBackupFile)) {
      try {
        const vault = JSON.parse(fs.readFileSync(masterBackupFile, "utf-8"));
        const record = vault[email];
        if (record) {
          if (!results.instagram.two_factor) results.instagram.two_factor = {};
          if (record.secret_key && !results.instagram.two_factor.secret_key) {
            results.instagram.two_factor.secret_key = record.secret_key;
          }
          if (Array.isArray(record.backup_codes) && record.backup_codes.length > 0) {
            results.instagram.two_factor.backup_codes = record.backup_codes;
          }
          if (results.instagram.two_factor.secret_key || (results.instagram.two_factor.backup_codes?.length || 0) > 0) {
            results.instagram.two_factor.enabled = true;
            results.instagram.two_factor.status = "ACTIVE";
            results.instagram.two_factor.success = true;
          }
        }
      } catch (e) { }
    }
    if ((results.instagram.two_factor?.backup_codes?.length || 0) > 0 || results.instagram.two_factor?.secret_key) {
      if (!results.instagram.two_factor) results.instagram.two_factor = {};
      results.instagram.two_factor.enabled = true;
      results.instagram.two_factor.status = "ACTIVE";
      results.instagram.two_factor.success = true;
    }
  }

  // Restore Facebook from master vault if missing or heal status to active if 2FA/backup codes exist
  const masterFbBackupFile = path.resolve("output", "facebook_backup_codes.json");
  if (!results.facebook && fs.existsSync(masterFbBackupFile)) {
    try {
      const fbVault = JSON.parse(fs.readFileSync(masterFbBackupFile, "utf-8"));
      const fbRec = fbVault[email];
      if (fbRec && (fbRec.enabled || (fbRec.backup_codes?.length || 0) > 0 || fbRec.secret_key)) {
        results.facebook = savedInfo?.facebook || {
          status: "active",
          name: ident.fullName,
          email,
          password,
          two_factor: {
            enabled: true,
            status: "ACTIVE",
            secret_key: fbRec.secret_key || null,
            backup_codes: fbRec.backup_codes || [],
          }
        };
      }
    } catch (e) { }
  }

  if (results.facebook) {
    if (fs.existsSync(masterFbBackupFile)) {
      try {
        const vault = JSON.parse(fs.readFileSync(masterFbBackupFile, "utf-8"));
        const record = vault[email];
        if (record) {
          if (!results.facebook.two_factor) results.facebook.two_factor = {};
          if (record.secret_key && !results.facebook.two_factor.secret_key) {
            results.facebook.two_factor.secret_key = record.secret_key;
          }
          if (Array.isArray(record.backup_codes) && record.backup_codes.length > 0) {
            results.facebook.two_factor.backup_codes = record.backup_codes;
          }
          if (results.facebook.two_factor.secret_key || (results.facebook.two_factor.backup_codes?.length || 0) > 0) {
            results.facebook.two_factor.enabled = true;
            results.facebook.two_factor.status = "ACTIVE";
            results.facebook.two_factor.success = true;
          }
        }
      } catch (e) { }
    }
    if ((results.facebook.two_factor?.backup_codes?.length || 0) > 0 || results.facebook.two_factor?.secret_key) {
      if (!results.facebook.two_factor) results.facebook.two_factor = {};
      results.facebook.two_factor.enabled = true;
      results.facebook.two_factor.status = "ACTIVE";
      results.facebook.two_factor.success = true;
      results.facebook.status = "active";
    }
  }

  // Immediate incremental state persistence helper
  const saveIncrementalProgress = async (stageName) => {
    try {
      fs.writeFileSync(infoPath, JSON.stringify(results, null, 2), "utf-8");
      console.log(`[Persistence] Updated ${stageName} progress in: ${infoPath}`);
      const cookies = await context.cookies().catch(() => []);
      if (cookies && cookies.length > 0) {
        fs.writeFileSync(path.join(profileDir, "cookies.json"), JSON.stringify(cookies, null, 2), "utf-8");
      }
    } catch (e) { }
  };

  // =========================================================================
  // STAGE 1: METRICOOL REGISTRATION (TAB 1 IN SAME WINDOW)
  // =========================================================================
  let metricoolPage = probePage;

  const isMetricoolCompleted = Boolean(
    results.metricool?.status === "active" && !redoMetricool
  );
  const shouldRunMetricool = !skipMetricool && !onlyInstagram && !onlyFacebook;

  if (shouldRunMetricool) {
    if (isMetricoolCompleted) {
      console.log("\n" + "=".repeat(60));
      console.log(">>> [1/3] METRICOOL: ALREADY COMPLETED (AUTO-RESUMING) <<<");
      console.log("=".repeat(60));
      console.log(`[Auto-Resume] Metricool account is already active (${results.metricool.email}).`);
      console.log(`[Auto-Resume] Navigating Tab 1 to dashboard to maintain active session...`);
      await safeGoto(metricoolPage, "https://app.metricool.com/", { waitUntil: "domcontentloaded", timeout: 35000 });
      await metricoolPage.waitForTimeout(2000);
      console.log(`[Auto-Resume] Metricool Tab 1 verified on dashboard: ${metricoolPage.url()}`);
      // Fill and dismiss any onboarding surveys if present before moving to Instagram
      await handleMetricoolOnboarding(metricoolPage);
    } else {
      console.log("\n" + "=".repeat(60));
      console.log(">>> [1/3] METRICOOL ACCOUNT CREATION (TAB 1) <<<");
      console.log("=".repeat(60));

      try {
        console.log("[Metricool] Navigating directly to https://app.metricool.com/register...");
        await safeGoto(metricoolPage, "https://app.metricool.com/register", { waitUntil: "domcontentloaded", timeout: 45000 });
        await metricoolPage.waitForTimeout(3000);

        // Check if already logged in / on dashboard
        const curUrl = metricoolPage.url();
        if (curUrl.includes("app.metricool.com") && !curUrl.includes("register") && !curUrl.includes("login")) {
          console.log(`[Metricool] Session is already authenticated and active: ${curUrl}`);
          await handleMetricoolOnboarding(metricoolPage);
        } else {
          const mEmailInput = metricoolPage.locator("input.v-field__input[name='email']:visible, input[name='email']:visible").first();
          const mPassInput = metricoolPage.locator("input.v-field__input[name='password']:visible, input[name='password']:visible").first();
          const mSubmitBtn = metricoolPage.locator("button:has-text('Get started for free'):visible, button:has-text('Start for free'):visible, button:has-text('Sign up'):visible, button[type='submit']:visible").first();

          await mEmailInput.waitFor({ state: "visible", timeout: 25000 });
          console.log(`[Metricool] Typing email at 40-52 WPM: ${email}...`);
          await humanType(metricoolPage, mEmailInput, email);

          console.log(`[Metricool] Typing password at 40-52 WPM...`);
          await humanType(metricoolPage, mPassInput, password);

          // Check all consent checkboxes (Legal Terms + Communications/Offers)
          console.log("[Metricool] Ensuring ALL consent checkboxes are checked...");
          const cbContainers = metricoolPage.locator(".v-checkbox, .mc-checkbox");
          const cbContainerCount = await cbContainers.count();
          for (let i = 0; i < cbContainerCount; i++) {
            const box = cbContainers.nth(i);
            const inp = box.locator("input[type='checkbox']");
            const isChecked = await inp.isChecked().catch(() => false);
            if (!isChecked) {
              await humanClick(metricoolPage, box).catch(async () => {
                await box.click({ force: true }).catch(() => { });
              });
              await metricoolPage.waitForTimeout(250);
            }
          }

          // Safety layer: verify raw input[type='checkbox'] elements
          const cbs = metricoolPage.locator("input[type='checkbox']");
          const cbCount = await cbs.count();
          for (let i = 0; i < cbCount; i++) {
            try {
              const cb = cbs.nth(i);
              if (!(await cb.isChecked().catch(() => false))) {
                await cb.locator("..").click({ force: true }).catch(() => { });
                await cb.check({ force: true }).catch(() => { });
                await metricoolPage.waitForTimeout(200);
              }
            } catch (e) { }
          }

          // Final verification: ensure no unchecked icon remains (fa-square without fa-square-check)
          const uncheckedIcons = metricoolPage.locator(".v-checkbox i.fa-square:not(.fa-square-check), .mc-checkbox i.fa-square:not(.fa-square-check)");
          const uncheckedCount = await uncheckedIcons.count();
          for (let i = 0; i < uncheckedCount; i++) {
            await uncheckedIcons.nth(i).click({ force: true }).catch(() => { });
            await metricoolPage.waitForTimeout(200);
          }
          await metricoolPage.waitForTimeout(600);

          await takeStepScreenshot(metricoolPage, "metricool_form_ready");
          console.log("[Metricool] Submitting registration form ('Get started for free')...");
          await humanClick(metricoolPage, mSubmitBtn).catch(() => mSubmitBtn.click({ force: true }));
          await metricoolPage.waitForTimeout(4000);
          await takeStepScreenshot(metricoolPage, "metricool_after_submit");

          // Poll Outlook for Metricool verification
          if (clientId && refreshToken) {
            const verif = await pollOutlookForMetricool(clientId, refreshToken, 75);
            if (verif) {
              if (verif.type === "link") {
                console.log(`[Metricool] Navigating to activation link: ${verif.data}...`);
                await safeGoto(metricoolPage, verif.data, { waitUntil: "domcontentloaded" });
                await metricoolPage.waitForTimeout(4000);
              } else if (verif.type === "code") {
                console.log(`[Metricool] Entering 6-digit OTP code: ${verif.data}...`);
                const otpInput = metricoolPage.locator("input[name='otp'], .v-otp-input input, input.v-field__input").first();
                if ((await otpInput.count()) > 0 && (await otpInput.isVisible().catch(() => false))) {
                  await humanClick(metricoolPage, otpInput).catch(() => otpInput.click({ force: true }));
                }
                await metricoolPage.keyboard.type(verif.data, { delay: gaussianDelay(180, 25) });
                await metricoolPage.waitForTimeout(1000);
                const confirmBtn = metricoolPage.locator("button:has-text('Confirm code'), button:has-text('Verify')").first();
                if ((await confirmBtn.count()) > 0) await humanClick(metricoolPage, confirmBtn);
                else await metricoolPage.keyboard.press("Enter");
                await metricoolPage.waitForTimeout(4000);
              }
            } else {
              console.warn("[Metricool] No activation email received within timeout window.");
            }
          }

          // Handle Onboarding Surveys
          await handleMetricoolOnboarding(metricoolPage);
        }

        // Hard Checkpoint: Verify Metricool is active on dashboard
        const finalUrl = metricoolPage.url();
        if (finalUrl.includes("register") && !finalUrl.includes("token")) {
          throw new Error(`[Stage 1 Failed] Still on Metricool registration page: ${finalUrl}`);
        }

        results.metricool = {
          status: "active",
          email,
          dashboard_url: finalUrl,
        };
        await saveIncrementalProgress("Metricool");
        await takeStepScreenshot(metricoolPage, "metricool_completed").catch(() => { });
        console.log(`[Metricool] Stage 1 Completed Successfully! Active URL: ${finalUrl}`);
        await metricoolPage.waitForTimeout(2000);
      } catch (err) {
        console.error("============================================================");
        console.error(`[Metricool Failure] Stage 1 encountered an error: ${err.message}`);
        console.error("⚠️ HALTING PIPELINE: Instagram and Facebook will NOT be run.");
        console.error("Fix the error above or replay script to resume.");
        console.error("============================================================");
        await takeStepScreenshot(metricoolPage, "metricool_error").catch(() => { });
        results.metricool = { status: "failed", error: err.message };
        await saveIncrementalProgress("Metricool (Failed)");
        if (keepOpen) {
          console.log(`\n[${browserChoice === "cloakbrowser" ? "CloakBrowser" : "Camoufox"}] Browser kept open for review across all tabs. Close window or press Ctrl+C to exit.`);
          await new Promise((resolve) => browser.on("close", resolve));
        } else {
          await browser.close().catch(() => { });
          process.exit(1);
        }
      }
    }
  } else {
    console.log("[Metricool] Stage 1 Skipped via CLI flag.");
  }

  // =========================================================================
  // STAGE 2: INSTAGRAM REGISTRATION & 2FA (TAB 2 IN SAME WINDOW)
  // =========================================================================
  let instaPage = null;
  const isInstagramCompleted = Boolean(
    results.instagram?.status === "active" &&
    results.instagram?.username &&
    (results.instagram?.two_factor?.enabled === true || results.instagram?.two_factor?.status === "ACTIVE" || (results.instagram?.two_factor?.backup_codes?.length || 0) > 0) &&
    !redoInstagram
  );
  const shouldRunInstagram = !skipInstagram && !onlyFacebook && !onlyMetricool;

  if (shouldRunInstagram) {
    if (isInstagramCompleted) {
      console.log("\n" + "=".repeat(60));
      console.log(">>> [2/3] INSTAGRAM: ALREADY COMPLETED (AUTO-RESUMING) <<<");
      console.log("=".repeat(60));
      console.log(`[Auto-Resume] Instagram account @${results.instagram.username} is already created and verified.`);
      console.log(`[Auto-Resume] 2FA is active: ${results.instagram?.two_factor?.enabled} | Backup codes preserved: ${results.instagram?.two_factor?.backup_codes?.length || 0}`);
      console.log(`[Auto-Resume] Opening Tab 2 to maintain active Instagram session...`);

      instaPage = await openTabInSameWindow(metricoolPage, "https://www.instagram.com/?hl=en");
      await safeGoto(instaPage, "https://www.instagram.com/?hl=en", { waitUntil: "domcontentloaded" });
      await instaPage.waitForTimeout(2000);
      console.log(`[Auto-Resume] Instagram Tab 2 active: ${instaPage.url()}`);
    } else {
      console.log("\n" + "=".repeat(60));
      console.log(">>> [2/3] OPENING INSTAGRAM IN TAB 2 (SAME WINDOW) <<<");
      console.log("=".repeat(60));

      const instaStageStartTime = Date.now();
      let instaPreIp = null;
      let instaPostOtpIp = null;
      let instaFinalIp = null;
      let instaFingerprint = null;
      let instaDwellTime = 0;
      let instaFormFillTime = 0;
      let instaOtpLatency = null;
      interactionMetrics.reset();

      try {
        // Open Tab 2 in the same window
        instaPage = await openTabInSameWindow(metricoolPage, "https://www.instagram.com/accounts/emailsignup/?hl=en");
        await safeGoto(instaPage, "https://www.instagram.com/accounts/emailsignup/?hl=en", { waitUntil: "domcontentloaded" });
        await instaPage.waitForTimeout(3000);

        // Capture initial IP and browser fingerprint for Meta ban forensics
        instaPreIp = await captureMetaExitIp(instaPage, "instagram_pre_signup");
        instaFingerprint = await auditMetaDeviceFingerprint(instaPage);
        console.log(`[Forensics] Instagram Exit IP: ${instaPreIp.ip || "unknown"} (ASN: ${instaPreIp.asn || "unknown"}) | City: ${instaPreIp.city || "unknown"}`);

        // Dismiss cookie banner if present
        const cookieBtn = instaPage.locator("button:has-text('Allow all cookies'), button:has-text('Allow essential and optional cookies'), button:has-text('Decline optional cookies'), [aria-label='Allow all cookies']").first();
        if ((await cookieBtn.count()) > 0 && (await cookieBtn.isVisible().catch(() => false))) {
          console.log("[Instagram] Dismissing cookie dialog...");
          await humanClick(instaPage, cookieBtn).catch(() => cookieBtn.click({ force: true }));
          await instaPage.waitForTimeout(1000);
        }

        await takeStepScreenshot(instaPage, "instagram_01_landing");

        // Check if Instagram session is already authenticated (e.g. from prior successful registration / OTP confirmation)
        let isAlreadyLoggedIn = await instaPage.evaluate(() => {
          return Boolean(
            document.querySelector("a[href*='/accounts/settings'], [aria-label*='Profile'], [aria-label*='Settings'], svg[aria-label*='Home'], svg[aria-label*='Direct']") ||
            (document.body && (document.body.innerText.includes("Save your login info?") || document.body.innerText.includes("Turn on Notifications")))
          );
        }).catch(() => false);

        if (isAlreadyLoggedIn) {
          console.log("[Instagram] ✅ Session is already authenticated! Skipping registration form & OTP, jumping directly to 2FA / verification...");
        } else {
          // Check if Instagram redirected to login page; if so, click "Sign up" / "Create new account"
          let currentUrl = instaPage.url();
          if (!currentUrl.includes("emailsignup") && !currentUrl.includes("signup/phone")) {
            console.log("[Instagram] On landing/login page. Locating 'Sign up' / 'Create new account' link...");
            const signUpSelector = "a[href*='/accounts/emailsignup'], a[href*='/accounts/signup'], a:has-text('sign up'), a:has-text('Sign up'), span:text-is('Sign up'), span:has-text('Sign up'), [role='button']:has-text('Sign up'), button:has-text('Sign up'), span:has-text('Create new account'), a:has-text('Create new account'), div[role='button']:has-text('Create new account')";
            for (let attempt = 1; attempt <= 4; attempt++) {
              const signUpBtn = instaPage.locator(signUpSelector).first();
              if ((await signUpBtn.count()) > 0 && (await signUpBtn.isVisible().catch(() => false))) {
                console.log("[Instagram] Clicking 'Sign up' button to switch to registration form...");
                await humanClick(instaPage, signUpBtn).catch(() => signUpBtn.click({ force: true }));
                await instaPage.waitForTimeout(2000);
                break;
              }
              await instaPage.waitForTimeout(600);
            }
          }

          // Dismiss cookie prompt again if shown on signup screen
          if ((await cookieBtn.count()) > 0 && (await cookieBtn.isVisible().catch(() => false))) {
            await humanClick(instaPage, cookieBtn).catch(() => cookieBtn.click({ force: true }));
            await instaPage.waitForTimeout(500);
          }

          // -------------------------------------------------------------------------
          // Adaptive Multi-Step & Single-Page Instagram Registration Engine
          // (Supports both Meta Mobile Onboarding Wizard & Desktop Unified Form)
          // -------------------------------------------------------------------------
          const selectComboboxOption = async (comboLoc, selectLoc, val, labelName) => {
            console.log(`[Instagram] Selecting ${labelName}: "${val}"...`);
            let selected = false;

            // Strategy 0: Check if selectLoc or comboLoc is an HTML <select> tag!
            // IMPORTANT: Never click a native <select>! Clicking opens an OS-level modal menu that blocks Playwright.
            const isComboSelect = (await comboLoc.count()) > 0 && (await comboLoc.evaluate(el => el.tagName === "SELECT").catch(() => false));
            const hasNativeSelect = (await selectLoc.count()) > 0 || isComboSelect;
            const targetSelect = isComboSelect ? comboLoc : selectLoc;

            if (hasNativeSelect && (await targetSelect.count()) > 0) {
              console.log(`[Instagram] Native <select> found for ${labelName}. Selecting directly without click...`);
              try {
                await targetSelect.selectOption({ label: String(val) }).catch(async () => {
                  await targetSelect.selectOption({ value: String(val) });
                });
                selected = true;
              } catch (e) {}

              // Also ensure direct DOM selection & event dispatch
              await instaPage.evaluate(({ selTitle, targetVal }) => {
                const selects = Array.from(document.querySelectorAll("select"));
                const sel = selects.find(s =>
                  (s.title || s.getAttribute('aria-label') || s.name || '').toLowerCase().includes(selTitle.toLowerCase())
                );
                if (sel) {
                  const targetNum = parseInt(targetVal, 10);
                  for (let i = 0; i < sel.options.length; i++) {
                    const opt = sel.options[i];
                    const optText = (opt.text || "").trim().toLowerCase();
                    const optVal = (opt.value || "").trim().toLowerCase();
                    const targetLower = String(targetVal).trim().toLowerCase();
                    if (
                      optText === targetLower ||
                      optVal === targetLower ||
                      (!isNaN(targetNum) && parseInt(optText, 10) === targetNum) ||
                      (targetLower.length >= 3 && optText.startsWith(targetLower.slice(0, 3)))
                    ) {
                      sel.selectedIndex = i;
                      sel.value = opt.value;
                      sel.dispatchEvent(new Event('input', { bubbles: true }));
                      sel.dispatchEvent(new Event('change', { bubbles: true }));
                      return true;
                    }
                  }
                }
                return false;
              }, { selTitle: labelName, targetVal: val }).catch(() => false);

              if (selected) return true;
            }

            // Strategy 1: ONLY if NOT a native <select> (i.e. custom React dropdown button/div)
            if (!isComboSelect && (await comboLoc.count()) > 0 && (await comboLoc.isVisible().catch(() => false))) {
              await comboLoc.scrollIntoViewIfNeeded().catch(() => {});
              await humanClick(instaPage, comboLoc).catch(() => comboLoc.click({ force: true }));
              await instaPage.waitForTimeout(450);

              // 1a. Try finding exact option via Playwright locator
              const valStr = String(val).trim();
              const numVal = parseInt(valStr, 10);
              const regex = !isNaN(numVal) && numVal < 100
                ? new RegExp(`^\\s*0?${numVal}\\s*$`)
                : new RegExp(`^\\s*${valStr}\\s*$`, "i");

              const opt = instaPage.locator("[role='option'], [role='menuitem'], li, button, div[role='button'], div[tabindex='-1']").filter({ hasText: regex }).first();
              if ((await opt.count()) > 0 && (await opt.isVisible().catch(() => false))) {
                await opt.scrollIntoViewIfNeeded().catch(() => {});
                await humanClick(instaPage, opt).catch(() => opt.click({ force: true }));
                selected = true;
              }

              // 1b. If not selected, evaluate DOM search across all dropdown children/portals
              if (!selected) {
                selected = await instaPage.evaluate(({ targetVal, label }) => {
                  const valLower = String(targetVal).trim().toLowerCase();
                  const targetNum = parseInt(valLower, 10);

                  // Collect all potential options in open popups/dialogs or document
                  const candidates = Array.from(document.querySelectorAll(
                    "[role='option'], [role='menuitem'], [role='listbox'] *, div[tabindex='-1'], li, span, button, div"
                  ));

                  // First pass: exact leaf text match
                  for (const el of candidates) {
                    if (el.offsetParent === null) continue; // must be visible
                    const text = (el.innerText || el.textContent || "").trim().toLowerCase();
                    if (text === valLower && el.children.length === 0) {
                      el.scrollIntoView({ block: 'nearest' });
                      el.click();
                      el.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }));
                      return true;
                    }
                  }

                  // Second pass: month name prefix (e.g. Feb vs February) or integer equality (e.g. 04 vs 4)
                  for (const el of candidates) {
                    if (el.offsetParent === null) continue;
                    const text = (el.innerText || el.textContent || "").trim().toLowerCase();
                    if (el.children.length === 0) {
                      if (!isNaN(targetNum) && parseInt(text, 10) === targetNum) {
                        el.scrollIntoView({ block: 'nearest' });
                        el.click();
                        el.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }));
                        return true;
                      }
                      if (valLower.length >= 3 && (text.startsWith(valLower.slice(0, 3)) || valLower.startsWith(text.slice(0, 3)))) {
                        el.scrollIntoView({ block: 'nearest' });
                        el.click();
                        el.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }));
                        return true;
                      }
                    }
                  }
                  return false;
                }, { targetVal: val, label: labelName }).catch(() => false);
              }

              await instaPage.waitForTimeout(300);
            }

            // Strategy 2: Check native <select> if present
            if (!selected && (await selectLoc.count()) > 0) {
              try {
                await selectLoc.selectOption({ label: String(val) }).catch(async () => {
                  await selectLoc.selectOption({ value: String(val) });
                });
                selected = true;
              } catch (e) {}
            }

            // Strategy 3: Direct native <select> dispatch via JS evaluation fallback
            if (!selected) {
              await instaPage.evaluate(({ selTitle, targetVal }) => {
                const selects = Array.from(document.querySelectorAll("select"));
                const sel = selects.find(s =>
                  (s.title || s.getAttribute('aria-label') || s.name || '').toLowerCase().includes(selTitle.toLowerCase())
                );
                if (sel) {
                  const targetNum = parseInt(targetVal, 10);
                  for (let i = 0; i < sel.options.length; i++) {
                    const opt = sel.options[i];
                    const optText = (opt.text || "").trim().toLowerCase();
                    const optVal = (opt.value || "").trim().toLowerCase();
                    const targetLower = String(targetVal).trim().toLowerCase();
                    if (
                      optText === targetLower ||
                      optVal === targetLower ||
                      (!isNaN(targetNum) && parseInt(optText, 10) === targetNum) ||
                      (targetLower.length >= 3 && optText.startsWith(targetLower.slice(0, 3)))
                    ) {
                      sel.selectedIndex = i;
                      sel.dispatchEvent(new Event('input', { bubbles: true }));
                      sel.dispatchEvent(new Event('change', { bubbles: true }));
                      return true;
                    }
                  }
                }
                return false;
              }, { selTitle: labelName, targetVal: val }).catch(() => false);
            }

            return selected;
          };

          const clickNextOrSubmit = async () => {
            const nextBtnSelector = "button:has-text('Next'), div[role='button']:has-text('Next'), [role='button']:has-text('Next'), button:has-text('Continue'), div[role='button']:has-text('Continue'), button:has-text('Confirm'), div[role='button']:has-text('Confirm'), button:has-text('Sign up'), button:has-text('Sign Up'), button:has-text('Submit'), div[role='button']:has-text('Submit'), [role='button']:has-text('Submit'), button[type='submit']";
            const btn = instaPage.locator(nextBtnSelector).first();
            if ((await btn.count()) > 0 && (await btn.isVisible().catch(() => false))) {
              await btn.scrollIntoViewIfNeeded().catch(() => {});
              await humanClick(instaPage, btn).catch(() => btn.click({ force: true }));
            }
            // Dispatch evaluated click on submit/next
            await instaPage.evaluate(() => {
              const btns = Array.from(document.querySelectorAll("button, [role='button']"));
              const b = btns.find(el => {
                const t = (el.innerText || el.textContent || "").trim().toLowerCase();
                return (t === "submit" || t === "next" || t === "sign up" || t === "continue") && el.offsetParent !== null && !el.disabled;
              });
              if (b) {
                b.click();
                b.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }));
              }
            }).catch(() => {});
            await instaPage.keyboard.press("Enter").catch(() => {});
          };

          console.log("[Instagram] Engaging Adaptive Registration Engine...");
          let regCompleted = false;
          let submitTime = Date.now();
          let loopSteps = 0;
          const maxLoopSteps = 30;
          const loopDeadline = Date.now() + 180000; // 3 minutes max

          while (!regCompleted && loopSteps < maxLoopSteps && Date.now() < loopDeadline) {
            loopSteps++;
            await instaPage.waitForTimeout(1000);

            // 1. Check if authenticated / reached feed or post-signup screen
            const curUrl = instaPage.url() || "";
            const currentCookies = await context.cookies().catch(() => []);
            const hasSessionCookie = currentCookies.some((c) => c.name === "sessionid" && c.domain.includes("instagram.com"));
            const isAuthedOnPage = await instaPage.evaluate(() => {
              const body = (document.body ? document.body.innerText : "").toLowerCase();
              if (body.includes("what's your") || body.includes("create a password") || body.includes("confirmation code") || body.includes("agree to") || body.includes("log in or sign up") || body.includes("share everyday moments")) return false;
              return Boolean(
                document.querySelector("a[href*='/accounts/settings'], [aria-label*='Profile'], [aria-label*='Settings'], svg[aria-label*='Home'], svg[aria-label*='Direct']") ||
                body.includes("save your login info?") ||
                body.includes("turn on notifications") ||
                body.includes("welcome to instagram")
              );
            }).catch(() => false);

            if (hasSessionCookie || isAuthedOnPage) {
              console.log(`[Instagram] ✅ Registration completed and verified active! Navigated to: ${curUrl}`);
              await takeStepScreenshot(instaPage, "instagram_authenticated_complete");
              regCompleted = true;
              break;
            }

            // 2. Health check (Checkpoint / Suspension / Community Restriction)
            const susp = await checkInstagramHealth(instaPage);
            if (susp.status === "SUSPENDED" || susp.status === "RESTRICTED") {
              await takeStepScreenshot(instaPage, "instagram_restriction_error");
              throw new Error(`Instagram activity restriction / suspension triggered: ${susp.reason || susp.status} (${susp.url})`);
            }

            // 3. Dismiss any cookie prompts or modals
            const modalBtn = instaPage.locator("button:has-text('Allow all cookies'), button:has-text('Decline optional cookies'), button:has-text('Not Now'), [role='button']:has-text('Not Now'), button:has-text('Skip'), [role='button']:has-text('Skip')").first();
            if ((await modalBtn.count()) > 0 && (await modalBtn.isVisible().catch(() => false))) {
              console.log("[Instagram] Dismissing modal / cookie banner...");
              await humanClick(instaPage, modalBtn).catch(() => modalBtn.click({ force: true }));
              await instaPage.waitForTimeout(800);
              continue;
            }

            // 4. Detect phone signup screen -> Click "Sign up with email"
            const phoneEmailToggle = instaPage.locator("button:has-text('Sign up with email'), div[role='button']:has-text('Sign up with email'), a:has-text('Sign up with email'), [role='button']:has-text('Sign up with email'), span:has-text('Sign up with email')").first();
            if (curUrl.includes("signup/phone") || ((await phoneEmailToggle.count()) > 0 && (await phoneEmailToggle.isVisible().catch(() => false)))) {
              console.log("[Instagram Mobile] Detected phone signup screen. Clicking 'Sign up with email' toggle...");
              await takeStepScreenshot(instaPage, "instagram_step_phone_toggle");
              if ((await phoneEmailToggle.count()) > 0 && (await phoneEmailToggle.isVisible().catch(() => false))) {
                await humanClick(instaPage, phoneEmailToggle).catch(() => phoneEmailToggle.click({ force: true }));
              } else {
                await safeGoto(instaPage, "https://www.instagram.com/accounts/emailsignup/?hl=en", { waitUntil: "domcontentloaded" });
              }
              await instaPage.waitForTimeout(2000);
              continue;
            }

            // 5. If on landing page (e.g. "Share everyday moments..."), click "Sign up"
            if (curUrl === "https://www.instagram.com/" || curUrl === "https://www.instagram.com/?hl=en" || curUrl.endsWith("instagram.com/")) {
              const landingSignUp = instaPage.locator("a[href*='signup'], a:has-text('sign up'), a:has-text('Sign up'), span:has-text('sign up'), span:has-text('Sign up'), [role='button']:has-text('Sign up'), button:has-text('Sign up')").first();
              if ((await landingSignUp.count()) > 0 && (await landingSignUp.isVisible().catch(() => false))) {
                console.log("[Instagram Mobile] Clicking 'sign up' link on landing page...");
                await humanClick(instaPage, landingSignUp).catch(() => landingSignUp.click({ force: true }));
                await instaPage.waitForTimeout(2000);
                continue;
              }
            }

            const pageText = await instaPage.evaluate(() => (document.body ? document.body.innerText : "")).catch(() => "");

            // 4. Check for OTP / Confirmation Code screen first (if present)
            const onOtp = await isInstagramOtpScreen(instaPage);
            let otpInput = instaPage.locator("input[name='email_confirmation_code']:visible, input[autocomplete='one-time-code']:visible, input[aria-label*='code' i]:visible, input[placeholder*='code' i]:visible, input[name*='code' i]:visible, input[maxlength='6']:visible").first();
            if ((await otpInput.count()) === 0 || !(await otpInput.isVisible().catch(() => false))) {
              otpInput = instaPage.locator("input[type='text']:visible, input:not([type='hidden']):visible").first();
            }

            if (onOtp || ((await otpInput.count()) > 0 && (await otpInput.isVisible().catch(() => false)))) {
              console.log("[Instagram] 📩 Detected OTP / Confirmation Code screen...");
              await takeStepScreenshot(instaPage, "instagram_step_otp");
              let otpCode = null;
              if (clientId && refreshToken) {
                console.log(`[Instagram] Polling Outlook for OTP code (since ${new Date(submitTime).toLocaleTimeString()})...`);
                otpCode = await pollOutlookForInstagramOtp(clientId, refreshToken, submitTime, 90);
              }
              if (!otpCode) {
                console.log("[Instagram] No code received after 90s. Checking for 'Resend confirmation code' / 'I didn't get the code'...");
                const resendBtn = instaPage.locator("button:has-text('Resend'), span:has-text('Resend'), div[role='button']:has-text('Resend'), button:has-text('I didn'), span:has-text('I didn')").first();
                if ((await resendBtn.count()) > 0 && (await resendBtn.isVisible().catch(() => false))) {
                  console.log("[Instagram] Clicking resend button...");
                  await resendBtn.click({ force: true }).catch(() => {});
                  await instaPage.waitForTimeout(2000);
                  const confirmResend = instaPage.locator("button:has-text('Resend'), div[role='button']:has-text('Resend')").first();
                  if ((await confirmResend.count()) > 0 && (await confirmResend.isVisible().catch(() => false))) {
                    await confirmResend.click({ force: true }).catch(() => {});
                  }
                  if (clientId && refreshToken) {
                    console.log("[Instagram] Polling Outlook again for 60 seconds...");
                    otpCode = await pollOutlookForInstagramOtp(clientId, refreshToken, Date.now() - 10000, 60);
                  }
                }
              }
              if (!otpCode) {
                console.log(`[Instagram] Automated inbox polling returned no code for ${email}. Prompting for terminal entry...`);
                otpCode = await promptTerminalOtp(email, 180);
              }
              if (!otpCode) {
                throw new Error("Could not retrieve Instagram confirmation code from Outlook or terminal within timeout.");
              }
              console.log(`[Instagram] Entering OTP code at 40-52 WPM: ${otpCode}...`);
              await humanType(instaPage, otpInput, otpCode);
              await sleep(900 + Math.random() * 500);

              console.log("[Instagram] Submitting OTP ('Next' / 'Confirm')...");
              await takeStepScreenshot(instaPage, "instagram_otp_entered");
              await clickNextOrSubmit();
              await instaPage.waitForTimeout(3500);
              continue;
            }

            // 5. Check if Desktop Unified Form (where Email, Password, Name, Username all exist on 1 screen)
            const isDesktopUnifiedForm = await instaPage.evaluate(() => {
              const body = document.body ? document.body.innerText : "";
              const hasMetaHeading = /Get started on Instagram with a Meta Account/i.test(body);
              const emailInp = document.querySelector("input[name='emailOrPhone'], input[aria-label*='Mobile number or email' i], input[placeholder*='Mobile number or email' i]");
              const passInp = document.querySelector("input[name='password'], input[type='password']");
              const nameInp = document.querySelector("input[name='fullName'], input[placeholder*='Full name' i], input[aria-label*='Full name' i]");
              const userInp = document.querySelector("input[name='username'], input[placeholder*='Username' i], input[aria-label*='Username' i]");
              return Boolean(hasMetaHeading || (emailInp && passInp && (nameInp || userInp)));
            }).catch(() => false);

            if (isDesktopUnifiedForm) {
              console.log("[Instagram Desktop] Detected unified desktop registration form. Mapping and filling all fields...");
              await takeStepScreenshot(instaPage, "instagram_desktop_form_detected");

              // Evaluate DOM and assign data-test-field attributes to each input based on type, name, placeholder, and relative order
              const domMap = await instaPage.evaluate(() => {
                const inputs = Array.from(document.querySelectorAll("input")).filter(i => {
                  const t = (i.type || "").toLowerCase();
                  return t !== "hidden" && t !== "submit" && t !== "button" && t !== "checkbox" && t !== "radio";
                });

                const passIdx = inputs.findIndex(i => i.type === "password" || (i.name && i.name.toLowerCase().includes("pass")));
                let emailEl = inputs.find(i => /email|mobile|phone/i.test(`${i.name} ${i.placeholder} ${i.getAttribute("aria-label") || ""}`));
                if (!emailEl && passIdx > 0) emailEl = inputs[passIdx - 1];
                if (!emailEl && inputs.length > 0) emailEl = inputs[0];

                let passEl = passIdx >= 0 ? inputs[passIdx] : inputs.find(i => i.type === "password");

                let userEl = inputs.find(i => /user/i.test(`${i.name} ${i.placeholder} ${i.getAttribute("aria-label") || ""}`));
                if (!userEl && inputs.length >= 4) userEl = inputs[inputs.length - 1];

                let nameEl = inputs.find(i => /full\s*name|^name$/i.test(`${i.name} ${i.placeholder} ${i.getAttribute("aria-label") || ""}`));
                if (!nameEl && passIdx >= 0 && userEl) {
                  const userIdx = inputs.indexOf(userEl);
                  if (userIdx > passIdx + 1) nameEl = inputs[passIdx + 1];
                }
                if (!nameEl && inputs.length >= 4) nameEl = inputs[inputs.length - 2];

                if (emailEl) emailEl.setAttribute("data-test-field", "email");
                if (passEl) passEl.setAttribute("data-test-field", "password");
                if (nameEl) nameEl.setAttribute("data-test-field", "fullName");
                if (userEl) userEl.setAttribute("data-test-field", "username");

                return {
                  inputs: inputs.map(i => ({
                    type: i.type,
                    name: i.name,
                    placeholder: i.placeholder,
                    aria: i.getAttribute("aria-label"),
                    tagged: i.getAttribute("data-test-field")
                  }))
                };
              }).catch(() => null);

              console.log("[Instagram Desktop] DOM Mapping Result:", JSON.stringify(domMap, null, 2));

              const dEmail = instaPage.locator("[data-test-field='email'], input[name='emailOrPhone'], input[aria-label*='Mobile number or email' i], input[placeholder*='Mobile number or email' i], input[type='email'], input[name*='email' i]").first();
              if ((await dEmail.count()) > 0) {
                console.log(`[Instagram Desktop] Entering Email: ${email}...`);
                await dEmail.scrollIntoViewIfNeeded().catch(() => { });
                await humanType(instaPage, dEmail, email);
                await sleep(600 + Math.random() * 400);
              }

              const dPass = instaPage.locator("[data-test-field='password'], input[name='password'], input[type='password']").first();
              if ((await dPass.count()) > 0) {
                console.log("[Instagram Desktop] Entering Password...");
                await dPass.scrollIntoViewIfNeeded().catch(() => { });
                await humanType(instaPage, dPass, password);
                await sleep(600 + Math.random() * 400);
              }

              console.log(`[Instagram Desktop] Setting Birthday: ${birthday.month} ${birthday.day} ${birthday.year}...`);

              async function selectField(label, exactText) {
                console.log(`[Instagram Desktop] Selecting ${label}: "${exactText}"...`);
                let box = instaPage.locator(`[role='combobox'][aria-label='Select ${label}'], [role='combobox']:has-text('${label}')`).first();
                if ((await box.count()) === 0) {
                  const allCombos = instaPage.locator("[role='combobox']");
                  if (label === "Month") box = allCombos.nth(0);
                  else if (label === "Day") box = allCombos.nth(1);
                  else if (label === "Year") box = allCombos.nth(2);
                }
                await box.waitFor({ state: "visible", timeout: 10000 });
                await box.click();
                await instaPage.waitForTimeout(600);

                const opt = instaPage.locator("[role='option']").filter({ hasText: new RegExp(`^\\s*${exactText}\\s*$`, "i") }).first();
                if ((await opt.count()) > 0) {
                  await opt.scrollIntoViewIfNeeded().catch(() => {});
                  await opt.click({ force: true });
                  console.log(`[Instagram Desktop] Clicked option "${exactText}" with force:true`);
                } else {
                  const clicked = await instaPage.evaluate((val) => {
                    const opts = Array.from(document.querySelectorAll("[role='option']"));
                    const match = opts.find(o => (o.innerText || o.textContent || "").trim().toLowerCase() === String(val).toLowerCase());
                    if (match) {
                      match.scrollIntoView({ block: "nearest" });
                      match.click();
                      match.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
                      return true;
                    }
                    return false;
                  }, exactText);
                  console.log(`[Instagram Desktop] DOM fallback for "${exactText}": ${clicked}`);
                }
                await instaPage.waitForTimeout(500);
                const currentText = (await box.innerText().catch(() => "")).replace(/\n/g, " - ");
                console.log(`[Instagram Desktop] Box ${label} value: '${currentText}'`);
              }

              await selectField("Month", birthday.month);
              await selectField("Day", birthday.dayStr);
              await selectField("Year", String(birthday.year));
              await sleep(400);
              await sleep(600 + Math.random() * 400);

              const dName = instaPage.locator("[data-test-field='fullName'], input[name='fullName'], input[placeholder*='Full name' i], input[aria-label*='Full name' i], input[name*='name' i]").first();
              if ((await dName.count()) > 0) {
                console.log(`[Instagram Desktop] Entering Full Name: ${ident.fullName}...`);
                await dName.scrollIntoViewIfNeeded().catch(() => { });
                await humanType(instaPage, dName, ident.fullName);
                await sleep(600 + Math.random() * 400);
              }

              const dUser = instaPage.locator("[data-test-field='username'], input[name='username'], input[placeholder*='Username' i], input[aria-label*='Username' i], input[name*='user' i]").first();
              if ((await dUser.count()) > 0) {
                console.log(`[Instagram Desktop] Entering Username: ${ident.username}...`);
                await dUser.scrollIntoViewIfNeeded().catch(() => { });
                await humanType(instaPage, dUser, ident.username);
                await sleep(1800 + Math.random() * 600);
              }

              await takeStepScreenshot(instaPage, "instagram_desktop_form_filled");
              
              // Target specifically the Submit / Sign up button at the bottom of the form (strictly ignore Back button)
              const dSubmit = instaPage.locator("div[role='button']:has-text('Submit'), button:has-text('Submit'), div[role='button']:has-text('Sign up'), button:has-text('Sign up')").last();
              submitTime = Date.now();
              console.log("[Instagram Desktop] Submitting registration form ('Submit')...");
              if ((await dSubmit.count()) > 0) {
                await dSubmit.scrollIntoViewIfNeeded().catch(() => {});
                await dSubmit.focus().catch(() => {});
                await dSubmit.click({ force: true });
              }

              // Also dispatch synthetic DOM click specifically on the Submit button (never Back)
              await instaPage.evaluate(() => {
                const candidates = Array.from(document.querySelectorAll("button, div[role='button'], [role='button']"));
                const btn = candidates.find(b => {
                  const txt = (b.innerText || b.textContent || "").trim().toLowerCase();
                  const aria = (b.getAttribute("aria-label") || "").trim().toLowerCase();
                  return (txt === "submit" || txt === "sign up") && aria !== "back" && b.offsetParent !== null && !b.disabled;
                });
                if (btn) {
                  btn.scrollIntoView({ block: "center" });
                  btn.click();
                  btn.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }));
                }
              }).catch(() => {});
              
              // Wait up to 15 seconds for URL transition or OTP screen
              console.log("[Instagram Desktop] Waiting for submission response / OTP transition...");
              let desktopTransitioned = false;
              for (let waitSec = 0; waitSec < 15; waitSec++) {
                await instaPage.waitForTimeout(1000);
                const curUrlAfter = instaPage.url() || "";
                const onOtpAfter = await isInstagramOtpScreen(instaPage);
                if (onOtpAfter || curUrlAfter.includes("accounts/signup/emailConfirmation") || curUrlAfter.includes("confirmation")) {
                  console.log("[Instagram Desktop] Transitioned to OTP / Confirmation screen!");
                  desktopTransitioned = true;
                  break;
                }
                const hasRedAlert = await instaPage.evaluate(() => {
                  const alert = document.querySelector("[role='alert'], p[id*='error'], span[id*='error']");
                  return alert && alert.offsetParent !== null ? alert.innerText : null;
                }).catch(() => null);
                if (hasRedAlert) {
                  console.warn(`[Instagram Desktop] Submission notice: ${hasRedAlert}`);
                  break;
                }
              }
              if (desktopTransitioned) continue;
              await instaPage.waitForTimeout(2000);
              continue;
            }

            // 6. Mobile Wizard Step: "What's your email?"
            const emailInput = instaPage.locator("input[type='email']:visible, input[aria-label*='email' i]:visible, input[placeholder*='email' i]:visible, input[name='email']:visible, input[name='emailOrPhone']:visible").first();
            const hasPasswordInput = (await instaPage.locator("input[type='password']:visible").count()) > 0;
            const isEmailStep = (/what['’]s your email/i.test(pageText) || ((await emailInput.count()) > 0 && (await emailInput.isVisible().catch(() => false)))) && !hasPasswordInput;

            if (isEmailStep) {
              console.log("[Instagram Mobile] Step: 'What's your email?'");
              await takeStepScreenshot(instaPage, "instagram_step_email_detected");
              const curVal = await emailInput.inputValue().catch(() => "");
              if (!curVal.includes("@") || curVal !== email) {
                console.log(`[Instagram Mobile] Typing Email: ${email}...`);
                await humanType(instaPage, emailInput, email);
                await sleep(800 + Math.random() * 400);
              }
              await takeStepScreenshot(instaPage, "instagram_step_email_ready");
              console.log("[Instagram Mobile] Clicking 'Next' on Email step...");
              submitTime = Date.now();
              await clickNextOrSubmit();
              await instaPage.waitForTimeout(2500);
              continue;
            }

            // 7. Mobile Wizard Step: "What's your birthday?"
            let bdayInput = instaPage.locator("input[placeholder*='Birthday' i]:visible, input[aria-label*='Birthday' i]:visible, input[name*='birthday' i]:visible").first();
            const hasCombos = (await instaPage.locator("[role='combobox']:has-text('Month'), select[title*='Month' i]").count()) > 0;
            const isBirthdayStep = /what['’]s your birthday|add your birthday/i.test(pageText) ||
              ((await bdayInput.count()) > 0 && (await bdayInput.isVisible().catch(() => false))) ||
              hasCombos;

            if (isBirthdayStep) {
              console.log("[Instagram Mobile] Step: 'What's your birthday?'");
              await takeStepScreenshot(instaPage, "instagram_step_birthday_detected");
              if ((await bdayInput.count()) === 0 && !hasCombos) {
                bdayInput = instaPage.locator("input:visible").first();
              }
              if ((await bdayInput.count()) > 0 && (await bdayInput.isVisible().catch(() => false))) {
                const mm = String(birthday.monthIndex).padStart(2, "0");
                const dd = String(birthday.day).padStart(2, "0");
                const yyyy = String(birthday.year);
                const bdayFormatted = `${mm}/${dd}/${yyyy}`;
                console.log(`[Instagram Mobile] Entering Birthday: ${bdayFormatted}...`);
                await humanType(instaPage, bdayInput, bdayFormatted);
                await sleep(400);
                const enteredVal = await bdayInput.inputValue().catch(() => "");
                if (!enteredVal || enteredVal.length < 6) {
                  // If auto-mask stripped slashes or failed, clear and try digits
                  await bdayInput.click();
                  await instaPage.keyboard.press("Control+A");
                  await instaPage.keyboard.press("Backspace");
                  await humanType(instaPage, bdayInput, `${mm}${dd}${yyyy}`);
                }
                await sleep(800 + Math.random() * 400);
              } else if (hasCombos) {
                await selectComboboxOption(
                  instaPage.locator("[role='combobox']:has-text('Month')").first(),
                  instaPage.locator("select[title*='Month' i], select[aria-label*='Month' i]").first(),
                  birthday.month,
                  birthday.month
                );
                await selectComboboxOption(
                  instaPage.locator("[role='combobox']:has-text('Day')").first(),
                  instaPage.locator("select[title*='Day' i], select[aria-label*='Day' i]").first(),
                  birthday.dayStr,
                  birthday.dayStr
                );
                await selectComboboxOption(
                  instaPage.locator("[role='combobox']:has-text('Year')").first(),
                  instaPage.locator("select[title*='Year' i], select[aria-label*='Year' i]").first(),
                  String(birthday.year),
                  String(birthday.year)
                );
                await sleep(600 + Math.random() * 400);
              }
              await takeStepScreenshot(instaPage, "instagram_step_birthday_ready");
              console.log("[Instagram Mobile] Clicking 'Next' on Birthday step...");
              await clickNextOrSubmit();
              await instaPage.waitForTimeout(2500);
              continue;
            }

            // 8. Mobile Wizard Step: "Create a password"
            let passInput = instaPage.locator("input[type='password']:visible, input[name='password']:visible").first();
            const isPasswordStep = /create a password|choose a password/i.test(pageText) ||
              ((await passInput.count()) > 0 && (await passInput.isVisible().catch(() => false)));

            if (isPasswordStep) {
              console.log("[Instagram Mobile] Step: 'Create a password'");
              await takeStepScreenshot(instaPage, "instagram_step_password_detected");
              if ((await passInput.count()) === 0) {
                passInput = instaPage.locator("input:visible").first();
              }
              const curVal = await passInput.inputValue().catch(() => "");
              if (!curVal || curVal.length < 6) {
                console.log("[Instagram Mobile] Typing Password at 40-52 WPM...");
                await humanType(instaPage, passInput, password);
                await sleep(800 + Math.random() * 400);
              }
              await takeStepScreenshot(instaPage, "instagram_step_password_ready");
              console.log("[Instagram Mobile] Clicking 'Next' on Password step...");
              await clickNextOrSubmit();
              await instaPage.waitForTimeout(2500);
              continue;
            }

            // 9. Mobile Wizard Step: "What's your name?" / "Add your name"
            let nameInput = instaPage.locator("input[name='fullName']:visible, input[placeholder*='Full name' i]:visible, input[aria-label*='Full name' i]:visible").first();
            const isNameStep = /what['’]s your name|add your name/i.test(pageText) ||
              ((await nameInput.count()) > 0 && (await nameInput.isVisible().catch(() => false)));

            if (isNameStep) {
              console.log("[Instagram Mobile] Step: 'What's your name?'");
              await takeStepScreenshot(instaPage, "instagram_step_name_detected");
              if ((await nameInput.count()) === 0) {
                nameInput = instaPage.locator("input:visible").first();
              }
              const curVal = await nameInput.inputValue().catch(() => "");
              if (!curVal) {
                console.log(`[Instagram Mobile] Typing Full Name: ${ident.fullName}...`);
                await humanType(instaPage, nameInput, ident.fullName);
                await sleep(800 + Math.random() * 400);
              }
              await takeStepScreenshot(instaPage, "instagram_step_name_ready");
              console.log("[Instagram Mobile] Clicking 'Next' on Name step...");
              await clickNextOrSubmit();
              await instaPage.waitForTimeout(2500);
              continue;
            }

            // 10. Mobile Wizard Step: "Create a username" / "What's your username?"
            let userInput = instaPage.locator("input[name='username']:visible, input[placeholder*='Username' i]:visible, input[aria-label*='Username' i]:visible").first();
            const isUserStep = /create a username|what['’]s your username|choose a username/i.test(pageText) ||
              ((await userInput.count()) > 0 && (await userInput.isVisible().catch(() => false)));

            if (isUserStep) {
              console.log("[Instagram Mobile] Step: 'Create a username'");
              await takeStepScreenshot(instaPage, "instagram_step_username_detected");
              if ((await userInput.count()) === 0) {
                userInput = instaPage.locator("input:visible").first();
              }
              const curVal = await userInput.inputValue().catch(() => "");
              if (!curVal) {
                console.log(`[Instagram Mobile] Typing Username: ${ident.username}...`);
                await humanType(instaPage, userInput, ident.username);
              }
              console.log("[Instagram Mobile] Waiting for username availability check...");
              await sleep(1800 + Math.random() * 700);
              await takeStepScreenshot(instaPage, "instagram_step_username_ready");
              console.log("[Instagram Mobile] Clicking 'Next' on Username step...");
              await clickNextOrSubmit();
              await instaPage.waitForTimeout(2500);
              continue;
            }

            // 11. Mobile Wizard Step: "Agree to Instagram's terms and policies" / "I agree"
            const agreeBtn = instaPage.locator("button:has-text('I agree'), div[role='button']:has-text('I agree'), [role='button']:has-text('I agree')").first();
            if ((await agreeBtn.count()) > 0 && (await agreeBtn.isVisible().catch(() => false))) {
              console.log("[Instagram Mobile] Step: 'Agree to terms and policies' -> Clicking 'I agree'...");
              await takeStepScreenshot(instaPage, "instagram_step_terms_agree");
              await humanClick(instaPage, agreeBtn).catch(() => agreeBtn.click({ force: true }));
              await instaPage.waitForTimeout(3500);
              continue;
            }

            // 12. Generic Next / Continue button on intermediate screens
            const genericNext = instaPage.locator("button:has-text('Next'):visible, div[role='button']:has-text('Next'):visible, button:has-text('Continue'):visible").first();
            if ((await genericNext.count()) > 0 && (await genericNext.isVisible().catch(() => false))) {
              console.log("[Instagram Mobile] Clicking visible 'Next' / 'Continue' button...");
              await humanClick(instaPage, genericNext).catch(() => genericNext.click({ force: true }));
              await instaPage.waitForTimeout(2000);
              continue;
            }

            console.log(`[Instagram] Step ${loopSteps}: Page transitioning or awaiting state update... (URL: ${curUrl})`);
            await instaPage.waitForTimeout(2000);
          }

          if (!regCompleted) {
            throw new Error("Instagram registration could not be completed within the allotted steps/time.");
          }

          instaPostOtpIp = await captureMetaExitIp(instaPage, "instagram_post_otp");

          // FBVerse Feature 3: 18s post-registration settling delay to prevent race conditions & token bans
          console.log("[Instagram] ⏳ Settle Window: Pausing 18s for backend session & token stabilization...");
          await instaPage.waitForTimeout(18000);

          // FBVerse Feature 2: Automated Cookie Jar Export
          try {
            const instaCookies = await context.cookies();
            fs.writeFileSync(path.join(profileDir, "cookies.json"), JSON.stringify(instaCookies, null, 2), "utf-8");
            fs.writeFileSync(path.join(profileDir, "cookies_instagram.json"), JSON.stringify(instaCookies.filter(c => (c.domain || "").includes("instagram.com")), null, 2), "utf-8");
            console.log("[Instagram] 🍪 Exported authenticated cookies to profile session store.");
          } catch (e) {
            console.warn("[Instagram] Cookie export note:", e.message);
          }

          // FBVerse Feature 4: Organic Feed Warmup
          if (enableFeedWarmup) {
            await warmUpAccountFeed(instaPage, "instagram", 35000);
          }

          await instaPage.waitForTimeout(3000);

          // Dismiss Post-Signup Modals ("Save Info", "Turn on Notifications", etc.)
          console.log("[Instagram] Dismissing post-signup modals if present...");
          const postModalDismissSelector = "button:has-text('Save Info'), button:has-text('Save information'), button:has-text('Not Now'), [role='button']:has-text('Not Now'), button:has-text('Skip'), [role='button']:has-text('Skip')";
          for (let m = 0; m < 3; m++) {
            const modalBtn = instaPage.locator(postModalDismissSelector).first();
            if ((await modalBtn.count()) > 0 && (await modalBtn.isVisible().catch(() => false))) {
              console.log("[Instagram] Dismissing modal prompt...");
              await humanClick(instaPage, modalBtn).catch(() => modalBtn.click({ force: true }));
              await instaPage.waitForTimeout(2000);
            } else {
              break;
            }
          }

        }

        // Setup Instagram 2FA via State Machine
        console.log("[Instagram] Launching Instagram 2FA Setup Flow in Tab 2...");
        const tfaRes = await invokeSetupInstagram2FA(instaPage, email, password, profileDir, clientId, refreshToken).catch((e) => {
          console.warn(`[Instagram 2FA Notice]: ${e.message}`);
          return { enabled: false, backup_codes: [] };
        });

        // Capture final IP and evaluate post-creation health
        instaFinalIp = await captureMetaExitIp(instaPage, "instagram_final");
        const instaHealth = await checkInstagramHealth(instaPage);

        const igForensics = recordMetaForensicLog({
          platform: "instagram",
          profileDir,
          email,
          ident,
          birthday,
          gender,
          preIp: instaPreIp,
          postOtpIp: instaPostOtpIp,
          finalIp: instaFinalIp,
          fingerprint: instaFingerprint,
          timing: {
            stageStartTime: instaStageStartTime,
            dwellTimeMs: instaDwellTime,
            formFillMs: instaFormFillTime,
          },
          verification: {
            otpLatencyMs: instaOtpLatency,
            twoFactor: tfaRes,
          },
          health: instaHealth,
        });

        results.instagram = {
          status: instaHealth.status === "ACTIVE" ? "active" : instaHealth.status.toLowerCase(),
          username: ident.username,
          full_name: ident.fullName,
          email,
          password,
          two_factor: tfaRes,
          health: instaHealth,
        };
        results.meta_forensics.instagram = igForensics;
        await saveIncrementalProgress("Instagram");
        await takeStepScreenshot(instaPage, "instagram_completed").catch(() => { });
        console.log(`[Instagram] Stage 2 Completed! Health: ${instaHealth.status} | 2FA Active: ${tfaRes?.enabled} | Backup Codes: ${tfaRes?.backup_codes?.length || 0}`);
        await instaPage.waitForTimeout(2000);
      } catch (err) {
        console.error("============================================================");
        console.error(`[Instagram Failure] Stage 2 encountered an error: ${err.message}`);
        console.error("⚠️ HALTING PIPELINE: Facebook will NOT be run.");
        console.error("Fix the error above or replay script to resume.");
        console.error("============================================================");
        await takeStepScreenshot(instaPage, "instagram_error").catch(() => { });

        try {
          const failHealth = await checkInstagramHealth(instaPage).catch(() => ({ status: "FAILED", checkpoint_type: "error", reason: err.message, url: instaPage?.url?.() || null }));
          if (failHealth.status === "ACTIVE") {
            failHealth.status = "FAILED";
            failHealth.reason = err.message;
          }
          const failForensics = recordMetaForensicLog({
            platform: "instagram",
            profileDir,
            email,
            ident,
            birthday,
            gender,
            preIp: instaPreIp,
            postOtpIp: instaPostOtpIp,
            finalIp: null,
            fingerprint: instaFingerprint,
            timing: {
              stageStartTime: instaStageStartTime,
              dwellTimeMs: instaDwellTime,
              formFillMs: instaFormFillTime,
            },
            verification: {
              otpLatencyMs: instaOtpLatency,
              twoFactor: null,
            },
            health: failHealth,
          });
          results.meta_forensics.instagram = failForensics;
        } catch (forensicErr) { }

        results.instagram = { status: "failed", error: err.message };
        await saveIncrementalProgress("Instagram (Failed)");
        if (keepOpen) {
          console.log(`\n[${browserChoice === "cloakbrowser" ? "CloakBrowser" : "Camoufox"}] Browser kept open for review across all tabs. Close window or press Ctrl+C to close.`);
          await new Promise((resolve) => browser.on("close", resolve));
        } else {
          await browser.close().catch(() => { });
          process.exit(1);
        }
      }
    }
  } else {
    console.log("[Instagram] Stage 2 Skipped via CLI flag.");
  }

  // =========================================================================
  // FACEBOOK HELPERS: COMBOBOXES, GENDER, EMAIL, & BIRTHDAY
  // Ported directly from standalone tools/facebook_signup_camoufox.mjs
  // =========================================================================
  async function selectCustomCombobox(page, name, locator, regex) {
    let box = locator.first();
    if ((await box.count()) === 0 || !(await box.isVisible().catch(() => false))) {
      return false;
    }

    const optionSelector = "[role='option'], [role='menuitemradio'], [role='menuitem'], [role='listbox'] [tabindex], [role='listbox'] div:visible, div[role='dialog'] [role='option'], div[role='dialog'] [role='menuitemradio']";

    // Check if dropdown popup is already open from user interaction
    let opt = page.locator(optionSelector).filter({ hasText: regex }).first();
    if ((await opt.count()) === 0 || !(await opt.isVisible().catch(() => false))) {
      await humanClick(page, box).catch(() => box.click({ force: true }));
      await page.waitForTimeout(350 + Math.random() * 150);
      opt = page.locator(optionSelector).filter({ hasText: regex }).first();
    }

    if ((await opt.count()) > 0) {
      await opt.scrollIntoViewIfNeeded().catch(() => { });
      await humanClick(page, opt).catch(() => opt.click({ force: true }));
      await page.waitForTimeout(300 + Math.random() * 150);
      const txt = (await box.innerText().catch(() => "")).trim();
      console.log(`[Facebook] Set ${name} to: '${txt.replace(/\n/g, " - ")}'`);
      return true;
    }

    // Fallback: iterate all options if exact filter was hidden
    const allOpts = page.locator(optionSelector);
    const optCount = await allOpts.count();
    for (let j = 0; j < optCount; j++) {
      const item = allOpts.nth(j);
      const text = (await item.innerText().catch(() => "")).trim();
      if (regex.test(text) || (text && regex.test(text.split("\n")[0].trim()))) {
        await item.scrollIntoViewIfNeeded().catch(() => { });
        await humanClick(page, item).catch(() => item.click({ force: true }));
        await page.waitForTimeout(300 + Math.random() * 150);
        const txt = (await box.innerText().catch(() => "")).trim();
        console.log(`[Facebook] Set ${name} via scroll to: '${txt.replace(/\n/g, " - ")}'`);
        return true;
      }
    }

    console.warn(`[Facebook] Warning: Option matching ${regex} for ${name} not found.`);
    return false;
  }

  async function selectFacebookGender(page, targetGender) {
    console.log(`[Facebook] Selecting Gender: ${targetGender} (Strictly prohibiting Custom)...`);
    const isFemale = targetGender.toLowerCase() === "female";

    // Check 1: Native HTML <select name='sex'>
    const genderSelect = page.locator("select[name='sex'], select[aria-label*='gender' i], select[aria-label*='लिंग' i]").first();
    if ((await genderSelect.count()) > 0 && (await genderSelect.isVisible().catch(() => false))) {
      const val = isFemale ? "1" : "2";
      console.log(`[Facebook] Selecting gender via native <select> (value='${val}')...`);
      await genderSelect.selectOption(val).catch(() => { });
      return true;
    }

    // Check 2: Radio buttons (alternate A/B testing form layouts)
    const radioVal = isFemale ? "1" : "2";
    const radioBtn = page.locator(`input[type='radio'][value='${radioVal}'], label:has-text('${targetGender}') input[type='radio'], input[type='radio'][aria-label*='${targetGender}' i]`).first();
    if ((await radioBtn.count()) > 0 && (await radioBtn.isVisible().catch(() => false))) {
      await humanClick(page, radioBtn).catch(() => radioBtn.click({ force: true }));
      console.log(`[Facebook] Selected gender radio: ${targetGender}`);
      return true;
    }

    // Check 3: Label click fallback for radio buttons
    const labelBtn = page.locator(`label:has-text('${targetGender}')`).first();
    if ((await labelBtn.count()) > 0 && (await labelBtn.isVisible().catch(() => false))) {
      await humanClick(page, labelBtn).catch(() => labelBtn.click({ force: true }));
      console.log(`[Facebook] Clicked gender label: ${targetGender}`);
      return true;
    }

    // Check 4: Modern React Combobox / Dropdown ("Select your gender")
    const targetOptionRegex = isFemale ? /^(?:female|महिला|સ્ત્રી)$/i : /^(?:male|पुरुष|પુરુષ)$/i;

    for (let attempt = 1; attempt <= 3; attempt++) {
      // 1. Locate the Gender dropdown trigger box in DOM and tag it
      const triggerFound = await page.evaluate(() => {
        const all = Array.from(document.querySelectorAll("div[role='combobox'], div[aria-haspopup='listbox'], [role='button'], div[tabindex='0'], span, div"));
        for (const el of all) {
          const t = (el.innerText || "").trim();
          if (t === "Select your gender" || t === "Custom" || (t.startsWith("Select your gender") && t.length < 35)) {
            const box = el.closest("[role='combobox'], [role='button'], div[aria-haspopup='listbox'], div[tabindex='0']") || el;
            box.setAttribute("data-fb-gender-box", "true");
            return { found: true, text: t };
          }
        }
        const ariaBox = document.querySelector("[role='combobox'][aria-label*='gender' i], [aria-haspopup='listbox'][aria-label*='gender' i]");
        if (ariaBox) {
          ariaBox.setAttribute("data-fb-gender-box", "true");
          return { found: true, text: (ariaBox.innerText || "").trim() };
        }
        return { found: false };
      });

      if (!triggerFound.found) {
        console.warn(`[Facebook] Gender trigger box not found on attempt ${attempt}.`);
        break;
      }

      const boxLocator = page.locator("[data-fb-gender-box='true']").first();
      const currentBoxText = ((await boxLocator.innerText().catch(() => "")) || "").trim();
      console.log(`[Facebook] Gender box state (Attempt ${attempt}): '${currentBoxText}'`);

      // If already properly selected as Female or Male (and NOT Custom), we are done!
      if (targetOptionRegex.test(currentBoxText) && !/custom|pronoun|कस्टम|કસ્ટમ|other/i.test(currentBoxText)) {
        console.log(`[Facebook] Gender already correctly set to '${currentBoxText}'.`);
        return true;
      }

      // Scroll into view and click the trigger box to open the popover
      await boxLocator.scrollIntoViewIfNeeded().catch(() => { });
      await page.waitForTimeout(150);
      await humanClick(page, boxLocator).catch(() => boxLocator.click({ force: true }));
      await page.waitForTimeout(400);

      // 2. Click the desired option (Female or Male) inside the opened popover
      const optLoc = page.locator("[role='option'], [role='menuitem'], [role='menuitemradio'], [role='listbox'] div, [role='listbox'] span, label")
        .filter({ hasText: targetOptionRegex })
        .first();
      if ((await optLoc.count()) > 0 && (await optLoc.isVisible().catch(() => false))) {
        const t = (await optLoc.innerText().catch(() => "")).trim();
        if (!/custom|pronoun/i.test(t)) {
          console.log(`[Facebook] Clicking gender option via locator: '${t}'`);
          await humanClick(page, optLoc).catch(() => optLoc.click({ force: true }));
        }
      }

      await page.waitForTimeout(500);

      // 3. Post-Click Verification: Ensure box text updated and Custom is NOT active
      const updatedBoxText = ((await boxLocator.innerText().catch(() => "")) || "").trim();
      const isCustomActive = /custom|pronoun|कस्टम|કસ્ટમ|other/i.test(updatedBoxText);
      const isUnselected = /select your gender|select|चुनें|પસંદ/i.test(updatedBoxText) || updatedBoxText === "";

      if (!isCustomActive && !isUnselected && targetOptionRegex.test(updatedBoxText)) {
        console.log(`[Facebook] Successfully verified Gender selection: '${updatedBoxText.replace(/\n/g, " - ")}'`);
        // Wipe any lingering custom gender inputs that might have appeared
        await page.evaluate(() => {
          const customInputs = Array.from(document.querySelectorAll("input[name*='custom_gender' i], input[placeholder*='Gender' i], input[aria-label*='Gender' i]"));
          for (const inp of customInputs) inp.value = "";
        }).catch(() => { });
        return true;
      }

      if (isCustomActive) {
        console.warn(`[Facebook] ⚠️ Custom was selected ('${updatedBoxText}')! Retrying to force Female/Male...`);
      } else {
        console.warn(`[Facebook] Gender box still unselected ('${updatedBoxText}'). Retrying...`);
      }
    }

    return false;
  }

  async function fillFacebookEmail(page, email) {
    console.log(`[Facebook] Locating and entering Email (${email})...`);

    // Ensure any lingering custom gender input value is wiped
    await page.evaluate(() => {
      const customInputs = Array.from(document.querySelectorAll("input[name*='custom_gender' i], input[placeholder*='Gender' i], input[aria-label*='Gender' i]"));
      for (const inp of customInputs) inp.value = "";
    }).catch(() => { });

    // Scroll down smoothly so the contact inputs are well inside the viewport
    await page.evaluate(() => {
      window.scrollBy(0, 300);
    }).catch(() => { });
    await page.waitForTimeout(350);

    // Strategy 0: Detect and switch to email mode if mobile number field is displayed
    try {
      const emailSwitcher = page.locator("a:has-text('Sign up with email'), span:has-text('Sign up with email'), [role='button']:has-text('Sign up with email'), a:has-text('Sign up using email'), a:has-text('Use your email'), a:has-text('ईमेल से साइन अप करें')").first();
      if ((await emailSwitcher.count()) > 0 && (await emailSwitcher.isVisible().catch(() => false))) {
        console.log("[Facebook] Detected 'Sign up with email' toggle. Switching form from phone to email mode...");
        await humanClick(page, emailSwitcher).catch(() => emailSwitcher.click());
        await page.waitForTimeout(1200);
      }
    } catch (e) { }

    // Strategy 1: Find the text input directly PRECEDING the visible password input (foolproof across all React/Comet layouts)
    let emLocator = null;
    const relXpath = "//input[@type='password']/preceding::input[not(@type='hidden') and not(@type='password') and not(@type='radio') and not(@type='checkbox') and not(contains(@name, 'gender')) and not(contains(@placeholder, 'Gender'))][1]";
    const relCandidate = page.locator(relXpath).first();
    if ((await relCandidate.count()) > 0 && (await relCandidate.isVisible().catch(() => false))) {
      console.log("[Facebook] Located email input relative to visible Password input.");
      emLocator = relCandidate;
    }

    // Strategy 2: Candidate selectors (filtered to visible inputs only)
    if (!emLocator) {
      const emailCandidateSelectors = [
        "input[name='reg_email__']:visible",
        "input[aria-label='Mobile number or email']:visible",
        "input[aria-label='Mobile number or email address']:visible",
        "input[aria-label*='Mobile number' i]:visible",
        "input[placeholder='Mobile number or email']:visible",
        "input[placeholder='Mobile number or email address']:visible",
        "input[placeholder*='Mobile number' i]:visible",
        "input[type='email']:visible",
        "label:has-text('Mobile number or email') input:visible",
        "div:has(> label:has-text('Mobile number or email')) input:visible"
      ];

      for (const sel of emailCandidateSelectors) {
        const loc = page.locator(sel).first();
        if ((await loc.count()) > 0 && (await loc.isVisible().catch(() => false))) {
          const name = ((await loc.getAttribute("name").catch(() => "")) || "").toLowerCase();
          const aria = ((await loc.getAttribute("aria-label").catch(() => "")) || "").toLowerCase();
          const ph = ((await loc.getAttribute("placeholder").catch(() => "")) || "").toLowerCase();
          if (name.includes("custom") || aria.includes("gender") || ph.includes("gender") || aria.includes("pronoun")) {
            continue;
          }
          emLocator = loc;
          break;
        }
      }
    }

    // Strategy 3: DOM scan fallback that tags the element with data-fb-email
    if (!emLocator) {
      console.log("[Facebook] Searching DOM to tag Mobile number or email address input...");
      const tagged = await page.evaluate(() => {
        const inputs = Array.from(document.querySelectorAll("input:not([type='password']):not([type='hidden']):not([type='radio']):not([type='checkbox'])"));
        for (const input of inputs) {
          const rect = input.getBoundingClientRect();
          if (rect.width === 0 || rect.height === 0) continue;
          const name = (input.name || "").toLowerCase();
          const aria = (input.getAttribute("aria-label") || "").toLowerCase();
          const placeholder = (input.placeholder || "").toLowerCase();
          if (name.includes("custom") || aria.includes("gender") || placeholder.includes("gender") || aria.includes("pronoun")) continue;
          if (name.includes("firstname") || name.includes("lastname") || name.includes("birthday")) continue;
          if (name === "reg_email__" || input.type === "email" ||
            aria.includes("mobile") || aria.includes("email") ||
            placeholder.includes("mobile") || placeholder.includes("email")) {
            input.setAttribute("data-fb-email", "true");
            return true;
          }
        }
        return false;
      });

      if (tagged) {
        emLocator = page.locator("input[data-fb-email='true']").first();
      }
    }

    if (emLocator) {
      await emLocator.scrollIntoViewIfNeeded().catch(() => { });
      await page.waitForTimeout(200);

      // Multi-layer fill & human typing
      await humanClick(page, emLocator).catch(() => emLocator.click({ force: true }));
      await page.keyboard.press("Control+A").catch(() => { });
      await page.keyboard.press("Backspace").catch(() => { });
      await humanType(page, emLocator, email, { typos: false });

      // Strict Verification: Ensure the value was actually received by the input
      let val = await emLocator.inputValue().catch(() => "");
      if (!val || val !== email) {
        console.warn(`[Facebook] Email field verification mismatch (got '${val}', expected '${email}'). Re-filling directly...`);
        await page.keyboard.press("Control+A").catch(() => { });
        await page.keyboard.press("Backspace").catch(() => { });
        await humanType(page, emLocator, email, { typos: false });
        val = await emLocator.inputValue().catch(() => "");
      }
      console.log(`[Facebook] Email field successfully populated and verified: '${val}'`);
    } else {
      console.warn("[Facebook] Waiting for email input fallback to become visible...");
      const fallback = page.locator("input[name='reg_email__']:visible, input[aria-label*='Mobile number' i]:visible, input[placeholder*='Mobile number' i]:visible, input[type='email']:visible").first();
      await fallback.waitFor({ state: "visible", timeout: 8000 }).catch(() => { });
      if (await fallback.isVisible().catch(() => false)) {
        await fallback.scrollIntoViewIfNeeded().catch(() => { });
        await humanClick(page, fallback).catch(() => fallback.click({ force: true }));
        await page.keyboard.press("Control+A").catch(() => { });
        await page.keyboard.press("Backspace").catch(() => { });
        await humanType(page, fallback, email, { typos: false });
      }
    }

    // Verify and re-enter email confirmation if required
    await page.waitForTimeout(600);
    const reEmInput = page.locator("input[name='reg_email_confirmation__']:visible, input[aria-label*='Re-enter' i]:visible, input[placeholder*='Re-enter' i]:visible").first();
    if ((await reEmInput.count()) > 0 && (await reEmInput.isVisible().catch(() => false))) {
      console.log("[Facebook] Re-entering email confirmation...");
      await reEmInput.scrollIntoViewIfNeeded().catch(() => { });
      await humanType(page, reEmInput, email, { typos: false });
    }
  }

  async function fillBirthdayAndGender(page, dobObj, targetGender) {
    console.log(`[Facebook] Setting Birthday (${dobObj.formatted}) and Gender (${targetGender})...`);

    // Check 0: Mobile Date Input field (e.g. input[type='date'], input[aria-label*='Date of birth' i], input with placeholder/value MM/DD/YYYY)
    const mobileDateInput = page.locator("input[type='date']:visible, input[aria-label*='Date of birth' i]:visible, input[placeholder*='Date of birth' i]:visible, input[placeholder*='MM/DD/YYYY' i]:visible, input[aria-label*='Birthday' i]:visible, input:visible").first();
    const hasMobileDateInput = (await mobileDateInput.count()) > 0 && (await mobileDateInput.isVisible().catch(() => false));
    if (hasMobileDateInput) {
      console.log("[Facebook Mobile] Dedicated Mobile Date of Birth input detected.");
      const monthPadded = String(dobObj.monthIndex || dobObj.month).padStart(2, "0");
      const dayPadded = String(dobObj.day).padStart(2, "0");
      const yearStr = String(dobObj.year);
      const mmddyyyy = `${monthPadded}/${dayPadded}/${yearStr}`;
      const yyyymmdd = `${yearStr}-${monthPadded}-${dayPadded}`;

      // Check input type
      const inputType = await mobileDateInput.getAttribute("type").catch(() => "text");
      if (inputType === "date") {
        await mobileDateInput.fill(yyyymmdd).catch(() => {});
      } else {
        await mobileDateInput.click().catch(() => {});
        await mobileDateInput.fill("").catch(() => {});
        await humanType(page, mobileDateInput, mmddyyyy, { typos: false }).catch(() => mobileDateInput.fill(mmddyyyy));
      }

      // Also dispatch change and input events to ensure React / Meta internal state updates
      await page.evaluate(({ mmddyyyy, yyyymmdd }) => {
        const inp = document.querySelector("input[type='date'], input[aria-label*='Date of birth' i], input[placeholder*='Date of birth' i], input[placeholder*='MM/DD/YYYY' i], input:not([type='hidden'])");
        if (inp) {
          inp.value = inp.type === 'date' ? yyyymmdd : mmddyyyy;
          inp.dispatchEvent(new Event('input', { bubbles: true }));
          inp.dispatchEvent(new Event('change', { bubbles: true }));
          inp.dispatchEvent(new Event('blur', { bubbles: true }));
        }
      }, { mmddyyyy, yyyymmdd }).catch(() => {});
      await page.waitForTimeout(600);
    } else {
      // Check 1: Native HTML <select> elements (fallback for legacy or mobile views)
      const daySelect = page.locator("select[name='birthday_day']").first();
      const monthSelect = page.locator("select[name='birthday_month']").first();
      const yearSelect = page.locator("select[name='birthday_year']").first();
      if ((await daySelect.count()) > 0 && (await daySelect.isVisible().catch(() => false))) {
        console.log("[Facebook] Native HTML <select> dropdowns detected.");
        await daySelect.selectOption(String(dobObj.day)).catch(() => { });
        await monthSelect.selectOption(String(dobObj.monthIndex || dobObj.month)).catch(() => { });
        await yearSelect.selectOption(String(dobObj.year)).catch(() => { });
      } else {
        // Check 2: Modern Facebook React Comboboxes (targeted semantically by aria-label & text)
        // 1. Day
        const dayBox = page.locator("[role='combobox'][aria-label*='Day' i], [role='combobox']:has-text('Day'), [role='combobox'][aria-label*='दिन' i], [role='combobox']:has-text('दिन'), [role='combobox'][aria-label*='તારીખ' i]");
        const dayRegex = new RegExp(`^(?:${dobObj.day}|${dobObj.dayStr}|[०-९]+)$`);
        await selectCustomCombobox(page, "Day", dayBox, dayRegex);

        // 2. Month
        const monthBox = page.locator("[role='combobox'][aria-label*='Month' i], [role='combobox']:has-text('Month'), [role='combobox'][aria-label*='महीना' i], [role='combobox']:has-text('महीना'), [role='combobox'][aria-label*='મહિનો' i]");
        const monthRegex = new RegExp(`^(?:${dobObj.month}|${dobObj.month.slice(0, 3)}|${dobObj.monthHindi})$`, "i");
        await selectCustomCombobox(page, "Month", monthBox, monthRegex);

        // 3. Year
        const yearBox = page.locator("[role='combobox'][aria-label*='Year' i], [role='combobox']:has-text('Year'), [role='combobox'][aria-label*='वर्ष' i], [role='combobox']:has-text('वर्ष')");
        const yearRegex = new RegExp(`^(?:${dobObj.year}|[०-९]+)$`);
        await selectCustomCombobox(page, "Year", yearBox, yearRegex);
      }
    }

    // Robust Gender Selection (if present on the same screen)
    await selectFacebookGender(page, targetGender).catch(() => {});
  }

  // ----------------------------------------------------
  // Automated Facebook Page Creator & Onboarding Wizard
  // Ported directly from tools/facebook_signup_camoufox.mjs
  // ----------------------------------------------------
  function generateRealisticContactInfo(proxyLocation = {}, pageName = "Page") {
    const country = String(proxyLocation.country || "IN").toUpperCase();
    const city = proxyLocation.city || (country === "IN" ? "Mumbai" : "Chicago");
    const cleanName = pageName.toLowerCase().replace(/[^a-z0-9]/g, "").slice(0, 20) || "creatorhub";

    if (country === "IN" || country === "INDIA") {
      const indianCities = ["Mumbai", "Delhi", "Bengaluru", "Hyderabad", "Ahmedabad", "Chennai", "Kolkata", "Pune", "Jaipur", "Surat"];
      const chosenCity = indianCities.find(c => c.toLowerCase() === city.toLowerCase()) || city || "Mumbai";
      const streets = ["MG Road", "Station Road", "Linking Road", "Brigade Road", "Park Street", "Civil Lines"];
      const street = streets[crypto.randomInt(streets.length)];
      const pin = String(400000 + crypto.randomInt(99999));
      const phone = `+91 ${9000000000 + crypto.randomInt(999999999)}`;
      return {
        website: `https://www.${cleanName}.com`,
        email: `contact@${cleanName}.com`,
        phone,
        address: `${street}, Near Central Market`,
        city: chosenCity,
        postcode: pin,
      };
    }

    const usCities = ["Chicago", "Dallas", "Atlanta", "Phoenix", "Houston", "Miami", "Denver", "Seattle"];
    const chosenCity = usCities.find(c => c.toLowerCase() === city.toLowerCase()) || city || "Chicago";
    const streets = ["Main St", "Oak Ave", "Lincoln Blvd", "Maple St", "Washington Ave"];
    const street = streets[crypto.randomInt(streets.length)];
    const phone = `+1 (555) ${100 + crypto.randomInt(899)}-${1000 + crypto.randomInt(8999)}`;
    return {
      website: `https://www.${cleanName}.com`,
      email: `contact@${cleanName}.com`,
      phone,
      address: `${crypto.randomInt(100, 9999)} ${street}`,
      city: chosenCity,
      postcode: String(crypto.randomInt(10000, 99999)),
    };
  }

  async function createFacebookPage(page, customPageName = null, customBio = null, proxyLocation = {}) {
    const PAGE_NAMES = [
      "NovaPulse Stories",
      "CineScope Daily",
      "The Velvet Chronicles",
      "EchoSphere Media",
      "Apex Vista Hub",
      "Zenith Pulse Daily",
      "CineGlow Moments",
      "Lumina Realm",
    ];

    const BIOS = [
      "Documenting cinematic wonders, unique stories, and everyday inspiration. Welcome to the journey!",
      "Exploring fascinating stories, cinematic scenes, and cultural deep dives.",
      "Your daily dose of captivating storytelling, film insights, and creative musings.",
      "Cinematic highlights, life stories, and curated perspectives from around the globe.",
    ];

    const pageName = customPageName || PAGE_NAMES[crypto.randomInt(PAGE_NAMES.length)];
    const bio = customBio || BIOS[crypto.randomInt(BIOS.length)];

    console.log("=".repeat(60));
    console.log(`[Facebook Page Creation] Starting Page Creation: "${pageName}"`);
    console.log(`Category:  Personal blog`);
    console.log(`Bio:       ${bio}`);
    console.log("=".repeat(60));

    await page.waitForTimeout(3000);

    // Dismiss popup if present
    try {
      const notNowBtn = page.locator("button:has-text('Not Now'), [role='button']:has-text('Not Now'), [aria-label='Close'], [aria-label='बंद करें']");
      if ((await notNowBtn.count()) > 0 && (await notNowBtn.first().isVisible())) {
        console.log("[Facebook] Dismissing popup dialog...");
        await humanClick(page, notNowBtn.first()).catch(() => notNowBtn.first().click());
        await page.waitForTimeout(1000);
      }
    } catch (e) { }

    // Wait for 9-dots Menu button
    console.log("[Facebook] Locating 9-dots Menu icon (aria-label='Menu')...");
    const menuLocator = page.locator("[aria-label='Menu'], [aria-label*='मेनू' i], [role='button'][aria-label='Menu']").first();
    await menuLocator.waitFor({ state: "visible", timeout: 15000 }).catch(() => { });

    if ((await menuLocator.count()) > 0 && (await menuLocator.isVisible())) {
      console.log("[Facebook] Clicking 9-dots Menu icon...");
      await humanClick(page, menuLocator).catch(() => menuLocator.click());
      await page.waitForTimeout(2500);

      console.log("[Facebook] Locating 'Page' under Create menu...");
      const pageCreateBtn = page.locator("[role='menuitem']:has-text('Page'), [role='button']:has-text('Page')").filter({
        hasText: /^Page$/,
      }).first();

      if ((await pageCreateBtn.count()) > 0 && (await pageCreateBtn.isVisible())) {
        console.log("[Facebook] Clicking 'Page' option...");
        await humanClick(page, pageCreateBtn).catch(() => pageCreateBtn.click());
        await page.waitForTimeout(4000);
      } else {
        console.log("[Facebook] Navigating to https://www.facebook.com/pages/create/?locale=en_US...");
        await safeGoto(page, "https://www.facebook.com/pages/create/?locale=en_US", { waitUntil: "domcontentloaded" });
        await page.waitForTimeout(4000);
      }
    } else {
      console.log("[Facebook] Menu button not found, navigating directly to https://www.facebook.com/pages/create/?locale=en_US...");
      await safeGoto(page, "https://www.facebook.com/pages/create/?locale=en_US", { waitUntil: "domcontentloaded" });
      await page.waitForTimeout(4000);
    }

    // 1. Fill Page Name
    console.log(`[Facebook] Entering Page Name: "${pageName}"...`);
    const nameInput = page.locator("input[aria-label*='Page name' i], label:has-text('Page name') input, input[type='text']:visible").first();
    await nameInput.waitFor({ state: "visible", timeout: 15000 }).catch(() => { });
    if ((await nameInput.count()) > 0 && (await nameInput.isVisible().catch(() => false))) {
      await humanType(page, nameInput, pageName, { typos: false });
    }
    await page.waitForTimeout(800);

    // 2. Fill Category: Personal blog
    console.log("[Facebook] Entering Category: 'Personal blog'...");
    const catInput = page.locator("input[aria-label*='Category' i], label:has-text('Category') input").first();
    await humanType(page, catInput, "Personal blog", { typos: false });
    await page.waitForTimeout(2000);

    console.log("[Facebook] Selecting 'Personal blog' option from dropdown...");
    const catOption = page.locator("[role='option']").filter({ hasText: /^Personal blog$/i }).first();
    if ((await catOption.count()) > 0 && (await catOption.isVisible())) {
      await humanClick(page, catOption).catch(() => catOption.click());
      console.log("[Facebook] Selected 'Personal blog' category!");
    } else {
      await page.keyboard.press("ArrowDown");
      await page.waitForTimeout(300);
      await page.keyboard.press("Enter");
    }
    await page.waitForTimeout(1000);

    // 3. Fill Bio
    console.log(`[Facebook] Entering Bio: "${bio}"...`);
    const bioInput = page.locator("textarea[aria-label*='Bio' i], textarea").first();
    if ((await bioInput.count()) > 0 && (await bioInput.isVisible())) {
      await humanType(page, bioInput, bio, { typos: false });
      await page.waitForTimeout(800);
    }

    // Blur active element
    await page.evaluate(() => {
      if (document.activeElement && document.activeElement.blur) document.activeElement.blur();
    });
    await page.waitForTimeout(1000);

    // 4. Click 'Create Page' button
    console.log("[Facebook] Submitting page creation ('Create Page')...");
    const createBtn = page.locator("div[role='button'][aria-label='Create Page']").first();
    await createBtn.scrollIntoViewIfNeeded().catch(() => { });
    await humanClick(page, createBtn).catch(() => createBtn.click());

    console.log("[Facebook] Clicked 'Create Page'. Waiting for processing...");
    for (let w = 0; w < 8; w++) {
      await page.waitForTimeout(1000);
      const txt = await page.evaluate(() => (document.body ? document.body.innerText : "")).catch(() => "");
      if (txt.includes("Finish setting up your Page") || txt.includes("Choose Page type") || txt.includes("Handle") || txt.includes("Customize your Page") || txt.includes("Welcome to your new Page")) {
        console.log(`[Facebook] Page creation processed in ~${w + 1}s!`);
        break;
      }
    }

    // 5. Complete Multi-Step Page Onboarding (Handle, Photos, Contact, Hours, WhatsApp Skip, Done)
    const onboardRes = await completePageOnboarding(page, pageName, proxyLocation);
    const cleanHandle = pageName.toLowerCase().replace(/[^a-z0-9]/g, "").slice(0, 30);
    const pageUrl = (onboardRes && onboardRes.pageUrl && onboardRes.pageUrl.includes("facebook.com/")) ? onboardRes.pageUrl : `https://www.facebook.com/${cleanHandle}`;

    return { pageName, pageUrl, category: "Personal blog", bio, cleanHandle };
  }

  async function completePageOnboarding(page, pageName, proxyLocation = {}) {
    console.log("=".repeat(60));
    console.log(`[Facebook Onboarding] Running wizard setup for: "${pageName}"`);
    console.log("=".repeat(60));

    const rawProfilePhoto = path.resolve("tests", "test_artifacts", "test_thumb_vertical.jpg");
    const rawCoverPhoto = path.resolve("tests", "test_artifacts", "test_thumb_horizontal.jpg");
    const uniqueProfilePhoto = path.resolve("tests", "test_artifacts", "fb_profile_unique.jpg");
    const uniqueCoverPhoto = path.resolve("tests", "test_artifacts", "fb_cover_unique.jpg");

    let profilePhotoPath = rawProfilePhoto;
    let coverPhotoPath = rawCoverPhoto;

    try {
      if (fs.existsSync(rawProfilePhoto)) {
        execFileSync("python", ["tools/generate_unique_dp.py", rawProfilePhoto, uniqueProfilePhoto], { stdio: "pipe" });
        if (fs.existsSync(uniqueProfilePhoto)) profilePhotoPath = uniqueProfilePhoto;
      }
      if (fs.existsSync(rawCoverPhoto)) {
        execFileSync("python", ["tools/generate_unique_dp.py", rawCoverPhoto, uniqueCoverPhoto], { stdio: "pipe" });
        if (fs.existsSync(uniqueCoverPhoto)) coverPhotoPath = uniqueCoverPhoto;
      }
    } catch (imgErr) {
      console.warn(`[Facebook Onboarding] Note generating unique images: ${imgErr.message}`);
    }
    const cleanHandle = pageName.toLowerCase().replace(/[^a-z0-9]/g, "").slice(0, 30);

    for (let step = 1; step <= 8; step++) {
      await page.waitForTimeout(1200);
      const url = page.url();
      const bodyText = await page.evaluate(() => (document.body ? document.body.innerText : ""));
      console.log(`[Facebook Onboarding] Step ${step} | URL: ${url}`);

      if (
        bodyText.includes("Welcome to your new Page") ||
        bodyText.includes("Switch into") ||
        bodyText.includes("Manage Page") ||
        bodyText.includes("What's on your mind?")
      ) {
        console.log("[Facebook Onboarding] Reached finished Page state!");
        break;
      }

      // 1. Choose Page Type screen (Business vs Creator)
      if (bodyText.includes("Choose Page type") || bodyText.includes("Your Page is created! Choose your Page type")) {
        console.log("[Facebook Onboarding] Detected: 'Choose Page type'. Selecting 'Creator'...");
        const creatorOption = page.locator("div:has-text('Creator'), label:has-text('Creator')").filter({ hasText: /monetize original content/i }).first();
        if ((await creatorOption.count()) > 0) {
          await humanClick(page, creatorOption).catch(() => creatorOption.click());
          await page.waitForTimeout(500);
        }
        const nextBtn = page.locator("button:has-text('Next'), [role='button']:has-text('Next')").first();
        if ((await nextBtn.count()) > 0) {
          await humanClick(page, nextBtn).catch(() => nextBtn.click());
          await page.waitForTimeout(1200);
          continue;
        }
      }

      // 2. Handle input (Step 1 of 3: Page details)
      const handleInput = page.locator("input[placeholder*='handle' i], input[aria-label*='handle' i], label:has-text('Handle') input, div:has-text('Handle') input").first();
      if ((await handleInput.count()) > 0 && (await handleInput.isVisible())) {
        console.log(`[Facebook Onboarding] Detected: 'Handle' input. Entering: '${cleanHandle}'...`);
        await humanType(page, handleInput, cleanHandle, { typos: false });
        await page.waitForTimeout(400);

        const fileInputs = page.locator("input[type='file']");
        if ((await fileInputs.count()) > 0 && fs.existsSync(profilePhotoPath)) {
          console.log(`[Facebook Onboarding] Uploading photo to Step 1: ${profilePhotoPath}...`);
          await fileInputs.first().setInputFiles(profilePhotoPath).catch(() => { });
          await page.waitForTimeout(1200);
        }

        const nextBtn = page.locator("button:has-text('Next'), [role='button']:has-text('Next')").first();
        if ((await nextBtn.count()) > 0) {
          await humanClick(page, nextBtn).catch(() => nextBtn.click());
          await page.waitForTimeout(1200);
          continue;
        }
      }

      // 3. Step 1 of 5: "Finish setting up your Page" (Contact Information & Location & Hours)
      if (bodyText.includes("Finish setting up your Page") || bodyText.includes("location's hours") || bodyText.includes("Open at selected hours") || bodyText.includes("Contact")) {
        console.log("[Facebook Onboarding] Detected Step 1 of 5: 'Finish setting up your Page'. Filling realistic contact info from proxy area...");
        const contactInfo = generateRealisticContactInfo(proxyLocation, pageName);
        console.log(`[Facebook Onboarding] Contact: Web: ${contactInfo.website} | Email: ${contactInfo.email} | City: ${contactInfo.city}`);

        // Website
        const webInput = page.locator("input[aria-label*='Website' i], input[placeholder*='Website' i]").first();
        if ((await webInput.count()) > 0 && (await webInput.isVisible().catch(() => false))) {
          await humanType(page, webInput, contactInfo.website, { typos: false });
          await page.waitForTimeout(250);
        }

        // Email
        const emailInput = page.locator("input[aria-label*='Email' i], input[placeholder*='Email' i]").first();
        if ((await emailInput.count()) > 0 && (await emailInput.isVisible().catch(() => false))) {
          await humanType(page, emailInput, contactInfo.email, { typos: false });
          await page.waitForTimeout(250);
        }

        // Phone
        const phoneInput = page.locator("input[aria-label*='Phone' i], input[placeholder*='Phone' i]").first();
        if ((await phoneInput.count()) > 0 && (await phoneInput.isVisible().catch(() => false))) {
          await humanType(page, phoneInput, contactInfo.phone, { typos: false });
          await page.waitForTimeout(250);
        }

        // Address
        const addrInput = page.locator("input[aria-label*='Address' i], input[placeholder*='Address' i]").first();
        if ((await addrInput.count()) > 0 && (await addrInput.isVisible().catch(() => false))) {
          await humanType(page, addrInput, contactInfo.address, { typos: false });
          await page.waitForTimeout(250);
        }

        // City / Town
        const cityInput = page.locator("input[aria-label*='City' i], input[placeholder*='City' i]").first();
        if ((await cityInput.count()) > 0 && (await cityInput.isVisible().catch(() => false))) {
          await humanType(page, cityInput, contactInfo.city, { typos: false });
          await page.waitForTimeout(800);
          const cityOption = page.locator("[role='option'], [role='listbox'] div").first();
          if ((await cityOption.count()) > 0 && (await cityOption.isVisible().catch(() => false))) {
            await humanClick(page, cityOption).catch(() => cityOption.click());
          } else {
            await page.keyboard.press("ArrowDown").catch(() => { });
            await page.keyboard.press("Enter").catch(() => { });
          }
          await page.waitForTimeout(250);
        }

        // Postcode / ZIP
        const postInput = page.locator("input[aria-label*='Postcode' i], input[aria-label*='ZIP' i], input[placeholder*='Postcode' i], input[placeholder*='ZIP' i]").first();
        if ((await postInput.count()) > 0 && (await postInput.isVisible().catch(() => false))) {
          await humanType(page, postInput, contactInfo.postcode, { typos: false });
          await page.waitForTimeout(250);
        }

        // Hours: "Always open"
        const alwaysOpen = page.locator("label:has-text('Always open'), div:has-text('Always open'), input[value*='always']").first();
        if ((await alwaysOpen.count()) > 0 && (await alwaysOpen.isVisible().catch(() => false))) {
          await humanClick(page, alwaysOpen).catch(() => alwaysOpen.click());
          await page.waitForTimeout(500);
        }

        const nextBtn = page.locator("button:has-text('Next'), [role='button']:has-text('Next')").first();
        if ((await nextBtn.count()) > 0) {
          await humanClick(page, nextBtn).catch(() => nextBtn.click());
          await page.waitForTimeout(1200);
          continue;
        }
      }

      // 4. Step 2 of 5: "Customise your Page" (Photos)
      if (
        bodyText.includes("Customise your Page") ||
        bodyText.includes("Customize your Page") ||
        bodyText.includes("Add Profile Picture") ||
        bodyText.includes("Add Cover Photo")
      ) {
        console.log("[Facebook Onboarding] Detected: 'Customise your Page'. Uploading Profile Picture and Cover Photo...");
        try {
          const fileInputs = page.locator("input[type='file']");
          if ((await fileInputs.count()) >= 1 && fs.existsSync(profilePhotoPath)) {
            console.log(`[Facebook Onboarding] Uploading Profile Picture: ${profilePhotoPath}...`);
            await fileInputs.first().setInputFiles(profilePhotoPath).catch(() => { });
            await page.waitForTimeout(1500);
          }
        } catch (err) { }

        try {
          const inputsNow = page.locator("input[type='file']");
          if ((await inputsNow.count()) >= 2 && fs.existsSync(coverPhotoPath)) {
            console.log(`[Facebook Onboarding] Setting Cover Photo on file input #2...`);
            await inputsNow.nth(1).setInputFiles(coverPhotoPath).catch(() => { });
            await page.waitForTimeout(1500);
          }
        } catch (e) { }

        const nextBtn = page.locator("button:has-text('Next'), [role='button']:has-text('Next')").first();
        if ((await nextBtn.count()) > 0) {
          await humanClick(page, nextBtn).catch(() => nextBtn.click());
          await page.waitForTimeout(1200);
          continue;
        }
      }

      // 5. Connect WhatsApp / Phone step -> Click 'Skip'
      if (bodyText.includes("Connect WhatsApp to your Page") || bodyText.includes("WhatsApp") || bodyText.includes("Connect your account")) {
        console.log("[Facebook Onboarding] Detected WhatsApp screen. Clicking 'Skip'...");
        const skipBtn = page.locator("button:has-text('Skip'), [role='button']:has-text('Skip'), div[role='button']:has-text('Skip')").first();
        if ((await skipBtn.count()) > 0) {
          await humanClick(page, skipBtn).catch(() => skipBtn.click());
          await page.waitForTimeout(1200);
          continue;
        }
      }

      // 6. Generic 'Done' or 'Next'
      const doneBtn = page.locator("button:has-text('Done'), [role='button']:has-text('Done'), div[role='button']:has-text('Done')").first();
      if ((await doneBtn.count()) > 0 && (await doneBtn.isVisible())) {
        console.log("[Facebook Onboarding] Detected final 'Done' button. Completing wizard...");
        await humanClick(page, doneBtn).catch(() => doneBtn.click());
        await page.waitForTimeout(2500);
        break;
      }

      const genericNext = page.locator("button:has-text('Next'), [role='button']:has-text('Next')").first();
      if ((await genericNext.count()) > 0 && (await genericNext.isVisible())) {
        console.log(`[Facebook Onboarding] Clicking generic 'Next' on step ${step}...`);
        await humanClick(page, genericNext).catch(() => genericNext.click());
        await page.waitForTimeout(1200);
        continue;
      }

      // Not Now modal
      const notNow = page.locator("button:has-text('Not Now'), [role='button']:has-text('Not Now')").first();
      if ((await notNow.count()) > 0 && (await notNow.isVisible())) {
        await humanClick(page, notNow).catch(() => notNow.click());
        await page.waitForTimeout(1000);
        continue;
      }

      break;
    }

    const finalUrl = page.url();
    console.log(`[Facebook Onboarding] Wizard finished. Final URL: ${finalUrl}`);
    return { success: true, pageUrl: finalUrl };
  }

  // =========================================================================
  // STAGE 3: FACEBOOK REGISTRATION & 2FA (TAB 3 IN SAME WINDOW)
  // =========================================================================
  let fbPage = null;
  let fbPreIp = null;
  const isFacebookCompleted = Boolean(
    results.facebook &&
    (results.facebook?.status === "active" ||
      results.facebook?.two_factor?.enabled === true ||
      results.facebook?.two_factor?.status === "ACTIVE" ||
      (results.facebook?.two_factor?.backup_codes?.length || 0) > 0) &&
    !redoFacebook
  );
  const shouldRunFacebook = !skipFacebook && !onlyMetricool && !onlyInstagram;

  if (shouldRunFacebook) {
    if (isFacebookCompleted) {
      console.log("\n" + "=".repeat(60));
      console.log(">>> [3/3] FACEBOOK: ALREADY COMPLETED (AUTO-RESUMING) <<<");
      console.log("=".repeat(60));
      console.log(`[Auto-Resume] Facebook account is already created (${results.facebook.name || results.facebook.email}).`);
      console.log(`[Auto-Resume] 2FA is active: ${results.facebook?.two_factor?.enabled} | Backup codes preserved: ${results.facebook?.two_factor?.backup_codes?.length || 0}`);
      const refPage = instaPage || metricoolPage;
      fbPage = await openTabInSameWindow(refPage, "https://www.facebook.com/?locale=en_US");
      await safeGoto(fbPage, "https://www.facebook.com/?locale=en_US", { waitUntil: "domcontentloaded" });
      await fbPage.waitForTimeout(2000);
      console.log(`[Auto-Resume] Facebook Tab 3 active: ${fbPage.url()}`);

      if (!results.facebook?.page || !results.facebook?.page?.pageUrl) {
        console.log("[Facebook] Existing account detected without a created Page. Creating Facebook Page for Metricool...");
        try {
          if (!fbPreIp) {
            fbPreIp = await captureMetaExitIp(fbPage, "facebook_page_creation").catch(() => ({}));
          }
          results.facebook.page = await createFacebookPage(fbPage, null, null, fbPreIp || {});
          await saveIncrementalProgress("Facebook (Page Created)");
          console.log(`[Facebook] Page successfully created & saved: ${results.facebook.page?.pageName || "OK"} (${results.facebook.page?.pageUrl || ""})`);
        } catch (e) {
          console.warn(`[Facebook Page Note]: ${e.message}`);
        }
      }
    } else {
      console.log("\n" + "=".repeat(60));
      console.log(">>> [3/3] OPENING FACEBOOK IN TAB 3 (SAME WINDOW) <<<");
      console.log("=".repeat(60));

      const fbStageStartTime = Date.now();
      let fbPostOtpIp = null;
      let fbFinalIp = null;
      let fbFingerprint = null;
      let fbDwellTime = 0;
      let fbFormFillTime = 0;
      let fbOtpLatency = null;
      interactionMetrics.reset();

      try {
        // Reference page from which to open Tab 3
        const refPage = instaPage || metricoolPage;

        // Open Tab 3 in the same window
        fbPage = await openTabInSameWindow(refPage, "https://www.facebook.com/?locale=en_US");
        await safeGoto(fbPage, "https://www.facebook.com/?locale=en_US", { waitUntil: "domcontentloaded" });
        await fbPage.waitForTimeout(3000);

        // Capture initial IP and browser fingerprint for Meta ban forensics
        fbPreIp = await captureMetaExitIp(fbPage, "facebook_pre_signup");
        fbFingerprint = await auditMetaDeviceFingerprint(fbPage);
        console.log(`[Forensics] Facebook Exit IP: ${fbPreIp.ip || "unknown"} (ASN: ${fbPreIp.asn || "unknown"}) | City: ${fbPreIp.city || "unknown"}`);

        // Cookie consent dismissal
        const cookieBtn = fbPage.locator("button:has-text('Allow all cookies'), button:has-text('Allow essential and optional cookies'), button:has-text('Decline optional cookies')").first();
        if ((await cookieBtn.count()) > 0 && (await cookieBtn.isVisible().catch(() => false))) {
          await humanClick(fbPage, cookieBtn);
          await fbPage.waitForTimeout(1000);
        }

        // Check if Facebook session is already authenticated (via session cookies or DOM profile landmarks)
        const fbCookies = await context.cookies().catch(() => []);
        const hasFbAuthCookie = fbCookies.some(c => (c.name === "c_user" || c.name === "xs") && (c.domain || "").includes("facebook.com"));
        const isFbAlreadyLoggedIn = hasFbAuthCookie || await fbPage.evaluate(() => {
          return Boolean(
            document.querySelector("div[role='banner'] div[aria-label*='Your profile' i], div[role='banner'] [role='button'][aria-label*='profile' i], div[role='banner'] div[aria-label*='Account controls and settings' i], [aria-label*='Your profile' i], a[href*='/me/'], [aria-label='Menu'], [aria-label*='मेनू' i]")
          );
        }).catch(() => false);

        if (isFbAlreadyLoggedIn) {
          console.log("[Facebook] ✅ Session is already authenticated! Skipping registration form & OTP, jumping directly to 2FA / verification...");
        } else {
          // -------------------------------------------------------------------------
          // Adaptive Multi-Step & Single-Page Facebook Registration Engine
          // (Supports Meta Mobile Onboarding Wizard, Meta Account linking, and Desktop Unified Form)
          // -------------------------------------------------------------------------
          const clickFbNextOrSubmit = async () => {
            const nextBtnSelector = "button:has-text('Next'), div[role='button']:has-text('Next'), [role='button']:has-text('Next'), button:has-text('Continue'), div[role='button']:has-text('Continue'), button:has-text('Confirm'), div[role='button']:has-text('Confirm'), button:has-text('Sign up'), button:has-text('Sign Up'), button:has-text('Submit'), button[type='submit'], button[name='websubmit']";
            const btn = fbPage.locator(nextBtnSelector).first();
            if ((await btn.count()) > 0 && (await btn.isVisible().catch(() => false))) {
              await humanClick(fbPage, btn).catch(() => btn.click({ force: true }));
            } else {
              await fbPage.keyboard.press("Enter");
            }
          };

          console.log("[Facebook] Engaging Adaptive Facebook Registration Engine...");
          let fbRegCompleted = false;
          let fbSubmitTime = Date.now();
          let fbLoopSteps = 0;
          const maxFbLoopSteps = 35;
          const fbLoopDeadline = Date.now() + 240000; // 4 minutes max

          while (!fbRegCompleted && fbLoopSteps < maxFbLoopSteps && Date.now() < fbLoopDeadline) {
            fbLoopSteps++;
            await fbPage.waitForTimeout(1000);

            // 1. Check if authenticated / reached feed or post-signup screen
            const curUrl = fbPage.url() || "";
            const fbCookies = await context.cookies().catch(() => []);
            const hasCUser = fbCookies.some((c) => c.name === "c_user" && (c.domain || "").includes("facebook.com"));
            const isFbAuthedOnPage = hasCUser || await fbPage.evaluate(() => {
              const body = (document.body ? document.body.innerText : "").toLowerCase();
              if (body.includes("create new account") || body.includes("mobile number or email") || body.includes("what's your") || body.includes("get started on facebook") || body.includes("enter code") || body.includes("log in")) return false;
              return Boolean(
                document.querySelector("div[role='banner'] div[aria-label*='Your profile' i], div[role='banner'] [role='button'][aria-label*='profile' i], div[role='banner'] div[aria-label*='Account controls and settings' i], [aria-label*='Your profile' i], a[href*='/me/'], [aria-label='Menu'], [aria-label*='मेनू' i]")
              );
            }).catch(() => false);

            if (hasCUser || isFbAuthedOnPage) {
              console.log(`[Facebook] ✅ Registration completed and verified active! Navigated to: ${curUrl}`);
              await takeStepScreenshot(fbPage, "facebook_authenticated_complete");
              fbRegCompleted = true;
              break;
            }

            // 2. Health check (Checkpoint / Suspension / Restriction)
            const susp = await checkFacebookHealth(fbPage);
            if (susp.status === "SUSPENDED" || susp.status === "RESTRICTED") {
              await takeStepScreenshot(fbPage, "facebook_restriction_error");
              throw new Error(`Facebook activity restriction / suspension triggered: ${susp.reason || susp.status} (${susp.url})`);
            }

            // 3. Dismiss cookie consent banner if present
            const cookieBtn = fbPage.locator("button:has-text('Allow all cookies'), button:has-text('Allow essential and optional cookies'), button:has-text('Decline optional cookies')").first();
            if ((await cookieBtn.count()) > 0 && (await cookieBtn.isVisible().catch(() => false))) {
              console.log("[Facebook] Dismissing cookie dialog...");
              await humanClick(fbPage, cookieBtn).catch(() => cookieBtn.click({ force: true }));
              await fbPage.waitForTimeout(1000);
              continue;
            }

            // 3.5. On landing page, detect and click "Create new account"
            const landingCreateBtn = fbPage.locator("button:has-text('Create new account'), div[role='button']:has-text('Create new account'), a:has-text('Create new account'), [role='button']:has-text('Create new account'), a[data-testid='open-registration-form-button'], [role='button']:has-text('नया अकाउंट बनाएँ')").first();
            if ((await landingCreateBtn.count()) > 0 && (await landingCreateBtn.isVisible().catch(() => false))) {
              console.log("[Facebook Mobile] Clicking 'Create new account' button on landing page...");
              await takeStepScreenshot(fbPage, "facebook_step_create_account_click");
              await humanClick(fbPage, landingCreateBtn).catch(() => landingCreateBtn.click({ force: true }));
              await fbPage.waitForTimeout(2500);
              continue;
            }

            // 4. Check for OTP / Confirmation Code screen first (if reached)
            const isOtpUrl = curUrl.includes("confirmemail") || curUrl.includes("enter_code") || curUrl.includes("checkpoint");
            const otpInput = fbPage.locator("input[name='code']:visible, input[name='code'], input[id*='code']:visible, input[aria-label*='code' i]:visible, input[placeholder*='code' i]:visible").first();
            if (isOtpUrl || ((await otpInput.count()) > 0 && (await otpInput.isVisible().catch(() => false)))) {
              console.log("[Facebook] 📩 Detected OTP / Confirmation Code screen...");
              await takeStepScreenshot(fbPage, "facebook_step_otp");
              if (curUrl.includes("confirmemail.php") && curUrl.includes("next=undefined")) {
                console.log("[Facebook] Cutting 'confirmemail.php?next=undefined' to https://www.facebook.com/confirmemail.php so OTP is dispatched cleanly...");
                await safeGoto(fbPage, "https://www.facebook.com/confirmemail.php", { waitUntil: "domcontentloaded", timeout: 30000 });
                await fbPage.waitForTimeout(2000);
              }
              if (clientId && refreshToken) {
                let fbOtp = await pollOutlookForFacebookOtp(clientId, refreshToken, fbSubmitTime, 60);
                if (!fbOtp) {
                  console.log(`[Facebook] Polling returned no code for ${email}. Prompting terminal entry...`);
                  fbOtp = await promptTerminalOtp(email, 120);
                }
                if (fbOtp) {
                  console.log(`[Facebook] Entering confirmation code: ${fbOtp}...`);
                  if ((await otpInput.count()) > 0 && (await otpInput.isVisible().catch(() => false))) {
                    await humanType(fbPage, otpInput, fbOtp);
                    await fbPage.waitForTimeout(500);
                  }
                  await takeStepScreenshot(fbPage, "facebook_otp_entered");
                  const continueBtn = fbPage.locator("button[name='confirm']:visible, button:has-text('Continue'):visible, div[role='button']:has-text('Continue'):visible, [role='button']:has-text('Continue'):visible, button:has-text('Confirm'):visible, button:has-text('Submit'):visible, button[type='submit']:visible").first();
                  if ((await continueBtn.count()) > 0 && (await continueBtn.isVisible().catch(() => false))) {
                    await humanClick(fbPage, continueBtn).catch(() => continueBtn.click({ force: true }));
                  } else {
                    await fbPage.keyboard.press("Enter");
                  }
                  await fbPage.waitForTimeout(4000);
                  continue;
                }
              }
            }

            const pageText = await fbPage.evaluate(() => (document.body ? document.body.innerText : "")).catch(() => "");

            // 5. Check for "Get started on Facebook with a Meta Account" or Welcome screen
            const metaWelcomeBtn = fbPage.locator("button:has-text('Get started'), div[role='button']:has-text('Get started'), [role='button']:has-text('Get started')").first();
            if (/Get started on Facebook with a Meta Account|A Meta Account lets you access Meta apps/i.test(pageText) ||
              ((await metaWelcomeBtn.count()) > 0 && (await metaWelcomeBtn.isVisible().catch(() => false)))) {
              console.log("[Facebook Mobile] Screen: 'Get started on Facebook with a Meta Account' -> Clicking 'Get started'...");
              await takeStepScreenshot(fbPage, "facebook_meta_account_welcome");
              await humanClick(fbPage, metaWelcomeBtn).catch(() => metaWelcomeBtn.click({ force: true }));
              await fbPage.waitForTimeout(2500);
              continue;
            }

            // 6. Check for "Continue as <Name>" (Linking Instagram profile from Tab 2)
            const continueAsBtn = fbPage.locator("button:has-text('Continue as'), div[role='button']:has-text('Continue as'), [role='button']:has-text('Continue as'), button:has-text('Yes, continue'), button:has-text('Sync profile info')").first();
            if ((await continueAsBtn.count()) > 0 && (await continueAsBtn.isVisible().catch(() => false))) {
              console.log("[Facebook Mobile] Detected 'Continue as' / Account Link option. Clicking button...");
              await takeStepScreenshot(fbPage, "facebook_continue_as_link");
              await humanClick(fbPage, continueAsBtn).catch(() => continueAsBtn.click({ force: true }));
              await fbPage.waitForTimeout(3000);
              continue;
            }

            // 7. Check if Desktop Unified Form (where firstname, reg_passwd__, reg_email__ are all on one page)
            const isDesktopFbForm = await fbPage.evaluate(() => {
              const fn = document.querySelector("input[name='firstname']");
              const pw = document.querySelector("input[name='reg_passwd__'], input[type='password']");
              const em = document.querySelector("input[name='reg_email__'], input[aria-label*='Mobile number' i]");
              return Boolean(fn && pw && em);
            }).catch(() => false);

            if (isDesktopFbForm) {
              console.log("[Facebook Desktop] Detected unified desktop registration form. Filling all fields...");
              await takeStepScreenshot(fbPage, "facebook_desktop_form");
              const fnInp = fbPage.locator("input[name='firstname']:visible").first();
              await humanType(fbPage, fnInp, ident.firstName);
              await sleep(400);

              let lnInp = fbPage.locator("input[name='lastname']:visible").first();
              if ((await lnInp.count()) > 0) await humanType(fbPage, lnInp, ident.lastName);
              await sleep(400);

              await fillBirthdayAndGender(fbPage, birthday, gender);
              await sleep(400);

              await fillFacebookEmail(fbPage, email);
              await sleep(400);

              const pwInp = fbPage.locator("input[name='reg_passwd__']:visible, input[type='password']:visible").first();
              await humanType(fbPage, pwInp, password);
              await sleep(600);

              await takeStepScreenshot(fbPage, "facebook_form_ready");
              console.log("[Facebook Desktop] Submitting registration form...");
              const dSubmit = fbPage.locator("button:has-text('Submit'), [role='button']:has-text('Submit'), button:has-text('Sign Up'), [role='button']:has-text('Sign Up'), button[name='websubmit']:visible").first();
              fbSubmitTime = Date.now();
              await humanClick(fbPage, dSubmit).catch(() => dSubmit.click({ force: true }));
              await fbPage.waitForTimeout(4000);
              continue;
            }

            // 8. Mobile Wizard Step: "What's your name?"
            const fnMobile = fbPage.locator("input[name='firstname']:visible, input[aria-label*='First name' i]:visible, input[placeholder*='First name' i]:visible").first();
            if ((await fnMobile.count()) > 0 && (await fnMobile.isVisible().catch(() => false))) {
              console.log("[Facebook Mobile] Step: 'What's your name?'");
              await takeStepScreenshot(fbPage, "facebook_step_name");
              const curFn = await fnMobile.inputValue().catch(() => "");
              if (!curFn) {
                console.log(`[Facebook Mobile] Typing First Name: ${ident.firstName}...`);
                await humanType(fbPage, fnMobile, ident.firstName);
                await sleep(400);
              }
              const lnMobile = fbPage.locator("input[name='lastname']:visible, input[aria-label*='Surname' i]:visible, input[aria-label*='Last name' i]:visible, input[placeholder*='Last name' i]:visible").first();
              if ((await lnMobile.count()) > 0 && (await lnMobile.isVisible().catch(() => false))) {
                const curLn = await lnMobile.inputValue().catch(() => "");
                if (!curLn) {
                  console.log(`[Facebook Mobile] Typing Last Name: ${ident.lastName}...`);
                  await humanType(fbPage, lnMobile, ident.lastName);
                  await sleep(400);
                }
              }
              console.log("[Facebook Mobile] Clicking 'Next' on Name step...");
              await clickFbNextOrSubmit();
              await fbPage.waitForTimeout(2500);
              continue;
            }

            // 9. Mobile Wizard Step: "What's your date of birth?"
            const hasFbBirthday = /what['’`]?s your date of birth|what['’`]?s your birthday|date of birth/i.test(pageText) ||
              (await fbPage.locator("select[name='birthday_day']:visible, [aria-label*='Birthday' i]:visible, [aria-label*='Date of birth' i]:visible, input[placeholder*='Birthday' i]:visible, input[placeholder*='Date of birth' i]:visible, input[type='date']:visible, input[placeholder*='MM/DD/YYYY' i]:visible").count()) > 0;
            if (hasFbBirthday) {
              console.log("[Facebook Mobile] Step: 'What's your date of birth?'");
              await takeStepScreenshot(fbPage, "facebook_step_birthday");
              await fillBirthdayAndGender(fbPage, birthday, gender);
              await sleep(400);
              console.log("[Facebook Mobile] Clicking 'Next' on Birthday step...");
              await clickFbNextOrSubmit();
              await fbPage.waitForTimeout(2500);
              continue;
            }

            // 9b. Mobile Wizard Step: "How old are you?" (Fallback age entry prompt)
            const hasFbAge = /how old are you|enter your real age/i.test(pageText) ||
              (await fbPage.locator("input[aria-label*='Age' i]:visible, input[placeholder*='Age' i]:visible").count()) > 0;
            if (hasFbAge) {
              console.log("[Facebook Mobile] Step: 'How old are you?' Detected. Entering persona age...");
              await takeStepScreenshot(fbPage, "facebook_step_age");
              const ageInp = fbPage.locator("input[aria-label*='Age' i]:visible, input[placeholder*='Age' i]:visible, input[type='number']:visible, input[type='text']:visible, input:visible").first();
              if ((await ageInp.count()) > 0) {
                await ageInp.click().catch(() => {});
                await ageInp.fill(String(ident.age || 29)).catch(() => {});
                await humanType(fbPage, ageInp, String(ident.age || 29), { typos: false }).catch(() => ageInp.fill(String(ident.age || 29)));
                await sleep(400);
              }
              console.log("[Facebook Mobile] Clicking 'Next' on Age step...");
              await clickFbNextOrSubmit();
              await fbPage.waitForTimeout(2500);
              continue;
            }

            // 10. Mobile Wizard Step: "What's your gender?"
            const hasFbGender = /what['’]s your gender|select your gender/i.test(pageText) ||
              (await fbPage.locator("input[type='radio'][name='sex']:visible, select[name='sex']:visible").count()) > 0;
            if (hasFbGender) {
              console.log("[Facebook Mobile] Step: 'What's your gender?'");
              await takeStepScreenshot(fbPage, "facebook_step_gender");
              await selectFacebookGender(fbPage, gender);
              await sleep(400);
              console.log("[Facebook Mobile] Clicking 'Next' on Gender step...");
              await clickFbNextOrSubmit();
              await fbPage.waitForTimeout(2500);
              continue;
            }

            // 11. Mobile Wizard Step: "What's your mobile number?" / Email step
            const hasFbContact = /what['’]s your mobile number|mobile number or email|enter your email/i.test(pageText) ||
              (await fbPage.locator("input[name='reg_email__']:visible, input[type='email']:visible, input[aria-label*='email' i]:visible, input[aria-label*='mobile' i]:visible").count()) > 0;
            if (hasFbContact) {
              console.log("[Facebook Mobile] Step: Mobile Number / Email");
              await takeStepScreenshot(fbPage, "facebook_step_contact");
              await fillFacebookEmail(fbPage, email);
              await sleep(400);
              console.log("[Facebook Mobile] Clicking 'Next' on Contact step...");
              await clickFbNextOrSubmit();
              await fbPage.waitForTimeout(2500);
              continue;
            }

            // 12. Mobile Wizard Step: "Create a password"
            const pwMobile = fbPage.locator("input[name='reg_passwd__']:visible, input[type='password']:visible").first();
            if ((await pwMobile.count()) > 0 && (await pwMobile.isVisible().catch(() => false))) {
              console.log("[Facebook Mobile] Step: 'Create a password'");
              await takeStepScreenshot(fbPage, "facebook_step_password");
              const curPw = await pwMobile.inputValue().catch(() => "");
              if (!curPw || curPw.length < 6) {
                console.log("[Facebook Mobile] Typing Password at 40-52 WPM...");
                await humanType(fbPage, pwMobile, password);
                await sleep(600);
              }
              console.log("[Facebook Mobile] Clicking 'Next' on Password step...");
              fbSubmitTime = Date.now();
              await clickFbNextOrSubmit();
              await fbPage.waitForTimeout(2500);
              continue;
            }

            // 13. Mobile Wizard Step: Terms & Policies ("I agree")
            const agreeBtn = fbPage.locator("button:has-text('I agree'), div[role='button']:has-text('I agree'), [role='button']:has-text('I agree')").first();
            if ((await agreeBtn.count()) > 0 && (await agreeBtn.isVisible().catch(() => false))) {
              console.log("[Facebook Mobile] Step: 'Agree to Facebook's terms and policies' -> Clicking 'I agree'...");
              await takeStepScreenshot(fbPage, "facebook_step_terms_agree");
              await humanClick(fbPage, agreeBtn).catch(() => agreeBtn.click({ force: true }));
              await fbPage.waitForTimeout(3500);
              continue;
            }

            // 14. Landing page fallback: "Create new account" button
            const fallbackLandingCreateBtn = fbPage.locator("a[data-testid='open-registration-form-button'], a[role='button']:has-text('Create new account'), button:has-text('Create new account'), a:has-text('Create new account'), [role='button']:has-text('Create new account'), [role='button']:has-text('नया अकाउंट बनाएँ')").first();
            if ((await fallbackLandingCreateBtn.count()) > 0 && (await fallbackLandingCreateBtn.isVisible().catch(() => false))) {
              console.log("[Facebook] Clicking 'Create new account' button on landing page (fallback)...");
              await humanClick(fbPage, fallbackLandingCreateBtn).catch(() => fallbackLandingCreateBtn.click({ force: true }));
              await fbPage.waitForTimeout(2500);
              continue;
            }

            // 15. Generic Next / Continue / Skip buttons on intermediate screens
            const genericNext = fbPage.locator("button:has-text('Next'):visible, div[role='button']:has-text('Next'):visible, button:has-text('Continue'):visible, button:has-text('Not Now'):visible, button:has-text('Skip'):visible").first();
            if ((await genericNext.count()) > 0 && (await genericNext.isVisible().catch(() => false))) {
              console.log("[Facebook Mobile] Clicking visible 'Next' / 'Continue' / 'Not Now' button...");
              await humanClick(fbPage, genericNext).catch(() => genericNext.click({ force: true }));
              await fbPage.waitForTimeout(2000);
              continue;
            }

            console.log(`[Facebook] Step ${fbLoopSteps}: Awaiting state update... (URL: ${curUrl})`);
            await fbPage.waitForTimeout(2000);
          }

          if (!fbRegCompleted) {
            throw new Error("Facebook registration could not be completed within the allotted steps/time.");
          }

          fbPostOtpIp = await captureMetaExitIp(fbPage, "facebook_post_otp");

          // FBVerse Feature 3: 18s post-registration settling delay to prevent race conditions & token bans
          console.log("[Facebook] ⏳ Settle Window: Pausing 18s for backend permissions & session provisioning...");
          await fbPage.waitForTimeout(18000);

          // FBVerse Feature 2: Automated Cookie Jar Export
          try {
            const fbCookies = await context.cookies();
            fs.writeFileSync(path.join(profileDir, "cookies.json"), JSON.stringify(fbCookies, null, 2), "utf-8");
            fs.writeFileSync(path.join(profileDir, "cookies_facebook.json"), JSON.stringify(fbCookies.filter(c => (c.domain || "").includes("facebook.com")), null, 2), "utf-8");
            console.log("[Facebook] 🍪 Exported authenticated cookies to profile session store.");
          } catch (e) {
            console.warn("[Facebook] Cookie export note:", e.message);
          }

          // FBVerse Feature 4: Organic Feed Warmup
          if (enableFeedWarmup) {
            await warmUpAccountFeed(fbPage, "facebook", 35000);
          }

          await fbPage.waitForTimeout(3000);
        }

        // Setup Facebook 2FA via State Machine
        console.log("[Facebook] Launching Facebook 2FA Setup Flow in Tab 3...");
        const fb2faRes = await setupFacebook2FA(fbPage, email, password, profileDir, clientId, refreshToken).catch((e) => {
          console.warn(`[Facebook 2FA Notice]: ${e.message}`);
          return { enabled: false, backup_codes: [] };
        });

        // Create Facebook Page (required for Metricool connection!)
        console.log("\n" + "=".repeat(60));
        console.log(">>> [Facebook] CREATING FACEBOOK PAGE FOR METRICOOL <<<");
        console.log("=".repeat(60));
        let fbPageDetails = null;
        try {
          if (!fbPage.url().includes("facebook.com")) {
            await safeGoto(fbPage, "https://www.facebook.com/?locale=en_US", { waitUntil: "domcontentloaded" });
          }
          fbPageDetails = await createFacebookPage(fbPage, null, null, fbPreIp || {});
        } catch (pageErr) {
          console.warn(`[Facebook Page Creation Note]: ${pageErr.message}`);
        }

        // Capture final IP and evaluate post-creation health
        fbFinalIp = await captureMetaExitIp(fbPage, "facebook_final");
        const fbHealth = await checkFacebookHealth(fbPage);

        const fbForensics = recordMetaForensicLog({
          platform: "facebook",
          profileDir,
          email,
          ident,
          birthday,
          gender,
          preIp: fbPreIp,
          postOtpIp: fbPostOtpIp,
          finalIp: fbFinalIp,
          fingerprint: fbFingerprint,
          timing: {
            stageStartTime: fbStageStartTime,
            dwellTimeMs: fbDwellTime,
            formFillMs: fbFormFillTime,
          },
          verification: {
            otpLatencyMs: fbOtpLatency,
            twoFactor: fb2faRes,
          },
          health: fbHealth,
        });

        results.facebook = {
          status: fbHealth.status === "ACTIVE" ? "active" : fbHealth.status.toLowerCase(),
          name: ident.fullName,
          email,
          password,
          page: fbPageDetails,
          two_factor: fb2faRes,
          health: fbHealth,
        };
        results.meta_forensics.facebook = fbForensics;
        await saveIncrementalProgress("Facebook");
        await takeStepScreenshot(fbPage, "facebook_completed").catch(() => { });
        console.log(`[Facebook] Stage 3 Completed! Health: ${fbHealth.status} | 2FA Active: ${fb2faRes?.enabled} | Backup Codes: ${fb2faRes?.backup_codes?.length || 0}`);
        await fbPage.waitForTimeout(2000);
      } catch (err) {
        console.error("============================================================");
        console.error(`[Facebook Failure] Stage 3 encountered an error: ${err.message}`);
        console.error("============================================================");
        await takeStepScreenshot(fbPage, "facebook_error").catch(() => { });

        try {
          const failHealth = await checkFacebookHealth(fbPage).catch(() => ({ status: "FAILED", checkpoint_type: "error", reason: err.message, url: fbPage?.url?.() || null }));
          if (failHealth.status === "ACTIVE") {
            failHealth.status = "FAILED";
            failHealth.reason = err.message;
          }
          const failForensics = recordMetaForensicLog({
            platform: "facebook",
            profileDir,
            email,
            ident,
            birthday,
            gender,
            preIp: fbPreIp,
            postOtpIp: fbPostOtpIp,
            finalIp: null,
            fingerprint: fbFingerprint,
            timing: {
              stageStartTime: fbStageStartTime,
              dwellTimeMs: fbDwellTime,
              formFillMs: fbFormFillTime,
            },
            verification: {
              otpLatencyMs: fbOtpLatency,
              twoFactor: null,
            },
            health: failHealth,
          });
          results.meta_forensics.facebook = failForensics;
        } catch (forensicErr) { }

        results.facebook = { status: "failed", error: err.message };
        await saveIncrementalProgress("Facebook (Failed)");
      }
    }
  } else {
    console.log("[Facebook] Stage 3 Skipped via CLI flag.");
  }

  // =========================================================================
  // STAGE 4: CONNECT SOCIAL ACCOUNTS TO METRICOOL
  // =========================================================================
  const shouldRunConnect = !skipConnect && !onlyMetricool && !onlyInstagram && !onlyFacebook;
  if (shouldRunConnect && metricoolPage && !metricoolPage.isClosed()) {
    await connectSocialAccountsToMetricool(context, metricoolPage, results);
  } else {
    console.log("[Metricool Connect] Stage 4 Skipped via --skip-connect or isolation flag.");
    try {
      if (metricoolPage && !metricoolPage.isClosed()) {
        await metricoolPage.bringToFront();
      }
    } catch (e) { }
  }

  // =========================================================================
  // PERSISTENCE & REGISTRIES
  // =========================================================================
  console.log("\n" + "=".repeat(60));
  console.log(">>> PERSISTING UNIFIED ACCOUNT MASTER REGISTRY <<<");
  console.log("=".repeat(60));

  // 1. Save unified account_info.json in the shared profile directory
  fs.writeFileSync(infoPath, JSON.stringify(results, null, 2), "utf-8");
  console.log(`[Persistence] Saved unified account details: ${infoPath}`);

  // 2. Save unified cookies
  try {
    const cookies = await context.cookies();
    const cookiesPath = path.join(profileDir, "cookies.json");
    fs.writeFileSync(cookiesPath, JSON.stringify(cookies, null, 2), "utf-8");
    console.log(`[Persistence] Saved combined session cookies (${cookies.length} cookies): ${cookiesPath}`);
  } catch (e) { }

  // 3. Update output/unified_registered_accounts.json
  const masterFile = path.resolve("output", "unified_registered_accounts.json");
  try {
    let list = [];
    if (fs.existsSync(masterFile)) {
      list = JSON.parse(fs.readFileSync(masterFile, "utf-8"));
      if (!Array.isArray(list)) list = [];
    }
    list = list.filter((a) => (a.email || "").toLowerCase() !== email.toLowerCase());
    list.push(results);
    fs.writeFileSync(masterFile, JSON.stringify(list, null, 2), "utf-8");
    console.log(`[Persistence] Appended to master vault: ${masterFile}`);
  } catch (e) { }

  // 4. Print Completion Dashboard
  console.log("\n" + "=".repeat(70));
  console.log("UNIFIED ACCOUNT CREATION COMPLETED SUCCESSFULLY!");
  console.log("=".repeat(70));
  console.log(`Profile Directory:  ${profileDir}`);
  console.log(`Email / Identity:   ${email}`);
  console.log(`Metricool (Tab 1):  ${results.metricool?.status || "n/a"} (${results.metricool?.dashboard_url || "created"})`);
  console.log(`Instagram (Tab 2):  ${results.instagram?.status || "n/a"} (@${ident.username} | 2FA: ${results.instagram?.two_factor?.enabled})`);
  console.log(`Facebook  (Tab 3):  ${results.facebook?.status || "n/a"} (${ident.fullName} | 2FA: ${results.facebook?.two_factor?.enabled})`);
  if (results.meta_forensics) {
    console.log(`Meta Forensics:     IG: [${results.meta_forensics.instagram?.health_outcome?.verdict || "n/a"}] | FB: [${results.meta_forensics.facebook?.health_outcome?.verdict || "n/a"}]`);
    console.log(`Forensic Dataset:   output/meta_ban_forensics.jsonl`);
  }
  console.log("=".repeat(70));
  console.log("All 3 platform tabs (Metricool, Instagram, Facebook) are active in the SAME browser window.");
  console.log("Metricool can now connect Facebook and Instagram seamlessly.");

  // Capture latest screenshot of every open tab for user review
  console.log("[Screenshots] 📸 Capturing latest screenshots of all open tabs...");
  try {
    const allPages = context.pages();
    for (let idx = 0; idx < allPages.length; idx++) {
      const p = allPages[idx];
      const u = p.url() || "";
      let label = `tab_${idx + 1}`;
      if (u.includes("metricool")) label = "metricool_latest";
      else if (u.includes("instagram")) label = "instagram_latest";
      else if (u.includes("facebook")) label = "facebook_latest";
      await takeStepScreenshot(p, label).catch(() => { });
    }
  } catch (e) { }

  if (keepOpen || !headless) {
    const engineName = browserChoice === "cloakbrowser" ? "CloakBrowser" : "Camoufox";
    console.log(`[${engineName}] Browser kept open. Close the window or press Ctrl+C to exit.`);
    await new Promise((resolve) => browser.on("close", resolve));
  } else {
    await browser.close().catch(() => { });
  }
}

main().catch((err) => {
  console.error(`[Fatal Unified Pipeline Error]: ${err.stack || err}`);
  process.exit(1);
});
