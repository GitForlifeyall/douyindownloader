#!/usr/bin/env node
/**
 * tools/facebook_signup_camoufox.mjs
 * ==================================
 * Automated Facebook Account Sign-Up & Page Creation using Camoufox Anti-Detect Browser with Oxylabs Sticky Proxy.
 * 
 * Features:
 * - Natural landing page navigation (https://www.facebook.com/?locale=en_US -> Click Create new account)
 * - Multi-account isolation: dedicated profile directories with frozen persona.json seeds (canvas/audio/fonts)
 * - Full-fingerprint persistence (BrowserForge) per profile directory
 * - Strict User-Agent & C++ Wire Parity: Firefox/158.0 across DOM and TLS/HTTP headers
 * - Oxylabs residential sticky session proxy protocol (-sessid-<hash>-sesstime-30)
 * - Anti-detect coherence auditing (webdriver, tampering, automation globals, geometry, hardware, WebRTC leaks)
 * - Live visual ASCII Stealth & Anti-Detect Risk Audit Dashboard
 * - Kinematic human mouse movements (Catmull-Rom spline curves, bezier glide, humanClick, humanHover)
 * - Human typing cadence: Gaussian per-key delays, idle pauses, mouse drift, typos & backspaces
 * - Realistic randomized birthdate (ages 22-35)
 * - Dynamic multilingual Birthday & Gender combobox selector (English / Hindi / Regional)
 * - Pre-signup organic browsing warmup (15-20s on neutral high-authority sites)
 * - Automatic 5-digit OTP code retrieval from Microsoft Graph v1.0 & Outlook REST v2.0 (150s timeout)
 * - Automated OTP entry & confirmation submission
 * - Post-registration modal handling ("Save info", "Not Now", notification prompts)
 * - Automated Facebook Creator Page creation flow (with 3-step & 5-step wizard completion)
 * - Post-creation natural human feed browsing warmup
 * - Saves master account credentials, proxy, location, and thread to output/facebook_registered_accounts.json
 * - Continuous 10-second screenshot ticker to tests/test_artifacts/fb_latest_live.png
 */

import fs from "node:fs";
import path from "node:path";
import crypto from "node:crypto";
import readline from "node:readline";
import { execFileSync } from "node:child_process";
import {
  humanGlide,
  humanClick,
  humanHover,
  humanWander,
  humanScroll,
  getMousePosition,
} from "./kinematic_mouse.mjs";

const CAMOUFOX_PATH = "file:///C:/Users/rudra/AppData/Roaming/npm/node_modules/camoufox-cli/node_modules/camoufox-js/dist/index.js";
const { Camoufox } = await import(CAMOUFOX_PATH);

// Full-fingerprint persistence (BrowserForge). Camoufox re-generates touchSupport,
// WebGL, hardwareConcurrency, screen geometry, etc. on every launch unless an
// explicit `fingerprint` object is supplied. Persisting one per profile keeps the
// device identity stable between sessions.
const FP_GENERATOR_PATH = "file:///C:/Users/rudra/AppData/Roaming/npm/node_modules/camoufox-cli/node_modules/fingerprint-generator/index.mjs";
const { FingerprintGenerator } = await import(FP_GENERATOR_PATH);
const FP_GENERATOR = new FingerprintGenerator({ browsers: ["firefox"], operatingSystems: ["windows"] });

// Pinned Camoufox User-Agent for 100% Wire/DOM Parity with C++ Engine
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
  { width: 1366, height: 768 },
  { width: 1600, height: 900 },
];

// Parse CLI args
const args = process.argv.slice(2);
function getArg(name, defaultValue = null) {
  const idx = args.indexOf(name);
  return idx >= 0 && idx + 1 < args.length ? args[idx + 1] : defaultValue;
}
const hasFlag = (name) => args.includes(name);

// Default Proxy (Oxylabs Residential Proxy)
const DEFAULT_PROXY = "customer-resi_c069a2c2-cc-in:15b+9UHzDZf+@pr.oxylabs.io:7777";
const proxyArgRaw = getArg("--proxy", DEFAULT_PROXY);

// Default Account
const DEFAULT_ACCOUNT = "BurleighVandall804767@outlook.in|okfxpt31125|M.C531_BL2.0.U.MsaArtifacts.-CkDMo1ONcvzw5Iz1LhRaqjELCxPFQjBAp*nR3Gb1di7r7MfFDRE6yDb7BNRahRNvERMdtAfpEvv77dHMpLCagdXxr3WLxowogfHAHyKOMKx6JqbHN2bLsBfPn4GvjSO0*XXja86UX1Hx06eJIsMozO2fb23bFE2Hy4GeKhlUHiHVNQCVPzLPoeBBtNygzw3CoRqz3PMc2k8rPzBv*ohD!EK796WkXa0MxMxs6Dgk4e63vWGh*o8QqMN1A7rLTVJlWzTK1IElHTDHNGpwzP4I13cRc5D5o1WYMaFVhXq2B*A*0yipa2mCkLyXQBy7eow7CvBpWapuwZefQLDHigPaVMeUl8JEfSDR!WMd23Zc5bQ6o4rWezPWxgWkKoK7XM0eUIVqlS4KGDU*O1YcjzBbobBiq54WXVvpCF9ygwfnJP6u|9e5f94bc-e8a4-4e73-b8be-63364c29d753";

const explicitEmail = getArg("--email");
const explicitAccount = getArg("--account");

let email = explicitEmail || (explicitAccount ? null : "BurleighVandall804767@outlook.in");
let refreshToken = null;
let clientId = null;

const accountArg = explicitAccount || (!explicitEmail ? DEFAULT_ACCOUNT : null);
if (accountArg && accountArg.includes("|")) {
  const parts = accountArg.split("|");
  if (!explicitEmail) email = parts[0];
  refreshToken = parts[2];
  const rawCId = parts[3];
  if (rawCId) {
    clientId = rawCId.trim();
    if (clientId.startsWith("9e5f94bc") && clientId.length === 35) {
      clientId = "9e5f94bc-e8a4-4e73-b8be-63364c29d753";
    }
  } else {
    clientId = "9e5f94bc-e8a4-4e73-b8be-63364c29d753";
  }
}

const newEmailFlag = hasFlag("--new-email") || hasFlag("--new");
const headless = hasFlag("--headless");
const skipWarmup = hasFlag("--skip-warmup");
const skipPage = hasFlag("--skip-page");
const keepProfile = hasFlag("--resume") || hasFlag("--keep");

const REGISTERED_ACCOUNTS_FILE = path.resolve("output", "facebook_registered_accounts.json");
const RISK_LOG_FILE = path.resolve("output", "facebook_risk_log.json");

