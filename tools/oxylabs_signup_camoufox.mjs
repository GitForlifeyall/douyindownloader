#!/usr/bin/env node
/**
 * tools/oxylabs_signup_camoufox.mjs
 * =================================
 * Oxylabs dashboard registration form filler using Camoufox.
 *
 * Flow:
 *   1. Open https://dashboard.oxylabs.io/en/
 *   2. Click the "Register instead" link ([data-testid="login-registration"])
 *   3. Wait for the registration fields to render
 *   4. Fill Name / Surname (random unless supplied), Email, Password
 *   5. Screenshot the filled form
 *   6. With --submit: click Register, poll the Outlook/Hotmail mailbox for the
 *      activation email, open its dashboard.oxylabs.io/activate-user?token=...
 *      link, go to /en/overview, click "Add product instance", the
 *      "Residential Proxies" card (/en/instances/new?type=RP), fill a random
 *      instance name, click "Create instance", select country/city in the
 *      endpoint generator, copy the proxy endpoint and read the commitment
 *      card usage ($ spent vs plan limit).
 *
 * Separate mode:
 *   --usage-only with an existing profile logs in and prints only the
 *   commitment card values (plan, spent, limit, remaining USD/%).
 *   --continue (or --create-instance) on an already-registered account logs in
 *   with the saved password and runs the dashboard flow to create the
 *   Residential Proxies instance, select the endpoint, copy the proxy and read
 *   the commitment card usage.
 *
 * Anonymity / anti-detect stack (ported from the Facebook/Instagram Camoufox
 * signup tools):
 *   - --proxy is REQUIRED by default. The proxy is curl-verified before launch
 *     and auto-upgraded to an Oxylabs sessid_oneip-...-sesstime-30 session, so
 *     the exit IP cannot rotate mid-run. --allow-direct is the explicit opt-out.
 *   - Frozen BrowserForge fingerprint + canvas/audio/fonts seeds + a WebGL pair
 *     verified against Camoufox's webgl_data.db, with webgl_config and
 *     fingerprint.videoCard kept aligned.
 *   - Timezone/locale derived from the proxy exit (never from the host),
 *     block_webrtc, DoH disabled, UBO excluded, profile aging, UA parity.
 *   - Pre-signup coherence audit (webdriver, automation globals, timezone,
 *     screen, WebGL, WebRTC) fails closed on real-IP/timezone leaks, and exit
 *     IP is re-checked after submit, activation, instance creation and at the
 *     end. TLS JA3/JA4 is captured from a real browser page.
 *   - Every account password, proxy, creation date, usage snapshot and risk
 *     event is persisted in output/oxylabs_accounts.db (SQLite) as well as the
 *     JSON mirror.
 *
 *
 * The browser stays open after the run (press Enter in the terminal to close)
 * unless --no-pause is passed, so the current screen can be reviewed.
 *
 * Usage:
 *   node tools/oxylabs_signup_camoufox.mjs --email you@outlook.com --proxy "user:pass@host:port"
 *   node tools/oxylabs_signup_camoufox.mjs --email you@outlook.com --submit \
 *     --refresh-token "<ms-refresh-token>" --proxy "user:pass@host:port"
 *   node tools/oxylabs_signup_camoufox.mjs --email you@outlook.com --submit \
 *     --account "you@outlook.com|<password>|<refreshToken>|<clientId>"
 *   node tools/oxylabs_signup_camoufox.mjs --email you@outlook.com --usage-only
 *   node tools/oxylabs_signup_camoufox.mjs --email you@outlook.com --continue
 *   node tools/oxylabs_signup_camoufox.mjs --email you@outlook.com --proxy ... --first-name John --surname Doe
 *   node tools/oxylabs_signup_camoufox.mjs --email you@outlook.com --allow-direct   # real IP exposed
 *
 * Options:
 *   --email <addr>        Account email (required; also read from --account)
 *   --password <value>    Password to use (saved one reused, generated when new)
 *   --first-name <value>  Override the random first name
 *   --surname <value>     Override the random surname
 *   --account <value>     "<email>|<pass>|<refreshToken>|<clientId>" for the
 *                         Outlook/Hotmail parser (same format as other tools)
 *   --refresh-token <v>   Microsoft refresh token (alternative to --account)
 *   --client-id <v>       Microsoft OAuth client id (defaults to Thunderbird's)
 *   --email-timeout <s>   Seconds to wait for the activation email (default 180)
 *   --instance-name <v>   Override the random Residential Proxies instance name
 *   --country <name>      Endpoint country (default India; "Any" skips)
 *   --city <name>         Endpoint city (default Mumbai; "Any" skips)
 *   --usage-only          Only log in and print the commitment card usage
 *   --continue            Existing account: log in and create the RP instance/endpoint/proxy
 *   --proxy <value>       Proxy: user:pass@host:port (required unless --allow-direct)
 *   --allow-direct        Explicitly allow running without a proxy (real IP leaks)
 *   --timezone <tz>       Override the persona timezone (default: proxy exit timezone)
 *   --headless            Run without a visible window
 *   --submit              Click Register and run the activation/overview flow
 *   --no-pause            Close the browser immediately after the run
 *   --keep-open <sec>     Keep the browser open for N seconds (overrides --no-pause)
 *   --profile <dir>       Override the profile directory
 *
 * Output:
 *   output/profiles oxylabs/<email-local-part>/   persistent Camoufox profile
 *   output/profiles oxylabs/<profile>/persona.json      frozen seeds/GPU/timezone
 *   output/profiles oxylabs/<profile>/fingerprint.json  frozen full fingerprint
 *   output/profiles oxylabs/<profile>/risk_log.json     per-account anonymity log
 *   output/oxylabs_accounts.db                    SQLite: accounts/proxies/usage/risk
 *   output/oxylabs_registered_accounts.json       JSON credential/result mirror
 *   output/oxylabs_risk_log.json                  compact cross-account risk index
 *   tests/test_artifacts/oxylabs_*.png
 */

import fs from "node:fs";
import path from "node:path";
import crypto from "node:crypto";
import readline from "node:readline";
import { execFileSync } from "node:child_process";
import { humanClick, humanWander } from "./kinematic_mouse.mjs";
import { getMsAccessToken } from "./fetch_outlook_otp.mjs";
import {
  DB_FILE,
  isDatabaseAvailable,
  openDatabase,
  persistRecord,
  persistRiskEvents,
  getAccount as getDbAccount,
  getPreferredProxy as getDbPreferredProxy,
  closeDatabase,
} from "./oxylabs_accounts_db.mjs";

const CAMOUFOX_PATH = "file:///C:/Users/rudra/AppData/Roaming/npm/node_modules/camoufox-cli/node_modules/camoufox-js/dist/index.js";
const { Camoufox } = await import(CAMOUFOX_PATH);

const FP_GENERATOR_PATH = "file:///C:/Users/rudra/AppData/Roaming/npm/node_modules/camoufox-cli/node_modules/fingerprint-generator/index.mjs";
const { FingerprintGenerator } = await import(FP_GENERATOR_PATH);
const FP_GENERATOR = new FingerprintGenerator({ browsers: ["firefox"], operatingSystems: ["windows"] });

const CAMOUFOX_LOCALE_PATH = "file:///C:/Users/rudra/AppData/Roaming/npm/node_modules/camoufox-cli/node_modules/camoufox-js/dist/locale.js";
const { getGeolocation } = await import(CAMOUFOX_LOCALE_PATH);

const LANDING_URL = "https://dashboard.oxylabs.io/en/";
const REGISTRATION_URL = "https://dashboard.oxylabs.io/en/registration";
const CAMOUFOX_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:158.0) Gecko/20100101 Firefox/158.0";

const ARTIFACTS_DIR = path.resolve("tests", "test_artifacts");
const PROFILES_DIR = path.resolve("output", "profiles oxylabs");
const REGISTRY_FILE = path.resolve("output", "oxylabs_registered_accounts.json");
const RISK_LOG_FILE = path.resolve("output", "oxylabs_risk_log.json");

// GPU pairs verified against Camoufox's data-files/webgl_data.db (win > 0),
// preferring the high-weight entries instead of the anachronistic 8800 GTX /
// Intel 945GM rows. Camoufox needs the exact vendor+renderer pair to inject
// coherent shader constants, so never invent a GPU string here.
const GPU_CONFIGURATIONS = [
  ["Google Inc. (NVIDIA)", "ANGLE (NVIDIA, NVIDIA GeForce GTX 980 Direct3D11 vs_5_0 ps_5_0), or similar"],
  ["Google Inc. (NVIDIA)", "ANGLE (NVIDIA, NVIDIA GeForce GTX 480 Direct3D11 vs_5_0 ps_5_0), or similar"],
  ["Google Inc. (AMD)", "ANGLE (AMD, Radeon R9 200 Series Direct3D11 vs_5_0 ps_5_0), or similar"],
  ["Google Inc. (AMD)", "ANGLE (AMD, Radeon HD 3200 Graphics Direct3D11 vs_5_0 ps_5_0), or similar"],
  ["Google Inc. (Intel)", "ANGLE (Intel, Intel(R) HD Graphics Direct3D11 vs_5_0 ps_5_0), or similar"],
  ["Google Inc. (Intel)", "ANGLE (Intel, Intel(R) HD Graphics 400 Direct3D11 vs_5_0 ps_5_0), or similar"],
];

const SCREEN_RESOLUTIONS = [
  { width: 1920, height: 1080 },
  { width: 1600, height: 900 },
  { width: 1536, height: 864 },
  { width: 1440, height: 900 },
  { width: 1366, height: 768 },
];

// ---------------------------------------------------------------------------
// CLI arguments
// ---------------------------------------------------------------------------
const args = process.argv.slice(2);
function getArg(name, defaultValue = null) {
  const idx = args.indexOf(name);
  return idx >= 0 && idx + 1 < args.length ? args[idx + 1] : defaultValue;
}
const hasFlag = (name) => args.includes(name);