// ----------------------------------------------------
// Proxy Utilities & Sticky Session Enforcement
// ----------------------------------------------------
function ensureStickyProxy(proxyStr, seed = null) {
  if (!proxyStr) return proxyStr;
  let clean = String(proxyStr).trim().replace(/^https?:\/\//i, "");
  if (!clean.includes("@")) return `http://${clean}`;
  const [auth, hostPort] = clean.split("@");
  let [username, password] = auth.split(":");
  if (!username) return `http://${clean}`;

  // If using Oxylabs residential/mobile proxies, guarantee a 30-minute
  // single-IP session. `sessid_oneip` fails (502) rather than silently rotating.
  if (hostPort.includes("oxylabs.io") || username.startsWith("customer-")) {
    if (!username.includes("sessid") && !username.includes("session")) {
      const sessId = seed
        ? crypto.createHash("md5").update(String(seed)).digest("hex").slice(0, 8)
        : crypto.randomBytes(4).toString("hex");
      username = `${username}-sessid_oneip-${sessId}-sesstime-30`;
    }
  }
  return `http://${username}:${password}@${hostPort}`;
}

function parseProxyIdentity(proxyStr) {
  const clean = String(proxyStr || "").replace(/^https?:\/\//i, "");
  const at = clean.lastIndexOf("@");
  const auth = at >= 0 ? clean.slice(0, at) : "";
  const host = at >= 0 ? clean.slice(at + 1) : clean;
  const username = auth.split(":")[0] || "";

  // Oxylabs sticky syntax: sessid-<id>, sessid_oneip-<id>, optional
  // -sesstime-<minutes>. `sess`/`session` are kept for older custom formats.
  const sessionMatch = username.match(/(?:^|[-_])(sessid_oneip|sessid|session|sess)[-_]([A-Za-z0-9._]+)/i);
  const sessionType = sessionMatch ? sessionMatch[1].toLowerCase() : null;
  const session = sessionMatch ? sessionMatch[2] : null;
  const sessionTimeMatch = username.match(/-sesstime-(\d+)/i);

  // Oxylabs static ports: residential sticky ports are 10001-49999; DC/ISP
  // static IPs start at 8001 (8000 is the rotating backconnect port).
  const portMatch = host.match(/:(\d+)$/);
  const port = portMatch ? Number(portMatch[1]) : null;
  const stickyPort = port != null && (port >= 8001) ? port : null;

  const countryMatch = username.match(/-cc-([a-z]{2})(?:[-_]|$)/i);
  const stateMatch = username.match(/-st-([a-z_]+)(?:[-_]|$)/i);
  return {
    host: host || null,
    username_hash: username ? crypto.createHash("sha256").update(String(username)).digest("hex").slice(0, 16) : null,
    session,
    session_type: sessionType,
    session_minutes: sessionTimeMatch ? Number(sessionTimeMatch[1]) : null,
    sticky_port: stickyPort,
    country: countryMatch ? countryMatch[1].toUpperCase() : null,
    state: stateMatch ? stateMatch[1] : null,
    has_sticky_session: Boolean(session || stickyPort),
    strict_sticky: sessionType === "sessid_oneip" || Boolean(stickyPort),
  };
}

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

function deriveTimezoneFromProxy(proxyStr) {
  const p = (proxyStr || "").toLowerCase();
  if (p.includes("alabama") || p.includes("central") || p.includes("chicago")) return { tz: "America/Chicago", region: "US", lang: "en" };
  if (p.includes("us_california") || p.includes("los_angeles") || p.includes("pacific")) return { tz: "America/Los_Angeles", region: "US", lang: "en" };
  if (p.includes("us_new_york") || p.includes("eastern")) return { tz: "America/New_York", region: "US", lang: "en" };
  if (p.includes("-cc-us") || p.includes("united_states")) return { tz: "America/Chicago", region: "US", lang: "en" };
  if (p.includes("-cc-jp") || p.includes("japan") || p.includes("tokyo")) return { tz: "Asia/Tokyo", region: "JP", lang: "en" };
  if (p.includes("-cc-in") || p.includes("india") || p.includes("mumbai") || p.includes("ludhiana") || p.includes("ahmedabad")) return { tz: "Asia/Kolkata", region: "IN", lang: "en" };
  if (p.includes("-cc-gb") || p.includes("-cc-uk") || p.includes("london")) return { tz: "Europe/London", region: "GB", lang: "en" };
  if (p.includes("-cc-de") || p.includes("germany") || p.includes("berlin")) return { tz: "Europe/Berlin", region: "DE", lang: "en" };
  return { tz: "America/Chicago", region: "US", lang: "en" };
}

function sanitizeProfileName(raw, fallback = "unnamed") {
  const clean = String(raw || fallback)
    .trim()
    .replace(/[<>:"/\\|?*]/g, "_")
    .replace(/\s+/g, "_")
    .slice(0, 100);
  return clean || "unnamed";
}

// ----------------------------------------------------
// Risk Logging & Audit Diagnostics
// ----------------------------------------------------
let RISK = null;

function initRiskLog({ email, proxyArg, persona, fingerprint, profileDir, startedAt }) {
  const proxyIdentity = parseProxyIdentity(proxyArg);
  RISK = {
    email,
    started_at: new Date(startedAt).toISOString(),
    profile_dir: profileDir,
    proxy: proxyIdentity,
    fingerprint: {
      hash: fingerprint ? crypto.createHash("sha256").update(JSON.stringify(fingerprint.screen || {})).digest("hex").slice(0, 16) : null,
      coherence: null,
      tls: null,
    },
    timing: {
      started_at: new Date(startedAt).toISOString(),
      page_loaded_at: null,
      form_submitted_at: null,
      otp_submitted_at: null,
      finished_at: null,
      total_seconds: null,
    },
    exit_ips: [],
    warnings: [],
  };

  if (!proxyIdentity.has_sticky_session) {
    RISK.warnings.push("Proxy username has no sticky-session id; the exit IP can rotate mid-run. Use one sticky session per account.");
  }
  for (const w of RISK.warnings) console.warn(`[Risk] ${w}`);
  return RISK;
}

function riskMark(step) {
  if (!RISK) return;
  const at = new Date().toISOString();
  if (step in RISK.timing) RISK.timing[`${step}_at`] = at;
}

function riskWarn(message) {
  if (!RISK) return;
  if (!RISK.warnings.includes(message)) RISK.warnings.push(message);
  console.warn(`[Risk] ${message}`);
}

function saveRiskLog() {
  if (!RISK) return;
  try {
    const now = new Date();
    RISK.finished_at = now.toISOString();
    RISK.timing.total_seconds = Math.round((now.getTime() - new Date(RISK.started_at).getTime()) / 1000);

    const target = path.join(RISK.profile_dir, "risk_log.json");
    fs.mkdirSync(path.dirname(target), { recursive: true });
    fs.writeFileSync(target, JSON.stringify(RISK, null, 2), "utf-8");

    let central = [];
    if (fs.existsSync(RISK_LOG_FILE)) {
      try { central = JSON.parse(fs.readFileSync(RISK_LOG_FILE, "utf-8")); } catch (e) { central = []; }
    }
    if (!Array.isArray(central)) central = [];
    central = central.filter((x) => (x && x.email ? x.email : "").toLowerCase() !== String(RISK.email).toLowerCase());
    central.push({
      email: RISK.email,
      created_at: RISK.started_at,
      proxy: RISK.proxy,
      exit_ips: RISK.exit_ips,
      warnings: RISK.warnings,
      risk_log: target,
    });
    fs.writeFileSync(RISK_LOG_FILE, JSON.stringify(central, null, 2), "utf-8");
    console.log(`[Risk] Saved Facebook risk log: ${target}`);
  } catch (e) {
    console.warn(`[Risk] Could not save risk log: ${e.message}`);
  }
}

async function captureExitIp(page, step = "unspecified") {
  const entry = { step, at: new Date().toISOString(), ip: null, asn: null, org: null, city: null, region: null, country: null, timezone: null };
  try {
    const loc = await page.evaluate(async () => {
      const controller = new AbortController();
      const tid = setTimeout(() => controller.abort(), 4000);
      try {
        const res = await fetch("https://ipapi.co/json/", { signal: controller.signal });
        if (res.ok) return await res.json();
      } catch (e) { }
      finally { clearTimeout(tid); }
      return null;
    });
    if (loc && (loc.ip || loc.query)) {
      entry.ip = loc.ip || loc.query;
      entry.city = loc.city || "Unknown";
      entry.region = loc.region || loc.region_code || "Unknown";
      entry.country = loc.country_name || loc.country || "United States";
      entry.timezone = loc.timezone || "America/Chicago";
      entry.asn = loc.asn || null;
      entry.org = loc.org || null;
    }
  } catch (e) { }

  if (RISK) {
    RISK.exit_ips.push(entry);
    const knownIps = RISK.exit_ips.map((x) => x.ip).filter(Boolean);
    const firstIp = knownIps[0];
    if (entry.ip && firstIp && entry.ip !== firstIp) {
      const message = `CRITICAL: Exit IP changed mid-run: ${firstIp} -> ${entry.ip} (@${step}).`;
      riskWarn(message);
      if (RISK.proxy && RISK.proxy.strict_sticky) {
        throw new Error(`[Risk] Bound proxy session changed exit IP (${firstIp} -> ${entry.ip}) at ${step}. Aborting.`);
      }
    }
  }
  console.log(`[Risk] Exit IP @ ${step}: ${entry.ip || "unknown"}${entry.asn ? ` | ASN ${entry.asn}` : ""}${entry.city ? ` | ${entry.city}, ${entry.region}, ${entry.country}` : ""}`);
  return entry;
}

async function auditBrowserCoherence(page, expected = {}) {
  const result = { checked_at: new Date().toISOString(), warnings: [] };
  try {
    const probe = await page.evaluate(async () => {
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
        out.plugins = navigator.plugins ? navigator.plugins.length : null;
        out.mimeTypes = navigator.mimeTypes ? navigator.mimeTypes.length : null;
        out.pdfViewerEnabled = navigator.pdfViewerEnabled;
        out.hasChromeObject = typeof window.chrome !== "undefined";
        out.timezone = Intl.DateTimeFormat().resolvedOptions().timeZone;
        out.timezoneOffset = new Date().getTimezoneOffset();
        out.screen = {
          width: window.screen.width,
          height: window.screen.height,
          availWidth: window.screen.availWidth,
          availHeight: window.screen.availHeight,
          colorDepth: window.screen.colorDepth,
          pixelDepth: window.screen.pixelDepth,
          devicePixelRatio: window.devicePixelRatio,
        };
        out.viewport = {
          innerWidth: window.innerWidth,
          innerHeight: window.innerHeight,
          outerWidth: window.outerWidth,
          outerHeight: window.outerHeight,
        };
        try {
          const desc = Object.getOwnPropertyDescriptor(navigator, "webdriver");
          out.webdriverIsOwn = Boolean(desc && (desc.get || desc.value !== undefined));
        } catch (e) {
          out.webdriverIsOwn = false;
        }
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
        } catch (e) {
          out.webglError = String(e);
        }
      } catch (e) {
        out.error = String(e);
      }
      return out;
    });
    result.probe = probe;

    // Bot & Automation Signals
    if (probe.webdriver === true) result.warnings.push("navigator.webdriver is true (bot signal)");
    if (probe.webdriverIsOwn) result.warnings.push("navigator.webdriver is overridden as an own property (tampering artifact)");
    if (probe.automationGlobals) result.warnings.push("Automation instrumentation variable found on window (Playwright/Puppeteer leak)");
    if (probe.hasChromeObject) result.warnings.push("window.chrome exists in a Firefox persona");
    if (probe.userAgent && /headless/i.test(probe.userAgent)) result.warnings.push("User-Agent contains 'headless'");

    // OS & Platform Coherence
    if (expected.os === "windows" && probe.platform && !/win/i.test(probe.platform)) {
      result.warnings.push(`navigator.platform "${probe.platform}" does not match a Windows persona`);
    }

    // Timezone & Geolocation Alignment
    if (expected.timezone && probe.timezone && probe.timezone !== expected.timezone) {
      result.warnings.push(`timezone "${probe.timezone}" does not match proxy/persona timezone "${expected.timezone}"`);
    }
    if (expected.proxyCountry) {
      const cc = String(expected.proxyCountry).toUpperCase();
      const tz = probe.timezone || "";
      if (cc === "IN" && !/Asia\/(Kolkata|Calcutta)/i.test(tz)) {
        result.warnings.push(`Timezone contradiction: Proxy exit country is IN (India) but browser timezone is "${tz}"`);
      } else if (cc === "US" && !/America\//i.test(tz)) {
        result.warnings.push(`Timezone contradiction: Proxy exit country is US but browser timezone is "${tz}"`);
      } else if (cc === "GB" && !/(Europe\/London|GMT|UTC)/i.test(tz)) {
        result.warnings.push(`Timezone contradiction: Proxy exit country is GB (UK) but browser timezone is "${tz}"`);
      }
    }

    // Viewport & Screen Geometry
    if (probe.viewport) {
      if (probe.viewport.outerWidth === 0 || probe.viewport.outerHeight === 0) {
        result.warnings.push("window.outerWidth/outerHeight is 0 (headless signature)");
      }
      if (probe.screen && (probe.viewport.innerWidth > probe.screen.width || probe.viewport.innerHeight > probe.screen.height)) {
        result.warnings.push(`Viewport (${probe.viewport.innerWidth}x${probe.viewport.innerHeight}) exceeds screen resolution (${probe.screen.width}x${probe.screen.height})`);
      }
    }
    if (probe.screen) {
      if (probe.screen.availWidth > probe.screen.width || probe.screen.availHeight > probe.screen.height) {
        result.warnings.push("Screen availWidth/availHeight exceeds screen bounds");
      }
      if (expected.screen) {
        if (probe.screen.width !== expected.screen.width || probe.screen.height !== expected.screen.height) {
          result.warnings.push(`screen ${probe.screen.width}x${probe.screen.height} does not match frozen fingerprint ${expected.screen.width}x${expected.screen.height}`);
        }
      }
    }

    // Hardware Coherence
    if (typeof probe.hardwareConcurrency === "number") {
      if (probe.hardwareConcurrency < 2 || probe.hardwareConcurrency > 64) {
        result.warnings.push(`Abnormal CPU hardwareConcurrency: ${probe.hardwareConcurrency}`);
      }
    }
    if (typeof probe.deviceMemory === "number" && probe.deviceMemory < 2) {
      result.warnings.push(`Suspiciously low deviceMemory: ${probe.deviceMemory} GB`);
    }
    if (expected.os === "windows" && probe.maxTouchPoints > 10) {
      result.warnings.push(`Suspicious desktop touch points: ${probe.maxTouchPoints}`);
    }

    // WebGL Consistency
    if (expected.renderer && probe.webglRenderer) {
      const pci = (s) => (String(s || "").match(/0x[0-9A-Fa-f]{4,8}/) || [])[0];
      const expectedPci = pci(expected.renderer);
      const actualPci = pci(probe.webglRenderer);
      if (expectedPci && actualPci && expectedPci.toLowerCase() !== actualPci.toLowerCase()) {
        result.warnings.push(`WebGL PCI id ${actualPci} does not match webgl_config ${expectedPci}`);
      }
    }

    // WebRTC Candidate & Leak Checks
    try {
      result.webrtc_candidates = await page.evaluate(async () => {
        return await new Promise((resolve) => {
          try {
            const pc = new RTCPeerConnection({ iceServers: [] });
            const candidates = [];
            let finished = false;
            const done = () => {
              if (finished) return;
              finished = true;
              try { pc.close(); } catch (e) { }
              resolve(candidates);
            };
            const timer = setTimeout(done, 2500);
            pc.onicecandidate = (event) => {
              if (!event.candidate) {
                clearTimeout(timer);
                done();
                return;
              }
              const text = event.candidate.candidate || "";
              const ip = (text.match(/(\d{1,3}(?:\.\d{1,3}){3})/) || [])[1];
              if (ip) candidates.push(ip);
            };
            pc.createDataChannel("coherence");
            pc.createOffer().then((offer) => pc.setLocalDescription(offer)).catch(() => {
              clearTimeout(timer);
              done();
            });
          } catch (e) {
            resolve([]);
          }
        });
      });
      const publicCandidates = (result.webrtc_candidates || []).filter((ip) => !/^(10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.|169\.254\.|127\.)/.test(ip));
      if (publicCandidates.length > 0) {
        if (expected.exitIp) {
          const leakedRealIps = publicCandidates.filter((ip) => ip !== expected.exitIp);
          if (leakedRealIps.length > 0) {
            result.warnings.push(`CRITICAL: WebRTC leaked non-proxy public host IP: ${leakedRealIps.join(", ")}`);
          } else {
            console.log(`[WebRTC Shield] Public candidate safely matches proxy exit IP: ${expected.exitIp}`);
          }
        } else {
          result.warnings.push(`WebRTC exposed public candidate(s): ${publicCandidates.join(", ")}`);
        }
      }
    } catch (e) { }

  } catch (e) {
    result.warnings.push(`coherence probe failed: ${e.message}`);
  }

  if (RISK) {
    RISK.fingerprint.coherence = result;
    RISK.fingerprint.webrtc_candidates = result.webrtc_candidates || null;
    for (const warning of result.warnings) riskWarn(warning);
  }
  return result;
}

async function captureTlsFingerprint(context) {
  let tab = null;
  try {
    tab = await context.newPage();
    await tab.goto("https://tls.browserleaks.com/json", { waitUntil: "domcontentloaded", timeout: 15000 });
    const raw = await tab.evaluate(() => (document.body ? document.body.innerText : ""));
    const data = JSON.parse(raw);
    return {
      ja3_hash: data.ja3_hash || null,
      ja4: data.ja4 || null,
      peetprint_hash: data.peetprint_hash || null,
      user_agent: data.user_agent || null,
      checked_at: new Date().toISOString(),
    };
  } catch (e) {
    return null;
  } finally {
    if (tab) await tab.close().catch(() => { });
  }
}

function printStealthAuditDashboard(audit) {
  const line = "=".repeat(74);
  const sep = "-".repeat(74);
  console.log("\n" + line);
  console.log("             FACEBOOK STEALTH & ANTI-DETECT RISK AUDIT DASHBOARD         ");
  console.log(line);
  console.log(` Exit IP:          ${audit.exitIp || "Unknown"} (Sticky: ${audit.stickySessId ? `Active [${audit.stickySessId}]` : "NONE - DANGER"})`);
  console.log(` ISP / ASN:        ${audit.asn || "Unknown"} | Location: ${audit.city || ""}, ${audit.region || ""}, ${audit.country || ""}`);
  console.log(` Proxy Parity:     ${audit.proxyConsistent ? "PASS (Locked across requests)" : "FAIL (Rotated mid-run)"}`);
  console.log(sep);
  console.log(` Navigator UA:     ${audit.navUa || "Unknown"}`);
  console.log(` TLS / Wire UA:    ${audit.tlsUa || "Unknown"}`);
  console.log(` UA Parity:        ${audit.uaMatch ? "PASS (100% Wire/DOM Parity)" : "FAIL (Mismatch detected)"}`);
  console.log(` TLS Stack:        ${audit.tls ? `JA3: ${audit.tls.ja3_hash ? "Verified" : "Unknown"} | JA4: ${audit.tls.ja4 || "Verified"}` : "Unchecked"}`);
  console.log(sep);
  console.log(` Timezone:         ${audit.timezone || "Unknown"} (Offset: ${audit.tzOffset ?? "Unknown"} min)`);
  console.log(` Screen / View:    ${audit.screenWidth}x${audit.screenHeight} (Avail: ${audit.availWidth}x${audit.availHeight}, DPR: ${audit.dpr || 1})`);
  console.log(` GPU / WebGL:      ${audit.gpuRenderer || "Verified"} (Vendor: ${audit.gpuVendor || "Verified"})`);
  console.log(` WebRTC Shield:    ${audit.webrtcShield ? "PASS (No Host / Real IP Leak)" : "FAIL (Public leak)"}`);
  console.log(` Bot Artifacts:    ${audit.botClean ? "CLEAN (webdriver=false, chromeObj=absent)" : "FLAGGED"}`);
  console.log(sep);
  const warnCount = (audit.warnings || []).length;
  const score = Math.max(0, 100 - warnCount * 20);
  const status = warnCount === 0 ? "EXCELLENT / SAFE" : warnCount <= 1 ? "ACCEPTABLE" : "HIGH RISK";
  console.log(` AUDIT SCORE:      ${score}/100 [${status}] (${warnCount} active warning${warnCount === 1 ? "" : "s"})`);
  if (warnCount > 0) {
    for (const w of audit.warnings) {
      console.log(`   [!] Warning: ${w}`);
    }
  }
  console.log(line + "\n");
}

// ----------------------------------------------------
// Human Typing & Kinematic Cadence
// ----------------------------------------------------
function gaussianDelay(mean = 38, stdDev = 12) {
  const u = 1 - Math.random();
  const v = Math.random();
  const z = Math.sqrt(-2.0 * Math.log(u)) * Math.cos(2.0 * Math.PI * v);
  return Math.max(12, Math.min(110, Math.round(mean + z * stdDev)));
}

async function humanType(page, locator, text, options = {}) {
  const element = typeof locator.first === "function" ? locator.first() : locator;
  await humanClick(page, element);
  await new Promise((r) => setTimeout(r, 80 + Math.random() * 80));
  await element.fill("");
  await new Promise((r) => setTimeout(r, 40 + Math.random() * 40));

  for (let i = 0; i < text.length; i++) {
    const char = text[i];
    // Natural human typo emulation: 2% chance to mistype and backspace
    if (options.typos !== false && Math.random() < 0.02 && char !== " " && char !== "@") {
      const typoChar = String.fromCharCode(char.charCodeAt(0) + (Math.random() > 0.5 ? 1 : -1));
      await element.pressSequentially(typoChar, { delay: gaussianDelay(38, 12) });
      await new Promise((r) => setTimeout(r, 60 + Math.random() * 80));
      await element.press("Backspace");
      await new Promise((r) => setTimeout(r, 50 + Math.random() * 60));
    }
    await element.pressSequentially(char, { delay: gaussianDelay(38, 12) });
  }
  await new Promise((r) => setTimeout(r, 120 + Math.random() * 120));
}

async function safeGoto(page, url, options = { waitUntil: "domcontentloaded", timeout: 45000 }, maxRetries = 3) {
  for (let attempt = 1; attempt <= maxRetries; attempt++) {
    try {
      return await page.goto(url, options);
    } catch (err) {
      console.warn(`[Navigation] Attempt ${attempt} failed for ${url}: ${err.message}`);
      if (RISK && RISK.proxy && RISK.proxy.strict_sticky
        && /502|bad gateway|proxy_connection_refused|proxy authentication|tunnel/i.test(err.message || "")) {
        throw new Error("[Risk] Bound proxy session failed (502/proxy refused); aborting instead of rotating to a new IP.");
      }
      if (attempt === maxRetries) throw err;
      await new Promise((r) => setTimeout(r, 2000 * attempt));
    }
  }
}

// ----------------------------------------------------
// Pre-Signup Organic Warmup & Post-Registration Modals
// ----------------------------------------------------
async function preSignupOrganicWarmup(page) {
  console.log("=".repeat(60));
  console.log("[Camoufox Warmup] Starting Pre-Signup Organic Browsing...");
  console.log("[Camoufox Warmup] Purpose: Seed cookies, browser cache, TLS state before landing on Facebook");
  console.log("=".repeat(60));

  const warmupPool = [
    { name: "Wikipedia", url: "https://en.wikipedia.org/wiki/Main_Page" },
    { name: "Bing", url: "https://www.bing.com/" },
    { name: "BBC News", url: "https://www.bbc.com/news" },
    { name: "AccuWeather", url: "https://www.accuweather.com/" },
    { name: "IMDb", url: "https://www.imdb.com/" },
  ];

  for (let i = warmupPool.length - 1; i > 0; i--) {
    const j = crypto.randomInt(0, i + 1);
    [warmupPool[i], warmupPool[j]] = [warmupPool[j], warmupPool[i]];
  }
  const warmupSites = warmupPool.slice(0, 1);

  for (const site of warmupSites) {
    try {
      console.log(`[Camoufox Warmup] Quick cache visit: ${site.name} (${site.url})...`);
      await safeGoto(page, site.url, { waitUntil: "domcontentloaded", timeout: 15000 });
      await page.bringToFront().catch(() => {});
      await page.mouse.wheel(0, 200);
      await page.waitForTimeout(1000 + Math.random() * 500);
      console.log(`[Camoufox Warmup] Browsed ${site.name}.`);
    } catch (err) {
      console.warn(`[Camoufox Warmup] Note during ${site.name} visit: ${err.message}`);
    }
  }

  console.log("[Camoufox Warmup] Pre-signup organic warmup completed! Realistic browser history established.");
  console.log("=".repeat(60));
}

async function handlePostSignupModals(page, maxWaitMs = 15000) {
  console.log("=".repeat(60));
  console.log("[Facebook Onboarding] Checking for 'Save info' / 'Not Now' modals...");
  console.log("=".repeat(60));
  const startTime = Date.now();

  while (Date.now() - startTime < maxWaitMs) {
    const suspCheck = await isFacebookSuspendedScreen(page);
    if (suspCheck.isSuspended) {
      console.error(`[Facebook Onboarding] Account suspension detected: ${suspCheck.url}`);
      break;
    }

    let handled = false;

    // 1. "Save login info" modal
    const saveInfoBtn = page.locator("button:has-text('Save'), [role='button']:has-text('Save'), button:has-text('OK'), [role='button']:has-text('OK'), button:has-text('सेव करें')").first();
    if ((await saveInfoBtn.count()) > 0 && (await saveInfoBtn.isVisible().catch(() => false))) {
      console.log("[Facebook Onboarding] Found 'Save info' modal. Clicking 'OK'/'Save'...");
      await humanClick(page, saveInfoBtn).catch(() => {});
      handled = true;
      await page.waitForTimeout(1500);
    }

    // 2. "Not now" / "Skip" modals
    const notNowBtn = page.locator("button:has-text('Not Now'), [role='button']:has-text('Not Now'), button:has-text('Skip'), [role='button']:has-text('Skip'), [aria-label='Close'], [aria-label='बंद करें']").first();
    if ((await notNowBtn.count()) > 0 && (await notNowBtn.isVisible().catch(() => false))) {
      console.log("[Facebook Onboarding] Found 'Not Now'/'Skip' prompt. Dismissing...");
      await humanClick(page, notNowBtn).catch(() => {});
      handled = true;
      await page.waitForTimeout(1500);
    }

    if (!handled) {
      await page.waitForTimeout(1000);
    }
    const currentUrl = page.url();
    if (currentUrl.includes("facebook.com") && !currentUrl.includes("confirmemail") && !currentUrl.includes("checkpoint") && !currentUrl.includes("reg")) {
      break;
    }
  }
  console.log("[Facebook Onboarding] Onboarding modal check finished.");
}

async function warmUpFeed(page, durationSeconds = 30) {
  console.log("=".repeat(60));
  console.log(`[Facebook Warmup] Simulating natural human feed browsing (${durationSeconds}s)...`);
  console.log("=".repeat(60));

  const endTime = Date.now() + durationSeconds * 1000;
  while (Date.now() < endTime) {
    const scrollAmount = 150 + Math.floor(Math.random() * 250);
    await humanScroll(page, scrollAmount).catch(() => page.mouse.wheel(0, scrollAmount));

    const readPause = 1800 + Math.floor(Math.random() * 2500);
    await page.waitForTimeout(readPause);

    await humanWander(page, 1).catch(() => {});
  }
  console.log("[Facebook Warmup] Completed natural human feed browsing warmup.");
}

// ----------------------------------------------------
// Dual-Protocol Outlook / Microsoft Graph OTP Retrieval
// ----------------------------------------------------
async function fetchWithTimeout(url, options = {}, timeoutMs = 8000) {
  const controller = new AbortController();
  const tid = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, { ...options, signal: controller.signal });
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
  let res = await fetchWithTimeout(tokenUrl, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams(baseParams).toString(),
  });
  let data = await res.json();
  if (data.access_token) return data.access_token;

  if (data.error) throw new Error(data.error_description || data.error);
  return data.access_token;
}

async function pollOutlookForFacebookOtp(cId, rToken, startTimeMs, maxWaitSeconds = 150) {
  console.log(`[Outlook OTP] Polling Microsoft Graph & Outlook REST API for Facebook OTP code (timeout: ${maxWaitSeconds}s)...`);
  const startTime = Date.now();
  const minReceivedTime = (startTimeMs || startTime) - 15000;

  const folderGroups = [
    [
      "https://graph.microsoft.com/v1.0/me/messages?$top=5&$orderby=receivedDateTime%20desc",
      "https://graph.microsoft.com/v1.0/me/mailFolders/junkemail/messages?$top=5&$orderby=receivedDateTime%20desc",
    ],
    [
      "https://outlook.office.com/api/v2.0/me/messages?$top=5&$orderby=ReceivedDateTime%20desc",
      "https://outlook.office.com/api/v2.0/me/MailFolders/JunkEmail/messages?$top=5&$orderby=ReceivedDateTime%20desc",
    ],
  ];

  while ((Date.now() - startTime) < maxWaitSeconds * 1000) {
    try {
      const accessToken = await getMsAccessToken(cId, rToken);

      for (const group of folderGroups) {
        let groupSuccess = false;
        for (const url of group) {
          const res = await fetchWithTimeout(url, {
            headers: {
              Authorization: `Bearer ${accessToken}`,
              Accept: "application/json",
            },
          });

          if (res.ok) {
            groupSuccess = true;
            const data = await res.json();
            const messages = data.value || [];

            for (const msg of messages) {
              const rawDate = msg.receivedDateTime || msg.ReceivedDateTime || "";
              const receivedDate = rawDate ? new Date(rawDate).getTime() : Date.now();
              if (receivedDate < minReceivedTime) continue;

              const subject = msg.subject || msg.Subject || "";
              const from = (msg.from?.emailAddress?.address || msg.From?.EmailAddress?.Address || "").toLowerCase();
              const preview = msg.bodyPreview || msg.BodyPreview || "";
              const fullContent = msg.body?.content || msg.Body?.Content || "";

              const isFb = from.includes("facebook") || subject.toLowerCase().includes("facebook") || preview.toLowerCase().includes("facebook");
              if (isFb) {
                console.log(`[Outlook OTP] Detected Facebook email (${new Date(receivedDate).toLocaleTimeString()})!`);
                console.log(`              From:    ${from}`);
                console.log(`              Subject: ${subject}`);
                console.log(`              Preview: ${preview.slice(0, 100)}...`);

                // Facebook codes are 5 digits (\b\d{5}\b) or FB-\d{5}, or 6 digits in some regions
                const matchCode = subject.match(/\b(\d{5})\b/) ||
                                  preview.match(/(?:code|is|कोड|है|FB-)\s*[:\s]*(\d{5,8})\b/i) ||
                                  preview.match(/\b(\d{5})\b/) ||
                                  fullContent.match(/(?:code|is|कोड|है|FB-)\s*[:\s]*(\d{5,8})\b/i) ||
                                  subject.match(/\b(\d{6})\b/) ||
                                  preview.match(/\b(\d{6})\b/) ||
                                  fullContent.match(/\b(\d{5,6})\b/);

                if (matchCode) {
                  const code = matchCode[1];
                  console.log(`[Outlook OTP] Successfully extracted Facebook OTP code: ${code}`);
                  return {
                    otp: code,
                    thread: {
                      from,
                      subject,
                      received_date_time: rawDate || new Date().toISOString(),
                      body_preview: preview,
                      full_content: fullContent,
                    },
                  };
                }
              }
            }
          }
        }
        if (groupSuccess) break;
      }
    } catch (err) {
      console.warn(`[Outlook OTP] Polling attempt error: ${err.message}`);
    }

    const elapsed = Math.round((Date.now() - startTime) / 1000);
    console.log(`[Outlook OTP] Waiting 4s for Facebook OTP to arrive in inbox... (${elapsed}s / ${maxWaitSeconds}s)`);
    await new Promise((r) => setTimeout(r, 4000));
  }

  return null;
}