// Outlook/Hotmail mailbox access (same "<email>|<pass>|<refreshToken>|<clientId>"
// format used by tools/fetch_outlook_otp.mjs and the Instagram/Facebook tools).
const accountArg = getArg("--account");
let refreshToken = String(getArg("--refresh-token", "") || "").trim();
let clientId = String(getArg("--client-id", "") || "").trim();
let emailFromAccount = "";
if (accountArg && accountArg.includes("|")) {
  const parts = accountArg.split("|");
  emailFromAccount = (parts[0] || "").trim();
  refreshToken = refreshToken || (parts[2] || "").trim();
  let rawClientId = (parts[3] || "").trim().replace(/["']/g, "");
  if (rawClientId.startsWith("9e5f94bc") && rawClientId.length === 35) {
    rawClientId = "9e5f94bc-e8a4-4e73-b8be-63364c29d753";
  }
  clientId = clientId || rawClientId;
}
if (refreshToken && !clientId) {
  clientId = "9e5f94bc-e8a4-4e73-b8be-63364c29d753";
}

const email = String(getArg("--email", emailFromAccount) || "").trim();
const explicitPassword = getArg("--password");
const explicitFirstName = getArg("--first-name");
const explicitSurname = getArg("--surname");
const explicitProxy = getArg("--proxy");
const allowDirect = hasFlag("--allow-direct");
const explicitTimezone = String(getArg("--timezone", "") || "").trim();
const instanceUrl = String(getArg("--instance-url", "") || "").trim();
const profileDirArg = getArg("--profile");
const headless = hasFlag("--headless");
const submit = hasFlag("--submit");
const usageOnly = hasFlag("--usage-only") || hasFlag("--check-usage");
const continueMode = hasFlag("--continue") || hasFlag("--create-instance");
const country = String(getArg("--country", "India") || "India").trim();
const city = String(getArg("--city", "Mumbai") || "Mumbai").trim();
const noPause = hasFlag("--no-pause");
const keepOpenSeconds = Number(getArg("--keep-open", "0")) || 0;
const fieldTimeout = Number(getArg("--timeout", "30000")) || 30000;
const emailTimeoutSec = Number(getArg("--email-timeout", "180")) || 180;
const explicitInstanceName = getArg("--instance-name");

if (!email && !profileDirArg) {
  console.error("Error: --email <address> is required (the Outlook address you want to register).");
  process.exit(1);
}
if (submit && !refreshToken) {
  console.warn("[Oxylabs] WARNING: no --refresh-token/--account supplied; the script will submit the form but cannot open the activation email automatically.");
}
if (email && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
  console.error(`Error: invalid email address: ${email}`);
  process.exit(1);
}
if (explicitInstanceName && String(explicitInstanceName).trim().length < 4) {
  console.error("Error: --instance-name must be at least 4 characters.");
  process.exit(1);
}

// ---------------------------------------------------------------------------
// Identity helpers
// ---------------------------------------------------------------------------
const FIRST_NAMES = [
  "James", "Oliver", "Liam", "Noah", "Ethan", "Lucas", "Mason", "Logan",
  "Daniel", "Henry", "Jack", "Samuel", "David", "Joseph", "Carter", "Owen",
  "Arjun", "Rohan", "Aditya", "Vikram", "Rahul", "Karan", "Ishaan", "Nikhil",
  "Amit", "Siddharth", "Varun", "Harsh", "Kabir", "Dhruv", "Yash", "Manish",
  "Emma", "Olivia", "Ava", "Sophia", "Isabella", "Mia", "Charlotte", "Amelia",
  "Priya", "Ananya", "Neha", "Kavya", "Meera", "Riya", "Sneha", "Pooja",
];

const SURNAMES = [
  "Smith", "Johnson", "Williams", "Brown", "Jones", "Miller", "Davis", "Wilson",
  "Anderson", "Taylor", "Thomas", "Moore", "Jackson", "Martin", "Lee", "Walker",
  "Sharma", "Patel", "Reddy", "Nair", "Iyer", "Gupta", "Mehta", "Chopra",
  "Verma", "Joshi", "Kapoor", "Malhotra", "Rao", "Desai", "Bose", "Menon",
  "Clark", "Lewis", "Young", "Hall", "Wright", "Green", "Baker", "Adams",
];

const pick = (list) => list[crypto.randomInt(list.length)];

const INSTANCE_ADJECTIVES = [
  "Global", "Prime", "Rapid", "Secure", "Smart", "Edge", "Reliable", "Flexible",
  "Dynamic", "Stable", "Bright", "Swift", "Nordic", "Pacific", "Atlantic", "Metro",
];

const INSTANCE_NOUNS = [
  "Node", "Pool", "Instance", "Asset", "Gateway", "Network", "Route", "Relay",
  "Endpoint", "Cluster", "Bridge", "Stream", "Link", "Hub", "Grid", "Compass",
];

function generateInstanceName() {
  return `${pick(INSTANCE_ADJECTIVES)} ${pick(INSTANCE_NOUNS)} ${crypto.randomInt(1000, 10000)}`;
}

function generatePassword(length = 18) {
  const lower = "abcdefghijkmnopqrstuvwxyz";
  const upper = "ABCDEFGHJKLMNPQRSTUVWXYZ";
  const digits = "23456789";
  // Oxylabs rejects any other symbols: "Password should contain only these
  // special characters !#%^&*()+-".
  const special = "!#%^&*()+-";
  const all = lower + upper + digits + special;
  const chars = [
    lower[crypto.randomInt(lower.length)],
    upper[crypto.randomInt(upper.length)],
    digits[crypto.randomInt(digits.length)],
    special[crypto.randomInt(special.length)],
  ];
  while (chars.length < length) chars.push(all[crypto.randomInt(all.length)]);
  for (let i = chars.length - 1; i > 0; i--) {
    const j = crypto.randomInt(i + 1);
    [chars[i], chars[j]] = [chars[j], chars[i]];
  }
  return chars.join("");
}

function sanitizeProfileName(value, fallbackSeed = "") {
  const cleaned = String(value || "").split("@")[0].replace(/[^A-Za-z0-9._-]/g, "");
  if (!cleaned || cleaned === "." || cleaned === "..") {
    return `profile_${crypto.createHash("sha256").update(fallbackSeed || value || String(Date.now())).digest("hex").slice(0, 8)}`;
  }
  return cleaned;
}

// ---------------------------------------------------------------------------
// Proxy identity, sticky sessions and fail-closed preflight
// ---------------------------------------------------------------------------
function sha256Short(value, length = 16) {
  if (!value) return null;
  return crypto.createHash("sha256").update(String(value)).digest("hex").slice(0, length);
}

function parseProxy(value) {
  if (!value) return null;
  const clean = String(value).trim().replace(/^https?:\/\//i, "");
  const at = clean.lastIndexOf("@");
  if (at >= 0) {
    const auth = clean.slice(0, at);
    const hostPort = clean.slice(at + 1);
    const colon = auth.indexOf(":");
    return {
      server: `http://${hostPort}`,
      username: decodeURIComponent(colon >= 0 ? auth.slice(0, colon) : auth),
      password: colon >= 0 ? decodeURIComponent(auth.slice(colon + 1)) : undefined,
    };
  }
  return { server: `http://${clean}` };
}

/**
 * Oxylabs residential/mobile proxies rotate the exit peer on every request
 * unless the username carries a sticky-session id. We always create a
 * `sessid_oneip` session (strict: the exit must not change mid-run) with a
 * 30-minute lifetime, seeded from the account email so reruns stay on the same
 * peer where possible.
 */
function ensureStickyProxy(value, seed = null, minutes = 30) {
  if (!value) return value;
  const clean = String(value).trim().replace(/^https?:\/\//i, "");
  const at = clean.lastIndexOf("@");
  if (at < 0) return `http://${clean}`;

  const auth = clean.slice(0, at);
  const hostPort = clean.slice(at + 1);
  const colon = auth.indexOf(":");
  let username = colon >= 0 ? auth.slice(0, colon) : auth;
  const password = colon >= 0 ? auth.slice(colon + 1) : "";
  if (!username) return `http://${clean}`;

  if (hostPort.includes("oxylabs.io") || username.startsWith("customer-")) {
    if (!/sessid|session/i.test(username)) {
      const seedHash = seed
        ? crypto.createHash("md5").update(String(seed)).digest("hex").slice(0, 4)
        : "";
      const sessId = `${seedHash}${crypto.randomBytes(3).toString("hex")}`;
      username = `${username}-sessid_oneip-${sessId}-sesstime-${minutes}`;
    }
  }

  return `http://${username}:${password}@${hostPort}`;
}

function parseProxyIdentity(value) {
  const clean = String(value || "").trim().replace(/^https?:\/\//i, "");
  const at = clean.lastIndexOf("@");
  const auth = at >= 0 ? clean.slice(0, at) : "";
  const host = at >= 0 ? clean.slice(at + 1) : clean;
  const username = auth.split(":")[0] || "";

  const sessionMatch = username.match(/(?:^|[-_])(sessid_oneip|sessid|session|sess)[-_]([A-Za-z0-9._]+)/i);
  const sessionType = sessionMatch ? sessionMatch[1].toLowerCase() : null;
  const session = sessionMatch ? sessionMatch[2] : null;
  const sessionTimeMatch = username.match(/-sesstime-(\d+)/i);

  const portMatch = host.match(/:(\d+)$/);
  const port = portMatch ? Number(portMatch[1]) : null;
  const stickyPort = port != null && port >= 8001 ? port : null;

  const countryMatch = username.match(/-cc-([a-z]{2})(?:[-_]|$)/i);
  const cityMatch = username.match(/-city-([a-z0-9_]+)(?:[-_]|$)/i);

  return {
    host: host || null,
    port,
    masked: maskProxy(value),
    username_hash: sha256Short(username),
    session,
    session_type: sessionType,
    session_minutes: sessionTimeMatch ? Number(sessionTimeMatch[1]) : null,
    sticky_port: stickyPort,
    country: countryMatch ? countryMatch[1].toUpperCase() : null,
    city: cityMatch ? cityMatch[1].replace(/_/g, " ") : null,
    has_sticky_session: Boolean(session || stickyPort),
    strict_sticky: sessionType === "sessid_oneip" || Boolean(stickyPort),
  };
}

function maskProxy(value) {
  if (!value) return null;
  const clean = String(value).trim().replace(/^https?:\/\//i, "");
  if (!isRealProxy(value)) return "*** (non-proxy text)";
  const at = clean.lastIndexOf("@");
  if (at >= 0) return `***@${clean.slice(at + 1)}`;
  return clean;
}

function isRealProxy(value) {
  const clean = String(value || "").trim();
  if (!clean) return false;
  return clean.includes("pr.oxylabs.io");
}

/**
 * Extracts an Oxylabs proxy URL from text on the instance page. The dashboard
 * shows the endpoint as `curl -x http://user:pass@pr.oxylabs.io:7777 ...` or as
 * a `http://...@pr.oxylabs.io:7777` line; this returns the URL only when it
 * contains pr.oxylabs.io.
 */
function extractProxyFromText(text) {
  if (!text) return null;
  const s = text.replace(/\s+/g, " ");

  // Form 1: curl -x pr.oxylabs.io:PORT ... -U "user:pass" ...
  const curlM = s.match(/curl\s+-x\s+[\"']?([^\s\"']+)[\"']?/i);
  const curlU = s.match(/-U\s+[\"']?([^\s\"']+:[^\s\"']+)[\"']?/i);
  if (curlM) {
    const hostPort = curlM[1];
    if (hostPort.includes("pr.oxylabs.io")) {
      const auth = curlU ? curlU[1] : null;
      return auth ? `http://${auth}@${hostPort}` : `http://${hostPort}`;
    }
  }

  // Form 2: curl -x https://user:pass@pr.oxylabs.io:PORT ...
  const fullCurl = s.match(/curl\s+-x\s+([^\s]+)/i);
  if (fullCurl) {
    const v = String(fullCurl[1]).replace(/^["']|["']$/g, "");
    if (v.includes("pr.oxylabs.io") && v.includes("@")) return v;
  }

  // Form 3: any URL containing pr.oxylabs.io with @ credentials
  const urlM = s.match(/https?:\/\/[^\s"'`<>]+@[^\s"'`<>]+/i);
  if (urlM) return urlM[0].replace(/["'`]+$/g, "").replace(/^["'`]+/, "");

  // Form 4: proxy[:=] http://...@pr.oxylabs.io
  const proxyM = s.match(/(?:proxy|server|endpoint)[:=]\s*["']?([^"'\s]+)["']?/i);
  if (proxyM) return proxyM[1];

  // Form 5: username/password and host on the same line
  const upM = s.match(/(customer-[\w-]+)[^ ]*:[^\s]+/i);
  const hostM = s.match(/pr\.oxylabs\.io:\d+/i);
  if (upM && hostM) return `http://${upM[1]}:${upM[0].split(":").pop()}@${hostM[0]}`;

  return null;
}

function sanitizeError(message) {
  return String(message || "")
    .replace(/([?&](?:token|code|key|access_token|refresh_token|id_token)=)[^&\s"']+/gi, "$1***")
    .replace(/(Bearer\s+)[A-Za-z0-9._~+/-]+=*/gi, "$1***");
}

const TZ_ALIASES = {
  "Asia/Calcutta": "Asia/Kolkata",
  "Asia/Katmandu": "Asia/Kathmandu",
  "Europe/Kiev": "Europe/Kyiv",
  "America/Godthab": "America/Nuuk",
  "Asia/Saigon": "Asia/Ho_Chi_Minh",
};

function canonicalTimezone(value) {
  return TZ_ALIASES[value] || value || null;
}

const COUNTRY_TIMEZONES = {
  IN: "Asia/Kolkata", INDIA: "Asia/Kolkata",
  US: "America/Chicago", USA: "America/Chicago", "UNITED STATES": "America/Chicago",
  CA: "America/Toronto", CANADA: "America/Toronto",
  GB: "Europe/London", UK: "Europe/London", "UNITED KINGDOM": "Europe/London",
  DE: "Europe/Berlin", GERMANY: "Europe/Berlin",
  FR: "Europe/Paris", FRANCE: "Europe/Paris",
  NL: "Europe/Amsterdam", NETHERLANDS: "Europe/Amsterdam",
  ES: "Europe/Madrid", SPAIN: "Europe/Madrid",
  IT: "Europe/Rome", ITALY: "Europe/Rome",
  JP: "Asia/Tokyo", JAPAN: "Asia/Tokyo",
  SG: "Asia/Singapore", SINGAPORE: "Asia/Singapore",
  AE: "Asia/Dubai", UAE: "Asia/Dubai", "UNITED ARAB EMIRATES": "Asia/Dubai",
  AU: "Australia/Sydney", AUSTRALIA: "Australia/Sydney",
  BR: "America/Sao_Paulo", BRAZIL: "America/Sao_Paulo",
  ZA: "Africa/Johannesburg", "SOUTH AFRICA": "Africa/Johannesburg",
};

function deriveTimezoneFromProxy(value, countryHint = null) {
  const p = String(value || "").toLowerCase();
  const identity = parseProxyIdentity(value);
  const hint = String(countryHint || "").trim().toUpperCase();
  const code = hint && hint !== "ANY" ? hint : identity.country;

  if (code) {
    const fromCountry = COUNTRY_TIMEZONES[code];
    if (fromCountry) return { tz: fromCountry, region: code.length === 2 ? code : null, lang: "en" };
  }

  if (p.includes("alabama") || p.includes("chicago")) return { tz: "America/Chicago", region: "US", lang: "en" };
  if (p.includes("california") || p.includes("los_angeles") || p.includes("pacific")) return { tz: "America/Los_Angeles", region: "US", lang: "en" };
  if (p.includes("new_york") || p.includes("new-york") || p.includes("eastern")) return { tz: "America/New_York", region: "US", lang: "en" };
  if (p.includes("mumbai") || p.includes("ludhiana") || p.includes("ahmedabad") || p.includes("india")) return { tz: "Asia/Kolkata", region: "IN", lang: "en" };
  if (p.includes("tokyo") || p.includes("japan")) return { tz: "Asia/Tokyo", region: "JP", lang: "en" };
  if (p.includes("london") || p.includes("united_kingdom")) return { tz: "Europe/London", region: "GB", lang: "en" };
  if (p.includes("berlin") || p.includes("germany")) return { tz: "Europe/Berlin", region: "DE", lang: "en" };

  // Never fall back to the host machine's timezone: that is exactly the real
  // signal we are trying to keep out of the browser.
  return { tz: "UTC", region: null, lang: "en" };
}

const COUNTRY_CODES = {
  INDIA: "IN",
  "UNITED STATES": "US", USA: "US", "UNITED STATES OF AMERICA": "US",
  "UNITED KINGDOM": "GB", UK: "GB", "GREAT BRITAIN": "GB",
  GERMANY: "DE", FRANCE: "FR", NETHERLANDS: "NL", SPAIN: "ES", ITALY: "IT",
  JAPAN: "JP", SINGAPORE: "SG", "UNITED ARAB EMIRATES": "AE", UAE: "AE",
  AUSTRALIA: "AU", BRAZIL: "BR", "SOUTH AFRICA": "ZA", CANADA: "CA",
  RUSSIA: "RU", "RUSSIAN FEDERATION": "RU", TURKEY: "TR", "TÜRKIYE": "TR",
};

function normalizeExitInfo(data) {
  if (!data || typeof data !== "object") return null;
  let country = data.country_code || data.country || data.country_name || null;
  if (country) {
    const upper = String(country).toUpperCase();
    country = upper.length === 2 ? upper : (COUNTRY_CODES[upper] || country);
  }

  // Some geolocation providers (ipinfo) return a "lat,lon" string; others
  // return separate fields. Parse either so the geolocation spoof can be
  // derived from the proxy exit even when the top-level latitude is missing.
  let latitude = data.latitude ?? data.lat;
  let longitude = data.longitude ?? data.lon;
  if ((latitude == null || longitude == null) && typeof data.loc === "string") {
    const [la, lo] = data.loc.split(",").map((v) => Number(String(v).trim())).filter((v) => Number.isFinite(v));
    latitude = latitude ?? la;
    longitude = longitude ?? lo;
  }

  return {
    ip: data.ip || data.query || data.origin || null,
    city: data.city || data.city_name || null,
    region: data.region || data.region_name || data.region_code || null,
    country: country || null,
    country_name: data.country_name || data.country || null,
    timezone: canonicalTimezone(data.timezone || data.time_zone || null),
    asn: data.asn || data.asn_number || data.org || null,
    org: data.org || data.isp || data.organization || null,
    latitude: latitude != null ? Number(latitude) : null,
    longitude: longitude != null ? Number(longitude) : null,
    source: data.source || null,
  };
}

/**
 * Curl preflight through the proxy. Curl is used (instead of Node fetch) so
 * the request really goes through the configured proxy and a 407/dead proxy
 * aborts before Camoufox launches. execFileSync avoids shell interpolation of
 * proxy credentials.
 */
function validateProxyConnectivity(proxyStr, timeoutMs = 75000) {
  if (!proxyStr) return { ok: false, error: "no proxy configured" };

  const endpoints = [
    "https://ipapi.co/json/",
    "https://ipinfo.io/json",
    "https://ip.oxylabs.io/location",
  ];
  let lastError = "";

  for (const url of endpoints) {
    try {
      const stdout = execFileSync(
        "curl.exe",
        [
          "-sS",
          "--max-time", "20",
          "-x", proxyStr,
          "-H", "Accept: application/json",
          "-w", "\n%{http_code}",
          url,
        ],
        { encoding: "utf-8", timeout: timeoutMs, stdio: ["ignore", "pipe", "pipe"] }
      );

      const lines = String(stdout || "").trim().split(/\r?\n/);
      const status = Number(lines.pop());
      const body = lines.join("\n");

      if (status === 407) {
        return { ok: false, statusCode: 407, error: "HTTP 407 Proxy Authentication Required" };
      }
      if (status === 200) {
        let info = null;
        try {
          info = normalizeExitInfo(JSON.parse(body));
        } catch (e) { }
        if (info && info.ip) {
          return { ok: true, statusCode: 200, endpoint: url, info };
        }
        lastError = `HTTP 200 but no IP in the ${url} response`;
      } else {
        lastError = `HTTP ${status || "?"} from ${url}`;
      }
    } catch (err) {
      const stderr = String(err.stderr || err.message || "").trim();
      if (/407/i.test(stderr)) {
        return { ok: false, statusCode: 407, error: stderr || "HTTP 407 Proxy Authentication Required" };
      }
      lastError = stderr || err.message;
    }
  }

  return { ok: false, error: lastError || "proxy preflight failed" };
}

/**
 * Derives a geolocation spoof from the proxy exit IP using Camoufox's bundled
 * GeoLite2 database. This closes a leak: Camoufox only spoofs geolocation when
 * `geoip` is enabled, which it would otherwise do via `geolocation:*` config
 * keys; without it, `navigator.geolocation` falls back to the OS location
 * services on the real machine. We set the config keys ourselves so the
 * geolocation API returns the proxy location while our explicit timezone
 * stays untouched.
 */
async function deriveGeolocationSpoof(ip) {
  if (!ip) return null;
  try {
    const geo = await getGeolocation(ip);
    if (!geo || !geo.latitude || !geo.longitude) return null;
    return {
      ip,
      latitude: geo.latitude,
      longitude: geo.longitude,
      accuracy: geo.accuracy != null ? geo.accuracy : 500,
      source: "camoufox_geoip",
    };
  } catch (err) {
    riskWarn(`Geolocation spoof could not be derived from proxy exit ${ip}: ${err.message}`, "geoip");
    return null;
  }
}

// ---------------------------------------------------------------------------
// Risk log (never contains passwords, OTPs, mailbox tokens or proxy auth)
// ---------------------------------------------------------------------------
let RISK = null;

function hashFingerprint(fingerprint) {
  if (!fingerprint) return null;
  return crypto
    .createHash("sha256")
    .update(JSON.stringify({
      screen: fingerprint.screen || null,
      navigator: fingerprint.navigator || null,
      videoCard: fingerprint.videoCard || null,
    }))
    .digest("hex")
    .slice(0, 16);
}

function initRiskLog({ email, proxyArg, persona, fingerprint, profileDir, startedAt, preflight, requestedCountry, fingerprintPath, personaPath }) {
  const identity = proxyArg ? parseProxyIdentity(proxyArg) : null;
  RISK = {
    email,
    started_at: new Date(startedAt).toISOString(),
    profile_dir: profileDir,
    requested_country: requestedCountry || null,
    proxy: identity ? { ...identity, masked: maskProxy(proxyArg) } : null,
    persona: persona
      ? {
        timezone: persona.timezone,
        webgl_config: persona.webgl_config,
        screen_resolution: persona.screen_resolution,
      }
      : null,
    fingerprint: {
      hash: hashFingerprint(fingerprint),
      screen: fingerprint?.screen || null,
      ua: fingerprint?.navigator?.userAgent || null,
      coherence: null,
      tls: null,
    },
    fingerprint_path: fingerprintPath || null,
    persona_path: personaPath || null,
    timing: {
      started_at: new Date(startedAt).toISOString(),
      preflight_at: null,
      form_submitted_at: null,
      activated_at: null,
      finished_at: null,
      total_seconds: null,
    },
    preflight: preflight?.info || null,
    exit_ips: [],
    events: [],
    warnings: [],
    persisted_event_count: 0,
  };

  if (preflight?.info?.ip) {
    RISK.exit_ips.push({ step: "curl_preflight", at: new Date().toISOString(), ...preflight.info });
  }

  if (!proxyArg) {
    riskWarn("DIRECT MODE: no proxy is configured, so the real IP/timezone can reach the dashboard.", "init");
  } else {
    if (!identity.has_sticky_session) {
      riskWarn("Proxy username has no sticky-session id; the exit IP can rotate mid-run.", "init");
    }
    if (identity.session_type && identity.session_type !== "sessid_oneip" && !identity.sticky_port) {
      riskWarn(`Proxy session type "${identity.session_type}" is not strict; use sessid_oneip so a mid-run IP change aborts.`, "init");
    }
  }

  return RISK;
}

function riskMark(step) {
  if (!RISK) return;
  const key = `${step}_at`;
  if (key in RISK.timing) RISK.timing[key] = new Date().toISOString();
}

function riskEvent(step, level = "info", message = "", details = undefined) {
  if (!RISK) return;
  const event = { at: new Date().toISOString(), step, level, message };
  if (details !== undefined) event.details = details;
  RISK.events.push(event);

  if (level === "warn" || level === "critical") {
    if (message && !RISK.warnings.includes(message)) RISK.warnings.push(message);
    if (message) console.warn(`[Risk] ${message}`);
  }
}

function riskWarn(message, step = "general") {
  riskEvent(step, "warn", message);
}

function saveRiskLog() {
  if (!RISK) return;
  try {
    const now = new Date();
    RISK.finished_at = now.toISOString();
    RISK.timing.finished_at = RISK.finished_at;
    RISK.timing.total_seconds = Math.round((now.getTime() - new Date(RISK.started_at).getTime()) / 1000);

    const target = path.join(RISK.profile_dir, "risk_log.json");
    fs.mkdirSync(path.dirname(target), { recursive: true });
    fs.writeFileSync(target, JSON.stringify(RISK, null, 2), "utf-8");

    let central = [];
    if (fs.existsSync(RISK_LOG_FILE)) {
      try { central = JSON.parse(fs.readFileSync(RISK_LOG_FILE, "utf-8")); } catch (e) { central = []; }
    }
    if (!Array.isArray(central)) central = [];
    central = central.filter((item) => String(item?.email || "").toLowerCase() !== String(RISK.email || "").toLowerCase());
    central.push({
      email: RISK.email,
      created_at: RISK.started_at,
      proxy: RISK.proxy ? {
        host: RISK.proxy.host,
        masked: RISK.proxy.masked,
        username_hash: RISK.proxy.username_hash,
        session: RISK.proxy.session,
        session_type: RISK.proxy.session_type,
        strict_sticky: RISK.proxy.strict_sticky,
        country: RISK.proxy.country,
      } : null,
      persona: RISK.persona,
      fingerprint_hash: RISK.fingerprint?.hash || null,
      tls: RISK.fingerprint?.tls || null,
      exit_ips: RISK.exit_ips,
      warnings: RISK.warnings,
      events: RISK.events.length,
      risk_log: target,
    });
    fs.writeFileSync(RISK_LOG_FILE, JSON.stringify(central, null, 2), "utf-8");

    const newEvents = RISK.events.slice(RISK.persisted_event_count || 0);
    if (newEvents.length > 0) {
      persistRiskEvents(RISK.email, newEvents);
      RISK.persisted_event_count = RISK.events.length;
    }
    console.log(`[Risk] Saved Oxylabs risk log: ${target}`);
  } catch (e) {
    console.warn(`[Risk] Could not save the risk log: ${e.message}`);
  }
}

function isPrivateIp(ip) {
  return /^(10\.|192\.168\.|169\.254\.|127\.|0\.0\.0\.0)/.test(ip)
    || /^172\.(1[6-9]|2\d|3[01])\./.test(ip)
    || /^(fe80:|fc|fd|::1$|::$)/i.test(ip);
}

async function captureExitIp(page, step = "unspecified") {
  const entry = {
    step,
    at: new Date().toISOString(),
    ip: null, asn: null, org: null, city: null, region: null,
    country: null, country_name: null, timezone: null, source: null, error: null,
  };

  try {
    const found = await page.evaluate(async () => {
      const urls = ["https://ipapi.co/json/", "https://ipinfo.io/json"];
      for (const url of urls) {
        const controller = new AbortController();
        const timer = setTimeout(() => controller.abort(), 6000);
        try {
          const res = await fetch(url, {
            signal: controller.signal,
            headers: { Accept: "application/json" },
            credentials: "omit",
          });
          if (res.ok) return { url, data: await res.json() };
        } catch (e) {
          // try the next endpoint
        } finally {
          clearTimeout(timer);
        }
      }
      return null;
    });

    if (found?.data) {
      const info = normalizeExitInfo({ ...found.data, source: found.url });
      Object.assign(entry, info);
    }
  } catch (e) {
    entry.error = e.message;
  }

  // CSP or CORS on the dashboard can block the in-page fetch. Fall back to a
  // throwaway tab that navigates to the JSON endpoint directly (still through
  // the browser proxy).
  if (!entry.ip) {
    let tab = null;
    try {
      tab = await page.context().newPage();
      for (const url of ["https://ipapi.co/json/", "https://ipinfo.io/json"]) {
        try {
          await tab.goto(url, { waitUntil: "domcontentloaded", timeout: 25000 });
          const text = await tab.evaluate(() => (document.body ? document.body.innerText : ""));
          const info = normalizeExitInfo(JSON.parse(text));
          if (info?.ip) {
            Object.assign(entry, info, { source: url });
            break;
          }
        } catch (e) {
          entry.error = e.message;
        }
      }
    } catch (e) {
      entry.error = e.message;
    } finally {
      if (tab) await tab.close().catch(() => { });
    }
  }

  if (RISK) {
    RISK.exit_ips.push(entry);
    const knownIps = [RISK.preflight?.ip, ...RISK.exit_ips.map((item) => item.ip)].filter(Boolean);
    const firstIp = knownIps[0];

    if (!entry.ip) {
      riskWarn(`Exit IP check failed at "${step}"; the proxy exit could not be verified.`, step);
    } else if (firstIp && entry.ip !== firstIp) {
      const message = `CRITICAL: exit IP changed mid-run: ${firstIp} -> ${entry.ip} (@${step}).`;
      riskEvent(step, "critical", message);
      if (RISK.proxy?.strict_sticky) {
        throw new Error(`[Risk] Bound proxy session changed exit IP (${firstIp} -> ${entry.ip}) at ${step}. Aborting.`);
      }
    } else {
      riskEvent(step, "info", `Exit IP ${entry.ip}${entry.asn ? ` | ASN ${entry.asn}` : ""}${entry.city ? ` | ${entry.city}, ${entry.region || ""}, ${entry.country || ""}` : ""}`);
    }
  }

  console.log(
    `[Risk] Exit IP @ ${step}: ${entry.ip || "unknown"}`
    + `${entry.asn ? ` | ASN ${entry.asn}` : ""}`
    + `${entry.city ? ` | ${entry.city}, ${entry.region || ""}, ${entry.country || ""}` : ""}`
  );
  return entry;
}

/**
 * Node/Intl report `getTimezoneOffset()` as minutes between UTC and local time
 * (east positive), while an explicit offset in a timezone name is usually
 * "GMT+...". Normalize to `getTimezoneOffset()` semantics so we can compare
 * the live browser offset with the spoofed timezone.
 */
function expectedTimezoneOffsetMinutes(tz, date = new Date()) {
  try {
    const dtf = new Intl.DateTimeFormat("en-US", { timeZone: tz, timeZoneName: "longOffset" });
    const name = (dtf.formatToParts(date).find((p) => p.type === "timeZoneName") || {}).value || "";
    const match = name.match(/GMT([+-])(\d{2}):?(\d{2})?/);
    if (!match) return null;
    const sign = match[1] === "-" ? -1 : 1;
    return sign * (Number(match[2]) * 60 + Number(match[3] || 0));
  } catch (e) {
    return null;
  }
}

async function auditBrowserCoherence(page, expected = {}) {
  const result = {
    checked_at: new Date().toISOString(),
    warnings: [],
    criticals: [],
    probe: null,
    webrtc_candidates: [],
  };

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
        out.locale = Intl.DateTimeFormat().resolvedOptions().locale;
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
          window.__playwright
          || window.__puppeteer
          || window.cdc_adoQpoasnfa76pfcZLmcfl_Array
          || window.__nightmare
          || window.callPhantom
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

        // WebRTC candidates (no STUN): a public address here that is not the
        // proxy exit is the real host address leaking.
        try {
          out.webrtcCandidates = await new Promise((resolve) => {
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
                const ips = text.match(/(?:\d{1,3}\.){3}\d{1,3}|[0-9a-f]{1,4}(?::[0-9a-f]{1,4}){2,7}/gi) || [];
                for (const ip of ips) {
                  if (!candidates.includes(ip)) candidates.push(ip);
                }
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
        } catch (e) {
          out.webrtcCandidates = [];
        }
      } catch (e) {
        out.error = String(e);
      }
      return out;
    });

    result.probe = probe;
    result.webrtc_candidates = probe.webrtcCandidates || [];

    // Bot signals: these are hard failures, never warnings.
    if (probe.webdriver === true) result.criticals.push("navigator.webdriver is true (bot signal)");
    if (probe.automationGlobals) result.criticals.push("Playwright/Puppeteer instrumentation variable found on window");
    if (probe.hasChromeObject) result.criticals.push("window.chrome exists in a Firefox persona");
    if (probe.userAgent && /headless/i.test(probe.userAgent)) result.criticals.push("User-Agent contains 'headless'");
    if (probe.webdriverIsOwn) result.warnings.push("navigator.webdriver is an own property (tampering artifact)");

    if (expected.os === "windows" && probe.platform && !/win/i.test(probe.platform)) {
      result.warnings.push(`navigator.platform "${probe.platform}" does not match a Windows persona`);
    }

    // Timezone must agree with the proxy exit / persona. A contradiction is a
    // real location leak, so it is critical whenever a proxy is in use.
    // `expected.timezone` is taken from the curl preflight / proxy exit, which
    // is authoritative. Do not re-check it against a single timezone per
    // country here: multi-zone countries (US, CA, AU, BR, RU) would false-abort.
    if (expected.timezone && probe.timezone
      && canonicalTimezone(probe.timezone) !== canonicalTimezone(expected.timezone)) {
      const message = `timezone "${probe.timezone}" does not match the proxy/persona timezone "${expected.timezone}"`;
      if (RISK?.proxy) result.criticals.push(message);
      else result.warnings.push(message);
    }

    // The `getTimezoneOffset()` pair (`timezone` + `timezoneOffset`) must also
    // agree; a mismatch means the browser is reporting an inconsistent
    // location, not just the wrong name.
    const expectedOffset = expectedTimezoneOffsetMinutes(probe.timezone);
    if (expectedOffset != null && typeof probe.timezoneOffset === "number"
      && -expectedOffset !== probe.timezoneOffset) {
      const message = `timezone offset ${probe.timezoneOffset} does not match ${probe.timezone} (expected ${-expectedOffset})`;
      if (RISK?.proxy) result.criticals.push(message);
      else result.warnings.push(message);
    }

    // Locale/language coherence: `navigator.languages` and the `Intl` locale
    // must be en-US-based, matching the persona. Camoufox applies the
    // `locale:all` config, so anything else means a host-locale leak.
    const langFamily = (l) => String(l).toLowerCase().split("-")[0];
    const browserLangFamilies = (probe.languages || []).map(langFamily);
    const expectedLangFamilies = (expected.languages || []).map(langFamily);
    const missingLangs = expectedLangFamilies.filter((code) => !browserLangFamilies.includes(code));
    if (expectedLangFamilies.length > 0 && missingLangs.length > 0) {
      const message = `navigator.languages [${(probe.languages || []).join(", ")}] does not include expected ${missingLangs.join(", ")}`;
      if (RISK?.proxy) result.criticals.push(message);
      else result.warnings.push(message);
    }
    const intlLocale = String(probe.locale || "").toLowerCase();
    if (intlLocale && !intlLocale.startsWith("en")) {
      const message = `Intl locale "${probe.locale}" is not an English persona locale`;
      if (RISK?.proxy) result.criticals.push(message);
      else result.warnings.push(message);
    }

    // Plugins/mimeTypes: Firefox personas normally expose these; a zero count
    // in a non-automation profile can indicate a headless/Chromium artifact.
    if (probe.plugins === 0 && probe.webdriver !== true) result.warnings.push("navigator.plugins is empty in a non-automation browser persona");
    if (probe.mimeTypes === 0 && probe.webdriver !== true) result.warnings.push("navigator.mimeTypes is empty in a non-automation browser persona");

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
      if (expected.screen && (probe.screen.width !== expected.screen.width || probe.screen.height !== expected.screen.height)) {
        result.warnings.push(`screen ${probe.screen.width}x${probe.screen.height} does not match the frozen fingerprint ${expected.screen.width}x${expected.screen.height}`);
      }
    }

    if (typeof probe.hardwareConcurrency === "number"
      && (probe.hardwareConcurrency < 2 || probe.hardwareConcurrency > 64)) {
      result.warnings.push(`Abnormal CPU hardwareConcurrency: ${probe.hardwareConcurrency}`);
    }
    if (typeof probe.deviceMemory === "number" && probe.deviceMemory < 2) {
      result.warnings.push(`Suspiciously low deviceMemory: ${probe.deviceMemory} GB`);
    }
    if (expected.os === "windows" && probe.maxTouchPoints > 10) {
      result.warnings.push(`Suspicious desktop touch points: ${probe.maxTouchPoints}`);
    }

    if (expected.renderer && probe.webglRenderer) {
      const pci = (value) => (String(value || "").match(/0x[0-9A-Fa-f]{4,8}/) || [])[0];
      const vendorTag = (value) => (String(value || "").match(/\b(NVIDIA|AMD|Intel|Microsoft|Apple)\b/i) || [])[1];
      const expectedPci = pci(expected.renderer);
      const actualPci = pci(probe.webglRenderer);
      if (expectedPci && actualPci && expectedPci.toLowerCase() !== actualPci.toLowerCase()) {
        result.warnings.push(`WebGL PCI id ${actualPci} does not match webgl_config ${expectedPci}`);
      }
      const expectedVendor = vendorTag(expected.renderer);
      const actualVendor = vendorTag(probe.webglRenderer);
      if (expectedVendor && actualVendor && expectedVendor.toLowerCase() !== actualVendor.toLowerCase()) {
        result.warnings.push(`WebGL vendor ${actualVendor} does not match webgl_config ${expectedVendor}`);
      }
    }

    const publicCandidates = (result.webrtc_candidates || []).filter((ip) => !isPrivateIp(ip));
    if (publicCandidates.length > 0) {
      if (expected.exitIp) {
        const leaked = publicCandidates.filter((ip) => ip !== expected.exitIp);
        if (leaked.length > 0) {
          result.criticals.push(`WebRTC leaked a non-proxy public host address: ${leaked.join(", ")}`);
        } else {
          console.log(`[WebRTC Shield] Public candidate matches the proxy exit IP: ${expected.exitIp}`);
        }
      } else if (RISK?.proxy) {
        result.criticals.push(`WebRTC exposed public candidate(s) with no verified proxy exit: ${publicCandidates.join(", ")}`);
      } else {
        result.warnings.push(`WebRTC exposed public candidate(s): ${publicCandidates.join(", ")}`);
      }
    }
  } catch (e) {
    result.criticals.push(`coherence probe failed: ${e.message}`);
  }

  if (RISK) {
    RISK.fingerprint.coherence = result;
    RISK.fingerprint.webrtc_candidates = result.webrtc_candidates || null;
    for (const warning of result.warnings) riskWarn(warning, "coherence");
    for (const critical of result.criticals) riskEvent("coherence", "critical", critical);
  }

  return result;
}

function printStealthAuditDashboard(report) {
  const line = "=".repeat(76);
  const sep = "-".repeat(76);
  const probe = report.probe || {};
  console.log(`\n${line}`);
  console.log("             OXYLABS STEALTH & ANTI-DETECT RISK AUDIT DASHBOARD");
  console.log(line);
  console.log(` Exit IP:          ${report.exitIp || "Unknown"} (Sticky: ${report.stickySession || "NONE - DANGER"})`);
  console.log(` ISP / ASN:        ${report.asn || "Unknown"} | Location: ${report.city || ""}, ${report.region || ""}, ${report.country || ""}`);
  console.log(sep);
  console.log(` Navigator UA:     ${probe.userAgent || "Unknown"}`);
  console.log(` Wire / TLS UA:    ${report.tlsUa || "unknown"}`);
  console.log(` UA Parity:        ${report.uaMatch === null ? "Unchecked" : report.uaMatch ? "PASS (Wire/DOM parity)" : "FAIL (mismatch)"}`);
  console.log(` TLS Stack:        ${report.tls ? `JA3: ${report.tls.ja3_hash || "unknown"} | JA4: ${report.tls.ja4 || "unknown"}` : "Unchecked"}`);
  console.log(sep);
  console.log(` Timezone:         ${probe.timezone || "Unknown"} (Offset: ${probe.timezoneOffset ?? "?"} min)`);
  console.log(` Languages:        ${(probe.languages || [probe.language]).join(", ") || "Unknown"}`);
  console.log(` Screen / View:    ${probe.screen?.width || "?"}x${probe.screen?.height || "?"} (Avail: ${probe.screen?.availWidth || "?"}x${probe.screen?.availHeight || "?"}, DPR: ${probe.screen?.devicePixelRatio || 1})`);
  console.log(` GPU / WebGL:      ${probe.webglRenderer || "unknown"} (Vendor: ${probe.webglVendor || "unknown"})`);
  console.log(` Geolocation:      ${report.geolocation ? `${report.geolocation.latitude}, ${report.geolocation.longitude}` : "not spoofed"}`);
  console.log(` WebRTC Shield:    ${report.webrtcShield ? "PASS (no host/real IP leak)" : "FAIL (public candidate)"}`);
  console.log(` Bot Artifacts:    ${report.botClean ? "CLEAN (webdriver=false, no automation globals)" : "FLAGGED"}`);
  console.log(sep);
  const warningCount = (report.warnings || []).length;
  const criticalCount = (report.criticals || []).length;
  const score = Math.max(0, 100 - criticalCount * 40 - warningCount * 10);
  const status = criticalCount > 0 ? "HIGH RISK / ABORT" : warningCount === 0 ? "EXCELLENT / SAFE" : "ACCEPTABLE";
  console.log(` AUDIT SCORE:      ${score}/100 [${status}] (${criticalCount} critical, ${warningCount} warning${warningCount === 1 ? "" : "s"})`);
  for (const warning of report.warnings || []) console.log(`   [!] Warning:  ${warning}`);
  for (const critical of report.criticals || []) console.log(`   [X] CRITICAL: ${critical}`);
  console.log(`${line}\n`);
}

async function captureTlsFingerprint(context) {
  let tab = null;
  try {
    tab = await context.newPage();
    await tab.goto("https://tls.browserleaks.com/json", { waitUntil: "domcontentloaded", timeout: 25000 });
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

/**
 * Replaces the frozen fingerprint UA with the UA the live Camoufox build
 * actually reports, then persists it. Prevents a DOM/wire UA split when the
 * bundled Firefox version changes.
 */
async function alignFrozenUserAgent(page, fingerprint, fingerprintPath) {
  try {
    const actualUa = await page.evaluate(() => navigator.userAgent);
    const frozenUa = fingerprint?.navigator?.userAgent || null;
    if (!actualUa || !fingerprint?.navigator || frozenUa === actualUa) {
      return { changed: false, actualUa, frozenUa };
    }
    fingerprint.navigator.userAgent = actualUa;
    if (Array.isArray(fingerprint.headers)) {
      for (const header of fingerprint.headers) {
        if (header?.name && String(header.name).toLowerCase() === "user-agent") header.value = actualUa;
      }
    }
    try { fs.writeFileSync(fingerprintPath, JSON.stringify(fingerprint, null, 2), "utf-8"); } catch (e) { }
    if (RISK) {
      RISK.fingerprint.hash = hashFingerprint(fingerprint);
      RISK.fingerprint.ua = actualUa;
      riskEvent("frozen_ua_aligned", "info", "Aligned the frozen fingerprint UA to the live browser UA", { from: frozenUa, to: actualUa });
    }
    console.log("[Fingerprint] Aligned the frozen UA to the browser's actual UA and persisted it.");
    return { changed: true, actualUa, frozenUa };
  } catch (e) {
    return { changed: false, error: e.message };
  }
}

/**
 * Reconciles the persisted fingerprint's screen block with the values the live
 * engine actually reports. Camoufox spoofs width/height from the frozen
 * fingerprint but leaves devicePixelRatio to the OS display scaling, so the
 * stored value must follow reality instead of staying at the BrowserForge
 * default (e.g. 2 vs the 1.25 a 125% Windows display reports).
 */
function reconcileFrozenScreen(probe, fingerprintPath, personaPath = null) {
  const live = probe?.screen;
  if (!live || !fingerprintPath) return { changed: false };

  let fingerprint = null;
  try {
    if (!fs.existsSync(fingerprintPath)) return { changed: false };
    fingerprint = JSON.parse(fs.readFileSync(fingerprintPath, "utf-8"));
  } catch (e) {
    return { changed: false, error: e.message };
  }
  if (!fingerprint?.screen) return { changed: false };

  const fields = ["width", "height", "availWidth", "availHeight", "colorDepth", "pixelDepth", "devicePixelRatio"];
  const changes = {};
  for (const field of fields) {
    const actual = live[field];
    if (actual === undefined || actual === null) continue;
    if (fingerprint.screen[field] !== actual) {
      changes[field] = { from: fingerprint.screen[field] ?? null, to: actual };
      fingerprint.screen[field] = actual;
    }
  }
  if (Object.keys(changes).length === 0) return { changed: false };

  try {
    fs.writeFileSync(fingerprintPath, JSON.stringify(fingerprint, null, 2), "utf-8");
  } catch (e) {
    return { changed: false, error: e.message };
  }

  let persona = null;
  if (personaPath) {
    try {
      if (fs.existsSync(personaPath)) {
        persona = JSON.parse(fs.readFileSync(personaPath, "utf-8"));
        persona.screen_resolution = {
          width: fingerprint.screen.width,
          height: fingerprint.screen.height,
        };
        fs.writeFileSync(personaPath, JSON.stringify(persona, null, 2), "utf-8");
      }
    } catch (e) {
      // persona sync is cosmetic; the fingerprint is the source of truth
    }
  }

  if (RISK) {
    RISK.fingerprint.screen = fingerprint.screen;
    RISK.fingerprint.hash = hashFingerprint(fingerprint);
    if (RISK.persona) RISK.persona.screen_resolution = persona?.screen_resolution || RISK.persona.screen_resolution;
    riskEvent("frozen_screen_reconciled", "info", "Reconciled the frozen fingerprint screen with the live browser values", changes);
  }

  const dpr = changes.devicePixelRatio;
  console.log(
    `[Fingerprint] Reconciled screen with the live browser${dpr ? ` (devicePixelRatio ${dpr.from} -> ${dpr.to})` : ""}.`
  );
  return { changed: true, changes };
}

let STEALTH_PREFLIGHT_DONE = false;

async function runStealthPreflight(page, context) {
  if (STEALTH_PREFLIGHT_DONE) return null;
  STEALTH_PREFLIGHT_DONE = true;

  riskMark("preflight");
  const exit = await captureExitIp(page, "browser_preflight");

  const coherence = await auditBrowserCoherence(page, {
    os: "windows",
    timezone: RISK?.proxy ? RISK?.persona?.timezone : null,
    screen: RISK?.fingerprint?.screen || null,
    renderer: RISK?.persona?.webgl_config?.[1] || null,
    exitIp: exit.ip || RISK?.preflight?.ip || null,
    languages: ["en-US", "en"],
  });

  const tls = await captureTlsFingerprint(context);
  if (RISK) RISK.fingerprint.tls = tls;
  if (!tls) {
    riskWarn("TLS/JA3 capture failed; the browser TLS stack could not be verified.", "tls");
  }

  const navUa = coherence.probe?.userAgent || RISK?.fingerprint?.ua || null;
  let uaMatch = null;
  if (tls?.user_agent && navUa) {
    uaMatch = tls.user_agent === navUa;
    if (!uaMatch) {
      riskWarn(`Wire UA "${tls.user_agent}" does not match the DOM UA "${navUa}".`, "tls");
    }
  }

  const publicCandidates = (coherence.webrtc_candidates || []).filter((ip) => !isPrivateIp(ip));
  const report = {
    exitIp: exit.ip || null,
    asn: exit.asn || null,
    city: exit.city || null,
    region: exit.region || null,
    country: exit.country || null,
    stickySession: RISK?.proxy?.session || RISK?.proxy?.sticky_port || null,
    tls,
    tlsUa: tls?.user_agent || null,
    uaMatch,
    probe: coherence.probe,
    geolocation: RISK?.geolocation_spoof || null,
    warnings: coherence.warnings,
    criticals: coherence.criticals,
    webrtcShield: publicCandidates.length === 0 || Boolean(exit.ip && publicCandidates.every((ip) => ip === exit.ip)),
    botClean: coherence.probe?.webdriver === false && !coherence.probe?.automationGlobals,
  };
  printStealthAuditDashboard(report);

  // The audit above deliberately compares the live browser with the frozen
  // fingerprint, so a mismatch is surfaced first. Only then do we reconcile the
  // stored fingerprint with what the engine actually reports (notably
  // devicePixelRatio, which follows the OS display scaling and is not spoofed
  // by Camoufox). Future runs then start from a self-consistent identity.
  reconcileFrozenScreen(coherence.probe, RISK?.fingerprint_path, RISK?.persona_path);

  if (RISK?.requested_country && exit.country
    && !/^any$/i.test(RISK.requested_country)
    && !String(exit.country).toUpperCase().startsWith(String(RISK.requested_country).toUpperCase().slice(0, 2))) {
    riskWarn(
      `Proxy exit country ${exit.country} does not match the requested endpoint country "${RISK.requested_country}".`,
      "preflight_country"
    );
  }

  if (coherence.criticals.length > 0) {
    throw new Error(`Stealth audit failed before signup: ${coherence.criticals.join(" | ")}`);
  }

  return { exit, coherence, tls, report };
}

// ---------------------------------------------------------------------------
// JSON registry + SQLite mirror
// ---------------------------------------------------------------------------
function readRegistry() {
  try {
    if (!fs.existsSync(REGISTRY_FILE)) return [];
    const parsed = JSON.parse(fs.readFileSync(REGISTRY_FILE, "utf-8"));
    return Array.isArray(parsed) ? parsed : [];
  } catch (e) {
    console.warn(`[Oxylabs] Registry read failed (${e.message}); starting a fresh list.`);
    return [];
  }
}

function appendRegistry(record) {
  const emailLower = String(record.email || "").toLowerCase();
  let list = readRegistry();
  const previous = list.find((item) => String(item.email || "").toLowerCase() === emailLower);

  if (previous) {
    // Usage-only runs must not wipe the stored password, proxy or earlier results.
    for (const key of Object.keys(previous)) {
      if (record[key] === undefined) record[key] = previous[key];
    }
    if (!record.password && previous.password) record.password = previous.password;
    if (previous.submitted) record.submitted = true;
    record.created_at = previous.created_at || record.created_at;
  }

  // Persist to SQLite first so the durable dates can be mirrored into JSON.
  // A usage-only run must not create a fresh "account created" date: only a
  // submitted record (or the existing row) supplies created_at.
  if (isDatabaseAvailable()) {
    try {
      const durable = persistRecord(record, {
        proxyIdentity: RISK?.proxy || parseProxyIdentity(record.proxy_used || ""),
        effectiveProxy: record.proxy_used || null,
      });
      if (durable && Object.keys(durable).length > 0) {
        for (const [key, value] of Object.entries(durable)) {
          if (value !== null && value !== undefined) record[key] = value;
        }
        record.account_created_date = durable.account_created_date || record.account_created_date || null;
        record.proxy_created_date = durable.proxy_created_date || record.proxy_created_date || null;
        if (record.proxy_string && !record.proxy_first_seen_at) {
          record.proxy_first_seen_at = durable.proxy_first_seen_at || null;
        }
      }
    } catch (e) {
      console.warn(`[Oxylabs DB] Could not persist ${record.email}: ${e.message}`);
    }

    if (RISK?.events?.length) {
      const pending = RISK.events.slice(RISK.persisted_event_count || 0);
      if (pending.length > 0) {
        persistRiskEvents(record.email, pending);
        RISK.persisted_event_count = RISK.events.length;
      }
    }
  }

  list = list.filter((item) => String(item.email || "").toLowerCase() !== emailLower);
  list.push(record);
  fs.mkdirSync(path.dirname(REGISTRY_FILE), { recursive: true });
  fs.writeFileSync(REGISTRY_FILE, JSON.stringify(list, null, 2), "utf-8");

  // FB/IG parity: mirror the master account record into the profile directory.
  // persona.json/fingerprint.json/risk_log.json already hold the spoof kernel;
  // account_info.json holds the identity/account metadata alongside them.
  try {
    if (record.profile_dir) {
      fs.mkdirSync(record.profile_dir, { recursive: true });
      const accountInfoPath = path.join(record.profile_dir, "account_info.json");
      const existingInfo = fs.existsSync(accountInfoPath)
        ? JSON.parse(fs.readFileSync(accountInfoPath, "utf-8"))
        : {};
      const merged = { ...existingInfo, ...record };
      fs.writeFileSync(accountInfoPath, JSON.stringify(merged, null, 2), "utf-8");
      console.log(`[Oxylabs] Synchronized account record to ${accountInfoPath}`);
    }
  } catch (e) {
    console.warn(`[Oxylabs] Could not write profile account_info.json: ${e.message}`);
  }
}

function loadSavedAccount(email) {
  const result = { password: null, instance_name: null, proxy_used: null, profile_dir: null };

  const previous = readRegistry().find(
    (item) => String(item.email || "").toLowerCase() === String(email || "").toLowerCase()
  );
  if (previous) {
    result.password = previous.password || null;
    result.instance_name = previous.instance_name || null;
    result.proxy_used = previous.proxy_used || null;
    result.profile_dir = previous.profile_dir || null;
  }

  if (isDatabaseAvailable()) {
    try {
      const account = getDbAccount(email);
      if (account) {
        result.password = result.password || account.password || null;
        result.instance_name = result.instance_name || account.instance_name || null;
        result.profile_dir = result.profile_dir || account.profile_dir || null;
      }
      const proxy = getDbPreferredProxy(email);
      if (proxy?.proxy_string) result.proxy_used = proxy.proxy_string;
    } catch (e) {
      console.warn(`[Oxylabs DB] Could not read the saved account: ${e.message}`);
    }
  }

  return result;
}

// ---------------------------------------------------------------------------
// Humanized form helpers
// ---------------------------------------------------------------------------
function gaussian(mean, sd) {
  const u = Math.max(Number.EPSILON, Math.random());
  const v = Math.max(Number.EPSILON, Math.random());
  return Math.max(10, Math.round(mean + sd * Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v)));
}

const sleep = (page, ms) => page.waitForTimeout(ms);

async function humanType(page, locator, text, label) {
  await locator.waitFor({ state: "visible", timeout: fieldTimeout });
  await locator.scrollIntoViewIfNeeded().catch(() => {});
  await locator.click();
  await sleep(page, 120 + Math.round(Math.random() * 180));
  await locator.fill("");
  for (const char of text) {
    await page.keyboard.type(char);
    await sleep(page, gaussian(70, 22));
    if (Math.random() < 0.03) await sleep(page, 140 + Math.round(Math.random() * 320));
  }

  const actual = await locator.inputValue().catch(() => "");
  if (actual !== text) {
    console.warn(`[Oxylabs] ${label}: typed value did not match exactly, forcing fill().`);
    await locator.fill(text);
  }
}

async function isVisible(locator, timeout = 1500) {
  try {
    await locator.first().waitFor({ state: "visible", timeout });
    return true;
  } catch (e) {
    return false;
  }
}

async function dismissCookieBanner(page) {
  const candidates = [
    "#onetrust-accept-btn-handler",
    'button[data-testid*="cookie"]',
    'button:has-text("Accept all")',
    'button:has-text("Accept All")',
    'button:has-text("Allow all")',
    'button:has-text("I agree")',
  ];
  for (const selector of candidates) {
    const btn = page.locator(selector).first();
    if (await isVisible(btn, 800)) {
      console.log(`[Oxylabs] Dismissing cookie banner via ${selector}`);
      await humanClick(page, btn).catch(() => {});
      await sleep(page, 600);
      return true;
    }
  }
  return false;
}

async function waitForRegistrationForm(page, timeoutMs = 60000) {
  const deadline = Date.now() + timeoutMs;
  const nameField = page.locator('[data-testid="input-registration-name"], input[name="name"]').first();

  while (Date.now() < deadline) {
    if (await isVisible(nameField, 2000)) return nameField;

    const body = await page.locator("body").innerText().catch(() => "");
    if (/just a moment|checking your browser|verify you are human/i.test(body)) {
      console.log("[Oxylabs] Anti-bot challenge detected; waiting for it to clear...");
      await sleep(page, 3000);
      continue;
    }
    if (/403 forbidden|access denied/i.test(body)) {
      throw new Error("The dashboard returned 403/access denied. Retry with --proxy or a different network.");
    }
    await sleep(page, 1000);
  }
  throw new Error(`Registration form did not appear within ${Math.round(timeoutMs / 1000)}s.`);
}

async function openRegistration(page) {
  console.log(`[Oxylabs] Opening ${LANDING_URL}`);
  await page.goto(LANDING_URL, { waitUntil: "domcontentloaded", timeout: 60000 });
  await sleep(page, 2500);
  await dismissCookieBanner(page);

  await page.screenshot({ path: path.join(ARTIFACTS_DIR, "oxylabs_registration_landing.png"), fullPage: true }).catch(() => {});

  // Anonymity gate: refuse to touch the form if the browser is leaking the
  // real IP/timezone/WebRTC stack or shows automation artifacts.
  await runStealthPreflight(page, page.context());

  const registerLink = page.locator('a[data-testid="login-registration"], a[href*="/registration"]').first();
  if (await isVisible(registerLink, 15000)) {
    console.log("[Oxylabs] Clicking 'Register instead'.");
    await humanClick(page, registerLink);
    await sleep(page, 2500);

    // The click can be swallowed by a cookie overlay; fall back to the URL.
    const nameField = page.locator('[data-testid="input-registration-name"], input[name="name"]').first();
    if (!(await isVisible(nameField, 4000))) {
      console.log("[Oxylabs] Register click did not navigate; opening /en/registration directly.");
      await page.goto(REGISTRATION_URL, { waitUntil: "domcontentloaded", timeout: 60000 });
      await sleep(page, 2500);
    }
  } else {
    console.log("[Oxylabs] Register link not found; navigating directly to /en/registration.");
    await page.goto(REGISTRATION_URL, { waitUntil: "domcontentloaded", timeout: 60000 });
    await sleep(page, 2500);
  }

  await dismissCookieBanner(page);
  return waitForRegistrationForm(page);
}

// ---------------------------------------------------------------------------
// Outlook/Hotmail activation email
// ---------------------------------------------------------------------------
function maskActivationLink(link) {
  try {
    const url = new URL(link);
    if (url.searchParams.has("token")) {
      const token = url.searchParams.get("token");
      url.searchParams.set("token", `${token.slice(0, 8)}...`);
    }
    return url.toString();
  } catch (e) {
    return String(link).slice(0, 60);
  }
}

function withTimeout(promise, ms, label) {
  let timer = null;
  const timeout = new Promise((_, reject) => {
    timer = setTimeout(() => reject(new Error(`${label} timed out after ${Math.round(ms / 1000)}s`)), ms);
  });
  return Promise.race([promise, timeout]).finally(() => clearTimeout(timer));
}

function extractActivationLink(html) {
  const text = String(html || "")
    .replace(/&amp;/g, "&")
    .replace(/&#x2F;/gi, "/")
    .replace(/&#47;/g, "/");

  const direct = text.match(/https?:\/\/dashboard\.oxylabs\.io\/[^\s"'<>)]*activate[^\s"'<>)]*/i);
  if (direct) return direct[0];

  for (const match of text.matchAll(/<a\b[^>]*href=["']([^"']+)["'][^>]*>([\s\S]*?)<\/a>/gi)) {
    const href = match[1].replace(/&amp;/g, "&");
    const label = match[2].replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim();
    if (/activate|verify|confirm|get started/i.test(`${href} ${label}`)) return href;
  }

  const generic = text.match(/https?:\/\/[^\s"'<>)]*oxylabs[^\s"'<>)]*(?:activate|verify|confirm)[^\s"'<>)]*/i);
  return generic ? generic[0] : null;
}

async function findOxylabsActivationEmail(accessToken, notBeforeMs) {
  // Inbox + Junk for both Microsoft Graph and the legacy Outlook REST API.
  const folderGroups = [
    [
      "https://graph.microsoft.com/v1.0/me/messages?$top=10&$orderby=receivedDateTime%20desc",
      "https://graph.microsoft.com/v1.0/me/mailFolders/junkemail/messages?$top=10&$orderby=receivedDateTime%20desc",
    ],
    [
      "https://outlook.office.com/api/v2.0/me/messages?$top=10&$orderby=ReceivedDateTime%20desc",
      "https://outlook.office.com/api/v2.0/me/MailFolders/JunkEmail/messages?$top=10&$orderby=ReceivedDateTime%20desc",
    ],
  ];

  for (const group of folderGroups) {
    let groupSuccess = false;
    for (const url of group) {
      const res = await fetch(url, {
        headers: { Authorization: `Bearer ${accessToken}`, Accept: "application/json" },
        signal: AbortSignal.timeout(30000),
      });
      if (!res.ok) continue;
      groupSuccess = true;
      const json = await res.json();
      const messages = json.value || [];

      for (const msg of messages) {
        const subject = msg.subject || msg.Subject || "";
        const from = msg.from?.emailAddress?.address || msg.From?.EmailAddress?.Address || "";
        const preview = msg.bodyPreview || msg.BodyPreview || "";
        const body = String(msg.body?.content || msg.Body?.Content || "");
        const receivedRaw = msg.receivedDateTime || msg.ReceivedDateTime || "";
        const receivedMs = Date.parse(receivedRaw) || 0;

        if (receivedMs && receivedMs < notBeforeMs) continue;
        if (!/oxylabs/i.test(`${from} ${subject} ${preview} ${body}`)) continue;

        const link = extractActivationLink(body) || extractActivationLink(preview);
        if (link) return { link, subject, from, received: receivedRaw };
      }
    }
    if (groupSuccess) break;
  }
  return null;
}

async function pollForActivationEmail(cId, rToken, notBeforeMs, maxWaitSec) {
  console.log(`[Oxylabs] Polling the Outlook/Hotmail mailbox for the activation email (up to ${maxWaitSec}s)...`);
  const startedAt = Date.now();
  let lastNote = "";

  while (Date.now() - startedAt < maxWaitSec * 1000) {
    try {
      const accessToken = await withTimeout(getMsAccessToken(cId, rToken), 30000, "Microsoft token exchange");
      if (accessToken) {
        const found = await findOxylabsActivationEmail(accessToken, notBeforeMs);
        if (found) {
          console.log(`[Oxylabs] Activation email found: "${found.subject}" from ${found.from || "unknown"}`);
          return found;
        }
      } else {
        lastNote = "Microsoft returned no access token (refresh token may be expired).";
      }
    } catch (e) {
      lastNote = e.message;
    }

    const elapsed = Math.round((Date.now() - startedAt) / 1000);
    console.log(`[Oxylabs] No activation email yet (${elapsed}s elapsed)${lastNote ? ` - ${lastNote}` : ""}`);
    await new Promise((resolve) => setTimeout(resolve, 4000));
  }
  return null;
}

// ---------------------------------------------------------------------------
// Post-activation dashboard flow
// ---------------------------------------------------------------------------
async function isLoginPage(page) {
  if (/login\.microsoftonline|oauth2\/v2\.0\/authorize|azure\/callback/i.test(page.url())) return true;
  const passwordField = page.locator('input[type="password"]').first();
  if (!(await isVisible(passwordField, 800))) return false;

  const heading = page.locator("h1, h2, [role='heading']")
    .filter({ hasText: /log ?in to your account|sign ?in to your account/i })
    .first();
  if (await isVisible(heading, 800)) return true;

  const loginButton = page.getByRole("button", { name: /^(log ?in|sign ?in)$/i }).first();
  return isVisible(loginButton, 800);
}

async function isMicrosoftLoginPage(page) {
  return /login\.microsoftonline|oauth2\/v2\.0\/authorize|azure\/callback/i.test(page.url());
}

async function clickMicrosoftLogin(page) {
  const candidates = [
    page.getByRole("button", { name: /continue with microsoft|sign in with microsoft|continue with azure/i }).first(),
    page.getByRole("button", { name: /microsoft/i }).first(),
    page.getByRole("button", { name: /continue|next/i }).first(),
  ];
  for (const loc of candidates) {
    if (await isVisible(loc, 800)) {
      console.log("[Oxylabs] Clicking Microsoft login button.");
      await humanClick(page, loc);
      return true;
    }
  }
  return false;
}

async function ensureLoggedIn(page, email, password, canLogin = true) {
  if (!(await isLoginPage(page))) return true;

  if (!canLogin) {
    console.warn("[Oxylabs] Login page detected, but no --password was supplied for this mode.");
    return false;
  }

  if (await isMicrosoftLoginPage(page)) {
    console.log("[Oxylabs] Microsoft login page detected.");
    const msEmail = page.locator('input[type="email"], input[name="email"]').first();
    const msPass = page.locator('input[type="password"]').first();
    if (await isVisible(msEmail, 1500) && await isVisible(msPass, 1500)) {
      await humanType(page, msEmail, email, "Microsoft login email");
      await humanType(page, msPass, password, "Microsoft login password");
      await sleep(page, 400);
    }
    await clickMicrosoftLogin(page);
    const msDeadline = Date.now() + 25000;
    while (Date.now() < msDeadline) {
      if (!(await isLoginPage(page))) return true;
      await sleep(page, 1500);
    }
    return false;
  }

  console.log("[Oxylabs] Login page detected; signing in with the registered credentials...");
  await dismissCookieBanner(page);

  const emailInput = page.locator(
    'input[name="username"], input[name="email"], input[type="email"], input[autocomplete="username"], input[data-testid*="email"]'
  ).first();
  const passInput = page.locator('input[type="password"]').first();

  if (!(await isVisible(emailInput, 10000)) || !(await isVisible(passInput, 5000))) {
    console.warn("[Oxylabs] Could not find the login email/password fields.");
    return false;
  }

  await humanType(page, emailInput, email, "Login email");
  await humanType(page, passInput, password, "Login password");
  await sleep(page, 400);

  const loginCandidates = [
    'button[type="submit"]',
    'button:has-text("Log In")',
    'button:has-text("Login")',
    'button:has-text("Sign in")',
  ];
  let loginBtn = null;
  for (const sel of loginCandidates) {
    const loc = page.locator(sel).first();
    if (!(await isVisible(loc, 800))) continue;
    const text = (await loc.innerText().catch(() => "")).trim();
    // Never click a Microsoft/OAuth style button when filling credentials.
    if (/microsoft|oauth|continue with (google|apple)/i.test(text)) continue;
    loginBtn = loc;
    break;
  }
  if (loginBtn) {
    console.log(`[Oxylabs] Clicking credential login button: "${(await loginBtn.innerText().catch(() => "")).trim()}".`);
    await humanClick(page, loginBtn);
  } else {
    await page.keyboard.press("Enter");
  }

  // Wait for the dashboard to replace the login form (poll instead of a fixed
  // sleep so slow redirects do not fail the run). If a Microsoft/OAuth login
  // page appears during the wait, click its button once.
  const deadline = Date.now() + 25000;
  let msClicked = false;
  while (Date.now() < deadline) {
    if (!(await isLoginPage(page))) return true;
    if (!msClicked && await isMicrosoftLoginPage(page)) {
      msClicked = await clickMicrosoftLogin(page);
    }
    await sleep(page, 1500);
  }

  // Credential login didn't clear it; if a Microsoft/OAuth button is now
  // visible, click it once and poll again.
  if (await isLoginPage(page)) {
    const clicked = await clickMicrosoftLogin(page);
    if (clicked) {
      const msDeadline = Date.now() + 20000;
      while (Date.now() < msDeadline) {
        if (!(await isLoginPage(page))) return true;
        await sleep(page, 1500);
      }
    }
  }
  const loginBody = (await page.locator("body").innerText().catch(() => "")).replace(/\s+/g, " ").trim();
  console.warn(`[Oxylabs] Login did not complete. Page preview: ${loginBody.slice(0, 900)}`);
  return false;
}

// ---------------------------------------------------------------------------
// Endpoint generator (country/city) + proxy copy
// ---------------------------------------------------------------------------
function moneyValue(value) {
  return Number(String(value || "").replace(/[^0-9.-]/g, "")) || 0;
}

async function selectComboboxOption(page, triggerSelector, optionText, label) {
  const trigger = page.locator(triggerSelector).first();
  if (!(await isVisible(trigger, 20000))) {
    console.warn(`[Oxylabs] ${label} combobox not found.`);
    return false;
  }

  const currentText = (await trigger.innerText().catch(() => "")).trim();
  if (currentText.toLowerCase() === optionText.toLowerCase()) {
    console.log(`[Oxylabs] ${label} already set to "${optionText}".`);
    return true;
  }

  // The city control stays disabled until the country request completes.
  for (let i = 0; i < 30; i++) {
    if (!(await trigger.isDisabled().catch(() => false))) break;
    await sleep(page, 500);
  }
  if (await trigger.isDisabled().catch(() => false)) {
    console.warn(`[Oxylabs] ${label} combobox is disabled.`);
    return false;
  }

  await humanClick(page, trigger);
  await sleep(page, 1200);

  const popup = page.locator('[role="dialog"], [role="listbox"]').last();
  await isVisible(popup, 5000);

  // Dump all visible options so failures are diagnosable from the logs.
  const optionSelectors = [
    `[role="option"]`,
    `button[role="option"]`,
    `a[role="option"]`,
    `li[role="option"]`,
    `div[role="option"]`,
  ];
  for (const sel of optionSelectors) {
    const locs = popup.locator(sel);
    const n = await locs.count().catch(() => 0);
    for (let i = 0; i < Math.min(n, 30); i++) {
      const t = (await locs.nth(i).innerText().catch(() => "")).replace(/\s+/g, " ").slice(0, 120);
      console.log(`[Oxylabs] ${label} option[${i}]: ${t}`);
    }
    if (n > 0) break;
  }

  const search = page.locator(
    'input[placeholder*="search" i], input[type="search"], [cmdk-input], [role="dialog"] input'
  ).last();
  if (await isVisible(search, 1200)) {
    await humanType(page, search, optionText, `${label} search`);
    await sleep(page, 1200);
  }

  const norm = (s) => String(s || "").toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
  const targetNorm = norm(optionText);

  let option = null;
  // Search the whole document, not only the dialog/popup: many component
  // libraries render listbox options in a portal at the document root.
  const optionLocators = [
    `[role="option"][title="${optionText}"]`,
    `[role="option"]`,
    `[role="menuitem"]`,
    `[role="menuitemradio"]`,
    `[data-testid*="option"]`,
    `[cmdk-item]`,
  ];
  for (const sel of optionLocators) {
    const locs = page.locator(sel);
    const n = await locs.count().catch(() => 0);
    for (let i = 0; i < n; i++) {
      const t = (await locs.nth(i).innerText().catch(() => "")).replace(/\s+/g, " ").trim();
      const tNorm = norm(t);
      if (tNorm === targetNorm || tNorm.includes(targetNorm) || tNorm.startsWith(targetNorm) || tNorm.endsWith(targetNorm)) {
        option = locs.nth(i);
        break;
      }
    }
    if (option) break;
  }
  if (!option) {
    const textMatch = page.locator(`text=${optionText}`).last();
    if (await isVisible(textMatch, 1500)) option = textMatch;
  }
  if (!option) {
    // Last resort: type the option text and press Enter (combobox keyboard flow).
    await page.keyboard.press("Escape").catch(() => {});
    await humanClick(page, trigger);
    await sleep(page, 600);
    await page.keyboard.type(optionText).catch(() => {});
    await sleep(page, 600);
    await page.keyboard.press("Enter").catch(() => {});
    await sleep(page, 1500);
    const afterText = (await trigger.innerText().catch(() => "")).trim();
    console.log(`[Oxylabs] ${label} after keyboard entry: "${afterText}"`);
    if (norm(afterText).includes(targetNorm)) return true;
    const allOptions = await page.locator('[role="option"], [role="menuitem"], [data-testid*="option"], [cmdk-item]').allTextContents().catch(() => []);
    console.warn(`[Oxylabs] Option "${optionText}" not found in the ${label} combobox. Candidates: ${allOptions.map((t) => String(t).trim()).filter(Boolean).slice(0, 40).join(" | ")}`);
    await page.keyboard.press("Escape").catch(() => {});
    return false;
  }

  await humanClick(page, option);
  await sleep(page, 1500);

  const afterText = (await trigger.innerText().catch(() => "")).trim();
  console.log(`[Oxylabs] ${label} selected: "${afterText}"`);
  return afterText.toLowerCase().includes(optionText.toLowerCase());
}

/**
 * Makes the endpoint sticky: opens "More options", enables "Sticky session
 * (one IP)" and sets the session time to 120 minutes. This must happen after
 * country selection and before the proxy URL is copied, so the endpoint
 * contains `-sessid_oneip-...-sesstime-120`.
 */
/**
 * After creating an instance, Oxylabs shows a "Step 1 of 2" onboarding guide on
 * the instance overview. Its overlay blocks the country/city comboboxes and the
 * "More options" sticky-session button. Dismiss it with "Skip guide" (or the
 * close button) before configuring the endpoint.
 */
async function dismissInstanceGuide(page) {
  const candidates = [
    page.locator('button:has-text("Skip guide")').first(),
    page.locator('button:has-text("Skip")').first(),
    page.locator('[role="button"]:has-text("Skip guide")').first(),
    page.locator('button[aria-label*="close" i], button:has-text("×")').first(),
  ];
  for (const loc of candidates) {
    if (await isVisible(loc, 800)) {
      const text = (await loc.innerText().catch(() => "")).trim();
      console.log(`[Oxylabs] Dismissing instance onboarding guide via "${text}".`);
      await humanClick(page, loc);
      await sleep(page, 1200);
      return true;
    }
  }
  return false;
}

async function configureStickySession(page, minutes = 120) {
  const moreBtn = page.locator('[data-testid="endpoint-generator-more-options"]').first();
  if (!(await isVisible(moreBtn, 2500))) {
    console.warn("[Oxylabs] 'More options' button not visible; sticky session not configured.");
    return false;
  }
  console.log("[Oxylabs] Opening 'More options' for the endpoint generator.");
  await humanClick(page, moreBtn);
  await sleep(page, 800);

  const stickyBtn = page.locator('button:has-text("Sticky session (one IP)")').first();
  if (!(await isVisible(stickyBtn, 2500))) {
    const preview = (await page.locator("body").innerText().catch(() => "")).replace(/\s+/g, " ").trim();
    console.warn(`[Oxylabs] 'Sticky session (one IP)' toggle not found. Page preview: ${preview.slice(0, 600)}`);
    const buttonTexts = await page.locator("button").allTextContents().catch(() => []);
    console.warn(`[Oxylabs] Buttons after More options: ${buttonTexts.map((t) => String(t).trim()).filter(Boolean).slice(0, 40).join(" | ")}`);
    return false;
  }
  const pressed = String(await stickyBtn.getAttribute("aria-pressed") || "");
  if (pressed !== "true") {
    await humanClick(page, stickyBtn);
    await sleep(page, 600);
    console.log(`[Oxylabs] Sticky session (one IP) enabled (aria-pressed=${await stickyBtn.getAttribute("aria-pressed")}).`);
  } else {
    console.log("[Oxylabs] Sticky session (one IP) already enabled.");
  }

  const timeInput = page.locator('input[data-testid="endpoint-generator-session-time"]').first();
  if (await isVisible(timeInput, 2500)) {
    const readValue = async () => {
      const viaProp = await timeInput.inputValue().catch(() => null);
      const viaAttr = await timeInput.getAttribute("value").catch(() => null);
      const n = Number(viaProp ?? viaAttr);
      return Number.isFinite(n) ? n : null;
    };
    const decrease = page.locator('[data-testid="endpoint-generator-session-time-decrease"]').first();
    const increase = page.locator('[data-testid="endpoint-generator-session-time-increase"]').first();
    let current = await readValue();
    for (let i = 0; i < 20 && current !== null && current !== minutes; i++) {
      if (current > minutes && await isVisible(decrease, 300)) {
        await humanClick(page, decrease);
      } else if (current < minutes && await isVisible(increase, 300)) {
        await humanClick(page, increase);
      } else {
        break;
      }
      await sleep(page, 60);
      current = await readValue();
    }
    if (current !== null && current !== minutes) {
      await page.evaluate((target) => {
        const el = document.querySelector('input[data-testid="endpoint-generator-session-time"]');
        if (!el) return;
        const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value").set;
        setter.call(el, String(target));
        el.dispatchEvent(new Event("input", { bubbles: true }));
        el.dispatchEvent(new Event("change", { bubbles: true }));
      }, minutes).catch(() => {});
      await sleep(page, 600);
      current = await readValue();
    }
    console.log(`[Oxylabs] Session time set to ${current} minutes (target ${minutes}).`);
  } else {
    console.warn("[Oxylabs] Session time slider not visible; leaving the default duration.");
  }

  await sleep(page, 1200); // allow the proxy endpoint to regenerate
  return true;
}

async function configureEndpointAndCopyProxy(page, country, city, email = null) {
  console.log("[Oxylabs] Configuring the endpoint generator (country/city)...");
  // The instance page may show aStep 1/2 guide overlay; dismiss it first so the
  // comboboxes and More options button are interactive.
  await dismissInstanceGuide(page);

  const countryTrigger = '[data-testid="endpoint-generator-country"]';
  if (!(await isVisible(page.locator(countryTrigger).first(), 25000))) {
    console.warn("[Oxylabs] Endpoint generator country control not found.");
    return { proxy: null, country_selected: false, city_selected: false };
  }

  let countrySelected = false;
  if (!/^any$/i.test(country)) {
    countrySelected = await selectComboboxOption(page, countryTrigger, country, "Country");
  } else {
    console.log("[Oxylabs] Country left as Any.");
  }

  let citySelected = false;
  if (!/^any$/i.test(city)) {
    citySelected = await selectComboboxOption(page, '[data-testid="endpoint-generator-city"]', city, "City");
  } else {
    console.log("[Oxylabs] City left as Any.");
  }

  // Always make the endpoint sticky (one IP, 120-minute session) before the
  // URL is copied, so every generated proxy carries its own session id.
  const stickyConfigured = await configureStickySession(page, 120);

  await sleep(page, 2500);
  console.log("[Oxylabs] Endpoint page settled; reading integration card...");

  // Prefer reading the endpoint straight from the integration card text. The
  // page preview shows e.g. `curl -x pr.oxylabs.io:7777 -U "user:pass" ...`;
  // the clipboard sometimes returns unrelated text in Camoufox, so we extract
  // from the page as the primary source and use the copy button as fallback.
  let proxy = null;
  try {
    const bodyText = (await page.locator("body").innerText().catch(() => "")).replace(/\s+/g, " ").trim();
    console.log(`[Oxylabs] Integration card text: ${bodyText.slice(0, 500)}`);
    proxy = extractProxyFromText(bodyText);
  } catch (e) {
    console.warn(`[Oxylabs] Could not read integration card text: ${e.message}`);
  }

  // Fallback: capture clipboard writes instead of relying on Firefox
  // clipboard read permissions, or the integration text.
  if (!isRealProxy(proxy)) {
    await page.evaluate(() => {
      window.__oxylabsCopiedText = null;
      try {
        const original = navigator.clipboard.writeText.bind(navigator.clipboard);
        navigator.clipboard.writeText = async (text) => {
          window.__oxylabsCopiedText = text;
          try {
            return await original(text);
          } catch (e) {
            return undefined;
          }
        };
      } catch (e) { }
      document.addEventListener("copy", () => {
        const selected = String(document.getSelection?.() || "");
        if (selected) window.__oxylabsCopiedText = selected;
      }, true);
    }).catch(() => {});
    console.log("[Oxylabs] Clipboard patch installed.");

    const copyBtn = page.locator('[data-testid="integration-text-copy-btn"]').first();
    const copyVisible = await isVisible(copyBtn, 15000);
    console.log(`[Oxylabs] Integration copy button visible: ${copyVisible}`);
    if (copyVisible) {
      await humanClick(page, copyBtn);
      await sleep(page, 1500);
    }
    if (!proxy) {
      proxy = await page.evaluate(() => window.__oxylabsCopiedText).catch(() => null);
    }
    if (!isRealProxy(proxy)) {
      proxy = await page.evaluate(async () => {
        try {
          return await navigator.clipboard.readText();
        } catch (e) {
          return null;
        }
      }).catch(() => null);
    }
    if (!isRealProxy(proxy)) {
      const scoped = page.locator('[data-testid*="integration-text"]:not([data-testid*="copy"]), pre, code').first();
      proxy = (await scoped.innerText().catch(() => "")).trim();
    }
  }

  if (!isRealProxy(proxy)) {
    console.warn("[Oxylabs] No valid Oxylabs proxy text found on the integration card or clipboard.");
    proxy = null;
  }

  proxy = String(proxy || "").trim();
  if (isRealProxy(proxy)) {
    // Guarantee stickiness even when the dashboard UI did not expose the
    // sticky-session toggle (e.g. country = Any). Append sessid_oneip with a
    // 120-minute lifetime to the copied endpoint so it stays sticky.
    if (!/sessid|session/i.test(proxy)) {
      proxy = ensureStickyProxy(proxy, email || country || "dashboard", 120);
      console.log(`[Oxylabs] Applied sticky session (one IP, 120 min) to the copied endpoint: ${maskProxy(proxy)}`);
    }
    console.log(`[Oxylabs] Proxy endpoint copied: ${maskProxy(proxy)} (saved in the registry/DB)`);
  } else {
    console.warn("[Oxylabs] Copy clicked, but no valid Oxylabs proxy text was captured.");
    proxy = null;
  }

  await page.screenshot({
    path: path.join(ARTIFACTS_DIR, "oxylabs_proxy_endpoint.png"),
    fullPage: true,
  }).catch(() => {});

  return {
    proxy: proxy || null,
    country_selected: countrySelected,
    city_selected: citySelected,
    sticky_configured: stickyConfigured,
  };
}

// ---------------------------------------------------------------------------
// Usage / commitment card
// ---------------------------------------------------------------------------
async function readCommitmentUsage(page) {
  const card = page.locator('[data-testid="commitment-card"]').first();
  if (!(await isVisible(card, 15000))) {
    console.warn("[Oxylabs] Commitment/usage card not found.");
    return null;
  }

  const getText = async (testid) => {
    return (await page.locator(`[data-testid="${testid}"]`).first().innerText().catch(() => "")).trim();
  };

  const planName = await getText("commitment-card-full-plan-name");
  const spentRaw = await getText("commitment-card-spent-value");
  const commitmentRaw = await getText("commitment-card-commitment-value");
  const percentRaw = await getText("commitment-card-spent-percentage");

  const bar = page.locator('[data-testid="commitment-card-progress-bar"]').first();
  const ariaNow = await bar.getAttribute("aria-valuenow").catch(() => null);
  const ariaText = await bar.getAttribute("aria-valuetext").catch(() => null);

  const spent = moneyValue(spentRaw);
  const commitment = moneyValue(commitmentRaw);
  const usedPercent = Number(String(percentRaw).replace(/[^0-9.-]/g, "")) || Number(ariaNow) || 0;

  const usage = {
    plan_name: planName,
    spent_usd: spent,
    commitment_usd: commitment,
    usage_left_usd: Math.max(0, Number((commitment - spent).toFixed(2))),
    used_percent: usedPercent,
    usage_left_percent: Math.max(0, Number((100 - usedPercent).toFixed(1))),
    progress_aria_now: ariaNow,
    progress_aria_text: ariaText,
  };

  console.log(`[Oxylabs] Usage card: plan=${usage.plan_name}, spent=${spentRaw}, limit=${commitmentRaw}, left=${usage.usage_left_usd} USD (${usage.usage_left_percent}% remaining)`);
  return usage;
}

/**
 * Diagnostic dump used when the dashboard does not expose the expected product
 * cards. Prints visible buttons and anchors so the next state can be read from
 * the logs (this model cannot view screenshots).
 */
async function dumpButtonsAndAnchors(page, label) {
  try {
    const buttons = page.locator("button, [role='button']");
    const buttonCount = await buttons.count().catch(() => 0);
    console.log(`[Oxylabs] ${label}: ${buttonCount} buttons`);
    for (let i = 0; i < Math.min(buttonCount, 30); i++) {
      const btn = buttons.nth(i);
      const text = (await btn.innerText().catch(() => "")).replace(/\s+/g, " ").slice(0, 100);
      const href = await btn.getAttribute("href").catch(() => "");
      const dataTest = await btn.getAttribute("data-testid").catch(() => "");
      console.log(`[Oxylabs]   button[${i}]: text="${text}" data-testid="${dataTest}" href="${href}"`);
    }
    const anchors = page.locator("a[href]");
    const anchorCount = await anchors.count().catch(() => 0);
    console.log(`[Oxylabs] ${label}: ${anchorCount} anchors`);
    for (let i = 0; i < Math.min(anchorCount, 30); i++) {
      const a = anchors.nth(i);
      const href = await a.getAttribute("href").catch(() => "");
      const text = (await a.innerText().catch(() => "")).replace(/\s+/g, " ").slice(0, 100);
      const dataTest = await a.getAttribute("data-testid").catch(() => "");
      console.log(`[Oxylabs]   anchor[${i}]: href="${href}" text="${text}" data-testid="${dataTest}"`);
    }
  } catch (e) {
    console.warn(`[Oxylabs] dumpButtonsAndAnchors failed: ${e.message}`);
  }
}

async function openOverviewAndCreateInstance(page, email, password, instanceName, country, city) {
  let usage = null;

  console.log("[Oxylabs] Opening https://dashboard.oxylabs.io/en/overview");
  let overviewNavigated = false;
  let overviewError = null;
  for (let attempt = 1; attempt <= 3 && !overviewNavigated; attempt++) {
    try {
      await page.goto("https://dashboard.oxylabs.io/en/overview", { waitUntil: "domcontentloaded", timeout: 60000 });
      overviewNavigated = true;
    } catch (err) {
      overviewError = err.message;
      console.warn(`[Oxylabs] Overview navigation attempt ${attempt} failed: ${overviewError}`);
      if (attempt < 3) await sleep(page, 5000);
    }
  }
  if (!overviewNavigated) throw new Error(`Could not open the dashboard overview: ${overviewError}`);
  await sleep(page, 5000);
  await dismissCookieBanner(page);
  await ensureLoggedIn(page, email, password);
  await sleep(page, 3000);
  await captureExitIp(page, "overview");

  // Some dashboards show an empty-state "Get Started" button on the overview
  // page; it must be clicked before the "Add product instance" controls exist.
  const getStartedCandidates = [
    'button[data-testid="overview-get-started"], button:has-text("Get Started")',
    'button:has-text("Get started"), button:has-text("GET STARTED")',
  ];
  for (const sel of getStartedCandidates) {
    const loc = page.locator(sel).first();
    if (await isVisible(loc, 3000)) {
      console.log("[Oxylabs] Clicking 'Get Started' on the overview page.");
      await humanClick(page, loc);
      await sleep(page, 10000);
      await page.waitForLoadState("domcontentloaded").catch(() => {});
      const afterText = (await page.locator("body").innerText().catch(() => "")).replace(/\s+/g, " ").trim();
      console.log(`[Oxylabs] Page preview after Get Started: ${afterText.slice(0, 700)}`);
      break;
    }
  }

  await page.screenshot({ path: path.join(ARTIFACTS_DIR, "oxylabs_overview.png"), fullPage: true }).catch(() => {});
  const overviewUrl = page.url();

  // The commitment card lives in the global sidebar; read it here so a later
  // page without the sidebar still has usage data.
  usage = await readCommitmentUsage(page);

  // Existing-instance fast path: if the dashboard already shows the saved
  // instance (e.g. after a previous run created it), navigate to it and
  // configure its endpoint instead of creating a duplicate instance.
  const existingInstance = page
    .locator('a[href*="/instances/"], button[data-testid*="instance"], a:has-text("Flexible Gateway")')
    .first();
  if (await isVisible(existingInstance, 5000)) {
    const existingText = (await existingInstance.innerText().catch(() => "")).replace(/\s+/g, " ").trim();
    if (existingText.includes(instanceName) || existingText.includes("Flexible Gateway")) {
      console.log("[Oxylabs] Existing instance found on the dashboard; navigating to it instead of creating a new one.");
      await humanClick(page, existingInstance);
      await sleep(page, 5000);
      await page.waitForLoadState("domcontentloaded").catch(() => {});
      await sleep(page, 3000);
      await captureExitIp(page, "existing_instance");
      const endpoint = await configureEndpointAndCopyProxy(page, country, city, email);
      usage = (await readCommitmentUsage(page)) || usage;
      return {
        opened: true,
        overview_url: overviewUrl,
        dialog_text: "",
        product_clicked: true,
        instance_name: instanceName,
        instance_create_clicked: false,
        instance_created: true,
        proxy_string: endpoint.proxy || null,
        endpoint_country_selected: Boolean(endpoint.country_selected),
        endpoint_city_selected: Boolean(endpoint.city_selected),
        usage,
        url: page.url(),
      };
    }
  }

  // "Add product instance" may be exposed under several testids/labels on
  // different dashboard builds; try them in order and log the page text if
  // none are visible so the state can be diagnosed from the logs.
  const addButtonCandidates = [
    '[data-testid="asset-table-controls-add-product-button"]',
    '[data-testid*="add-product"]',
    '[data-testid*="add-product-instance"]',
    '[data-testid*="add-instance"]',
    '[data-testid*="product-add"]',
    'button:has-text("Add product instance")',
    'button:has-text("Add product")',
  ];
  let addButton = null;
  for (const sel of addButtonCandidates) {
    const loc = page.locator(sel).first();
    if (await isVisible(loc, 12000)) {
      addButton = loc;
      console.log(`[Oxylabs] Found add-product button: ${sel}`);
      break;
    }
  }
  if (!addButton) {
    const bodyText = (await page.locator("body").innerText().catch(() => "")).replace(/\s+/g, " ").trim();
    console.warn(`[Oxylabs] "Add product instance" button not found. Current URL: ${page.url()}`);
    console.warn(`[Oxylabs] Page preview: ${bodyText.slice(0, 1200)}`);
    await page.screenshot({ path: path.join(ARTIFACTS_DIR, "oxylabs_overview_no_add.png"), fullPage: true }).catch(() => {});
    return { opened: false, overview_url: overviewUrl, url: page.url(), usage };
  }

  console.log("[Oxylabs] Clicking 'Add product instance'.");
  await humanClick(page, addButton);
  await sleep(page, 4000);

  const dialog = page.locator('[role="dialog"]').first();
  if (!(await isVisible(dialog, 2000))) {
    console.log("[Oxylabs] No dialog after the human click; retrying with a direct click.");
    await addButton.click({ force: true, timeout: 10000 }).catch(() => {});
    await sleep(page, 4000);
  }

  await page.screenshot({ path: path.join(ARTIFACTS_DIR, "oxylabs_add_product_dialog.png"), fullPage: true }).catch(() => {});

  let dialogText = "";
  if (await isVisible(dialog, 5000)) {
    dialogText = (await dialog.innerText().catch(() => "")).replace(/\s+/g, " ").trim();
    console.log(`[Oxylabs] Add product dialog opened: ${dialogText.slice(0, 800)}`);
  } else {
    console.log("[Oxylabs] Clicked Add product; no [role=dialog] detected yet.");
  }

  // "Skip guide" may or may not appear. Never wait for it: give it a short,
  // bounded look (under a second), click it when present, then continue. If it
  // does not appear, proceed straight to instance/proxy creation.
  let skipClicked = false;
  const skipGuide = page
    .locator('button:has-text("Skip guide"), button:has-text("Skip"), [role="button"]:has-text("Skip guide"), [role="button"]:has-text("Skip")')
    .first();
  if (await isVisible(skipGuide, 700)) {
    console.log("[Oxylabs] Clicking 'Skip guide' on the add-product dialog.");
    await humanClick(page, skipGuide);
    skipClicked = true;
    await sleep(page, 1200);
    dialogText = (await page.locator('[role="dialog"]').first().innerText().catch(() => "")).replace(/\s+/g, " ").trim();
    if (!dialogText) dialogText = (await page.locator("body").innerText().catch(() => "")).replace(/\s+/g, " ").trim();
    console.log(`[Oxylabs] Add product dialog after Skip guide: ${dialogText.slice(0, 800)}`);
  } else {
    console.log("[Oxylabs] No 'Skip guide' button; continuing to product selection/instance creation.");
  }

  // Only re-open the picker if we actually skipped a guide. Otherwise leave
  // the product selection or fallback flow to create the instance.
  if (skipClicked && await isVisible(addButton, 3000)) {
    console.log("[Oxylabs] Clicking 'Add product instance' again after Skip guide.");
    await humanClick(page, addButton);
    await sleep(page, 2500);
    await page.waitForLoadState("domcontentloaded").catch(() => {});
    dialogText = (await page.locator('[role="dialog"]').first().innerText().catch(() => "")).replace(/\s+/g, " ").trim();
    if (!dialogText) dialogText = (await page.locator("body").innerText().catch(() => "")).replace(/\s+/g, " ").trim();
  }

  // Log the product cards present on the page so we can diagnose selectors.
  const productCards = page.locator('a[data-testid*="product-card"]');
  const productCardCount = await productCards.count().catch(() => 0);
  if (productCardCount > 0) {
    for (let i = 0; i < Math.min(productCardCount, 20); i++) {
      const card = productCards.nth(i);
      const href = await card.getAttribute("href").catch(() => "");
      const text = (await card.innerText().catch(() => "")).replace(/\s+/g, " ").slice(0, 120);
      console.log(`[Oxylabs] Product card ${i}: href=${href} text=${text}`);
    }
  } else {
    console.log("[Oxylabs] No product-card anchors found; page text logged below.");
  }

  // Product list -> Residential Proxies card (/en/instances/new?type=RP).
  let productClicked = false;
  let instanceCreateClicked = false;
  let instanceCreated = false;
  let proxyResult = { proxy: null, country_selected: false, city_selected: false };

  const rpCard = page
    .locator(
      'a[data-testid="product-card"][href*="type=RP"], a[data-testid="product-card"][href*="residential"], a[data-testid="product-card"]:has-text("Residential Proxies"), a[data-testid="product-card"]:has-text("Residential"), a[data-testid*="product-card"]:has-text("RP")'
    )
    .first();

  let rpVisible = await isVisible(rpCard, 10000);
  if (!rpVisible) {
    await dumpButtonsAndAnchors(page, "after-add-product-no-card");
    // Fallback: navigate directly to the documented instance-creation page
    // (/en/instances/new?type=RP). Some dashboard builds do not surface the
    // product cards after "Skip guide".
    console.log("[Oxylabs] Falling back to navigating directly to /en/instances/new?type=RP");
    await page.goto("https://dashboard.oxylabs.io/en/instances/new?type=RP", {
      waitUntil: "domcontentloaded",
      timeout: 60000,
    });
    await sleep(page, 6000);
    await page.waitForLoadState("domcontentloaded").catch(() => {});
    await dismissCookieBanner(page);
    rpVisible = true;
    productClicked = true;
  }

  if (rpVisible) {
    if (!productClicked) {
      console.log("[Oxylabs] Clicking the 'Residential Proxies' product card.");
      await humanClick(page, rpCard);
      await sleep(page, 5000);
      await page.waitForLoadState("domcontentloaded").catch(() => {});
      await sleep(page, 2500);
      productClicked = true;
    }

    await page.screenshot({
      path: path.join(ARTIFACTS_DIR, "oxylabs_instance_new.png"),
      fullPage: true,
    }).catch(() => {});

    const pageText = (await page.locator("body").innerText().catch(() => "")).replace(/\s+/g, " ").trim();
    console.log(`[Oxylabs] Instance creation page opened: ${page.url()}`);
    console.log(`[Oxylabs] Page preview: ${pageText.slice(0, 700)}`);

    // Instance name (min 4 chars) -> Create instance.
    const nameInput = page.locator(
      'input[data-testid="create-asset-name-rp"], input[placeholder*="Residential Proxies"]'
    ).first();

    if (await isVisible(nameInput, 20000)) {
      console.log(`[Oxylabs] Filling instance name: ${instanceName}`);
      await humanType(page, nameInput, instanceName, "Instance name");
      await sleep(page, 500);

      // Some builds show the endpoint generator on the creation form itself;
      // configure the geo targeting there before creating the instance.
      if (await isVisible(page.locator('[data-testid="endpoint-generator-country"]').first(), 1500)) {
        proxyResult = await configureEndpointAndCopyProxy(page, country, city, email);
      }

      const createBtn = page.locator(
        'button[data-testid="asset-form-create-project-button"], button:has-text("Create instance")'
      ).first();

      if (await isVisible(createBtn, 10000)) {
        console.log("[Oxylabs] Clicking 'Create instance'.");
        await humanClick(page, createBtn);
        await sleep(page, 8000);
        await page.waitForLoadState("domcontentloaded").catch(() => {});
        await sleep(page, 3000);

        instanceCreateClicked = true;
        await page.screenshot({
          path: path.join(ARTIFACTS_DIR, "oxylabs_instance_created.png"),
          fullPage: true,
        }).catch(() => {});

        const afterText = (await page.locator("body").innerText().catch(() => "")).replace(/\s+/g, " ").trim();
        const leftForm = !/\/instances\/new/i.test(page.url());
        instanceCreated = leftForm || /(created successfully|instance created|asset created|success)/i.test(afterText);

        console.log(`[Oxylabs] After 'Create instance': ${page.url()}`);
        console.log(`[Oxylabs] Page preview: ${afterText.slice(0, 700)}`);
      } else {
        console.warn("[Oxylabs] 'Create instance' button not found.");
      }
    } else {
      console.warn("[Oxylabs] Instance name field not found.");
    }

    if (instanceCreateClicked) {
      // Re-check on the instance page: this is where the generator usually
      // lives, and the trigger already shows the pre-selected geo.
      const endpoint = await configureEndpointAndCopyProxy(page, country, city, email);
      proxyResult = {
        proxy: endpoint.proxy || proxyResult.proxy,
        country_selected: proxyResult.country_selected || endpoint.country_selected,
        city_selected: proxyResult.city_selected || endpoint.city_selected,
      };
    }

    usage = (await readCommitmentUsage(page)) || usage;
    await captureExitIp(page, "post_instance");
  } else {
    console.warn("[Oxylabs] 'Residential Proxies' product card not found and fallback navigation failed.");
  }

  return {
    opened: true,
    overview_url: overviewUrl,
    dialog_text: dialogText,
    product_clicked: productClicked,
    instance_name: instanceName,
    instance_create_clicked: instanceCreateClicked,
    instance_created: instanceCreated,
    proxy_string: proxyResult.proxy,
    endpoint_country_selected: proxyResult.country_selected,
    endpoint_city_selected: proxyResult.city_selected,
    usage,
    url: page.url(),
  };
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------
async function main() {
  const startedAt = Date.now();

  if (isDatabaseAvailable()) {
    openDatabase();
    console.log(`[Oxylabs] Database: ${DB_FILE}`);
  }

  // Reuse the stored password, instance and proxy for existing accounts. A
  // usage check therefore never needs the password on the command line, and a
  // rerun never moves the account to a different exit IP.
  const saved = loadSavedAccount(email);

  const firstName = explicitFirstName || pick(FIRST_NAMES);
  const surname = explicitSurname || pick(SURNAMES);
  const password = explicitPassword || saved.password || (usageOnly ? null : generatePassword());
  const instanceName = explicitInstanceName || saved.instance_name || generateInstanceName();

  const profileName = sanitizeProfileName(email || "oxylabs", email);
  const profileDir = path.resolve(profileDirArg || path.join(PROFILES_DIR, profileName));
  fs.mkdirSync(profileDir, { recursive: true });
  fs.mkdirSync(ARTIFACTS_DIR, { recursive: true });

  // -------------------------------------------------------------------------
  // Proxy resolution: explicit -> saved -> fail closed
  // -------------------------------------------------------------------------
  const proxySource = explicitProxy ? "cli" : saved.proxy_used ? "saved" : null;
  const rawProxy = explicitProxy || saved.proxy_used || null;

  if (!rawProxy && !allowDirect) {
    console.error("=".repeat(74));
    console.error("Error: --proxy is required so the real IP / timezone / WebRTC stack");
    console.error("       never reach the Oxylabs dashboard.");
    console.error("       Pass --proxy \"user:pass@host:port\" or an existing account email");
    console.error("       with a saved proxy. Use --allow-direct only if you explicitly");
    console.error("       accept exposing this machine's real network identity.");
    console.error("=".repeat(74));
    process.exit(1);
  }

  const effectiveProxy = rawProxy ? ensureStickyProxy(rawProxy, email) : null;
  const proxyIdentity = effectiveProxy ? parseProxyIdentity(effectiveProxy) : null;

  let preflight = null;
  if (effectiveProxy) {
    console.log(`[Proxy] Pre-flight through ${maskProxy(effectiveProxy)} (source: ${proxySource})...`);
    preflight = validateProxyConnectivity(effectiveProxy);
    if (!preflight.ok) {
      console.error("=".repeat(74));
      console.error(preflight.statusCode === 407
        ? "[Proxy 407] Proxy Authentication Required / Access Denied."
        : "[Proxy Error] Pre-flight verification failed.");
      console.error(`[Proxy Error] Target: ${maskProxy(effectiveProxy)}`);
      console.error(`[Proxy Error] Reason: ${preflight.error}`);
      console.error("[Proxy Error] Refusing to launch without a verified proxy.");
      console.error("=".repeat(74));
      process.exit(1);
    }
    console.log(
      `[Proxy] OK: exit ${preflight.info.ip}`
      + `${preflight.info.city ? ` | ${preflight.info.city}, ${preflight.info.region || ""}, ${preflight.info.country || ""}` : ""}`
      + `${preflight.info.asn ? ` | ASN ${preflight.info.asn}` : ""}`
    );
    if (!proxyIdentity.has_sticky_session) {
      console.warn("[Proxy] WARNING: no sticky-session id found on the proxy; the exit IP can rotate mid-run.");
    }
    if (proxyIdentity.session_type && proxyIdentity.session_type !== "sessid_oneip" && !proxyIdentity.sticky_port) {
      console.warn(`[Proxy] WARNING: session type "${proxyIdentity.session_type}" is not sessid_oneip; a mid-run IP change may not abort.`);
    }
  } else {
    console.warn("=".repeat(74));
    console.warn("[Oxylabs] DIRECT MODE (--allow-direct): this machine's real IP, timezone");
    console.warn("          and WebRTC stack can reach the dashboard. Nothing is masked.");
    console.warn("=".repeat(74));
  }

  // -------------------------------------------------------------------------
  // Frozen persona seeds + timezone aligned to the proxy exit
  // -------------------------------------------------------------------------
  const personaPath = path.join(profileDir, "persona.json");
  let persona = null;
  if (fs.existsSync(personaPath)) {
    try {
      persona = JSON.parse(fs.readFileSync(personaPath, "utf-8"));
      // Let the full fingerprint own the screen geometry.
      delete persona["screen:width"];
      delete persona["screen:height"];
      delete persona["screen.width"];
      delete persona["screen.height"];
      delete persona["screen.availWidth"];
      delete persona["screen.availHeight"];
      console.log(`[Camoufox] Reusing frozen persona seeds: ${personaPath}`);
    } catch (e) {
      persona = null;
    }
  }

  const isGpuValid = Boolean(
    persona?.webgl_config
    && GPU_CONFIGURATIONS.some(([vendor, renderer]) => (
      vendor === persona.webgl_config[0] && renderer === persona.webgl_config[1]
    ))
  );

  const derivedTz = deriveTimezoneFromProxy(effectiveProxy || "", country);
  const proxyTimezone = effectiveProxy ? (preflight?.info?.timezone || derivedTz.tz) : null;
  const hostTimezone = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  const chosenTz = canonicalTimezone(explicitTimezone || proxyTimezone || hostTimezone) || "UTC";
  const chosenRegion = persona?.["locale:region"] || derivedTz.region || "US";
  const chosenLang = persona?.["locale:language"] || derivedTz.lang || "en";

  const personaOutdated = !persona
    || !persona["canvas:seed"]
    || !isGpuValid
    || !persona.timezone
    || canonicalTimezone(persona.timezone) !== canonicalTimezone(chosenTz);

  if (personaOutdated) {
    persona = {
      "canvas:seed": persona?.["canvas:seed"] || crypto.randomInt(1, 4_000_000_000),
      "audio:seed": persona?.["audio:seed"] || crypto.randomInt(1, 4_000_000_000),
      "fonts:spacing_seed": persona?.["fonts:spacing_seed"] || crypto.randomInt(1, 4_000_000_000),
      webgl_config: isGpuValid ? persona.webgl_config : GPU_CONFIGURATIONS[crypto.randomInt(GPU_CONFIGURATIONS.length)],
      screen_resolution: persona?.screen_resolution || SCREEN_RESOLUTIONS[crypto.randomInt(SCREEN_RESOLUTIONS.length)],
      timezone: chosenTz,
      "locale:region": chosenRegion,
      "locale:language": chosenLang,
    };
    fs.writeFileSync(personaPath, JSON.stringify(persona, null, 2), "utf-8");
    console.log(`[Camoufox] Saved verified persona: ${personaPath}`);
    console.log(`          GPU:      ${persona.webgl_config[1]}`);
    console.log(`          Screen:   ${persona.screen_resolution.width}x${persona.screen_resolution.height}`);
    console.log(`          Timezone: ${persona.timezone} (aligned to ${effectiveProxy ? "proxy exit" : "direct mode"})`);
  } else if (persona.timezone !== chosenTz) {
    persona.timezone = chosenTz;
    fs.writeFileSync(personaPath, JSON.stringify(persona, null, 2), "utf-8");
    console.log(`[Camoufox] Re-aligned persona timezone to ${chosenTz}.`);
  }

  // -------------------------------------------------------------------------
  // Frozen full BrowserForge fingerprint (device identity stays stable)
  // -------------------------------------------------------------------------
  const fingerprintPath = path.join(profileDir, "fingerprint.json");
  let fingerprint = null;
  if (fs.existsSync(fingerprintPath)) {
    try {
      const fp = JSON.parse(fs.readFileSync(fingerprintPath, "utf-8"));
      if (fp && fp.navigator && fp.screen) {
        fingerprint = fp;
        console.log(`[Oxylabs] Reusing frozen fingerprint: ${fingerprintPath}`);
      }
    } catch (e) { }
  }

  if (fingerprint?.screen?.width) {
    const previousScreen = persona.screen_resolution;
    persona.screen_resolution = {
      width: fingerprint.screen.width,
      height: fingerprint.screen.height,
    };
    if (!previousScreen
      || previousScreen.width !== persona.screen_resolution.width
      || previousScreen.height !== persona.screen_resolution.height) {
      console.log(
        `[Camoufox] Persona screen synced to the frozen fingerprint: `
        + `${persona.screen_resolution.width}x${persona.screen_resolution.height}`
      );
    }
  }

  if (!fingerprint) {
    const scr = persona.screen_resolution || { width: 1920, height: 1080 };
    try {
      fingerprint = FP_GENERATOR.getFingerprint({
        screen: {
          minWidth: scr.width, maxWidth: scr.width,
          minHeight: scr.height, maxHeight: scr.height,
        },
        operatingSystems: ["windows"],
      }).fingerprint;
    } catch (e) {
      fingerprint = FP_GENERATOR.getFingerprint({
        screen: { maxWidth: 1920, maxHeight: 1080 },
        operatingSystems: ["windows"],
      }).fingerprint;
      persona.screen_resolution = {
        width: fingerprint.screen.width,
        height: fingerprint.screen.height,
      };
    }
    fs.writeFileSync(fingerprintPath, JSON.stringify(fingerprint, null, 2));
    console.log(`[Oxylabs] Generated frozen fingerprint (${fingerprint.screen.width}x${fingerprint.screen.height}): ${fingerprintPath}`);
  }

  // Strict UA parity with the native Camoufox C++ Firefox engine.
  if (fingerprint?.navigator) {
    if (fingerprint.navigator.userAgent !== CAMOUFOX_UA || fingerprint.navigator.appVersion !== "5.0 (Windows)") {
      fingerprint.navigator.userAgent = CAMOUFOX_UA;
      fingerprint.navigator.appVersion = "5.0 (Windows)";
      if (Array.isArray(fingerprint.headers)) {
        for (const header of fingerprint.headers) {
          if (header && header.name && header.name.toLowerCase() === "user-agent") {
            header.value = CAMOUFOX_UA;
          }
        }
      }
      console.log(`[Camoufox] Aligned fingerprint UA to the native Camoufox stack (${CAMOUFOX_UA})`);
    }
  }

  // Sync videoCard with the explicit WebGL pair so WebGL/WebGPU agree.
  if (persona?.webgl_config && fingerprint) {
    const expectedCard = { vendor: persona.webgl_config[0], renderer: persona.webgl_config[1] };
    if (!fingerprint.videoCard
      || fingerprint.videoCard.vendor !== expectedCard.vendor
      || fingerprint.videoCard.renderer !== expectedCard.renderer) {
      fingerprint.videoCard = expectedCard;
    }
  }

  fs.writeFileSync(fingerprintPath, JSON.stringify(fingerprint, null, 2), "utf-8");
  fs.writeFileSync(personaPath, JSON.stringify(persona, null, 2), "utf-8");

  initRiskLog({
    email,
    proxyArg: effectiveProxy,
    persona,
    fingerprint,
    profileDir,
    startedAt,
    preflight,
    requestedCountry: country,
    fingerprintPath,
    personaPath,
  });

  // Spoof geolocation from the proxy exit (see deriveGeolocationSpoof).
  const spoofedGeolocation = effectiveProxy && preflight?.info?.ip
    ? await deriveGeolocationSpoof(preflight.info.ip)
    : null;
  if (spoofedGeolocation) {
    if (RISK) RISK.geolocation_spoof = spoofedGeolocation;
    riskEvent("geolocation_spoofed", "info", `Spoofed geolocation to ${spoofedGeolocation.latitude}, ${spoofedGeolocation.longitude} (proxy exit ${spoofedGeolocation.ip})`);
  }

  // Profile aging: bookmarks/history so a brand-new profile does not look like
  // a freshly-created automation directory.
  try {
    const agingScript = path.resolve("tools", "profile_aging.py");
    execFileSync("python", [agingScript, profileDir], { timeout: 15000, stdio: "ignore" });
    console.log("[Profile Aging] Seeded bookmarks and browsing history into the profile.");
  } catch (e) {
    console.warn(`[Profile Aging] Skipped: ${e.message}`);
  }

  const scr = persona.screen_resolution || { width: 1920, height: 1080 };
  const browserConfig = {
    user_data_dir: profileDir,
    headless,
    os: "windows",
    humanize: false,
    block_webrtc: true,
    exclude_addons: ["UBO"], // avoid bundled ad-blocker CSP/data: injection artifacts
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
      "network.trr.mode": 5, // disable DoH so DNS follows the proxy
      "network.proxy.socks_remote_dns": true,
      "network.http.connection-retry-timeout": 1500,
      // LiarJS Hardening: Match ClearType rendering between DOM canvas and OffscreenCanvas in Windows
      "gfx.font_rendering.cleartype_params.rendering_mode": 2,
      // LiarJS Hardening: Restrict host font enumeration to standard base fonts to avoid CJK leak on non-CJK locale
      "layout.css.font-visibility.standard": 1,
      "layout.css.font-visibility.base": 1,
      "layout.css.font-visibility.private": 1,
      "dom.webnotifications.enabled": true,
    },
    webgl_config: persona.webgl_config || undefined,
    i_know_what_im_doing: true,
    config: {
      "canvas:seed": persona["canvas:seed"],
      "canvas:aaOffset": 0,
      "canvas:aaCapOffset": false,
      "audio:seed": persona["audio:seed"],
      "fonts:spacing_seed": persona["fonts:spacing_seed"],
      timezone: chosenTz,
      "locale:region": chosenRegion,
      "locale:language": chosenLang,
      "locale:all": "en-US, en",
      ...(spoofedGeolocation
        ? {
            "geolocation:latitude": spoofedGeolocation.latitude,
            "geolocation:longitude": spoofedGeolocation.longitude,
            "geolocation:accuracy": spoofedGeolocation.accuracy,
          }
        : {}),
    },
  };

  const parsedProxy = effectiveProxy ? parseProxy(effectiveProxy) : null;
  if (parsedProxy) {
    browserConfig.proxy = parsedProxy;
    // Only let Camoufox geolocate when we have no explicit timezone from the
    // preflight. An explicit config timezone always wins.
    if (!explicitTimezone && !preflight?.info?.timezone) browserConfig.geoip = true;
  }

  console.log("=".repeat(64));
  console.log(`[Oxylabs] EMAIL:       ${email || "(profile only)"}`);
  console.log(`[Oxylabs] NAME:        ${usageOnly ? "(existing account)" : `${firstName} ${surname}`}`);
  console.log(`[Oxylabs] PASSWORD:    ${explicitPassword ? "(supplied)" : password ? "(generated/saved; stored in the database)" : "(profile session)"}`);
  console.log(`[Oxylabs] INSTANCE:    ${usageOnly ? "(unchanged)" : instanceName}`);
  console.log(`[Oxylabs] PROXY:       ${effectiveProxy ? `${maskProxy(effectiveProxy)} (${proxySource})` : "DIRECT - real IP exposed"}`);
  console.log(`[Oxylabs] TIMEZONE:    ${chosenTz}`);
  console.log(`[Oxylabs] COUNTRY:     ${country} | CITY: ${city}`);
  console.log(`[Oxylabs] PROFILE:     ${profileDir}`);
  console.log(`[Oxylabs] MODE:        ${usageOnly ? "usage-check" : "registration"}`);
  console.log(`[Oxylabs] SUBMIT:      ${submit}`);
  console.log(`[Oxylabs] HEADLESS:    ${headless}`);
  console.log("=".repeat(64));

  const context = await Camoufox(browserConfig);
  const pages = context.pages();
  const page = pages.length > 0 ? pages[0] : await context.newPage();
  await page.bringToFront().catch(() => {});

  // Anti-Detect Webdriver Leak Verification (Rule #2)
  const isWebdriver = await page.evaluate(() => navigator.webdriver).catch(() => false);
  if (isWebdriver) {
    console.error("=".repeat(64));
    console.error("[Anti-Detect Alert] ⚠️ navigator.webdriver is LEAKING (true)!");
    console.error("Script halted immediately per workspace security rules.");
    console.error("Solutions to prevent webdriver leaks:");
    console.error("  1. Camoufox C++ kernel spoofing strips webdriver natively in Firefox.");
    console.error("  2. Ensure marionette automation flags are not set in user prefs.");
    console.error("  3. Check that external CDP wrappers or extensions are not injecting webdriver properties.");
    console.error("=".repeat(64));
    await context.close().catch(() => {});
    process.exit(1);
  }
  console.log("[Anti-Detect Check] navigator.webdriver = false (CLEAN & SPOOFED)");

  await alignFrozenUserAgent(page, fingerprint, fingerprintPath);

  const record = {
    email,
    password: password || undefined,
    first_name: usageOnly ? undefined : firstName,
    surname: usageOnly ? undefined : surname,
    instance_name: usageOnly ? undefined : instanceName,
    profile_dir: profileDir,
    proxy_used: effectiveProxy || null,
    proxy_server: effectiveProxy ? maskProxy(effectiveProxy) : null,
    proxy_source: proxySource || "direct",
    endpoint_country: /^any$/i.test(country) ? null : country,
    endpoint_city: /^any$/i.test(city) ? null : city,
    email_hash: {
      sha256: crypto.createHash("sha256").update(String(email || "").toLowerCase()).digest("hex"),
      md5: crypto.createHash("md5").update(String(email || "").toLowerCase()).digest("hex"),
      full_hash: crypto.createHash("sha256").update(String(email || "").toLowerCase()).digest("hex"),
    },
    created_day: new Date().toLocaleDateString("en-US", { weekday: "long", year: "numeric", month: "long", day: "numeric" }),
    proxy_ip: preflight?.info?.ip || RISK?.preflight?.ip || RISK?.exit_ips?.[0]?.ip || null,
    persona_hash: RISK?.persona
      ? crypto.createHash("sha256").update(JSON.stringify(RISK.persona)).digest("hex").slice(0, 16)
      : null,
    fingerprint_hash: RISK?.fingerprint?.hash || null,
    submitted: false,
    status: "started",
    final_url: null,
    errors: [],
    created_at: new Date().toISOString(),
  };

  try {
    if (instanceUrl) {
      console.log(`[Oxylabs] Instance-URL mode: opening ${instanceUrl}`);
      let navigated = false;
      let lastError = null;
      for (let attempt = 1; attempt <= 3 && !navigated; attempt++) {
        try {
          await page.goto(instanceUrl, { waitUntil: "domcontentloaded", timeout: 120000 });
          navigated = true;
        } catch (err) {
          lastError = err.message;
          console.warn(`[Oxylabs] Instance-URL navigation attempt ${attempt} failed: ${lastError}`);
          if (attempt < 3) await sleep(page, 5000);
        }
      }
      if (!navigated) throw new Error(`Could not navigate to instance URL: ${instanceUrl} (${lastError})`);
      console.log(`[Oxylabs] Navigated to instance URL: ${page.url()}`);
      await sleep(page, 5000);
      await dismissCookieBanner(page);
      await runStealthPreflight(page, context);
      await ensureLoggedIn(page, email, password, Boolean(password));
      await sleep(page, 3000);
      await captureExitIp(page, "instance_url_start");
      const endpoint = await configureEndpointAndCopyProxy(page, country, city, email);
      console.log(`[Oxylabs] Endpoint result: ${JSON.stringify(endpoint).slice(0, 500)}`);
      record.status = "endpoint_configured";
      record.proxy_string = endpoint.proxy || null;
      record.proxy_source = "instance-url";
      record.final_url = page.url();
      record.usage = (await readCommitmentUsage(page)) || null;
      await captureExitIp(page, "instance_url_end");
      riskMark("finished");
      appendRegistry(record);
      console.log(`[Oxylabs] Result: ${record.status} | ${record.final_url}`);
      if (record.usage) {
        console.log(`[Oxylabs] Usage left: ${record.usage.usage_left_usd} USD (${record.usage.usage_left_percent}% remaining)`);
      }
      return;
    }

    if (usageOnly) {
      console.log("[Oxylabs] Usage-check mode: opening the dashboard overview.");
      await page.goto("https://dashboard.oxylabs.io/en/overview", { waitUntil: "domcontentloaded", timeout: 60000 });
      await sleep(page, 5000);
      await dismissCookieBanner(page);

      await runStealthPreflight(page, context);

      const loggedIn = await ensureLoggedIn(page, email, password, Boolean(password));
      record.final_url = page.url();
      if (!loggedIn) {
        throw new Error("Not logged in. Pass --password (from the registry) or reuse the signup profile.");
      }

      const usage = await readCommitmentUsage(page);
      if (!usage) {
        throw new Error("Commitment/usage card not found on the overview page.");
      }

      record.status = "usage_checked";
      record.usage = usage;
      await captureExitIp(page, "usage_final");
      record.final_url = page.url();
      appendRegistry(record);

      console.log(`[Oxylabs] Plan: ${usage.plan_name}`);
      console.log(`[Oxylabs] Spent: ${usage.spent_usd} / ${usage.commitment_usd} USD`);
      console.log(`[Oxylabs] Usage left: ${usage.usage_left_usd} USD (${usage.usage_left_percent}% remaining)`);
      return;
    }

    if (continueMode) {
      console.log("[Oxylabs] Continue mode: skipping registration and opening the dashboard to create the Residential Proxies instance.");
      record.submitted = true;
      record.status = "continue";
      await captureExitIp(page, "continue_start");

      // Navigate to the landing page for the stealth preflight only. The single
      // login happens inside openOverviewAndCreateInstance; doing it here too
      // caused a second login prompt and failed sessions.
      await page.goto(LANDING_URL, { waitUntil: "domcontentloaded", timeout: 60000 });
      await sleep(page, 4000);
      await dismissCookieBanner(page);
      await runStealthPreflight(page, context);

      const overview = await openOverviewAndCreateInstance(page, email, password, instanceName, country, city);
      record.overview_url = overview.overview_url || overview.url;
      record.add_product_dialog_text = overview.dialog_text || null;
      record.residential_product_clicked = Boolean(overview.product_clicked);
      record.instance_name = overview.instance_name || instanceName;
      record.proxy_string = overview.proxy_string || null;
      record.endpoint_country_selected = Boolean(overview.endpoint_country_selected);
      record.endpoint_city_selected = Boolean(overview.endpoint_city_selected);
      record.usage = overview.usage || null;
      if (overview.instance_created) {
        record.status = "instance_created";
      } else if (overview.instance_create_clicked) {
        record.status = "instance_create_clicked";
      } else if (overview.product_clicked) {
        record.status = "instance_creation_opened";
      } else if (overview.opened) {
        record.status = "add_product_dialog_opened";
      } else {
        record.status = "continue_add_button_not_found";
      }
      record.final_url = page.url();
      await captureExitIp(page, "final");
      riskMark("finished");
      appendRegistry(record);
      console.log(`[Oxylabs] Result: ${record.status} | ${record.final_url}`);
      if (record.usage) {
        console.log(`[Oxylabs] Usage left: ${record.usage.usage_left_usd} USD (${record.usage.usage_left_percent}% remaining)`);
      }
      return;
    }

    const nameField = await openRegistration(page);
    console.log("[Oxylabs] Registration form is visible.");

    const nameInput = page.locator('[data-testid="input-registration-name"], input[name="name"]').first();
    const surnameInput = page.locator('[data-testid="input-registration-surname"], input[name="surname"]').first();
    const emailInput = page.locator('[data-testid="input-registration-email"], input[name="email"]').first();
    const passwordInput = page.locator('[data-testid="input-registration-accountPassword"], input[name="password"]').first();

    await nameInput.waitFor({ state: "visible", timeout: fieldTimeout });

    console.log(`[Oxylabs] Filling name: ${firstName} ${surname}`);
    await humanType(page, nameInput, firstName, "Name");
    await sleep(page, 300);

    await humanType(page, surnameInput, surname, "Surname");
    await sleep(page, 300);

    console.log(`[Oxylabs] Filling email: ${email}`);
    await humanType(page, emailInput, email, "Email");
    await sleep(page, 300);

    // Optional confirm-password / confirm-email fields (present on some builds).
    const confirmPassword = page.locator(
      'input[data-testid*="confirm"][type="password"], input[name*="confirm" i][type="password"], input[name="passwordConfirmation"]'
    ).first();
    if (await isVisible(confirmPassword, 1000)) {
      console.log("[Oxylabs] Filling confirm password field.");
      await humanType(page, confirmPassword, password, "Confirm password");
      await sleep(page, 300);
    }

    const confirmEmail = page.locator(
      'input[data-testid*="confirm"][type="email"], input[data-testid*="email-confirm"], input[name*="confirm" i][type="email"], input[name="emailConfirmation"]'
    ).first();
    if (await isVisible(confirmEmail, 1000)) {
      console.log("[Oxylabs] Filling confirm email field.");
      await humanType(page, confirmEmail, email, "Confirm email");
      await sleep(page, 300);
    }

    await humanType(page, passwordInput, password, "Password");

    // Mouse drift + a short settle pause before any submit.
    await humanWander(page).catch(() => {});
    await sleep(page, 800 + Math.round(Math.random() * 700));

    const passwordLength = (await passwordInput.inputValue().catch(() => "")).length;
    console.log(`[Oxylabs] Password field filled (${passwordLength} characters, value hidden).`);

    const captcha = page.locator(
      'iframe[src*="captcha"], iframe[src*="turnstile"], iframe[src*="hcaptcha"], div[class*="turnstile"], div[class*="h-captcha"]'
    ).first();
    if (await isVisible(captcha, 1000)) {
      console.log("[Oxylabs] NOTE: a CAPTCHA widget is present and may require a manual click.");
    }

    await page.screenshot({
      path: path.join(ARTIFACTS_DIR, "oxylabs_registration_filled.png"),
      fullPage: true,
    }).catch(() => {});
    console.log("[Oxylabs] Saved tests/test_artifacts/oxylabs_registration_filled.png");

    const visibleErrors = async () => {
      const nodes = page.locator('[data-testid^="input-error-"]');
      const count = await nodes.count().catch(() => 0);
      const messages = [];
      for (let i = 0; i < count; i++) {
        const node = nodes.nth(i);
        if (await node.isVisible().catch(() => false)) {
          const text = (await node.innerText().catch(() => "")).trim();
          if (text) messages.push(text);
        }
      }
      return [...new Set(messages)];
    };

    const preSubmitErrors = await visibleErrors();
    record.errors = preSubmitErrors;
    record.status = "filled";
    record.final_url = page.url();
    appendRegistry(record);
    console.log(`[Oxylabs] Form filled. URL: ${page.url()}`);

    if (preSubmitErrors.length > 0) {
      console.warn(`[Oxylabs] Visible validation messages: ${preSubmitErrors.join(" | ")}`);
    }

    if (submit) {
      console.log("[Oxylabs] Looking for the Register button...");
      const submitCandidates = [
        'button[data-test="button-registration-continue"]',
        'button[data-testid="button-registration-continue"]',
        'button[data-testid="button-registration-submit"]',
        'button[data-testid*="registration"][data-testid*="submit"]',
        'button[data-testid*="submit"]',
        'button[type="submit"]',
        'button:has-text("Register")',
        'button:has-text("Create account")',
        'button:has-text("Sign up")',
      ];

      let submitBtn = null;
      for (const selector of submitCandidates) {
        const candidate = page.locator(selector).first();
        if (await isVisible(candidate, 1200)) {
          const text = (await candidate.innerText().catch(() => "")).trim();
          if (/register|sign up|create account|submit/i.test(text) || /submit/i.test(selector)) {
            submitBtn = candidate;
            console.log(`[Oxylabs] Using submit button: ${selector} ("${text}")`);
            break;
          }
        }
      }

      if (!submitBtn) {
        console.warn("[Oxylabs] Could not identify the Register button. Fill is complete; submit manually.");
        record.status = "filled_submit_button_not_found";
      } else {
        const submitStartedAt = Date.now();
        console.log("[Oxylabs] Clicking Register...");
        await humanClick(page, submitBtn);
        await sleep(page, 7000);
        await page.waitForLoadState("domcontentloaded").catch(() => {});
        await sleep(page, 2500);

        await page.screenshot({
          path: path.join(ARTIFACTS_DIR, "oxylabs_registration_submitted.png"),
          fullPage: true,
        }).catch(() => {});

        const postErrors = await visibleErrors();
        record.final_url = page.url();
        record.errors = postErrors;

        if (postErrors.length > 0) {
          record.status = "validation_error";
          console.warn(`[Oxylabs] Validation errors: ${postErrors.join(" | ")}`);
        } else {
          record.submitted = true;
          riskMark("form_submitted");
          console.log(`[Oxylabs] Registration submitted. URL: ${page.url()}`);
          await captureExitIp(page, "post_submit");

          // 1. Activation email -> activation link
          let activation = null;
          if (refreshToken) {
            activation = await pollForActivationEmail(
              clientId,
              refreshToken,
              submitStartedAt - 90_000, // clock tolerance; ignore stale messages
              emailTimeoutSec
            );
          } else {
            console.log("[Oxylabs] No mailbox refresh token supplied; skipping automatic activation-link retrieval.");
          }

          if (!activation) {
            record.status = refreshToken ? "activation_email_not_found" : "submitted_no_mailbox_token";
            console.warn(`[Oxylabs] Activation email was not retrieved (${record.status}).`);
          } else {
            record.activation_email_from = activation.from || null;
            record.activation_email_subject = activation.subject || null;
            record.activation_email_received = activation.received || null;

            console.log(`[Oxylabs] Opening activation link: ${maskActivationLink(activation.link)}`);
            await page.goto(activation.link, { waitUntil: "domcontentloaded", timeout: 60000 });
            await sleep(page, 6000);
            await page.screenshot({
              path: path.join(ARTIFACTS_DIR, "oxylabs_activation.png"),
              fullPage: true,
            }).catch(() => {});

            const activationBody = await page.locator("body").innerText().catch(() => "");
            const activationFailed = /(invalid|expired|already used|not valid)/i.test(activationBody)
              && /(token|activation|link)/i.test(activationBody);

            if (activationFailed) {
              record.status = "activation_link_error";
              console.warn("[Oxylabs] Activation page reports an invalid/expired/used token.");
            } else {
              record.activation_completed = true;
              record.status = "activated";
              riskMark("activated");
              console.log(`[Oxylabs] Activation completed. URL: ${page.url()}`);
              await captureExitIp(page, "post_activation");

              // 2. Overview -> Add product instance
              const overview = await openOverviewAndCreateInstance(page, email, password, instanceName, country, city);
              record.overview_url = overview.overview_url || overview.url;
              record.add_product_dialog_text = overview.dialog_text || null;
              record.residential_product_clicked = Boolean(overview.product_clicked);
              record.instance_name = overview.instance_name || instanceName;
              record.proxy_string = overview.proxy_string || null;
              record.endpoint_country_selected = Boolean(overview.endpoint_country_selected);
              record.endpoint_city_selected = Boolean(overview.endpoint_city_selected);
              record.usage = overview.usage || null;
              if (overview.instance_created) {
                record.status = "instance_created";
              } else if (overview.instance_create_clicked) {
                record.status = "instance_create_clicked";
              } else if (overview.product_clicked) {
                record.status = "instance_creation_opened";
              } else if (overview.opened) {
                record.status = "add_product_dialog_opened";
              } else {
                record.status = "activation_done_add_button_not_found";
              }
              record.final_url = page.url();
            }
          }
        }
      }
    } else {
      console.log("[Oxylabs] --submit not passed: leaving the form for manual review/submission.");
    }

    await captureExitIp(page, "final");
    riskMark("finished");
    appendRegistry(record);
    console.log(`[Oxylabs] Result: ${record.status} | ${record.final_url}`);
    if (record.usage) {
      console.log(`[Oxylabs] Usage left: ${record.usage.usage_left_usd} USD (${record.usage.usage_left_percent}% remaining)`);
    }
    console.log(`[Oxylabs] Credentials saved to ${REGISTRY_FILE}`);
    console.log("[Oxylabs] Password: stored in the registry and the SQLite database");
  } catch (err) {
    record.status = "failed";
    record.errors = [sanitizeError(err.message)];
    record.final_url = page.url();
    riskEvent("run_failed", "critical", sanitizeError(err.message));
    appendRegistry(record);
    console.error(`[Oxylabs] FAILED: ${sanitizeError(err.message)}`);
    await page.screenshot({ path: path.join(ARTIFACTS_DIR, "oxylabs_registration_error.png"), fullPage: true }).catch(() => {});
    process.exitCode = 1;
  } finally {
    saveRiskLog();
    closeDatabase();
    if (headless || noPause) {
      if (keepOpenSeconds > 0) {
        console.log(`[Oxylabs] Keeping the browser open for ${keepOpenSeconds}s...`);
        await new Promise((resolve) => setTimeout(resolve, keepOpenSeconds * 1000));
      }
      await context.close().catch(() => {});
    } else if (keepOpenSeconds > 0) {
      console.log(`[Oxylabs] Keeping the browser open for ${keepOpenSeconds}s...`);
      await new Promise((resolve) => setTimeout(resolve, keepOpenSeconds * 1000));
      await context.close().catch(() => {});
    } else if (process.stdin.isTTY) {
      const rl = readline.createInterface({ input: process.stdin, output: process.stdout });
      await new Promise((resolve) => rl.question("\n[Oxylabs] Press Enter to close the browser... ", resolve));
      rl.close();
      await context.close().catch(() => {});
    } else {
      console.log("[Oxylabs] Non-interactive terminal; closing the browser.");
      await context.close().catch(() => {});
    }
  }
}

main().catch((err) => {
  console.error(`[Oxylabs] Unhandled error: ${err.stack || err.message}`);
  process.exit(1);
});