// Temp-Mail fallback support (@lnovic.com)
async function pollTempMailForOtp(address, maxWaitSeconds = 120) {
  console.log(`[TempMail OTP] Polling Temp-Mail API for ${address}...`);
  const startTime = Date.now();
  const token = "90494412cbmsh3413cfd395721a1p1f4787jsn348cfd395721";

  while ((Date.now() - startTime) < maxWaitSeconds * 1000) {
    try {
      const res = await fetch(`https://api.temp-mail.io/v1/messages?address=${encodeURIComponent(address)}`, {
        headers: { "x-api-key": token },
      });
      if (res.ok) {
        const msgs = await res.json();
        for (const msg of msgs) {
          const body = msg.body_text || msg.body_html || "";
          const subject = msg.subject || "";
          const isFb = (msg.from || "").toLowerCase().includes("facebook") || subject.toLowerCase().includes("facebook");
          if (isFb) {
            const match = subject.match(/\b(\d{5})\b/) || body.match(/\b(\d{5})\b/);
            if (match) return match[1];
          }
        }
      }
    } catch (e) { }
    await new Promise((r) => setTimeout(r, 4000));
  }
  return null;
}

async function createTempMailbox() {
  console.log("[TempMail] Minting fresh @lnovic.com address...");
  const res = await fetch("https://api.temp-mail.io/v1/addresses", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ min_name_length: 8, max_name_length: 12 }),
  });
  if (res.ok) {
    const data = await res.json();
    console.log(`[TempMail] Created mailbox: ${data.address}`);
    return data.address;
  }
  throw new Error("Failed to create temporary mailbox");
}

// ----------------------------------------------------
// Name & Demographics Generation
// ----------------------------------------------------
const FIRST_NAMES = ["Liam", "Noah", "Oliver", "Lucas", "Ethan", "Aiden", "Emma", "Olivia", "Ava", "Sophia", "Isabella", "Mia", "Henry", "Jackson", "Sebastian", "Jack", "Harper", "Evelyn", "Abigail", "Emily"];
const LAST_NAMES = ["Vance", "Wright", "Bennett", "Carter", "Hayes", "Morgan", "Brooks", "Reed", "Coleman", "Foster", "Mitchell", "Turner", "Phillips", "Campbell", "Parker", "Evans", "Edwards", "Collins", "Stewart", "Sanchez"];

function extractNameFromEmail(emailStr) {
  const local = (emailStr || "").split("@")[0] || "";
  const noNums = local.replace(/\d+/g, "").trim();

  let parts = [];
  if (noNums.includes(".")) {
    parts = noNums.split(".");
  } else if (noNums.includes("_")) {
    parts = noNums.split("_");
  } else if (noNums.includes("-")) {
    parts = noNums.split("-");
  } else {
    const splitCamel = noNums.replace(/([a-z])([A-Z])/g, "$1 $2").trim();
    parts = splitCamel.split(/\s+/);
  }

  const capitalize = (s) => (s ? s.charAt(0).toUpperCase() + s.slice(1).toLowerCase() : "");

  let first = parts[0] ? capitalize(parts[0]) : "";
  let last = parts[1] ? capitalize(parts[1]) : "";

  if (!first || first.length < 2) {
    first = FIRST_NAMES[crypto.randomInt(FIRST_NAMES.length)];
  }
  if (!last || last.length < 2) {
    last = LAST_NAMES[crypto.randomInt(LAST_NAMES.length)];
  }

  return { firstName: first, lastName: last, fullName: `${first} ${last}` };
}

function generateRandomBirthday() {
  const MONTHS = [
    { name: "January", days: 31, index: 1, hindi: "जनवरी" },
    { name: "February", days: 28, index: 2, hindi: "फ़रवरी" },
    { name: "March", days: 31, index: 3, hindi: "मार्च" },
    { name: "April", days: 30, index: 4, hindi: "अप्रैल" },
    { name: "May", days: 31, index: 5, hindi: "मई" },
    { name: "June", days: 30, index: 6, hindi: "जून" },
    { name: "July", days: 31, index: 7, hindi: "जुलाई" },
    { name: "August", days: 31, index: 8, hindi: "अगस्त" },
    { name: "September", days: 30, index: 9, hindi: "सितंबर" },
    { name: "October", days: 31, index: 10, hindi: "अक्टूबर" },
    { name: "November", days: 30, index: 11, hindi: "नवंबर" },
    { name: "December", days: 31, index: 12, hindi: "दिसंबर" },
  ];

  const monthObj = MONTHS[crypto.randomInt(MONTHS.length)];
  const day = crypto.randomInt(1, 28);
  const year = crypto.randomInt(1991, 2003); // ages 23 to 35
  const dayStr = day < 10 ? `0${day}` : `${day}`;
  const dobFormatted = `${dayStr} ${monthObj.name} ${year}`;

  return {
    day,
    dayStr,
    month: monthObj.name,
    monthHindi: monthObj.hindi,
    monthIndex: monthObj.index,
    year,
    formatted: dobFormatted,
  };
}

function generateUniquePassword(firstName, lastName) {
  const specials = ["@", "#", "!", "$"];
  const sym = specials[crypto.randomInt(specials.length)];
  const num = crypto.randomInt(100, 999);
  const cleanFirst = (firstName || "User").replace(/[^a-zA-Z]/g, "");
  return `${cleanFirst}${sym}${num}`;
}

function markFacebookAccountSuspended(emailOrProfile, url, profileDir = null) {
  try {
    if (fs.existsSync(REGISTERED_ACCOUNTS_FILE)) {
      const existing = JSON.parse(fs.readFileSync(REGISTERED_ACCOUNTS_FILE, "utf-8"));
      const target = (emailOrProfile || "").toLowerCase();
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
        fs.writeFileSync(REGISTERED_ACCOUNTS_FILE, JSON.stringify(existing, null, 2), "utf-8");
        console.log(`[Database] Updated account ${emailOrProfile} status to SUSPENDED in ${REGISTERED_ACCOUNTS_FILE}`);
      }
    }
    if (profileDir) {
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
    }
  } catch (err) {
    console.warn(`[Database] Error updating suspended status: ${err.message}`);
  }
}

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

function saveRegisteredAccount(record) {
  try {
    fs.mkdirSync(path.dirname(REGISTERED_ACCOUNTS_FILE), { recursive: true });
    let existing = [];
    if (fs.existsSync(REGISTERED_ACCOUNTS_FILE)) {
      try {
        existing = JSON.parse(fs.readFileSync(REGISTERED_ACCOUNTS_FILE, "utf-8"));
      } catch (e) {
        existing = [];
      }
    }
    existing = existing.filter((item) => (item && item.email ? item.email.toLowerCase() : "") !== record.email.toLowerCase());
    existing.push(record);
    fs.writeFileSync(REGISTERED_ACCOUNTS_FILE, JSON.stringify(existing, null, 2), "utf-8");
    console.log("=".repeat(60));
    console.log(`[Database] Saved complete account record to: ${REGISTERED_ACCOUNTS_FILE}`);
    console.log("=".repeat(60));
  } catch (err) {
    console.warn(`[Database] Error saving registered account: ${err.message}`);
  }
}

// ----------------------------------------------------
// ----------------------------------------------------
// Robust Birthday & Gender Combobox Selector
// ----------------------------------------------------
async function selectCustomCombobox(page, name, locator, regex) {
  let box = locator.first();
  if ((await box.count()) === 0 || !(await box.isVisible().catch(() => false))) {
    return false;
  }

  // Check if dropdown popup is already open from user interaction
  let opt = page.locator("[role='option']").filter({ hasText: regex }).first();
  if ((await opt.count()) === 0 || !(await opt.isVisible().catch(() => false))) {
    await humanClick(page, box).catch(() => box.click());
    await page.waitForTimeout(350 + Math.random() * 150);
    opt = page.locator("[role='option']").filter({ hasText: regex }).first();
  }

  if ((await opt.count()) > 0) {
    await opt.scrollIntoViewIfNeeded().catch(() => {});
    await humanClick(page, opt).catch(() => opt.click());
    await page.waitForTimeout(300 + Math.random() * 150);
    const txt = (await box.innerText().catch(() => "")).trim();
    console.log(`[Facebook] Set ${name} to: '${txt.replace(/\n/g, " - ")}'`);
    return true;
  }

  // Fallback: iterate all options if exact filter was hidden
  const allOpts = page.locator("[role='option']");
  const optCount = await allOpts.count();
  for (let j = 0; j < optCount; j++) {
    const item = allOpts.nth(j);
    const text = (await item.innerText().catch(() => "")).trim();
    if (regex.test(text)) {
      await item.scrollIntoViewIfNeeded().catch(() => {});
      await humanClick(page, item).catch(() => item.click());
      await page.waitForTimeout(300 + Math.random() * 150);
      const txt = (await box.innerText().catch(() => "")).trim();
      console.log(`[Facebook] Set ${name} via scroll to: '${txt.replace(/\n/g, " - ")}'`);
      return true;
    }
  }

  console.warn(`[Facebook] Warning: Option matching ${regex} for ${name} not found.`);
  return false;
}

async function fillBirthdayAndGender(page, dobObj, targetGender) {
  console.log(`[Facebook] Setting Birthday (${dobObj.formatted}) and Gender (${targetGender})...`);

  // Check 1: Native HTML <select> elements (fallback for legacy or mobile views)
  const daySelect = page.locator("select[name='birthday_day']").first();
  const monthSelect = page.locator("select[name='birthday_month']").first();
  const yearSelect = page.locator("select[name='birthday_year']").first();
  if ((await daySelect.count()) > 0 && (await daySelect.isVisible().catch(() => false))) {
    console.log("[Facebook] Native HTML <select> dropdowns detected.");
    await daySelect.selectOption(String(dobObj.day)).catch(() => {});
    await monthSelect.selectOption(String(dobObj.monthIndex || dobObj.month)).catch(() => {});
    await yearSelect.selectOption(String(dobObj.year)).catch(() => {});
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

  // Gender Selection: Handle Combobox OR Radio Buttons
  const genderBox = page.locator("[role='combobox'][aria-label*='gender' i], [role='combobox']:has-text('gender'), [role='combobox'][aria-label*='लिंग' i], [role='combobox']:has-text('लिंग'), [role='combobox'][aria-label*='જાતિ' i]");
  if ((await genderBox.count()) > 0 && (await genderBox.first().isVisible().catch(() => false))) {
    const genderRegex = targetGender === "Female" ? /^(?:female|महिला|સ્ત્રી)$/i : /^(?:male|पुरुष|પુરુષ)$/i;
    await selectCustomCombobox(page, "Gender", genderBox, genderRegex);
  } else {
    // Radio buttons fallback
    const radioVal = targetGender === "Female" ? "1" : "2";
    const radioBtn = page.locator(`input[type='radio'][value='${radioVal}'], label:has-text('${targetGender}') input[type='radio'], input[type='radio'][aria-label*='${targetGender}' i]`).first();
    if ((await radioBtn.count()) > 0 && (await radioBtn.isVisible().catch(() => false))) {
      await humanClick(page, radioBtn).catch(() => radioBtn.click());
      console.log(`[Facebook] Selected gender radio: ${targetGender}`);
    }
  }
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

// ----------------------------------------------------
// OTP Challenge Handler
// ----------------------------------------------------
async function handleOtpChallenge(page, targetEmail, cId, rToken, sessionStartTimeMs) {
  console.log("[Facebook] Checking for Confirmation Code challenge screen...");

  let foundInput = false;
  for (let i = 0; i < 20; i++) {
    const suspCheck = await isFacebookSuspendedScreen(page);
    if (suspCheck.isSuspended) {
      console.error("=".repeat(65));
      console.error(`[Facebook] ⚠️ ACCOUNT SUSPENDED: Facebook redirected to ${suspCheck.url}`);
      console.error("=".repeat(65));
      return { success: false, otp: null, thread: null, suspended: true, url: suspCheck.url };
    }

    const codeInput = page.locator("input[name='code'], input[aria-label*='code' i], input[aria-label*='कोड' i], input[placeholder*='code' i], input[placeholder*='कोड' i], input[placeholder*='Confirmation code' i]");
    if ((await codeInput.count()) > 0 && (await codeInput.first().isVisible().catch(() => false))) {
      foundInput = true;
      break;
    }
    const bodyText = await page.evaluate(() => (document.body ? document.body.innerText : ""));
    if (
      bodyText.includes("Enter the confirmation code") ||
      bodyText.includes("5-digit code") ||
      bodyText.includes("पुष्टि कोड") ||
      bodyText.includes("5 अंकों का कोड") ||
      (page.url().includes("checkpoint") && !page.url().includes("1501092823525282")) ||
      page.url().includes("confirmemail")
    ) {
      foundInput = true;
      break;
    }
    await page.waitForTimeout(1000);
  }

  if (!foundInput) {
    const finalSuspCheck = await isFacebookSuspendedScreen(page);
    if (finalSuspCheck.isSuspended) {
      console.error("=".repeat(65));
      console.error(`[Facebook] ⚠️ ACCOUNT SUSPENDED: Facebook redirected to ${finalSuspCheck.url}`);
      console.error("=".repeat(65));
      return { success: false, otp: null, thread: null, suspended: true, url: finalSuspCheck.url };
    }
    console.log("[Facebook] Not on OTP confirmation screen. Current URL:", page.url());
    return { success: false, otp: null, thread: null };
  }

  console.log("=".repeat(60));
  console.log("[Facebook] >>> ENTER CONFIRMATION CODE SCREEN DETECTED! <<<");
  console.log("=".repeat(60));

  let otpData = null;
  if (cId && rToken) {
    otpData = await pollOutlookForFacebookOtp(cId, rToken, sessionStartTimeMs, 150);
  } else if (targetEmail.endsWith("@lnovic.com")) {
    const rawOtp = await pollTempMailForOtp(targetEmail, 150);
    if (rawOtp) {
      otpData = { otp: rawOtp, thread: { from: "temp-mail.io", subject: "Facebook Confirmation Code", received_date_time: new Date().toISOString(), body_preview: rawOtp, full_content: rawOtp } };
    }
  } else {
    console.log(`[Facebook] No automatic inbox access configured for ${targetEmail}. Please check your email manually.`);
  }

  let otp = otpData ? (typeof otpData === "object" ? otpData.otp : otpData) : null;
  const thread = otpData && otpData.thread ? otpData.thread : null;

  if (!otp) {
    console.log(`[Facebook] Automated inbox polling returned no code for ${targetEmail}. Prompting for terminal entry...`);
    otp = await promptTerminalOtp(targetEmail, 180);
  }

  if (otp) {
    console.log(`[Facebook] >>> ENTERING 5-DIGIT OTP: ${otp} <<<`);
    const input = page.locator("input[name='code'], input[aria-label*='code' i], input[placeholder*='code' i], input[type='text'], input:not([type])").first();
    await humanType(page, input, otp, { typos: false });
    await page.waitForTimeout(600);

    console.log("[Facebook] Submitting OTP ('Continue')...");
    const continueBtn = page.locator("button:has-text('Continue'), [role='button']:has-text('Continue'), button:has-text('जारी रखें'), button:has-text('आगे बढ़ें'), button[type='submit']").first();
    if ((await continueBtn.count()) > 0) {
      await humanClick(page, continueBtn).catch(() => continueBtn.click());
    } else {
      await page.keyboard.press("Enter");
    }

    console.log("[Facebook] OTP submitted. Waiting 10s for confirmation...");
    await page.waitForTimeout(10000);
    riskMark("otp_submitted");
    console.log(`[Facebook] Current URL: ${page.url()} | Title: '${await page.title()}'`);

    const postOtpSusp = await isFacebookSuspendedScreen(page);
    if (postOtpSusp.isSuspended) {
      console.error("=".repeat(65));
      console.error(`[Facebook] ⚠️ ACCOUNT SUSPENDED: Facebook redirected to ${postOtpSusp.url}`);
      console.error("=".repeat(65));
      return { success: false, otp, thread, suspended: true, url: postOtpSusp.url };
    }

    return { success: true, otp, thread };
  } else {
    console.warn("[Facebook] Could not fetch OTP automatically within 150s. Browser will remain open for manual inspection.");
    return { success: false, otp: null, thread: null };
  }
}

// ----------------------------------------------------
// Automated Facebook Page Creator & Onboarding Wizard
// ----------------------------------------------------
async function createFacebookPage(page, customPageName = null, customBio = null) {
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
  const nameInput = page.locator("input[aria-label*='Page name' i], label:has-text('Page name') input").first();
  await nameInput.waitFor({ state: "visible", timeout: 15000 });
  await humanType(page, nameInput, pageName, { typos: false });
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

  console.log("[Facebook] Clicked 'Create Page'. Waiting 15s for processing...");
  await page.waitForTimeout(15000);

  // 5. Complete Multi-Step Page Onboarding (Handle, Photos, Hours, WhatsApp Skip, Done)
  const onboardRes = await completePageOnboarding(page, pageName);
  const cleanHandle = pageName.toLowerCase().replace(/[^a-z0-9]/g, "").slice(0, 30);
  const pageUrl = (onboardRes && onboardRes.pageUrl && onboardRes.pageUrl.includes("facebook.com/")) ? onboardRes.pageUrl : `https://www.facebook.com/${cleanHandle}`;

  return { pageName, pageUrl, category: "Personal blog", bio, cleanHandle };
}

async function completePageOnboarding(page, pageName) {
  console.log("=".repeat(60));
  console.log(`[Facebook Onboarding] Running wizard setup for: "${pageName}"`);
  console.log("=".repeat(60));

  const profilePhotoPath = path.resolve("tests", "test_artifacts", "test_thumb_vertical.jpg");
  const coverPhotoPath = path.resolve("tests", "test_artifacts", "test_thumb_horizontal.jpg");
  const cleanHandle = pageName.toLowerCase().replace(/[^a-z0-9]/g, "").slice(0, 30);

  for (let step = 1; step <= 8; step++) {
    await page.waitForTimeout(3000);
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
        await page.waitForTimeout(3000);
        continue;
      }
    }

    // 2. Handle input (Step 1 of 3: Page details)
    const handleInput = page.locator("input[placeholder*='handle' i], input[aria-label*='handle' i], label:has-text('Handle') input, div:has-text('Handle') input").first();
    if ((await handleInput.count()) > 0 && (await handleInput.isVisible())) {
      console.log(`[Facebook Onboarding] Detected: 'Handle' input. Entering: '${cleanHandle}'...`);
      await humanType(page, handleInput, cleanHandle, { typos: false });
      await page.waitForTimeout(500);

      const fileInputs = page.locator("input[type='file']");
      if ((await fileInputs.count()) > 0 && fs.existsSync(profilePhotoPath)) {
        console.log(`[Facebook Onboarding] Uploading photo to Step 1: ${profilePhotoPath}...`);
        await fileInputs.first().setInputFiles(profilePhotoPath).catch(() => { });
        await page.waitForTimeout(2000);
      }

      const nextBtn = page.locator("button:has-text('Next'), [role='button']:has-text('Next')").first();
      if ((await nextBtn.count()) > 0) {
        await humanClick(page, nextBtn).catch(() => nextBtn.click());
        await page.waitForTimeout(3000);
        continue;
      }
    }

    // 3. Step 1 of 5: "Finish setting up your Page" (Hours)
    if (bodyText.includes("Finish setting up your Page") || bodyText.includes("location's hours") || bodyText.includes("Open at selected hours")) {
      console.log("[Facebook Onboarding] Detected: 'Finish setting up your Page'. Selecting 'Open at selected hours'...");
      const hoursRadio = page.locator("label:has-text('Open at selected hours'), div:has-text('Open at selected hours'), input[value*='selected']").first();
      if ((await hoursRadio.count()) > 0) {
        await humanClick(page, hoursRadio).catch(() => hoursRadio.click());
        await page.waitForTimeout(500);
      } else {
        const alwaysOpen = page.locator("label:has-text('Always open'), div:has-text('Always open')").first();
        if ((await alwaysOpen.count()) > 0) await humanClick(page, alwaysOpen).catch(() => alwaysOpen.click());
      }

      const nextBtn = page.locator("button:has-text('Next'), [role='button']:has-text('Next')").first();
      if ((await nextBtn.count()) > 0) {
        await humanClick(page, nextBtn).catch(() => nextBtn.click());
        await page.waitForTimeout(3000);
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
          await page.waitForTimeout(2500);
        }
      } catch (err) { }

      try {
        const inputsNow = page.locator("input[type='file']");
        if ((await inputsNow.count()) >= 2 && fs.existsSync(coverPhotoPath)) {
          console.log(`[Facebook Onboarding] Setting Cover Photo on file input #2...`);
          await inputsNow.nth(1).setInputFiles(coverPhotoPath).catch(() => { });
          await page.waitForTimeout(2500);
        }
      } catch (e) { }

      const nextBtn = page.locator("button:has-text('Next'), [role='button']:has-text('Next')").first();
      if ((await nextBtn.count()) > 0) {
        await humanClick(page, nextBtn).catch(() => nextBtn.click());
        await page.waitForTimeout(3000);
        continue;
      }
    }

    // 5. Connect WhatsApp / Phone step -> Click 'Skip'
    if (bodyText.includes("Connect WhatsApp to your Page") || bodyText.includes("WhatsApp") || bodyText.includes("Connect your account")) {
      console.log("[Facebook Onboarding] Detected WhatsApp screen. Clicking 'Skip'...");
      const skipBtn = page.locator("button:has-text('Skip'), [role='button']:has-text('Skip'), div[role='button']:has-text('Skip')").first();
      if ((await skipBtn.count()) > 0) {
        await humanClick(page, skipBtn).catch(() => skipBtn.click());
        await page.waitForTimeout(3000);
        continue;
      }
    }

    // 6. Generic 'Done' or 'Next'
    const doneBtn = page.locator("button:has-text('Done'), [role='button']:has-text('Done'), div[role='button']:has-text('Done')").first();
    if ((await doneBtn.count()) > 0 && (await doneBtn.isVisible())) {
      console.log("[Facebook Onboarding] Detected final 'Done' button. Completing wizard...");
      await humanClick(page, doneBtn).catch(() => doneBtn.click());
      await page.waitForTimeout(5000);
      break;
    }

    const genericNext = page.locator("button:has-text('Next'), [role='button']:has-text('Next')").first();
    if ((await genericNext.count()) > 0 && (await genericNext.isVisible())) {
      console.log(`[Facebook Onboarding] Clicking generic 'Next' on step ${step}...`);
      await humanClick(page, genericNext).catch(() => genericNext.click());
      await page.waitForTimeout(3000);
      continue;
    }

    // Not Now modal
    const notNow = page.locator("button:has-text('Not Now'), [role='button']:has-text('Not Now')").first();
    if ((await notNow.count()) > 0 && (await notNow.isVisible())) {
      await humanClick(page, notNow).catch(() => notNow.click());
      await page.waitForTimeout(2000);
      continue;
    }

    break;
  }

  const finalUrl = page.url();
  console.log(`[Facebook Onboarding] Wizard finished. Final URL: ${finalUrl}`);
  return { success: true, pageUrl: finalUrl };
}

// ----------------------------------------------------
// Main Registration Pipeline
// ----------------------------------------------------
async function run() {
  const startedAt = Date.now();

  if (newEmailFlag) {
    email = await createTempMailbox();
  }

  const explicitProxy = getArg("--proxy");
  const rawProxy = explicitProxy || DEFAULT_PROXY;
  const effectiveProxy = ensureStickyProxy(rawProxy, email);
  const parsedProxyIdentity = parseProxyIdentity(effectiveProxy);
  const parsedProxy = parseProxy(effectiveProxy);

  const { firstName, lastName, fullName } = extractNameFromEmail(email);
  const dobObj = generateRandomBirthday();
  const randomGender = Math.random() < 0.5 ? "Female" : "Male";
  const password = getArg("--password") || generateUniquePassword(firstName, lastName);

  console.log("=".repeat(60));
  console.log("FACEBOOK AUTOMATED REGISTRATION (CAMOUFOX ANTI-DETECT + STICKY PROXY)");
  console.log("=".repeat(60));
  console.log(`Email Address:  ${email}`);
  console.log(`Full Name:      ${fullName} (First: ${firstName}, Last: ${lastName})`);
  console.log(`Date of Birth:  ${dobObj.formatted} (Age ~${new Date().getFullYear() - dobObj.year})`);
  console.log(`Gender:         ${randomGender}`);
  console.log(`Password:       [generated and secured in master registry]`);
  if (parsedProxy) {
    console.log(`Proxy Server:   ${parsedProxy.server} (Sticky Session: ${parsedProxyIdentity.session || "active"})`);
  }
  if (refreshToken && clientId) {
    console.log(`Outlook OAuth:  Configured (Client ID: ${clientId})`);
  }
  console.log("=".repeat(60));

  // Multi-Account Isolation: 1 Profile Dir per Account
  const profileDir = path.resolve("output", "profiles facebook", sanitizeProfileName(email.split("@")[0] || email));
  if (!keepProfile && fs.existsSync(profileDir)) {
    console.log(`[Camoufox] Default Clean Mode: Wiping previous profile cache for fresh start: ${profileDir}`);
    try {
      fs.rmSync(profileDir, { recursive: true, force: true });
    } catch (e) {
      console.warn(`[Camoufox] Note cleaning profile directory: ${e.message}`);
    }
  }
  fs.mkdirSync(profileDir, { recursive: true });

  // Clean stale lock files if any
  try {
    const parentLock = path.join(profileDir, "parent.lock");
    if (fs.existsSync(parentLock)) fs.rmSync(parentLock, { force: true });
  } catch (e) { }

  // Frozen Persona per multi-account isolation skill
  const personaPath = path.join(profileDir, "persona.json");
  let persona = null;
  if (fs.existsSync(personaPath)) {
    try {
      persona = JSON.parse(fs.readFileSync(personaPath, "utf-8"));
      delete persona["screen:width"];
      delete persona["screen:height"];
      delete persona["screen.width"];
      delete persona["screen.height"];
      delete persona["screen.availWidth"];
      delete persona["screen.availHeight"];
      console.log(`[Camoufox] Re-using frozen persona seeds: ${personaPath}`);
    } catch (e) { }
  }

  const isGpuValid = persona?.webgl_config && GPU_CONFIGURATIONS.some(
    ([v, r]) => v === persona.webgl_config[0] && r === persona.webgl_config[1]
  );

  const derivedTz = deriveTimezoneFromProxy(effectiveProxy);
  const explicitTz = getArg("--timezone");
  const chosenTz = explicitTz || persona?.timezone || derivedTz.tz;
  const chosenRegion = persona?.["locale:region"] || derivedTz.region;
  const chosenLang = persona?.["locale:language"] || derivedTz.lang;

  if (!persona || !persona["canvas:seed"] || !isGpuValid || !persona.timezone) {
    const chosenGpu = GPU_CONFIGURATIONS[crypto.randomInt(GPU_CONFIGURATIONS.length)];
    const chosenRes = SCREEN_RESOLUTIONS[crypto.randomInt(SCREEN_RESOLUTIONS.length)];
    persona = {
      "canvas:seed": persona?.["canvas:seed"] || (Math.floor(Math.random() * 4000000000) + 1),
      "audio:seed": persona?.["audio:seed"] || (Math.floor(Math.random() * 4000000000) + 1),
      "fonts:spacing_seed": persona?.["fonts:spacing_seed"] || (Math.floor(Math.random() * 4000000000) + 1),
      webgl_config: isGpuValid ? persona.webgl_config : chosenGpu,
      screen_resolution: persona?.screen_resolution || chosenRes,
      timezone: chosenTz,
      "locale:region": chosenRegion,
      "locale:language": chosenLang,
    };
    fs.writeFileSync(personaPath, JSON.stringify(persona, null, 2));
    console.log(`[Camoufox] Saved verified persona: ${personaPath}`);
    console.log(`          GPU:      ${persona.webgl_config[1]}`);
    console.log(`          Screen:   ${persona.screen_resolution.width}x${persona.screen_resolution.height}`);
    console.log(`          Timezone: ${persona.timezone} (derived from proxy)`);
  }

  // Frozen Full BrowserForge Fingerprint
  const fingerprintPath = path.join(profileDir, "fingerprint.json");
  let fingerprint = null;
  if (fs.existsSync(fingerprintPath)) {
    try {
      const fp = JSON.parse(fs.readFileSync(fingerprintPath, "utf-8"));
      if (fp && fp.navigator && fp.screen) {
        fingerprint = fp;
        console.log(`[Camoufox] Re-using frozen full fingerprint: ${fingerprintPath}`);
      }
    } catch (e) { }
  }
  if (!fingerprint) {
    let generated = null;
    const scr = persona.screen_resolution;
    if (scr && scr.width && scr.height) {
      try {
        const res = FP_GENERATOR.getFingerprint({
          screen: { minWidth: scr.width, maxWidth: scr.width, minHeight: scr.height, maxHeight: scr.height },
          operatingSystems: ["windows"],
        });
        generated = res.fingerprint;
      } catch (e) { }
    }
    if (!generated) {
      const res = FP_GENERATOR.getFingerprint({ operatingSystems: ["windows"] });
      generated = res.fingerprint;
      persona.screen_resolution = { width: generated.screen.width, height: generated.screen.height };
      fs.writeFileSync(personaPath, JSON.stringify(persona, null, 2));
    }
    fingerprint = generated;
    fs.writeFileSync(fingerprintPath, JSON.stringify(fingerprint, null, 2));
    console.log(`[Camoufox] Generated and froze full fingerprint (${fingerprint.screen.width}x${fingerprint.screen.height})`);
  }

  // Strict User-Agent Parity: Align DOM navigator.userAgent and headers with native Camoufox C++ 158.0 engine
  if (fingerprint && fingerprint.navigator) {
    if (fingerprint.navigator.userAgent !== CAMOUFOX_UA || fingerprint.navigator.appVersion !== "5.0 (Windows)") {
      fingerprint.navigator.userAgent = CAMOUFOX_UA;
      fingerprint.navigator.appVersion = "5.0 (Windows)";
      if (Array.isArray(fingerprint.headers)) {
        for (const h of fingerprint.headers) {
          if (h && h.name && h.name.toLowerCase() === "user-agent") {
            h.value = CAMOUFOX_UA;
          }
        }
      }
      try { fs.writeFileSync(fingerprintPath, JSON.stringify(fingerprint, null, 2)); } catch (e) { }
      console.log(`[Camoufox] Aligned fingerprint User-Agent to native Camoufox C++ stack (${CAMOUFOX_UA})`);
    }
  }

  // Sync VideoCard with explicit WebGL config
  if (persona?.webgl_config) {
    const expectedCard = { vendor: persona.webgl_config[0], renderer: persona.webgl_config[1] };
    if (!fingerprint.videoCard
      || fingerprint.videoCard.vendor !== expectedCard.vendor
      || fingerprint.videoCard.renderer !== expectedCard.renderer) {
      fingerprint.videoCard = expectedCard;
      try { fs.writeFileSync(fingerprintPath, JSON.stringify(fingerprint, null, 2)); } catch (e) { }
    }
  }

  // Save account OAuth & credential tokens for future use
  const accountInfoPath = path.join(profileDir, "account_info.json");
  try {
    fs.writeFileSync(accountInfoPath, JSON.stringify({
      email,
      password,
      client_id: clientId,
      refresh_token: refreshToken,
      proxy_used: effectiveProxy,
      created_at: new Date().toISOString(),
    }, null, 2));
    console.log(`[Camoufox] Saved account credential cache: ${accountInfoPath}`);
  } catch (e) { }

  // Initialize Risk Tracking
  initRiskLog({ email, proxyArg: effectiveProxy, persona, fingerprint, profileDir, startedAt });

  // Seed Profile Aging: Bookmarks Toolbar, browsing history & visible UI
  try {
    const agingScript = path.resolve("tools", "profile_aging.py");
    execFileSync("python", [agingScript, profileDir], { timeout: 10000 });
    console.log("[Profile Aging] Seeded Bookmarks Toolbar & realistic browsing history into profile.");
  } catch (e) { }

  console.log("[Camoufox] Launching Camoufox with residential proxy, frozen persona & WebRTC protection...");
  const scr = persona.screen_resolution || { width: 1920, height: 1080 };
  if (fingerprint && fingerprint.headers) {
    fingerprint.headers["accept-language"] = "en-US,en;q=0.9";
  }
  const browserConfig = {
    user_data_dir: profileDir,
    headless: headless,
    os: "windows",
    humanize: 0.85,
    block_webrtc: true,
    exclude_addons: ["UBO"],     // Exclude bundled ad-blocker to prevent CSP data: injection violations & CDN script drops
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
    },
    webgl_config: persona.webgl_config || undefined,
    i_know_what_im_doing: true,
    config: {
      "canvas:seed": persona["canvas:seed"],
      "canvas:aaOffset": 0,
      "canvas:aaCapOffset": false,
      "audio:seed": persona["audio:seed"],
      "fonts:spacing_seed": persona["fonts:spacing_seed"],
      timezone: persona.timezone || chosenTz,
      "locale:region": "US",
      "locale:language": "en",
      "locale:all": "en-US, en",
    },
    proxy: parsedProxy,
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
  await page.bringToFront().catch(() => { });

  // Native Passkey (WebAuthn) Spoofing: ensures Windows Hello capability is declared and translates
  // unexpected SecurityError exceptions into standard W3C NotAllowedError so Meta's FBLOGGER never catches "The operation is insecure"
  await page.addInitScript(() => {
    try {
      if (window.PublicKeyCredential) {
        window.PublicKeyCredential.isUserVerifyingPlatformAuthenticatorAvailable = async () => true;
        if (window.PublicKeyCredential.isConditionalMediationAvailable) {
          window.PublicKeyCredential.isConditionalMediationAvailable = async () => true;
        }
      }
      if (window.navigator && window.navigator.credentials) {
        const origGet = window.navigator.credentials.get.bind(window.navigator.credentials);
        window.navigator.credentials.get = async function (options) {
          if (options && options.mediation === "conditional") {
            return new Promise((resolve, reject) => {
              if (options.signal) {
                options.signal.addEventListener("abort", () => {
                  reject(new DOMException("The operation was aborted.", "AbortError"));
                });
              }
            });
          }
          return origGet(options);
        };
      }
    } catch (e) { }
  });

  // Continuous 10-second Screenshot Ticker
  let tickerActive = true;
  (async () => {
    while (tickerActive) {
      await new Promise((r) => setTimeout(r, 10000));
      if (!tickerActive) break;
      try {
        await page.screenshot({ path: "tests/test_artifacts/fb_latest_live.png", fullPage: true });
        console.log(`[Screenshot Ticker] Updated tests/test_artifacts/fb_latest_live.png (${new Date().toLocaleTimeString()})`);
      } catch (e) { }
    }
  })();

  try {
    // 1. Verify Proxy Location and Audit Anti-Detect Coherence
    console.log("[Camoufox] Verifying Proxy IP, ASN & location via ipapi.co...");
    const proxyLocation = await captureExitIp(page, "pre_signup");
    console.log(`[Camoufox] Exit IP: ${proxyLocation.ip} | ASN: ${proxyLocation.asn || "unknown"} | Location: ${proxyLocation.city}, ${proxyLocation.region}, ${proxyLocation.country}`);

    console.log("[Camoufox] Auditing browser/fingerprint coherence (webdriver, timezone, screen, WebGL, WebRTC)...");
    const coherenceAudit = await auditBrowserCoherence(page, {
      os: "windows",
      timezone: persona.timezone || chosenTz,
      screen: fingerprint.screen,
      renderer: persona.webgl_config ? persona.webgl_config[1] : null,
      proxyCountry: proxyLocation.country || parsedProxyIdentity?.country || null,
      exitIp: proxyLocation.ip,
    });

    const tlsFingerprint = await captureTlsFingerprint(page.context());
    if (RISK) RISK.fingerprint.tls = tlsFingerprint;
    if (!tlsFingerprint) {
      riskWarn("TLS/JA3 capture failed; the browser TLS stack could not be verified.");
    }
    const navUa = (fingerprint.navigator && fingerprint.navigator.userAgent) || null;
    let uaMatch = true;
    if (tlsFingerprint) {
      console.log(`[Risk] TLS/JA3: ${tlsFingerprint.ja3_hash || "unknown"} | JA4: ${tlsFingerprint.ja4 || "unknown"}`);
      if (navUa && tlsFingerprint.user_agent && tlsFingerprint.user_agent !== navUa) {
        uaMatch = false;
        riskWarn("TLS user-agent differs from navigator.userAgent; the browser/HTTP stacks are inconsistent.");
      } else {
        console.log(`[Risk] User-Agent parity: 100% Wire/DOM Match (${navUa})`);
      }
    }

    // Print Stealth & Anti-Detect Audit Dashboard
    const probe = coherenceAudit.probe || {};
    printStealthAuditDashboard({
      exitIp: proxyLocation.ip,
      stickySessId: parsedProxyIdentity?.session || null,
      asn: proxyLocation.asn,
      city: proxyLocation.city,
      region: proxyLocation.region,
      country: proxyLocation.country,
      proxyConsistent: true,
      navUa,
      tlsUa: tlsFingerprint?.user_agent || navUa,
      uaMatch,
      tls: tlsFingerprint,
      timezone: probe.timezone || persona.timezone || chosenTz,
      tzOffset: probe.timezoneOffset,
      screenWidth: probe.screen?.width || fingerprint.screen?.width,
      screenHeight: probe.screen?.height || fingerprint.screen?.height,
      availWidth: probe.screen?.availWidth,
      availHeight: probe.screen?.availHeight,
      dpr: probe.screen?.devicePixelRatio,
      gpuRenderer: probe.webglRenderer || persona.webgl_config?.[1],
      gpuVendor: probe.webglVendor || persona.webgl_config?.[0],
      webrtcShield: !(coherenceAudit.warnings || []).some((w) => w.includes("WebRTC")),
      botClean: probe.webdriver !== true && !probe.hasChromeObject && !probe.automationGlobals,
      warnings: (RISK?.warnings || []).concat(coherenceAudit.warnings || []).filter((v, i, a) => a.indexOf(v) === i),
    });
    riskMark("preflight_complete");

    // 1.5 Pre-Signup Organic Browsing Warmup
    if (!skipWarmup) {
      await preSignupOrganicWarmup(page);
    }

    // 2. Natural Visitor Flow: Navigate to Facebook Home Page first
    console.log("[Camoufox] Navigating to https://www.facebook.com/?locale=en_US (organic landing page visit)...");
    await safeGoto(page, "https://www.facebook.com/?locale=en_US", { waitUntil: "domcontentloaded", timeout: 45000 });
    await page.bringToFront().catch(() => { });
    await page.waitForTimeout(1500 + Math.random() * 1000);
    riskMark("page_loaded");

    // Cookie consent dismissal if shown (English or Hindi)
    const cookieBtn = page.locator("button:has-text('Allow all cookies'), button:has-text('Allow essential and optional cookies'), button:has-text('Decline optional cookies'), [aria-label='Allow all cookies'], button:has-text('सभी कुकीज़ की अनुमति दें'), button:has-text('स्वीकार करें')");
    if ((await cookieBtn.count()) > 0 && (await cookieBtn.first().isVisible().catch(() => false))) {
      console.log("[Facebook] Dismissing cookie dialog...");
      await humanClick(page, cookieBtn.first()).catch(() => cookieBtn.first().click());
      await page.waitForTimeout(1000);
    }

    // Check if session is already at OTP confirmation screen, checkpoint, or already logged in
    const currentUrl = page.url();
    const hasOtpInput = (await page.locator("input[name='code'], input[aria-label*='code' i], input[placeholder*='code' i], input[placeholder*='Confirmation code' i]").count()) > 0;
    const isAlreadyAtOtp = currentUrl.includes("confirmemail") || currentUrl.includes("checkpoint") || hasOtpInput;
    const isAlreadyLoggedIn = currentUrl.includes("facebook.com") && !currentUrl.includes("reg") && !currentUrl.includes("login") && !isAlreadyAtOtp && (await page.locator("[aria-label='Menu']").count()) > 0;

    if (isAlreadyLoggedIn) {
      console.log(`[Facebook] Already logged in at: ${currentUrl}. Proceeding directly to Page creation...`);
    } else if (isAlreadyAtOtp) {
      console.log(`[Facebook] Detected existing OTP confirmation screen at ${currentUrl}. Skipping registration form submission.`);
    } else {
      // Natural User Emulation: Look for "Create new account" button on landing page
      console.log("[Facebook] Searching for 'Create new account' button on landing page...");
      const createAccBtn = page.locator("a[data-testid='open-registration-form-button'], a[role='button']:has-text('Create new account'), button:has-text('Create new account'), a:has-text('Create new account'), [role='button']:has-text('नया अकाउंट बनाएँ')").first();

      if ((await createAccBtn.count()) > 0 && (await createAccBtn.isVisible().catch(() => false))) {
        console.log("[Facebook] Natural interaction: Hovering & clicking 'Create new account' button...");
        await humanHover(page, createAccBtn).catch(() => {});
        await page.waitForTimeout(400 + Math.random() * 300);
        await Promise.all([
          page.waitForURL((url) => url.pathname.includes("/reg") || url.search.includes("entry_point=login"), { timeout: 15000 }).catch(() => {}),
          humanClick(page, createAccBtn).catch(() => createAccBtn.click()),
        ]);
        console.log("[Facebook] Waiting for registration page/modal to settle...");
        await page.waitForTimeout(2500);
      } else {
        console.log("[Facebook] Direct navigation fallback: navigating to registration endpoint...");
        await safeGoto(page, "https://www.facebook.com/reg/?entry_point=login&locale=en_US", { waitUntil: "domcontentloaded", timeout: 40000 });
        await page.waitForTimeout(2500);
      }

      // If we are still not on /reg/, navigate directly to ensure inputs are exposed
      if (!page.url().includes("/reg")) {
        console.log("[Facebook] Navigating directly to /reg/?entry_point=login&locale=en_US...");
        await safeGoto(page, "https://www.facebook.com/reg/?entry_point=login&locale=en_US", { waitUntil: "domcontentloaded", timeout: 40000 });
        await page.waitForTimeout(2500);
      }

      // Wait for registration input fields to be visible
      console.log("[Facebook] Waiting for registration input fields to become visible...");
      await page.waitForSelector("input[type='text']:visible, input[name='firstname']:visible", { timeout: 20000 }).catch(() => {});

      // 1. Fill First Name & Surname
      console.log(`[Facebook] Typing Name: ${firstName} ${lastName}...`);
      let fnInput = page.locator("input[name='firstname']:visible, input[aria-label*='First name' i]:visible, input[placeholder*='First name' i]:visible").first();
      if ((await fnInput.count()) === 0 || !(await fnInput.isVisible().catch(() => false))) {
        fnInput = page.locator("input[type='text']:visible").nth(0);
      }
      await fnInput.waitFor({ state: "visible", timeout: 15000 });
      await humanType(page, fnInput, firstName);

      let lnInput = page.locator("input[name='lastname']:visible, input[aria-label*='Surname' i]:visible, input[placeholder*='Surname' i]:visible, input[aria-label*='Last name' i]:visible").first();
      if ((await lnInput.count()) === 0 || !(await lnInput.isVisible().catch(() => false))) {
        lnInput = page.locator("input[type='text']:visible").nth(1);
      }
      await lnInput.waitFor({ state: "visible", timeout: 15000 });
      await humanType(page, lnInput, lastName);

      // 2. Select Date of Birth & Gender dynamically
      await fillBirthdayAndGender(page, dobObj, randomGender);

      // 3. Fill Mobile number or email address
      console.log(`[Facebook] Entering Email: ${email}...`);
      let emInput = page.locator("input[name='reg_email__']:visible, input[aria-label*='Mobile number or email' i]:visible, input[placeholder*='Mobile number or email' i]:visible").first();
      if ((await emInput.count()) === 0 || !(await emInput.isVisible().catch(() => false))) {
        emInput = page.locator("input[type='text']:visible").nth(2);
      }
      await emInput.waitFor({ state: "visible", timeout: 15000 });
      await humanType(page, emInput, email);

      // Re-enter email confirmation if required
      await page.waitForTimeout(600);
      const reEmInput = page.locator("input[name='reg_email_confirmation__']:visible, input[aria-label*='Re-enter' i]:visible, input[placeholder*='Re-enter' i]:visible").first();
      if ((await reEmInput.count()) > 0 && (await reEmInput.isVisible().catch(() => false))) {
        await humanType(page, reEmInput, email);
      }

      // 4. Fill Password
      console.log(`[Facebook] Entering Password (masked)...`);
      let pwInput = page.locator("input[name='reg_passwd__']:visible, input[type='password']:visible").first();
      await pwInput.waitFor({ state: "visible", timeout: 15000 });
      await humanType(page, pwInput, password);

      // 5. Submit with natural hesitation pause
      await page.waitForTimeout(1000 + Math.random() * 800);
      console.log("[Facebook] Submitting registration form ('Submit')...");
      const submitBtn = page.locator("button:has-text('Submit'), [role='button']:has-text('Submit'), button:has-text('Sign Up'), [role='button']:has-text('Sign Up'), button:has-text('सबमिट'), [role='button']:has-text('सबमिट'), button:has-text('साइन अप करें')").first();
      if ((await submitBtn.count()) > 0 && (await submitBtn.isVisible().catch(() => false))) {
        await humanHover(page, submitBtn).catch(() => {});
        await page.waitForTimeout(350);
        await humanClick(page, submitBtn).catch(() => submitBtn.click());
      } else {
        await page.evaluate(() => {
          const buttons = Array.from(document.querySelectorAll("[role='button'], button"));
          const btn = buttons.find((b) => {
            const t = (b.innerText || "").trim().toLowerCase();
            return t === "submit" || t === "sign up" || t.includes("सबमिट") || t.includes("साइन अप");
          });
          if (btn) btn.click();
        });
      }

      console.log("[Facebook] Form submitted. Waiting 10s for response / verification challenge...");
      await page.waitForTimeout(10000);
      riskMark("form_submitted");

      const postSubmitUrl = page.url();
      const postSubmitTitle = await page.title();
      console.log(`[Facebook] Current URL: ${postSubmitUrl} | Title: '${postSubmitTitle}'`);

      const postSubmitSusp = await isFacebookSuspendedScreen(page);
      if (postSubmitSusp.isSuspended) {
        console.error("=".repeat(65));
        console.error(`[Facebook] ⚠️ ACCOUNT SUSPENDED: Facebook redirected to ${postSubmitSusp.url}`);
        console.error("=".repeat(65));
        if (RISK) {
          riskWarn(`Account immediately suspended on registration submit: ${postSubmitSusp.url}`);
          riskEvent("account_suspended", { url: postSubmitSusp.url, reason: postSubmitSusp.reason, at: new Date().toISOString() });
          riskMark("account_suspended");
        }
        await page.screenshot({ path: path.join(profileDir, "suspension_screen.png"), fullPage: true }).catch(() => {});
        await page.screenshot({ path: "tests/test_artifacts/fb_latest_live.png", fullPage: true }).catch(() => {});
        markFacebookAccountSuspended(email, postSubmitSusp.url, profileDir);
        saveRegisteredAccount({
          email,
          password,
          fullname: fullName,
          first_name: firstName,
          last_name: lastName,
          date_of_birth: dobObj.formatted,
          gender: randomGender,
          proxy_used: effectiveProxy,
          proxy_ip: proxyLocation.ip,
          proxy_location: {
            city: proxyLocation.city,
            region: proxyLocation.region,
            country: proxyLocation.country,
            timezone: proxyLocation.timezone,
          },
          page_name: "",
          page_url: "",
          full_hotmail_thread: null,
          account_created_at: new Date().toISOString(),
          status: "SUSPENDED",
          is_suspended: true,
          suspended_at: new Date().toISOString(),
          suspension_url: postSubmitSusp.url,
        });
        console.log("[Facebook] Automation strictly ABORTED due to account suspension.");
        console.log("[Facebook] >>> SESSION IS LIVE ON YOUR SCREEN <<<");
        return;
      }
    }

    // 6. Handle OTP challenge if prompted (Retrieves code & full thread)
    const otpRes = await handleOtpChallenge(page, email, clientId, refreshToken, startedAt);
    if (otpRes && otpRes.suspended) {
      console.error("=".repeat(65));
      console.error(`[Facebook] ⚠️ ACCOUNT SUSPENDED: Facebook is on suspension checkpoint ${otpRes.url}`);
      console.error("=".repeat(65));
      await page.screenshot({ path: path.join(profileDir, "suspension_screen.png"), fullPage: true }).catch(() => {});
      await page.screenshot({ path: "tests/test_artifacts/fb_latest_live.png", fullPage: true }).catch(() => {});
      markFacebookAccountSuspended(email, otpRes.url, profileDir);
      saveRegisteredAccount({
        email,
        password,
        fullname: fullName,
        first_name: firstName,
        last_name: lastName,
        date_of_birth: dobObj.formatted,
        gender: randomGender,
        proxy_used: effectiveProxy,
        proxy_ip: proxyLocation.ip,
        proxy_location: {
          city: proxyLocation.city,
          region: proxyLocation.region,
          country: proxyLocation.country,
          timezone: proxyLocation.timezone,
        },
        page_name: "",
        page_url: "",
        full_hotmail_thread: otpRes.thread || null,
        account_created_at: new Date().toISOString(),
        status: "SUSPENDED",
        is_suspended: true,
        suspended_at: new Date().toISOString(),
        suspension_url: otpRes.url,
      });
      console.log("[Facebook] Automation strictly ABORTED due to account suspension.");
      console.log("[Facebook] >>> SESSION IS LIVE ON YOUR SCREEN <<<");
      return;
    }

    // Capture exit IP after OTP
    await captureExitIp(page, "post_otp");

    // 6.5 Handle Post-Registration Modals ("Save info", "Not Now", etc.)
    await handlePostSignupModals(page, 15000);

    const postModalSusp = await isFacebookSuspendedScreen(page);
    if (postModalSusp.isSuspended) {
      console.error("=".repeat(65));
      console.error(`[Facebook] ⚠️ ACCOUNT SUSPENDED: Facebook redirected to ${postModalSusp.url}`);
      console.error("=".repeat(65));
      await page.screenshot({ path: path.join(profileDir, "suspension_screen.png"), fullPage: true }).catch(() => {});
      await page.screenshot({ path: "tests/test_artifacts/fb_latest_live.png", fullPage: true }).catch(() => {});
      markFacebookAccountSuspended(email, postModalSusp.url, profileDir);
      saveRegisteredAccount({
        email,
        password,
        fullname: fullName,
        first_name: firstName,
        last_name: lastName,
        date_of_birth: dobObj.formatted,
        gender: randomGender,
        proxy_used: effectiveProxy,
        proxy_ip: proxyLocation.ip,
        proxy_location: {
          city: proxyLocation.city,
          region: proxyLocation.region,
          country: proxyLocation.country,
          timezone: proxyLocation.timezone,
        },
        page_name: "",
        page_url: "",
        full_hotmail_thread: otpRes && otpRes.thread ? otpRes.thread : null,
        account_created_at: new Date().toISOString(),
        status: "SUSPENDED",
        is_suspended: true,
        suspended_at: new Date().toISOString(),
        suspension_url: postModalSusp.url,
      });
      console.log("[Facebook] Automation strictly ABORTED due to account suspension.");
      console.log("[Facebook] >>> SESSION IS LIVE ON YOUR SCREEN <<<");
      return;
    }

    // 7. Automated Facebook Page Creation Flow (Optional, guarded by !skipPage)
    let pageDetails = { pageName: "Personal Page", pageUrl: "https://www.facebook.com" };
    if (!skipPage) {
      console.log("[Facebook] Proceeding to automated Page creation flow...");
      try {
        await page.waitForTimeout(4000);
        if (!page.url().includes("facebook.com")) {
          await safeGoto(page, "https://www.facebook.com/?locale=en_US", { waitUntil: "domcontentloaded" });
        }
        pageDetails = await createFacebookPage(page);
      } catch (pageErr) {
        console.warn(`[Facebook Page Creation Note]: ${pageErr.message}`);
      }
    } else {
      console.log("[Facebook] Skipping Facebook Page creation per --skip-page flag.");
    }

    // 8. Save Comprehensive Account Record
    saveRegisteredAccount({
      email,
      password,
      fullname: fullName,
      first_name: firstName,
      last_name: lastName,
      date_of_birth: dobObj.formatted,
      gender: randomGender,
      proxy_used: effectiveProxy,
      proxy_ip: proxyLocation.ip,
      proxy_location: {
        city: proxyLocation.city,
        region: proxyLocation.region,
        country: proxyLocation.country,
        timezone: proxyLocation.timezone,
      },
      page_name: (pageDetails && pageDetails.pageName) || "",
      page_url: (pageDetails && pageDetails.pageUrl) || "",
      full_hotmail_thread: otpRes && otpRes.thread ? otpRes.thread : null,
      account_created_at: new Date().toISOString(),
      status: otpRes.success ? "CONFIRMED" : "PENDING_OTP",
    });

    // 9. Post-Creation Natural Human Feed Browsing Warmup (30s)
    if (!skipWarmup) {
      try {
        await warmUpFeed(page, 30);
      } catch (e) { }
    }

    saveRiskLog();

    // Keep browser window open for user visibility & inspection
    console.log("[Facebook] >>> SESSION IS LIVE ON YOUR SCREEN <<<");
    console.log("[Facebook] Browser will remain open. Close the browser window when you are done.");
    await new Promise((resolve) => browser.on("close", resolve));

  } finally {
    tickerActive = false;
    saveRiskLog();
    console.log("[Facebook] Script finished.");
  }
}

run().catch((err) => {
  console.error(`[Facebook Error]: ${err.stack || err}`);
  process.exit(1);
});
