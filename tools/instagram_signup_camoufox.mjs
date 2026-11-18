#!/usr/bin/env node
/**
 * tools/instagram_signup_camoufox.mjs
 * ===================================
 * Automated Instagram Account Creation & OTP Verification via Camoufox Anti-Detect Browser.
 * 
 * Features:
 * - Natural landing page navigation (https://www.instagram.com/ -> Click Sign Up)
 * - Identity is decoupled from the mailbox: display name comes from a wide pool and
 *   the username uses one of 10 shapes, never the email local part
 * - Realistic randomized birthdate (ages 22-35)
 * - Human cadence: Gaussian per-key delays, idle pauses, mouse drift, typos/backspaces,
 *   and occasional tab switches before submit
 * - Multi-account isolation: dedicated profile directories with frozen persona.json seeds (canvas/audio/font)
 * - Automatic 6-digit OTP code retrieval from Outlook REST API (Office 365 / Hotmail)
 * - Automatic OTP entry & confirmation submission
 * - Per-account risk log (exit IP/ASN per step, proxy session hash, email-domain/pattern
 *   reuse, fingerprint hash, timing, coherence warnings) without credentials
 * - Saves master account credentials, proxy, location, full email thread to output/instagram_registered_accounts.json
 *
 * The mailbox domain itself cannot be changed here: rotate providers/domains outside
 * this script. `--strict-diversity` refuses to run when the registry already shows a
 * concentrated domain or local-part pattern.
 */

import fs from "node:fs";
import path from "node:path";
import crypto from "node:crypto";
import { execFileSync } from "node:child_process";
import { setupInstagram2FA } from "./setup_instagram_2fa.mjs";
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
// device identity stable between sessions (the persona seeds only freeze
// canvas/audio/font-spacing).
const FP_GENERATOR_PATH = "file:///C:/Users/rudra/AppData/Roaming/npm/node_modules/camoufox-cli/node_modules/fingerprint-generator/index.mjs";
const { FingerprintGenerator } = await import(FP_GENERATOR_PATH);
const FP_GENERATOR = new FingerprintGenerator({ browsers: ["firefox"], operatingSystems: ["windows"] });

// Parse CLI arguments
const args = process.argv.slice(2);
function getArg(name, defaultValue = null) {
  const idx = args.indexOf(name);
  return idx >= 0 && idx + 1 < args.length ? args[idx + 1] : defaultValue;
}
const hasFlag = (name) => args.includes(name);

// Never print OTP codes. Email subjects/previews often embed the 6-digit code.
const redactDigits = (value) => String(value || "").replace(/\b\d{4,8}\b/g, "***");

// Bound every external HTTP call so a dead proxy / Graph endpoint can never
// wedge the run forever (Node's fetch has no default timeout).
const HTTP_TIMEOUT_MS = 30000;
async function fetchWithTimeout(url, options = {}, timeoutMs = HTTP_TIMEOUT_MS) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, { ...options, signal: controller.signal });
  } finally {
    clearTimeout(timer);
  }
}

// ---------------------------------------------------------------------------
// Per-account risk log. Records the signals Meta can cluster on (exit IP/ASN
// per step, email-domain/pattern reuse, fingerprint hash reuse, timing and
// coherence warnings) without writing any password, OTP, token or proxy auth.
// ---------------------------------------------------------------------------
let RISK = null;

function sha256Short(value, len = 16) {
  return crypto.createHash("sha256").update(String(value || "")).digest("hex").slice(0, len);
}

function readRegistry() {
  const file = path.resolve("output", "instagram_registered_accounts.json");
  try {
    if (!fs.existsSync(file)) return [];
    const list = JSON.parse(fs.readFileSync(file, "utf-8"));
    return Array.isArray(list) ? list : [];
  } catch (e) {
    return [];
  }
}

// One profile name everywhere: signup, 2FA and open_ig_profile must resolve the
// same directory. Unsanitized local parts (+, =, spaces) silently created
// different folders in the other entry points.
function sanitizeProfileName(value, fallbackSeed = "") {
  const cleaned = String(value || "").split("@")[0].replace(/[^A-Za-z0-9._-]/g, "");
  if (!cleaned || cleaned === "." || cleaned === "..") {
    return `profile_${sha256Short(fallbackSeed || value || Date.now(), 8)}`;
  }
  return cleaned;
}

function classifyLocalPart(local) {
  const raw = String(local || "");
  const s = raw.toLowerCase();
  if (/^[A-Z][a-z]+(?:[A-Z][a-z]+)+\d*$/.test(raw)) return "camelcase_digits";
  if (/^[a-z]+\.[a-z]+/.test(s)) return "first.last";
  if (/^[a-z]+_[a-z]+/.test(s)) return "first_last";
  if (/^[a-z]+-[a-z]+/.test(s)) return "first-last";
  if (/^[a-z]{3,}\d{2,}$/.test(s)) return "word_digits";
  if (/^[a-z0-9]{8,}$/.test(s) && !/[aeiou]/.test(s)) return "random_consonants";
  if (/^[a-z0-9]{8,}$/.test(s)) return "alnum";
  return "other";
}

function ensureStickyProxy(proxyStr, seed = null) {
  if (!proxyStr) return proxyStr;
  let clean = String(proxyStr).trim().replace(/^https?:\/\//i, "");
  if (!clean.includes("@")) return `http://${clean}`;
  const [auth, hostPort] = clean.split("@");
  let [username, password] = auth.split(":");
  if (!username) return `http://${clean}`;

  // If using Oxylabs residential proxies (pr.oxylabs.io or customer-*), guarantee a 30-minute sticky session id
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

function parseProxyIdentity(proxyStr) {
  const clean = String(proxyStr || "").replace(/^https?:\/\//i, "");
  const at = clean.lastIndexOf("@");
  const auth = at >= 0 ? clean.slice(0, at) : "";
  const host = at >= 0 ? clean.slice(at + 1) : clean;
  const username = auth.split(":")[0] || "";
  const sessionMatch = username.match(/(?:^|[-_])(?:sessid|session|sess)[-_]([A-Za-z0-9]+)/i);
  const countryMatch = username.match(/-cc-([a-z]{2})(?:[-_]|$)/i);
  const stateMatch = username.match(/-st-([a-z_]+)(?:[-_]|$)/i);
  return {
    host: host || null,
    username_hash: username ? sha256Short(username, 16) : null,
    session: sessionMatch ? sessionMatch[1] : null,
    country: countryMatch ? countryMatch[1].toUpperCase() : null,
    state: stateMatch ? stateMatch[1] : null,
    has_sticky_session: Boolean(sessionMatch),
  };
}

function analyzeEmailDiversity(email) {
  const [local, domain] = String(email || "").split("@");
  const pattern = classifyLocalPart(local || "");
  const list = readRegistry();
  const cutoff = Date.now() - 30 * 24 * 60 * 60 * 1000;
  const domainLower = (domain || "").toLowerCase();
  const recent = list.filter((a) => {
    const ts = new Date(a && a.account_created_at ? a.account_created_at : 0).getTime();
    return Number.isFinite(ts) && ts >= cutoff;
  });
  const domainTotal = list.filter((a) => ((a && a.email ? a.email : "").split("@")[1] || "").toLowerCase() === domainLower).length;
  const domainRecent = recent.filter((a) => ((a && a.email ? a.email : "").split("@")[1] || "").toLowerCase() === domainLower).length;
  const patternRecent = recent.filter((a) => classifyLocalPart((a && a.email ? a.email : "").split("@")[0] || "") === pattern).length;
  const patternTotal = list.filter((a) => classifyLocalPart((a && a.email ? a.email : "").split("@")[0] || "") === pattern).length;
  const sameEmailCount = list.filter((a) => ((a && a.email ? a.email : "").toLowerCase() === String(email || "").toLowerCase())).length;
  const warnings = [];
  if (sameEmailCount > 0) {
    warnings.push(`Mailbox ${email} already appears ${sameEmailCount}x in the registry. Re-registering the same address links the attempts.`);
  }
  if (domainRecent >= 3) {
    warnings.push(`${domainRecent} accounts in the last 30 days use @${domainLower} (${domainTotal} total). Rotate mailbox providers/domains; one shared domain is a strong cluster signal.`);
  } else if (domainTotal >= 10) {
    warnings.push(`${domainTotal} registered accounts use @${domainLower}. Even spread over time, one domain concentrates the identities; rotate providers.`);
  }
  if (patternRecent >= 3) {
    warnings.push(`${patternRecent} accounts in the last 30 days use the "${pattern}" mailbox naming pattern (${patternTotal} total). Vary the local-part format.`);
  } else if (patternTotal >= 10) {
    warnings.push(`${patternTotal} registered accounts use the "${pattern}" mailbox naming pattern. Vary the local-part format even if signups are spaced out.`);
  }
  return {
    domain: domainLower || null,
    local_part_pattern: pattern,
    domain_accounts_30d: domainRecent,
    domain_accounts_total: domainTotal,
    pattern_accounts_30d: patternRecent,
    pattern_accounts_total: patternTotal,
    same_email_in_registry: sameEmailCount,
    warnings,
  };
}

function computeFingerprintHash(fp) {
  if (!fp) return null;
  const nav = fp.navigator || {};
  const fonts = Array.isArray(fp.fonts) ? [...fp.fonts].sort() : fp.fonts || null;
  const stable = {
    ua: nav.userAgent || null,
    platform: nav.platform || null,
    oscpu: nav.oscpu || null,
    hardwareConcurrency: nav.hardwareConcurrency != null ? nav.hardwareConcurrency : null,
    deviceMemory: nav.deviceMemory != null ? nav.deviceMemory : null,
    language: nav.language || null,
    languages: nav.languages || null,
    screen: fp.screen || null,
    videoCard: fp.videoCard || null,
    fonts,
    plugins: fp.pluginsData || null,
    audioCodecs: fp.audioCodecs || null,
    videoCodecs: fp.videoCodecs || null,
    battery: fp.battery || null,
  };
  return crypto.createHash("sha256").update(JSON.stringify(stable)).digest("hex");
}

function initRiskLog({ email, username, proxyArg, persona, fingerprint, profileDir, startedAt, usernamePattern, nameSource }) {
  const explicitProxy = getArg("--proxy");
  const emailDiversity = analyzeEmailDiversity(email);
  const proxyIdentity = parseProxyIdentity(proxyArg);
  const fingerprintHash = computeFingerprintHash(fingerprint);
  const others = readRegistry().filter((a) => (a && a.email ? a.email : "").toLowerCase() !== String(email).toLowerCase());
  const duplicateFingerprint = fingerprintHash
    ? others.find((a) => a && a.fingerprint_hash && a.fingerprint_hash === fingerprintHash) || null
    : null;
  const duplicateProxy = proxyIdentity.username_hash
    ? others.find((a) => a && a.proxy_username_hash && a.proxy_username_hash === proxyIdentity.username_hash) || null
    : null;

  RISK = {
    email,
    username,
    username_pattern: usernamePattern || null,
    name_source: nameSource || null,
    started_at: new Date(startedAt).toISOString(),
    profile_dir: profileDir,
    proxy: {
      ...proxyIdentity,
      via_default: !explicitProxy && proxyArg === DEFAULT_PROXY,
      asn: null,
      org: null,
    },
    email_identity: emailDiversity,
    fingerprint: {
      hash: fingerprintHash,
      duplicate_of: duplicateFingerprint ? duplicateFingerprint.email : null,
      coherence: null,
      tls: null,
      webrtc_candidates: null,
    },
    timing: {
      started_at: new Date(startedAt).toISOString(),
      page_loaded_at: null,
      form_submitted_at: null,
      otp_submitted_at: null,
      profile_setup_started_at: null,
      twofa_started_at: null,
      finished_at: null,
      total_seconds: null,
      fields: [],
    },
    exit_ips: [],
    warnings: emailDiversity.warnings.slice(),
    events: [],
  };

  if (!explicitProxy && proxyArg === DEFAULT_PROXY) {
    RISK.warnings.push("No --proxy passed: using the shared default proxy. Every account on it shares one provider identity.");
  }
  if (!proxyIdentity.has_sticky_session) {
    RISK.warnings.push("Proxy username has no sticky-session id; the exit IP can rotate mid-run. Use one sticky session per account.");
  }
  if (!fingerprintHash) {
    RISK.warnings.push("No fingerprint hash available; device identity may drift between runs.");
  }
  if (duplicateFingerprint) {
    RISK.warnings.push(`Fingerprint hash matches ${duplicateFingerprint.email}; two profiles present the same device identity.`);
  }
  if (duplicateProxy) {
    RISK.warnings.push(`Proxy username hash matches ${duplicateProxy.email}; proxy credentials/session are shared.`);
  }
  for (const warning of RISK.warnings) console.warn(`[Risk] ${warning}`);
  return RISK;
}

function riskMark(step, extra = {}) {
  if (!RISK) return;
  const at = new Date().toISOString();
  if (step in RISK.timing) RISK.timing[`${step}_at`] = at;
  RISK.events.push({ step, at, ...extra });
}

function riskEvent(step, extra = {}) {
  if (!RISK) return;
  RISK.events.push({ step, at: new Date().toISOString(), ...extra });
}

function riskField(stats) {
  if (!RISK || !stats) return;
  // Duration/corrections are useful; the character count of a password is not.
  RISK.timing.fields.push(stats.field === "password" ? { ...stats, chars: null } : stats);
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
    RISK.log_saved_at = now.toISOString();
    // Do not let a browser left open for hours inflate the flow duration:
    // prefer the timestamp from riskMark("finished").
    const flowEnd = RISK.timing.finished_at ? new Date(RISK.timing.finished_at) : now;
    RISK.finished_at = flowEnd.toISOString();
    if (!RISK.timing.finished_at) RISK.timing.finished_at = RISK.finished_at;
    RISK.timing.total_seconds = Math.round((flowEnd.getTime() - new Date(RISK.started_at).getTime()) / 1000);
    const target = path.join(RISK.profile_dir, "risk_log.json");
    fs.mkdirSync(path.dirname(target), { recursive: true });
    fs.writeFileSync(target, JSON.stringify(RISK, null, 2), "utf-8");

    const centralPath = path.resolve("output", "instagram_risk_log.json");
    let central = [];
    if (fs.existsSync(centralPath)) {
      try { central = JSON.parse(fs.readFileSync(centralPath, "utf-8")); } catch (e) { central = []; }
    }
    if (!Array.isArray(central)) central = [];
    const summary = {
      email: RISK.email,
      username: RISK.username,
      username_pattern: RISK.username_pattern,
      name_source: RISK.name_source,
      created_at: RISK.started_at,
      proxy: RISK.proxy,
      email_identity: RISK.email_identity,
      fingerprint_hash: RISK.fingerprint.hash,
      fingerprint_duplicate_of: RISK.fingerprint.duplicate_of,
      exit_ips: RISK.exit_ips,
      timing: RISK.timing,
      warnings: RISK.warnings,
      risk_log: target,
    };
    central = central.filter((x) => (x && x.email ? x.email : "").toLowerCase() !== String(RISK.email).toLowerCase());
    central.push(summary);
    fs.writeFileSync(centralPath, JSON.stringify(central, null, 2), "utf-8");
    console.log(`[Risk] Wrote per-account risk log: ${target}`);
  } catch (e) {
    console.warn(`[Risk] Could not save risk log: ${e.message}`);
  }
}

// Default Proxy (Oxylabs US Alabama Mobile Proxy)
const DEFAULT_PROXY = "customer-mobile_abb45c08-cc-us-st-us_alabama:uJPTpI+1nca~@pr.oxylabs.io:7777";
const proxyArg = getArg("--proxy", DEFAULT_PROXY);

// Default Account (Fresh Unused Outlook string)
const DEFAULT_ACCOUNT = "LexieSavinon95096@outlook.in|qdugfp46949|M.C543_BAY.0.U.MsaArtifacts.-CiAmYMxnXgpEiInE1zXpduQiHUVdu3On8BsaKtW8!6RobsbFEPwgoszVGqYjIAi2A9jCIVlrEDhTFY82wl6lO4PtPSvfHHWeHkiF47Lkam*PbBr1EaKJwx1LZtOAJDeeaVZuF!wUnW3iSvGLYZDRpAuLdsYp3ixzUFH62SBR3h4w0oDqVzZ97ykxsRy*b0qQvazCKNPXYwART9L17idTTV8rAI6lZl5aqle89NPCEMsTf8QhbqxHYJHiY906W8v12P9sRZkqRjQbjMDQ8UIahHg250WBvOVTiyRSXafQWGOquqU2juwshLCF4MAhGC5rBaZHgsBgV02Y0PGQPYZdHbHbuEOMO1MvrTuSQwFzPz8plDnC5ot2dOz*v*jvLymuIynWVeCQXxoXQgaXsJZi0GI$|9e5f94bc-e8a4-4e73-b8be-63364c29d753";

const accountArg = getArg("--account", DEFAULT_ACCOUNT);
let email = getArg("--email", "LexieSavinon95096@outlook.in");
let refreshToken = null;
let clientId = null;

if (accountArg) {
  const parts = accountArg.split("|");
  email = (parts[0] || "").trim();
  if (parts.length >= 4) {
    refreshToken = (parts[2] || "").trim();
    let rawCId = (parts[3] || "").trim().replace(/["']/g, "");
    if (rawCId.startsWith("9e5f94bc") && rawCId.length === 35) {
      rawCId = "9e5f94bc-e8a4-4e73-b8be-63364c29d753";
    }
    clientId = rawCId || "9e5f94bc-e8a4-4e73-b8be-63364c29d753";
  }
}

const headless = hasFlag("--headless");
const skipWarmup = hasFlag("--skip-warmup");
const skip2fa = hasFlag("--skip-2fa");

// 1. Outlook OAuth Token Exchange
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

  // Tier 1: Explicitly request Microsoft Graph Mail.Read scope (required for accounts with restricted defaults)
  try {
    const res = await fetchWithTimeout(tokenUrl, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({ ...baseParams, scope: "https://graph.microsoft.com/Mail.Read" }).toString(),
    });
    const data = await res.json();
    if (data.access_token) return data.access_token;
  } catch (e) {}

  // Tier 2: Explicitly request legacy Outlook Mail.Read scope
  try {
    const res = await fetchWithTimeout(tokenUrl, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({ ...baseParams, scope: "https://outlook.office.com/Mail.Read" }).toString(),
    });
    const data = await res.json();
    if (data.access_token) return data.access_token;
  } catch (e) {}

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

// 2. Outlook / Microsoft Graph Polling for Instagram 6-digit (or 5-digit) OTP
async function pollOutlookForInstagramOtp(cId, rToken, startTimeMs, maxWaitSeconds = 120) {
  console.log(`[Outlook OTP] Polling Microsoft Graph & Outlook REST API for Instagram OTP code (timeout: ${maxWaitSeconds}s)...`);
  const startTime = Date.now();
  const minReceivedTime = (startTimeMs || startTime) - 15000;

  while ((Date.now() - startTime) < maxWaitSeconds * 1000) {
    try {
      const accessToken = await getMsAccessToken(cId, rToken);
      
      // Dual-protocol endpoint list: Try Microsoft Graph v1.0 first, then legacy Outlook REST v2.0
      const folderGroups = [
        [
          "https://graph.microsoft.com/v1.0/me/messages?$top=5&$orderby=receivedDateTime%20desc",
          "https://graph.microsoft.com/v1.0/me/mailFolders/junkemail/messages?$top=5&$orderby=receivedDateTime%20desc"
        ],
        [
          "https://outlook.office.com/api/v2.0/me/messages?$top=5&$orderby=ReceivedDateTime%20desc",
          "https://outlook.office.com/api/v2.0/me/MailFolders/JunkEmail/messages?$top=5&$orderby=ReceivedDateTime%20desc"
        ]
      ];

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
              // Strictly ignore older emails received before this registration session
              if (receivedDate < minReceivedTime) {
                continue;
              }

              const subject = msg.subject || msg.Subject || "";
              const from = (
                msg.from?.emailAddress?.address ||
                msg.From?.EmailAddress?.Address ||
                ""
              ).toLowerCase();
              const preview = msg.bodyPreview || msg.BodyPreview || "";
              const fullContent = msg.body?.content || msg.Body?.Content || "";

              const isIg = from.includes("instagram") ||
                from.includes("facebook") ||
                subject.toLowerCase().includes("instagram") ||
                subject.toLowerCase().includes("code") ||
                preview.toLowerCase().includes("instagram");

              if (isIg) {
                console.log(`[Outlook OTP] Detected new verification email (${new Date(receivedDate).toLocaleTimeString()})!`);
                console.log(`              From:    ${from}`);
                console.log(`              Subject: ${redactDigits(subject)}`);
                console.log(`              Preview: ${redactDigits(preview.slice(0, 100))}...`);

                // Instagram codes are usually 6 digits
                const matchCode = subject.match(/\b(\d{6})\b/) ||
                  preview.match(/(?:code|is|is:)\s*[:\s]*(\d{6})\b/i) ||
                  preview.match(/\b(\d{6})\b/) ||
                  fullContent.match(/\b(\d{6})\b/);

                if (matchCode) {
                  const code = matchCode[1];
                  console.log(`[Outlook OTP] Successfully extracted Instagram OTP code (${code.length} digits, value not logged).`);
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
        if (groupSuccess) {
          // If Microsoft Graph succeeded (or Outlook v2 succeeded), no need to query the fallback group
          break;
        }
      }
    } catch (err) {
      console.warn(`[Outlook OTP] Polling attempt note: ${err.message}`);
    }

    const elapsed = Math.round((Date.now() - startTime) / 1000);
    console.log(`[Outlook OTP] Waiting 4s for Instagram OTP to arrive in inbox... (${elapsed}s elapsed)`);
    await new Promise((r) => setTimeout(r, 4000));
  }
  return null;
}

// 3. Name & Username Generator. Deliberately decoupled from the mailbox local
// part: if every @outlook.in address is FirstLastNNNNN, reusing that string as
// the IG username/display name reinforces the cluster. Names come from a wide
// pool and usernames use many shapes instead of one FirstLastNN template.
const FIRST_NAMES = [
  "Liam", "Noah", "Oliver", "Lucas", "Ethan", "Aiden", "Mason", "Logan", "James", "Benjamin",
  "Elijah", "Daniel", "Henry", "Jackson", "Sebastian", "Jack", "Owen", "Samuel", "Ryan", "Nathan",
  "Emma", "Olivia", "Ava", "Sophia", "Isabella", "Mia", "Charlotte", "Amelia", "Harper", "Evelyn",
  "Abigail", "Emily", "Ella", "Elizabeth", "Camila", "Luna", "Sofia", "Avery", "Mila", "Aria",
  "Nora", "Layla", "Chloe", "Penelope", "Riley", "Zoey", "Natalie", "Leah", "Hazel", "Violet",
  "Diego", "Mateo", "Carlos", "Adrian", "Javier", "Marco", "Leo", "Oscar", "Theo", "Miles",
  "Priya", "Ananya", "Rohan", "Arjun", "Meera", "Ishaan", "Valeria", "Elena", "Marina", "Nikolai",
];
const LAST_NAMES = [
  "Vance", "Wright", "Bennett", "Carter", "Hayes", "Morgan", "Brooks", "Reed", "Coleman", "Foster",
  "Bailey", "Rivera", "Sullivan", "Price", "Watson", "Sanders", "Murphy", "Bishop", "Fleming", "Hale",
  "Grant", "Doyle", "Pierce", "Barnes", "Hudson", "Spencer", "Marsh", "Ellis", "Watts", "Dean",
  "Silva", "Costa", "Reyes", "Flores", "Ortega", "Navarro", "Romero", "Vargas", "Mendoza", "Castro",
  "Patel", "Shah", "Mehta", "Kapoor", "Rao", "Nair", "Iyer", "Desai", "Chopra", "Bose",
  "Novak", "Petrov", "Ivanov", "Kowalski", "Andersen", "Larsen", "Berg", "Fischer", "Weber", "Hoffmann",
];
const USERNAME_WORDS = [
  // Generic personal-handle words (dominant) plus a few account-theme words.
  "sun", "moon", "star", "sky", "wave", "mint", "coffee", "pixel", "orbit", "north",
  "echo", "ember", "river", "stone", "maple", "cloud", "fox", "sage", "dawn", "dusk",
  "nova", "atom", "byte", "coast", "field", "grove", "harbor", "island", "kite", "lake",
  "oak", "pine", "rain", "reef", "trail", "vale", "wind", "amber", "coral", "frost",
  "reel", "frame", "scene", "cinema", "screen", "plot", "twist", "story", "film", "lens",
];

function extractNameAndUsername(emailStr) {
  const local = (emailStr || "").split("@")[0] || "";
  const noNums = local.replace(/\d+/g, "").trim();

  let parts = [];
  if (noNums.includes(".")) parts = noNums.split(".");
  else if (noNums.includes("_")) parts = noNums.split("_");
  else if (noNums.includes("-")) parts = noNums.split("-");
  else {
    const splitCamel = noNums.replace(/([a-z])([A-Z])/g, "$1 $2").trim();
    parts = splitCamel.split(/\s+/);
  }

  const capitalize = (s) => (s ? s.charAt(0).toUpperCase() + s.slice(1).toLowerCase() : "");

  let first = parts[0] ? capitalize(parts[0]) : "";
  let last = parts[1] ? capitalize(parts[1]) : "";
  const emailLooksLikeName = Boolean(first && last && /^[A-Za-z]{2,}$/.test(first) && /^[A-Za-z]{2,}$/.test(last));
  const nameSource = emailLooksLikeName && Math.random() < 0.5 ? "email" : "pool";

  if (nameSource === "pool" || !first || first.length < 2) first = FIRST_NAMES[crypto.randomInt(0, FIRST_NAMES.length)];
  if (nameSource === "pool" || !last || last.length < 2) last = LAST_NAMES[crypto.randomInt(0, LAST_NAMES.length)];

  const fullName = `${first} ${last}`;
  const fl = first.toLowerCase();
  const ll = last.toLowerCase();
  const suffix2 = () => crypto.randomInt(10, 100);
  const suffix3 = () => crypto.randomInt(100, 1000);
  const birthYear = () => crypto.randomInt(1985, 2005);
  const word = () => USERNAME_WORDS[crypto.randomInt(0, USERNAME_WORDS.length)];

  const patterns = [
    ["firstlast_digits", () => `${fl}${ll}${suffix2()}`],
    ["first.last_digits", () => `${fl}.${ll}${suffix2()}`],
    ["first_last_digits", () => `${fl}_${ll}${suffix2()}`],
    ["firstlast_underscore_digits", () => `${fl}${ll}_${suffix2()}`],
    ["the_firstlast", () => `the.${fl}${ll}`],
    ["first_initial_digits", () => `${fl}${ll[0]}${suffix3()}`],
    ["first.last.year", () => `${fl}.${ll}.${birthYear()}`],
    ["word.word_digits", () => `${word()}.${word()}${suffix2()}`],
    ["word_first_digits", () => `${word()}_${fl}${suffix2()}`],
    ["first_word_digits", () => `${fl}${word()}${suffix2()}`],
  ];

  // Compare the *letters* of the candidate username against the mailbox stem.
  // Otherwise `lexiesavinon42` slips past a check that only compares the full
  // local part `lexiesavinon95096`, and the IG handle still mirrors the email.
  const localStem = local.toLowerCase().replace(/[^a-z0-9]/g, "").replace(/\d+/g, "");
  const mirrorsMailbox = (candidate) => {
    const letters = String(candidate || "").toLowerCase().replace(/[^a-z]/g, "");
    if (!localStem || localStem.length < 5 || letters.length < 5) return false;
    return letters.includes(localStem) || localStem.includes(letters);
  };
  const cleanUsername = (value) => String(value || "").toLowerCase()
    .replace(/[^a-z0-9._]/g, "")
    .replace(/^[._]+|[._]+$/g, "")
    .slice(0, 28);

  let username = (getArg("--username") || "").trim();
  let usernamePattern = "cli";
  if (username) {
    username = cleanUsername(username);
    if (mirrorsMailbox(username)) {
      console.warn("[Identity] WARNING: --username mirrors the mailbox local part; this is a cluster signal. Consider a different handle.");
    }
  } else {
    // Try up to 8 random shapes; reject any that still mirror the mailbox.
    for (let attempt = 0; attempt < 8; attempt++) {
      const index = crypto.randomInt(0, patterns.length);
      const candidate = cleanUsername(patterns[index][1]());
      if (!mirrorsMailbox(candidate)) {
        username = candidate;
        usernamePattern = patterns[index][0];
        break;
      }
      usernamePattern = `${patterns[index][0]}+reshuffled`;
    }
    // All attempts mirrored (tiny mailbox stem or repeated name patterns):
    // force a word-based handle, which cannot contain the stem.
    if (!username) {
      usernamePattern = "word.word_digits+forced";
      username = cleanUsername(patterns[7][1]());
    }
  }
  if (username.length < 4) {
    usernamePattern = "fallback_firstlast_digits";
    username = cleanUsername(`${fl}${ll}${suffix3()}`);
  }

  return { firstName: first, lastName: last, fullName, username, nameSource, usernamePattern };
}

// 4. Randomized Organic Birthday (Ages 22-35)
function generateRandomBirthday() {
  const MONTHS = [
    { name: "January", index: 1, abbr: "Jan" },
    { name: "February", index: 2, abbr: "Feb" },
    { name: "March", index: 3, abbr: "Mar" },
    { name: "April", index: 4, abbr: "Apr" },
    { name: "May", index: 5, abbr: "May" },
    { name: "June", index: 6, abbr: "Jun" },
    { name: "July", index: 7, abbr: "Jul" },
    { name: "August", index: 8, abbr: "Aug" },
    { name: "September", index: 9, abbr: "Sep" },
    { name: "October", index: 10, abbr: "Oct" },
    { name: "November", index: 11, abbr: "Nov" },
    { name: "December", index: 12, abbr: "Dec" },
  ];

  const monthObj = MONTHS[crypto.randomInt(MONTHS.length)];
  const day = crypto.randomInt(1, 29);
  const year = crypto.randomInt(1991, 2003);
  const dayStr = `${day}`;

  return {
    day,
    dayStr,
    month: monthObj.name,
    monthAbbr: monthObj.abbr,
    monthIndex: monthObj.index,
    year,
    formatted: `${dayStr} ${monthObj.name} ${year}`,
  };
}

// 4.1 Unique Human-Like Password Generator (Anti-Cluster & Anti-Sybil Defense)
function generateUniquePassword(firstName, lastName) {
  const ADJECTIVES = ["Swift", "Silver", "Bright", "Golden", "Silent", "Noble", "Cosmic", "Vibrant", "Crimson", "Wild", "Brave", "Grand", "True", "Prime", "Lush", "Amber", "Mystic", "Solar", "Echo", "Frost"];
  const NOUNS = ["Eagle", "Falcon", "Summit", "Harbor", "Breeze", "Canyon", "Pillar", "Ranger", "River", "Forest", "Beacon", "Horizon", "Shadow", "Thunder", "Zenith", "Glade", "Ridge", "Orbit", "Haven", "Spark"];
  const SYMBOLS = ["!", "@", "#", "$", "%", "*"];

  const adj = ADJECTIVES[crypto.randomInt(ADJECTIVES.length)];
  const noun = NOUNS[crypto.randomInt(NOUNS.length)];
  const num = crypto.randomInt(100, 999);
  const sym = SYMBOLS[crypto.randomInt(SYMBOLS.length)];

  if (Math.random() < 0.5 && firstName && firstName.length >= 3) {
    return `${firstName}${noun}${num}${sym}`;
  }
  return `${adj}${noun}${num}${sym}`;
}

// 4.2 Dynamic Bio Generator (Defeats OCR & Text Similarity Clustered Flags)
function generateUniqueBio() {
  const HOOKS = [
    "Exploring the art of cinema",
    "Stories that stay with you long after the credits",
    "Daily deep dives into cinema & endings explained",
    "Unpacking hidden details & plot twists",
    "Cinema lover dissecting the best scenes",
    "Your daily movie recap & narrative breakdown guide",
    "Film enthusiast • Ending breakdowns & movie reviews",
    "Decoding the plot twists in modern cinema",
    "Where storytelling meets deep analysis",
    "Movie lover with an eye for the ending",
    "Chronicles of cinema, narratives & visual craft",
    "Tracking down the best movies & secret endings",
  ];
  const FOCUSES = [
    "Plot breakdowns, ending theories & scene analysis",
    "Daily recaps, hidden gems & must-watch recommendations",
    "Character studies, unexpected twists & final scenes",
    "Recaps, analysis & what to watch this weekend",
    "Behind-the-scenes thoughts & storyline explanations",
    "Plot twists, character arcs & cinematic perspectives",
    "Curated recaps and ending breakdowns daily",
  ];
  const CALLS = [
    "Comment 'MOVIE' for titles 🍿",
    "New breakdowns posted daily 🎬",
    "Catch the latest recap above 🍿✨",
    "Join the conversation in the comments 🎬",
    "Stay tuned for daily plot explanations 📽️",
    "What should I review next? Drop comments 🍿",
    "Follow for daily cinema deep dives 🎬✨",
  ];
  const SEPARATORS = [" | ", " • ", " // ", " — "];

  const hook = HOOKS[crypto.randomInt(HOOKS.length)];
  const focus = FOCUSES[crypto.randomInt(FOCUSES.length)];
  const call = CALLS[crypto.randomInt(CALLS.length)];
  const sep = SEPARATORS[crypto.randomInt(SEPARATORS.length)];

  return `${hook}${sep}${focus}${sep}${call}`;
}

// 4.3 Screen Resolutions (verified authentic resolutions in BrowserForge Bayesian distribution)
const SCREEN_RESOLUTIONS = [
  { width: 1920, height: 1080 }, // 1080p FHD (most popular desktop)
  { width: 1440, height: 900 },  // 1440x900 (widescreen desktop/laptop)
  { width: 1920, height: 1200 }, // 1920x1200 (16:10 productivity display)
  { width: 2560, height: 1080 }, // 2560x1080 (21:9 ultrawide)
  { width: 3440, height: 1440 }, // 3440x1440 (34" UWQHD display)
];

// 4.4 Verified authentic Windows GPU pairs strictly matching Camoufox's internal
// WebGL hardware database (dist/data-files/webgl_data.db). Camoufox requires that
// vendor & renderer exist in webgl_fingerprints WHERE win > 0 so that authentic
// shader constants, precision formats, and parameter blocks can be injected.
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

// 4.4.1 Timezone & Regional Alignment (Defeating Multi-Account Isolation Defect 1: Timezone Leak)
function deriveTimezoneFromProxy(proxyStr) {
  const p = (proxyStr || "").toLowerCase();
  if (p.includes("alabama") || p.includes("central") || p.includes("chicago")) return { tz: "America/Chicago", region: "US", lang: "en" };
  if (p.includes("us_california") || p.includes("los_angeles") || p.includes("pacific")) return { tz: "America/Los_Angeles", region: "US", lang: "en" };
  if (p.includes("us_new_york") || p.includes("eastern")) return { tz: "America/New_York", region: "US", lang: "en" };
  if (p.includes("-cc-us") || p.includes("united_states")) return { tz: "America/Chicago", region: "US", lang: "en" };
  if (p.includes("-cc-jp") || p.includes("japan") || p.includes("tokyo")) return { tz: "Asia/Tokyo", region: "JP", lang: "ja" };
  if (p.includes("-cc-in") || p.includes("india") || p.includes("ludhiana") || p.includes("mumbai")) return { tz: "Asia/Kolkata", region: "IN", lang: "en" };
  if (p.includes("-cc-gb") || p.includes("-cc-uk") || p.includes("london")) return { tz: "Europe/London", region: "GB", lang: "en" };
  if (p.includes("-cc-de") || p.includes("germany") || p.includes("berlin")) return { tz: "Europe/Berlin", region: "DE", lang: "de" };
  return { tz: "America/Chicago", region: "US", lang: "en" };
}

// 4.5 Registration Velocity Monitor
function checkRegistrationVelocity(minCooldownMinutes = 15) {
  const regFile = path.resolve("output", "instagram_registered_accounts.json");
  if (!fs.existsSync(regFile)) return;
  try {
    const list = JSON.parse(fs.readFileSync(regFile, "utf-8"));
    if (!Array.isArray(list) || list.length === 0) return;
    let latest = null;
    for (const item of list) {
      const ts = new Date(item?.account_created_at || 0).getTime();
      if (Number.isFinite(ts) && ts > 0 && (!latest || ts > latest.ts)) {
        latest = { ts, email: item.email };
      }
    }
    if (latest) {
      const elapsedMins = Math.round((Date.now() - latest.ts) / (60 * 1000));
      if (elapsedMins < minCooldownMinutes) {
        console.warn("=".repeat(60));
        console.warn(`[VELOCITY ALERT] Most recent account (${latest.email}) was created ${elapsedMins} minute(s) ago!`);
        console.warn(`Meta's fraud filters flag bursts within ${minCooldownMinutes} minutes. Recommended to wait or rotate proxy.`);
        console.warn("=".repeat(60));
      } else {
        console.log(`[Velocity Check] Cool-off OK: Most recent account created ${elapsedMins}m ago (> ${minCooldownMinutes}m).`);
      }
    }
  } catch (e) { }
}

// 5. Proxy Parser & Geolocation Lookup
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

async function getProxyLocation(page) {
  // First try an in-page fetch on the current document. Before navigating to
  // Instagram this is about:blank, so it uses the browser's own proxy stack and
  // gives an authoritative baseline exit IP. If CSP blocks it later in the
  // flow, fall through to the context request API.
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
      return {
        ip: loc.ip || loc.query,
        city: loc.city || "Unknown",
        region: loc.region || loc.region_code || "Unknown",
        country: loc.country_name || loc.country || "United States",
        timezone: loc.timezone || "America/Chicago",
        asn: loc.asn || null,
        org: loc.org || null,
      };
    }
  } catch (e) { }

  // Prefer the browser context's request API: it uses the context proxy but
  // bypasses the page's CSP, so it works even on instagram.com.
  try {
    const res = await page.context().request.get("https://ipapi.co/json/", { timeout: 8000 });
    if (res.ok()) {
      const loc = await res.json();
      if (loc && (loc.ip || loc.query)) {
        return {
          ip: loc.ip || loc.query,
          city: loc.city || "Unknown",
          region: loc.region || loc.region_code || "Unknown",
          country: loc.country_name || loc.country || "United States",
          timezone: loc.timezone || "America/Chicago",
          asn: loc.asn || null,
          org: loc.org || null,
        };
      }
    }
  } catch (e) { }

  try {
    const res = await page.context().request.get("https://api.ipify.org?format=json", { timeout: 6000 });
    if (res.ok()) {
      const loc = await res.json();
      if (loc && loc.ip) {
        return {
          ip: loc.ip,
          city: "Unknown",
          region: "Unknown",
          country: "United States",
          timezone: "America/Chicago",
          asn: null,
          org: null,
        };
      }
    }
  } catch (e) { }

  return { ip: "Unknown", city: "Unknown", region: "Unknown", country: "United States", timezone: "America/Chicago", asn: null, org: null };
}

async function captureExitIp(page, step, known = null) {
  const loc = known || await getProxyLocation(page);
  const entry = {
    step,
    at: new Date().toISOString(),
    ip: loc.ip || null,
    asn: loc.asn || null,
    org: loc.org || null,
    city: loc.city || null,
    region: loc.region || null,
    country: loc.country || null,
    timezone: loc.timezone || null,
  };
  if (RISK) {
    RISK.exit_ips.push(entry);
    if (entry.asn) RISK.proxy.asn = entry.asn;
    if (entry.org) RISK.proxy.org = entry.org;
    const first = RISK.exit_ips[0];
    if (RISK.exit_ips.length > 1 && first.ip && entry.ip && first.ip !== entry.ip) {
      riskWarn(`Exit IP changed during the run: ${first.ip} -> ${entry.ip} (@${step}). Use one sticky session for the whole account.`);
    }
  }
  console.log(`[Risk] Exit IP @ ${step}: ${entry.ip || "unknown"}${entry.asn ? ` | ASN ${entry.asn}` : ""}${entry.city ? ` | ${entry.city}, ${entry.region}, ${entry.country}` : ""}`);
  return entry;
}

// Local, network-free coherence probes. Compares what the page actually
// exposes against the frozen persona/fingerprint and flags contradictions.
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
      const vendorTag = (s) => (String(s || "").match(/\b(NVIDIA|AMD|Intel|Microsoft|Apple)\b/i) || [])[1];
      if (vendorTag(expected.renderer) && vendorTag(probe.webglRenderer)
        && vendorTag(expected.renderer).toLowerCase() !== vendorTag(probe.webglRenderer).toLowerCase()) {
        result.warnings.push(`WebGL vendor ${vendorTag(probe.webglRenderer)} does not match webgl_config ${vendorTag(expected.renderer)}`);
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

function printStealthAuditDashboard(audit) {
  const line = "=".repeat(74);
  const sep = "-".repeat(74);
  console.log("\n" + line);
  console.log("             INSTAGRAM STEALTH & ANTI-DETECT RISK AUDIT DASHBOARD        ");
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

async function captureTlsFingerprint(context) {
  // Must be measured by the browser itself. context.request() uses Node's TLS
  // stack, so it would report a JA3/JA4 that no page request ever presents.
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

async function safeGoto(page, url, options = { waitUntil: "domcontentloaded", timeout: 35000 }, maxRetries = 3) {
  for (let attempt = 1; attempt <= maxRetries; attempt++) {
    try {
      return await page.goto(url, options);
    } catch (err) {
      console.warn(`[Navigation] Attempt ${attempt} failed for ${url}: ${err.message}`);
      if (attempt === maxRetries) throw err;
      await new Promise((r) => setTimeout(r, 2500 * attempt));
    }
  }
}

// 6. Human behavior: Gaussian key delay, non-uniform pauses, mouse drift,
// occasional typos/backspaces and real tab switches. Uniform per-char delays
// are themselves a timing fingerprint, so pauses are drawn from a mixture.
// Natural human keystroke timing (Gaussian ~38ms with jitter, range 16ms - 85ms)
function gaussianDelay(mean = 38, stdDev = 12) {
  let u = 0;
  let v = 0;
  while (u === 0) u = Math.random();
  while (v === 0) v = Math.random();
  const z = Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v);
  return Math.max(16, Math.min(85, Math.round(mean + z * stdDev)));
}

const sleepJitter = (ms) => new Promise((resolve) => setTimeout(resolve, Math.max(8, Math.round(ms))));

// Playwright applies `delay` as the key-down -> key-up hold, not the gap
// between characters. Passing one char at a time therefore gives long key
// holds and near-zero inter-key gaps. Wait explicitly after every keystroke.
async function typeJittered(locator, text, mean = 38, stdDev = 12) {
  for (const char of String(text)) {
    await locator.pressSequentially(char);
    await sleepJitter(gaussianDelay(mean, stdDev));
  }
}

// Crisp human pause between actions (default 120ms - 280ms)
function humanPause(min = 120, max = 280) {
  const ms = min + Math.random() * (max - min);
  return new Promise((resolve) => setTimeout(resolve, Math.round(ms)));
}

async function humanMouseMove(page) {
  try {
    await humanWander(page);
  } catch (e) { }
}

async function humanType(locator, text, label = "field") {
  const started = Date.now();
  const value = String(text);
  let corrections = 0;
  let pauses = 0;
  const page = locator.page ? locator.page() : null;

  if (page) {
    await humanClick(page, locator);
  } else {
    await locator.click();
  }
  await locator.fill("");
  await humanPause(50, 120);

  for (let i = 0; i < value.length; i++) {
    // Rare natural typo (1.5% chance) with immediate snappy correction
    if (value.length > 5 && Math.random() < 0.015) {
      const alphabet = "abcdefghijklmnopqrstuvwxyz";
      const wrong = alphabet[crypto.randomInt(0, alphabet.length)];
      await locator.pressSequentially(wrong);
      await sleepJitter(gaussianDelay(35, 10));
      await humanPause(60, 140);
      await locator.press("Backspace");
      corrections++;
      await humanPause(40, 100);
    }

    await locator.pressSequentially(value[i]);
    await sleepJitter(gaussianDelay(38, 12));

    // Very rare micro-hesitation (0.8% chance)
    if (Math.random() < 0.008) {
      pauses++;
      await humanPause(120, 260);
    }
  }

  await humanPause(100, 220);
  return { field: label, duration_ms: Date.now() - started, corrections, pauses, chars: value.length };
}

async function simulateTabSwitch(page) {
  let other = null;
  try {
    const sites = [
      "https://www.bing.com/",
      "https://en.wikipedia.org/wiki/Main_Page",
      "https://www.accuweather.com/",
    ];
    const url = sites[crypto.randomInt(0, sites.length)];
    other = await page.context().newPage();
    await other.goto(url, { waitUntil: "domcontentloaded", timeout: 15000 }).catch(() => { });
    await other.bringToFront().catch(() => { });
    await other.waitForTimeout(1800 + crypto.randomInt(0, 3200));
  } catch (e) {
  } finally {
    if (other) await other.close().catch(() => { });
    await page.bringToFront().catch(() => { });
    await humanPause(350, 900);
  }
  riskEvent("tab_switch", { reason: "simulated checking another tab" });
}

// 7. Account Database Persistence
const REGISTERED_ACCOUNTS_FILE = path.resolve("output", "instagram_registered_accounts.json");

function saveInstagramAccount(record) {
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
    existing = existing.filter((item) => (item.email || "").toLowerCase() !== (record.email || "").toLowerCase());
    existing.push(record);
    fs.writeFileSync(REGISTERED_ACCOUNTS_FILE, JSON.stringify(existing, null, 2), "utf-8");
    console.log("=".repeat(60));
    console.log(`[Database] Saved Instagram account record to: ${REGISTERED_ACCOUNTS_FILE}`);
    console.log("=".repeat(60));
  } catch (err) {
    console.warn(`[Database] Error saving account: ${err.message}`);
  }
}

// 8. Step 2: Handle Post-Registration Onboarding (Dismiss Notifications, Go to Profile, Edit Profile, Change DP & Bio)
async function setupInstagramProfile(page, username, customBio = null, emailTarget = null) {
  console.log("=".repeat(60));
  console.log("[Instagram Step 2] Starting Profile Setup (DP Upload & Bio Update)...");
  console.log("=".repeat(60));

  const emailStem = sanitizeProfileName(emailTarget || username, emailTarget || username);
  const targetDir = path.resolve("output", "profiles instagram", emailStem);
  fs.mkdirSync(targetDir, { recursive: true });

  const rawDpPath = getArg("--dp") || path.resolve("tests", "test_artifacts", "test_thumb_vertical.jpg");
  const uniqueDpPath = path.join(targetDir, "dp_unique.jpg");

  let dpPhotoPath = rawDpPath;
  try {
    console.log(`[Instagram Step 2] Generating perceptually unique DP from: ${rawDpPath}...`);
    execFileSync("python", ["tools/generate_unique_dp.py", rawDpPath, uniqueDpPath], { stdio: "pipe" });
    if (fs.existsSync(uniqueDpPath)) {
      dpPhotoPath = uniqueDpPath;
      console.log(`[Instagram Step 2] Created unique DP with distinct pHash & fresh metadata: ${uniqueDpPath}`);
    }
  } catch (dpErr) {
    console.warn(`[Instagram Step 2] Note generating unique DP: ${dpErr.message}`);
  }

  const bioText = customBio || getArg("--bio") || generateUniqueBio();
  console.log(`[Instagram Step 2] Assigned Unique Bio: "${bioText}"`);

  // 1. Dismiss "Turn on Notifications" or "Save Info" modals
  console.log("[Instagram Step 2] Checking for 'Turn on Notifications' modal...");
  for (let i = 0; i < 4; i++) {
    const notNow = page.locator("button:has-text('Not Now'), [role='button']:has-text('Not Now'), button:has-text('Cancel')").first();
    if ((await notNow.count()) > 0 && (await notNow.isVisible())) {
      console.log("[Instagram Step 2] Clicking 'Not Now'...");
      await notNow.click();
      await page.waitForTimeout(1500);
    }
  }

  // 2. Go to Profile page by clicking avatar / profile navigation link
  console.log(`[Instagram Step 2] Locating & clicking Profile link for /${username}/...`);
  const profileSelector = `a[href*='/${username}/'], a[href='/${username}/'], a:has(img[alt*='profile picture']), a:has(img[alt*='${username}']), [aria-label*='Profile'], span:has(a[href*='/${username}/'])`;
  let profileClicked = false;
  for (let i = 0; i < 6; i++) {
    const profileLink = page.locator(profileSelector).first();
    if ((await profileLink.count()) > 0 && (await profileLink.isVisible())) {
      console.log(`[Instagram Step 2] Clicking Profile navigation link...`);
      await profileLink.hover().catch(() => {});
      await page.waitForTimeout(350);
      await profileLink.click().catch(() => {});
      profileClicked = true;
      break;
    }
    await page.waitForTimeout(1500);
  }
  if (!profileClicked) {
    console.log(`[Instagram Step 2] Profile link not found via selector, falling back to direct navigation...`);
    await safeGoto(page, `https://www.instagram.com/${username}/?hl=en`, { waitUntil: "domcontentloaded", timeout: 30000 });
  }
  await page.waitForTimeout(4000);

  // Dismiss any modal on profile
  const notNowProfile = page.locator("button:has-text('Not Now'), [role='button']:has-text('Not Now')").first();
  if ((await notNowProfile.count()) > 0 && (await notNowProfile.isVisible())) {
    await notNowProfile.click();
    await page.waitForTimeout(1000);
  }

  // 3. Navigate directly to 'Edit profile' page to avoid clicking options gear menu
  console.log("[Instagram Step 2] Navigating directly to /accounts/edit/?hl=en...");
  await safeGoto(page, "https://www.instagram.com/accounts/edit/?hl=en", { waitUntil: "domcontentloaded", timeout: 30000 });
  await page.waitForTimeout(2000);

  // 4. Change DP photo
  console.log("[Instagram Step 2] Uploading new DP (Profile Picture)...");
  if (fs.existsSync(dpPhotoPath)) {
    const changePhotoBtn = page.locator("div:has-text('Change photo'), button:has-text('Change photo'), [role='button']:has-text('Change photo')").first();
    if ((await changePhotoBtn.count()) > 0 && (await changePhotoBtn.isVisible())) {
      const fcPromise = page.waitForEvent("filechooser", { timeout: 3500 }).catch(() => null);
      await changePhotoBtn.click();
      const fc = await fcPromise;
      if (fc) {
        console.log(`[Instagram Step 2] Intercepted filechooser. Uploading: ${dpPhotoPath}...`);
        await fc.setFiles(dpPhotoPath);
      } else {
        const fileInp = page.locator("main input[type='file'], input[type='file']").first();
        if ((await fileInp.count()) > 0) {
          console.log(`[Instagram Step 2] Setting files directly on input[type='file']...`);
          await fileInp.setInputFiles(dpPhotoPath);
        }
      }
    } else {
      const fileInp = page.locator("input[type='file']").first();
      if ((await fileInp.count()) > 0) {
        await fileInp.setInputFiles(dpPhotoPath);
      }
    }
    await page.waitForTimeout(7000);
    console.log("[Instagram Step 2] DP photo uploaded successfully!");
  }

  // 5. Update Bio
  if (bioText) {
    const bioTextarea = page.locator("textarea:visible").first();
    if ((await bioTextarea.count()) > 0 && (await bioTextarea.isVisible())) {
      console.log(`[Instagram Step 2] Setting Bio: "${bioText}"...`);
      await bioTextarea.click();
      await page.keyboard.press("Control+A");
      await page.keyboard.press("Backspace");
      await page.waitForTimeout(200);
      await typeJittered(bioTextarea, bioText, 45, 15);
      await humanPause(400, 1000);

      const submitBioBtn = page.locator("div[role='button']:has-text('Submit'), [role='button']:has-text('Submit'), button:has-text('Submit')").first();
      if ((await submitBioBtn.count()) > 0 && (await submitBioBtn.isVisible())) {
        console.log("[Instagram Step 2] Submitting Bio changes...");
        await submitBioBtn.click();
        await page.waitForTimeout(3500);
      }
    }
  }

  // 6. Navigate back to Profile to verify
  console.log(`[Instagram Step 2] Clicking Profile link to return to /${username}/ and confirm DP & Bio...`);
  let returnClicked = false;
  for (let i = 0; i < 5; i++) {
    const profileLink2 = page.locator(profileSelector).first();
    if ((await profileLink2.count()) > 0 && (await profileLink2.isVisible())) {
      await profileLink2.hover().catch(() => {});
      await page.waitForTimeout(300);
      await profileLink2.click().catch(() => {});
      returnClicked = true;
      break;
    }
    await page.waitForTimeout(1000);
  }
  if (!returnClicked) {
    await safeGoto(page, `https://www.instagram.com/${username}/?hl=en`, { waitUntil: "domcontentloaded", timeout: 30000 });
  }
  await page.waitForTimeout(4000);
  await page.screenshot({ path: "tests/test_artifacts/ig_latest_live.png", fullPage: true });
  console.log("[Instagram Step 2] Profile verified and screenshot saved!");
}

// Pre-Signup Organic Browsing Warmup (randomized 2-3 neutral sites per identity)
async function preSignupOrganicWarmup(page) {
  console.log("=".repeat(60));
  console.log("[Camoufox Warmup] Starting Pre-Signup Organic Browsing...");
  console.log("[Camoufox Warmup] Purpose: Seed cookies, browser cache, TLS state before landing on Instagram");
  console.log("=".repeat(60));

  const warmupPool = [
    { name: "Wikipedia", url: "https://en.wikipedia.org/wiki/Main_Page" },
    { name: "Bing", url: "https://www.bing.com/" },
    { name: "BBC News", url: "https://www.bbc.com/news" },
    { name: "AccuWeather", url: "https://www.accuweather.com/" },
    { name: "ESPN", url: "https://www.espn.com/" },
    { name: "IMDb", url: "https://www.imdb.com/" },
  ];

  // Rotate the warmup set and order per identity so every account does not
  // produce the exact same first two navigations.
  for (let i = warmupPool.length - 1; i > 0; i--) {
    const j = crypto.randomInt(0, i + 1);
    [warmupPool[i], warmupPool[j]] = [warmupPool[j], warmupPool[i]];
  }
  const warmupSites = warmupPool.slice(0, 1).map((site) => ({
    ...site,
    stayMs: 2000 + crypto.randomInt(0, 1000), // Quick 2-3s visit to establish cache
  }));

  for (const site of warmupSites) {
    try {
      console.log(`[Camoufox Warmup] Quick cache visit: ${site.name} (${site.url})...`);
      await safeGoto(page, site.url, { waitUntil: "domcontentloaded", timeout: 15000 });
      await page.bringToFront().catch(() => {});

      // Simulate quick natural scroll
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

// 8.5 Handle Post-Registration Modals ("Save info", "Not Now", "Turn on notifications")
async function handlePostSignupModals(page, maxWaitMs = 18000) {
  console.log("=".repeat(60));
  console.log("[Instagram Onboarding] Checking for 'Save info' / 'Not Now' modals...");
  console.log("=".repeat(60));
  const startTime = Date.now();

  while (Date.now() - startTime < maxWaitMs) {
    let handled = false;

    // 1. "Save Your Login Info" modal -> Click "Save info" or "Not now"
    const saveInfoBtn = page.locator("button:has-text('Save info'), button:has-text('Save Info'), [role='button']:has-text('Save info'), [role='button']:has-text('Save Info'), button:has-text('Save')").first();
    if ((await saveInfoBtn.count()) > 0 && (await saveInfoBtn.isVisible().catch(() => false))) {
      console.log("[Instagram Onboarding] Found 'Save info' prompt. Clicking 'Save info'...");
      await humanClick(page, saveInfoBtn).catch(() => {});
      await page.waitForTimeout(800);
      handled = true;
    }

    // 2. "Turn on Notifications" modal -> Click "Not Now"
    const notNowBtn = page.locator("button:has-text('Not Now'), button:has-text('Not now'), [role='button']:has-text('Not Now'), [role='button']:has-text('Not now'), button:has-text('Cancel')").first();
    if ((await notNowBtn.count()) > 0 && (await notNowBtn.isVisible().catch(() => false))) {
      console.log("[Instagram Onboarding] Found 'Not Now' / Notifications prompt. Clicking 'Not Now'...");
      await humanClick(page, notNowBtn).catch(() => {});
      await page.waitForTimeout(800);
      handled = true;
    }

    // Check if on feed cleanly
    const url = page.url();
    const isFeed = url === "https://www.instagram.com/" || url.includes("instagram.com/?") || url.includes("/feed/") || url.includes("/explore/");
    if (!handled && isFeed && (Date.now() - startTime > 3000)) {
      console.log("[Instagram Onboarding] No blocking modals visible. Ready for feed browsing.");
      break;
    }

    await page.waitForTimeout(500);
  }
}

// 9. Natural Feed Warmup
async function warmUpInstagramFeed(page, durationSeconds = 25) {
  console.log("=".repeat(60));
  console.log(`[Instagram Warmup] Stimulating natural human feed browsing (${durationSeconds}s)...`);
  console.log("=".repeat(60));

  const endTime = Date.now() + durationSeconds * 1000;
  while (Date.now() < endTime) {
    // Check if any modal popped up during feed browsing
    const modalBtn = page.locator("button:has-text('Not Now'), button:has-text('Not now'), button:has-text('Save info'), button:has-text('Save Info'), [role='button']:has-text('Not Now')").first();
    if ((await modalBtn.count()) > 0 && (await modalBtn.isVisible().catch(() => false))) {
      console.log("[Instagram Warmup] Dismissing in-feed modal prompt...");
      await humanClick(page, modalBtn).catch(() => {});
      await page.waitForTimeout(600);
    }

    // Natural inertial wheel scroll
    const scrollAmount = 180 + Math.floor(Math.random() * 260);
    await humanScroll(page, scrollAmount).catch(async () => {
      await page.mouse.wheel(0, scrollAmount).catch(() => {});
    });

    // Natural reading dwell pause
    const readPause = 1400 + Math.floor(Math.random() * 2000);
    await page.waitForTimeout(readPause);

    // Natural cursor wander
    await humanWander(page).catch(() => {});
  }
  console.log("[Instagram Warmup] Completed natural feed browsing warmup.");
}

// Only a real OTP screen (or a code-specific input) counts. A generic visible
// input must never be treated as the confirmation-code field.
async function isOtpScreen(page) {
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
    "input[autocomplete='one-time-code'], input[aria-label*='code' i], input[placeholder*='code' i], input[name*='code' i], input[maxlength='6']"
  ).first();
  return (await codeInput.count()) > 0 && (await codeInput.isVisible().catch(() => false));
}

// 9. Main Automation Workflow
async function run() {
  const startedAt = Date.now();

  // Optional hard stop: refuse to add another account to an already overused
  // mailbox domain/pattern. Enable with --strict-diversity.
  if (hasFlag("--strict-diversity")) {
    const diversity = analyzeEmailDiversity(email);
    if (diversity.warnings.length > 0) {
      console.error("[Identity] Strict diversity enabled; refusing to create another clustered account:");
      for (const warning of diversity.warnings) console.error(`  - ${warning}`);
      process.exit(1);
    }
  }

  // Check registration velocity to prevent burst flags
  checkRegistrationVelocity(15);

  const { firstName, lastName, fullName, username, nameSource, usernamePattern } = extractNameAndUsername(email);
  const dobObj = generateRandomBirthday();
  const explicitProxy = getArg("--proxy");
  const rawProxy = explicitProxy || DEFAULT_PROXY;
  const effectiveProxy = ensureStickyProxy(rawProxy, email);
  const parsedProxyIdentity = parseProxyIdentity(effectiveProxy);
  const parsedProxy = parseProxy(effectiveProxy);
  const password = getArg("--password") || generateUniquePassword(firstName, lastName);

  console.log("=".repeat(60));
  console.log("INSTAGRAM AUTOMATED REGISTRATION (CAMOUFOX ANTI-DETECT + PROXY)");
  console.log("=".repeat(60));
  console.log(`Email Address:  ${email}`);
  console.log(`Full Name:      ${fullName}`);
  console.log(`Username:       ${username} (pattern: ${usernamePattern}, name source: ${nameSource})`);
  console.log(`Date of Birth:  ${dobObj.formatted} (Age ~${new Date().getFullYear() - dobObj.year})`);
  console.log(`Password:       [generated, saved to the account registry]`);
  if (parsedProxy) {
    console.log(`Proxy Server:   ${parsedProxy.server} (Sticky Session: ${parsedProxyIdentity.session || "active"})`);
  }
  if (refreshToken && clientId) {
    console.log(`Outlook OAuth:  Configured (Client ID: ${clientId})`);
  }
  console.log("=".repeat(60));

  // 1-to-1 Configuration Invariant: One Identity = One Profile = One Frozen Persona
  const profileDir = path.resolve("output", "profiles instagram", sanitizeProfileName(email, email));
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
      // Clean up any deprecated keys so config strictly matches Camoufox properties schema
      delete persona["screen:width"];
      delete persona["screen:height"];
      delete persona["screen.width"];
      delete persona["screen.height"];
      delete persona["screen.availWidth"];
      delete persona["screen.availHeight"];
      console.log(`[Camoufox] Re-using frozen persona seeds for identity: ${personaPath}`);
    } catch (e) { }
  }
  // Verify persona webgl_config is strictly in the verified database pool
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
    console.log(`[Camoufox] Saved and froze verified persona for identity: ${personaPath}`);
    console.log(`          GPU:      ${persona.webgl_config[1]}`);
    console.log(`          Screen:   ${persona.screen_resolution.width}x${persona.screen_resolution.height}`);
    console.log(`          Timezone: ${persona.timezone} (matches proxy exit IP)`);
  }

  // Frozen FULL fingerprint per identity.
  const fingerprintPath = path.join(profileDir, "fingerprint.json");
  let fingerprint = null;
  if (fs.existsSync(fingerprintPath)) {
    try {
      const fp = JSON.parse(fs.readFileSync(fingerprintPath, "utf-8"));
      if (fp && fp.navigator && fp.screen) {
        fingerprint = fp;
        console.log(`[Camoufox] Re-using frozen full fingerprint for identity: ${fingerprintPath}`);
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
      } catch (e) {
        console.log(`[Camoufox] Screen ${scr.width}x${scr.height} not directly in BrowserForge Bayesian network. Sampling coherent Windows screen...`);
      }
    }
    if (!generated) {
      const res = FP_GENERATOR.getFingerprint({ operatingSystems: ["windows"] });
      generated = res.fingerprint;
      persona.screen_resolution = { width: generated.screen.width, height: generated.screen.height };
      fs.writeFileSync(personaPath, JSON.stringify(persona, null, 2));
    }
    fingerprint = generated;
    fs.writeFileSync(fingerprintPath, JSON.stringify(fingerprint, null, 2));
    console.log(`[Camoufox] Generated and froze full fingerprint (${fingerprint.screen.width}x${fingerprint.screen.height}) for identity: ${fingerprintPath}`);
  }

  // Strict User-Agent Parity: Ensure DOM navigator.userAgent and request headers strictly match
  // Camoufox's native C++ Firefox 158.0 engine. Prevents TLS/JA3/HTTP discrepancies on anti-bot detectors.
  const CAMOUFOX_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:158.0) Gecko/20100101 Firefox/158.0";
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

  // Keep the frozen fingerprint's videoCard coherent with the explicit WebGL
  // pair. If they disagree, detectors see a GPU/WebGL mismatch.
  if (persona?.webgl_config) {
    const expectedCard = { vendor: persona.webgl_config[0], renderer: persona.webgl_config[1] };
    if (!fingerprint.videoCard
      || fingerprint.videoCard.vendor !== expectedCard.vendor
      || fingerprint.videoCard.renderer !== expectedCard.renderer) {
      fingerprint.videoCard = expectedCard;
      try { fs.writeFileSync(fingerprintPath, JSON.stringify(fingerprint, null, 2)); } catch (e) { }
    }
  }

  // Save account OAuth & credential tokens for future 2FA / login operations
  const accountInfoPath = path.join(profileDir, "account_info.json");
  try {
    fs.writeFileSync(accountInfoPath, JSON.stringify({
      email,
      password: password,
      username,
      client_id: clientId,
      refresh_token: refreshToken,
      proxy_used: effectiveProxy,
      created_at: new Date().toISOString(),
    }, null, 2));
    console.log(`[Camoufox] Saved account credential cache to: ${accountInfoPath}`);
  } catch (e) { }

  // Start the per-account risk log before launch. Records only signals, never
  // passwords, OTPs, tokens or proxy authentication.
  initRiskLog({ email, username, proxyArg: effectiveProxy, persona, fingerprint, profileDir, startedAt, usernamePattern, nameSource });

  console.log("[Camoufox] Launching Camoufox with residential proxy, frozen persona & WebRTC protection...");
  const scr = persona.screen_resolution || { width: 1920, height: 1080 };
  const browserConfig = {
    user_data_dir: profileDir,
    headless: headless,
    os: "windows",
    humanize: 0.85,
    block_webrtc: true,
    exclude_addons: ["UBO"],     // Exclude bundled ad-blocker to prevent CSP data: injection violations & CDN script drops
    screen: { maxWidth: scr.width, maxHeight: scr.height },
    fingerprint,                 // full frozen BrowserForge fingerprint (stable device identity)
    webgl_config: persona.webgl_config || undefined, // explicit real consumer GPU pair
    i_know_what_im_doing: true,  // intentional: we persist the fingerprint ourselves
    config: {
      "canvas:seed": persona["canvas:seed"],
      "canvas:aaOffset": 0,
      "canvas:aaCapOffset": false,
      "audio:seed": persona["audio:seed"],
      "fonts:spacing_seed": persona["fonts:spacing_seed"],
      timezone: persona.timezone || chosenTz,
      "locale:region": persona["locale:region"] || chosenRegion,
      "locale:language": persona["locale:language"] || chosenLang,
    },
  };
  if (parsedProxy) {
    browserConfig.proxy = parsedProxy;
  }

  const browser = await Camoufox(browserConfig);
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
          try {
            return await origGet(options);
          } catch (err) {
            throw new DOMException("The operation either timed out or was not allowed.", "NotAllowedError");
          }
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
        await page.screenshot({ path: "tests/test_artifacts/ig_latest_live.png", fullPage: true });
        console.log(`[Screenshot Ticker] Updated tests/test_artifacts/ig_latest_live.png (${new Date().toLocaleTimeString()})`);
      } catch (e) { }
    }
  })();

  try {
    // 1. Verify Proxy Location, capture the per-step exit IP/ASN and audit
    // what the page actually exposes against the frozen persona.
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
      riskWarn("TLS/JA3 capture failed; the browser TLS stack could not be verified (proxy blocked the probe or the endpoint is down).");
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

    // 1.5 Pre-Signup Organic Browsing Warmup (15-20s on neutral high-authority sites)
    if (!skipWarmup) {
      await preSignupOrganicWarmup(page);
    }

    // 2. Natural Navigation Flow to Instagram
    console.log("[Camoufox] Navigating to https://www.instagram.com/?hl=en (organic landing page visit in English)...");
    await safeGoto(page, "https://www.instagram.com/?hl=en", { waitUntil: "domcontentloaded", timeout: 40000 });
    await page.bringToFront().catch(() => { });
    await page.waitForTimeout(600 + Math.random() * 400);
    riskMark("page_loaded");

    // Dismiss Cookie dialog if shown
    const cookieBtn = page.locator("button:has-text('Allow all cookies'), button:has-text('Allow essential and optional cookies'), button:has-text('Decline optional cookies'), [aria-label='Allow all cookies']");
    if ((await cookieBtn.count()) > 0 && (await cookieBtn.first().isVisible())) {
      console.log("[Instagram] Dismissing cookie prompt...");
      await humanClick(page, cookieBtn.first()).catch(() => { });
      await page.waitForTimeout(400);
    }

    // Check if already on sign-up page or click "Create new account" / "Sign up"
    let currentUrl = page.url();
    if (!currentUrl.includes("emailsignup")) {
      console.log("[Instagram] Locating 'Create new account' / 'Sign up'...");
      await page.waitForTimeout(400);

      const signUpSelector = "span:text-is('Create new account'), span:has-text('Create new account'), div[role='button']:has-text('Create new account'), a:has-text('Create new account'), a[href*='/accounts/emailsignup'], span:text-is('Sign up'), a:has-text('Sign up')";
      let clickedSignUp = false;

      for (let attempt = 1; attempt <= 4; attempt++) {
        const signUpBtn = page.locator(signUpSelector).first();
        if ((await signUpBtn.count()) > 0 && (await signUpBtn.isVisible())) {
          console.log("[Instagram] Found 'Create new account' / 'Sign up' element. Clicking...");
          await humanClick(page, signUpBtn).catch(() => {});
          await page.waitForTimeout(1000);
          clickedSignUp = true;
          break;
        }
        await page.waitForTimeout(600);
      }

      if (!clickedSignUp) {
        console.log("[Instagram] Direct navigation to sign-up page...");
        await safeGoto(page, "https://www.instagram.com/accounts/emailsignup/?hl=en", { waitUntil: "domcontentloaded", timeout: 30000 });
        await page.waitForTimeout(800);
      }
    }

    // Dismiss cookie prompt again if shown on signup screen
    if ((await cookieBtn.count()) > 0 && (await cookieBtn.first().isVisible())) {
      await humanClick(page, cookieBtn.first()).catch(() => { });
      await page.waitForTimeout(300);
    }

    // 3. Fill Registration Form
    console.log("=".repeat(60));
    console.log("[Instagram] Filling registration form...");
    console.log("=".repeat(60));

    // Wait for the form to render, then begin naturally
    await page.waitForSelector("input", { timeout: 15000 });
    await humanPause(150, 350);

    const textInputs = page.locator("input[type='text']:visible, input:not([type='password']):not([type='hidden']):not([type='search']):visible");

    // Field 1: Mobile number or email
    console.log(`[Instagram] Entering Email: ${email}...`);
    let emailInput = page.locator("input[name='emailOrPhone'], input[aria-label*='email' i], input[placeholder*='Mobile number or email' i]").first();
    if ((await emailInput.count()) === 0 || !(await emailInput.isVisible())) {
      emailInput = textInputs.nth(0);
    }
    await emailInput.waitFor({ state: "visible", timeout: 15000 });
    riskField(await humanType(emailInput, email, "email"));
    await humanPause(120, 260);

    // Field 2: Password
    console.log(`[Instagram] Entering password (hidden)...`);
    const passInput = page.locator("input[name='password'], input[type='password']").first();
    await passInput.waitFor({ state: "visible", timeout: 10000 });
    riskField(await humanType(passInput, password, "password"));
    await humanPause(120, 260);

    // Field 3: Birthday (Month, Day, Year comboboxes or selects)
    console.log(`[Instagram] Setting Birthday: ${dobObj.formatted}...`);

    async function selectComboboxOption(comboLocator, exactText, labelName) {
      if ((await comboLocator.count()) > 0 && (await comboLocator.isVisible())) {
        console.log(`[Instagram] Selecting ${labelName}: "${exactText}"...`);
        await humanClick(page, comboLocator);
        await humanPause(80, 180);

        // Find option with exact text match to prevent "5" matching "2025" or "15"
        const opt = page.locator("[role='option']").filter({ hasText: new RegExp(`^\\s*${exactText}\\s*$`) }).first();
        if ((await opt.count()) > 0) {
          await opt.scrollIntoViewIfNeeded().catch(() => { });
          await humanClick(page, opt);
        } else {
          const optFallback = page.locator(`[role='option']:text-is('${exactText}')`).first();
          if ((await optFallback.count()) > 0) {
            await optFallback.scrollIntoViewIfNeeded().catch(() => { });
            await humanClick(page, optFallback);
          } else {
            await page.evaluate((val) => {
              const options = Array.from(document.querySelectorAll("[role='option']"));
              const match = options.find((o) => (o.innerText || "").trim() === String(val));
              if (match) match.click();
            }, exactText);
          }
        }
        await humanPause(80, 180);
        return true;
      }
      return false;
    }

    // Month
    const monthCombo = page.locator("[role='combobox']:has-text('Month')").first();
    const monthSelected = await selectComboboxOption(monthCombo, dobObj.month, "Month");
    if (!monthSelected) {
      const monthSelect = page.locator("select[title*='Month' i], select[aria-label*='Month' i]").first();
      if ((await monthSelect.count()) > 0 && (await monthSelect.isVisible())) {
        await monthSelect.selectOption({ label: dobObj.month }).catch(async () => {
          await monthSelect.selectOption({ value: String(dobObj.monthIndex) });
        });
      }
    }

    // Day
    await humanPause(80, 200);
    const dayCombo = page.locator("[role='combobox']:has-text('Day')").first();
    const daySelected = await selectComboboxOption(dayCombo, dobObj.dayStr, "Day");
    if (!daySelected) {
      const daySelect = page.locator("select[title*='Day' i], select[aria-label*='Day' i]").first();
      if ((await daySelect.count()) > 0 && (await daySelect.isVisible())) {
        await daySelect.selectOption({ label: dobObj.dayStr }).catch(async () => {
          await daySelect.selectOption({ value: String(dobObj.day) });
        });
      }
    }

    // Year
    await humanPause(80, 200);
    const yearCombo = page.locator("[role='combobox']:has-text('Year')").first();
    const yearSelected = await selectComboboxOption(yearCombo, String(dobObj.year), "Year");
    if (!yearSelected) {
      const yearSelect = page.locator("select[title*='Year' i], select[aria-label*='Year' i]").first();
      if ((await yearSelect.count()) > 0 && (await yearSelect.isVisible())) {
        await yearSelect.selectOption({ label: String(dobObj.year) }).catch(async () => {
          await yearSelect.selectOption({ value: String(dobObj.year) });
        });
      }
    }

    // Field 4: Full Name (second visible text input)
    await humanPause(100, 240);
    console.log(`[Instagram] Entering Full Name: "${fullName}"...`);
    let nameInput = page.locator("input[name='fullName'], input[aria-label*='Full name' i], input[placeholder*='Full name' i]").first();
    if ((await nameInput.count()) === 0 || !(await nameInput.isVisible())) {
      nameInput = textInputs.nth(1);
    }
    if ((await nameInput.count()) > 0 && (await nameInput.isVisible())) {
      riskField(await humanType(nameInput, fullName, "full_name"));
      await humanPause(100, 220);
    }

    // Field 5: Username
    console.log(`[Instagram] Entering Username: "${username}"...`);
    const userInput = page.locator("input[aria-label*='Username' i], input[placeholder*='Username' i], input[name='username'], input[type='search'], input[role='combobox']").first();
    if ((await userInput.count()) > 0 && (await userInput.isVisible())) {
      await userInput.click();
      await page.keyboard.press("Control+A");
      await page.keyboard.press("Backspace");
      await humanPause(40, 90);
      riskField(await humanType(userInput, username, "username"));
      await humanPause(120, 260);
    }

    // Clean focus blur before submit
    await page.evaluate(() => {
      if (document.activeElement && document.activeElement.blur) document.activeElement.blur();
    });
    await humanPause(150, 300);

    // 4. Click Submit / Sign Up Button
    console.log("[Instagram] Submitting registration form ('Submit' / 'Sign Up')...");
    const submitBtn = page.locator("div[role='button']:has-text('Submit'), [role='button']:has-text('Submit'), button:has-text('Submit'), button[type='submit'], button:has-text('Sign up'), button:has-text('Sign Up')").first();
    await submitBtn.waitFor({ state: "visible", timeout: 10000 });
    const formSubmitTime = Date.now();
    await humanClick(page, submitBtn);
    riskMark("form_submitted", {
      seconds_since_page_load: RISK && RISK.timing.page_loaded_at
        ? Math.round((Date.now() - new Date(RISK.timing.page_loaded_at).getTime()) / 1000)
        : null,
    });

    console.log("[Instagram] Form submitted. Waiting for OTP challenge screen (up to 150s)...");

    // 5. Handle OTP Challenge: Poll up to 150 seconds for the OTP screen to appear
    let foundOtpInput = false;
    const otpWaitStart = Date.now();
    const maxOtpScreenWaitMs = 150000; // 150 seconds per user requirement

    while (Date.now() - otpWaitStart < maxOtpScreenWaitMs) {
      if (await isOtpScreen(page)) {
        foundOtpInput = true;
        break;
      }

      // Check for inline form validation or rate-limit error messages
      const formError = await page.evaluate(() => {
        const errEl = document.querySelector("#ssfErrorAlert, [role='alert'], [data-testid='login-error-message'], .error-message");
        if (errEl && errEl.innerText && errEl.innerText.trim().length > 0) {
          return errEl.innerText.trim();
        }
        const alerts = Array.from(document.querySelectorAll("span, div, p")).filter((el) => {
          const txt = (el.innerText || "").trim();
          return /another account is using|username isn't available|enter a valid|try again later|something went wrong|wait a few minutes/i.test(txt);
        });
        if (alerts.length > 0) return alerts[0].innerText.trim();
        return null;
      }).catch(() => null);

      if (formError) {
        console.warn(`[Instagram Form Notice]: "${formError}"`);
      }

      const elapsedSec = Math.round((Date.now() - otpWaitStart) / 1000);
      if (elapsedSec > 0 && elapsedSec % 20 === 0) {
        console.log(`[Instagram] Waiting for OTP challenge screen (${elapsedSec}s / 150s elapsed)... URL: ${page.url()}`);
        // If submit button is still visible and not submitting, re-click gently
        const submitRetry = page.locator("button[type='submit']:visible, button:has-text('Sign up'):visible, button:has-text('Sign Up'):visible").first();
        if ((await submitRetry.count()) > 0 && (await submitRetry.isVisible())) {
          console.log("[Instagram] Submit button still visible on form. Re-clicking...");
          await humanClick(page, submitRetry).catch(() => {});
        }
      }

      await page.waitForTimeout(2000);
    }

    let otpData = null;
    let otpSubmitted = false;
    let otpVerified = false;
    if (foundOtpInput) {
      console.log("============================================================");
      console.log("[Instagram] >>> ENTER CONFIRMATION CODE SCREEN DETECTED! <<<");
      console.log("============================================================");

      if (clientId && refreshToken) {
        // Poll for up to 60s first
        otpData = await pollOutlookForInstagramOtp(clientId, refreshToken, formSubmitTime, 60);

        // If not received yet, try clicking "I didn't get the code" to trigger resend
        if (!otpData) {
          const resendBtn = page.locator("button:has-text(\"I didn't get the code\"), div[role='button']:has-text(\"I didn't get the code\"), [role='button']:has-text(\"I didn't get the code\")").first();
          if ((await resendBtn.count()) > 0 && (await resendBtn.isVisible())) {
            console.log("[Instagram] Clicking 'I didn't get the code' to check for resend options...");
            await humanClick(page, resendBtn).catch(() => {});
            await page.waitForTimeout(2000);
            const resendConfirm = page.locator("button:has-text('Resend confirmation code'), button:has-text('Resend code'), div[role='button']:has-text('Resend')").first();
            if ((await resendConfirm.count()) > 0 && (await resendConfirm.isVisible())) {
              console.log("[Instagram] Clicking 'Resend confirmation code'...");
              await humanClick(page, resendConfirm).catch(() => {});
              await page.waitForTimeout(2000);
            }
          }
          // Poll again for another 60s
          otpData = await pollOutlookForInstagramOtp(clientId, refreshToken, formSubmitTime, 60);
        }
      }

      if (otpData && otpData.otp) {
        console.log(`[Instagram] >>> ENTERING RETRIEVED OTP (hidden) <<<`);
        const codeInput = page.locator(
          "input[autocomplete='one-time-code'], input[aria-label*='code' i], input[placeholder*='code' i], input[name*='code' i], input[maxlength='6']"
        ).first();
        let targetInput = codeInput;
        if ((await targetInput.count()) === 0 || !(await targetInput.isVisible().catch(() => false))) {
          targetInput = page.locator("input[type='text']:visible").last();
        }
        await targetInput.waitFor({ state: "visible", timeout: 8000 });
        await humanPause(80, 180);
        await humanClick(page, targetInput);
        await targetInput.fill("");
        await typeJittered(targetInput, otpData.otp, 35, 12);
        await page.waitForTimeout(200);

        console.log("[Instagram] Submitting OTP ('Continue' / 'Confirm')...");
        const confirmBtn = page.locator("button:has-text('Continue'), div[role='button']:has-text('Continue'), [role='button']:has-text('Continue'), button:has-text('Next'), button:has-text('Confirm'), button[type='submit']").first();
        if ((await confirmBtn.count()) > 0 && (await confirmBtn.isVisible())) {
          await humanClick(page, confirmBtn);
        } else {
          await page.keyboard.press("Enter");
        }

        otpSubmitted = true;
        riskMark("otp_submitted");
        console.log("[Instagram] OTP submitted. Waiting 12s for account finalization...");
        await page.waitForTimeout(12000);

        const postText = (await page.evaluate(() => (document.body ? document.body.innerText : "")).catch(() => "")).toLowerCase();
        const otpError = /(incorrect|wrong code|invalid code|try again|couldn['’]t confirm|code (?:has )?expired)/i.test(postText);
        const stillOnOtp = await isOtpScreen(page);
        otpVerified = !otpError && !stillOnOtp;
        riskEvent("otp_verification", { otp_submitted: otpSubmitted, otp_verified: otpVerified, error_detected: otpError });
        console.log(`[Instagram] OTP verification: ${otpVerified ? "CONFIRMED" : "NOT CONFIRMED"}${otpError ? " (error message detected)" : ""}`);
      } else {
        console.warn("[Instagram] Could not automatically retrieve OTP from Outlook. Browser will remain open for manual entry.");
      }
    } else {
      console.log(`[Instagram] No OTP challenge detected after 150s. Current URL: ${page.url()}`);
    }

    // STRICT GUARD: If OTP was NOT verified, do NOT pretend the account exists or run feed warmup!
    if (!otpVerified) {
      console.warn("=".repeat(65));
      console.warn("[Instagram Warning]: OTP was NOT confirmed. Account is not yet created!");
      console.warn(`Current URL: ${page.url()}`);
      console.warn("Holding browser open for 150 seconds for manual inspection or code entry...");
      console.warn("Do NOT close the window yet. Enter the OTP code if visible.");
      console.warn("=".repeat(65));

      const manualHoldEnd = Date.now() + 150000;
      while (Date.now() < manualHoldEnd) {
        const curUrl = page.url();
        // Check if user manually verified or if Instagram navigated away from signup
        if (!curUrl.includes("emailsignup") && !curUrl.includes("challenge") && curUrl.includes("instagram.com")) {
          console.log(`[Instagram] Progression detected! Current URL: ${curUrl}`);
          otpVerified = true;
          break;
        }
        await page.waitForTimeout(3000);
      }

      if (!otpVerified) {
        console.error("[Instagram] Registration was not completed within 150s window. Aborting post-signup steps.");
        return;
      }
    }

    await captureExitIp(page, "post_otp");

    // 6. Save Registered Account Record
    saveInstagramAccount({
      email,
      password: password,
      username,
      full_name: fullName,
      first_name: firstName,
      last_name: lastName,
      date_of_birth: dobObj.formatted,
      proxy_used: effectiveProxy,
      proxy_ip: proxyLocation.ip,
      proxy_location: {
        city: proxyLocation.city,
        region: proxyLocation.region,
        country: proxyLocation.country,
        timezone: proxyLocation.timezone,
      },
      instagram_url: `https://www.instagram.com/${username}/`,
      full_hotmail_thread: otpData && otpData.thread ? otpData.thread : null,
      account_created_at: new Date().toISOString(),
      otp_submitted: otpSubmitted,
      otp_verified: otpVerified,
      status: otpVerified ? "CONFIRMED" : (otpSubmitted ? "PENDING_OTP" : "NEEDS_OTP"),
      email_domain: RISK && RISK.email_identity ? RISK.email_identity.domain : null,
      email_pattern: RISK && RISK.email_identity ? RISK.email_identity.local_part_pattern : null,
      name_source: nameSource,
      username_pattern: usernamePattern,
      proxy_session: RISK && RISK.proxy ? RISK.proxy.session : null,
      proxy_asn: RISK && RISK.proxy ? RISK.proxy.asn : null,
      proxy_username_hash: RISK && RISK.proxy ? RISK.proxy.username_hash : null,
      fingerprint_hash: RISK && RISK.fingerprint ? RISK.fingerprint.hash : null,
      risk_log: path.relative(process.cwd(), path.join(profileDir, "risk_log.json")),
      risk_warnings: RISK ? RISK.warnings : [],
    });
    riskMark("account_saved");

    // Step 2a: Dismiss Post-Registration Modals ("Save info" / "Not Now" / "Turn on Notifications")
    try {
      await handlePostSignupModals(page, 18000);
    } catch (e) {
      console.warn(`[Instagram Onboarding] Note handling modals: ${e.message}`);
    }

    // Step 2b: Stimulate the Feed Naturally
    console.log("[Instagram] Stimulating natural human feed browsing on Home feed...");
    try {
      await warmUpInstagramFeed(page, 25);
    } catch (e) { }

    // Step 2c: Profile Setup / DP Upload
    // Per user instruction: Strictly DO NOT upload DP right now. Keep fresh account organic.
    const uploadDp = hasFlag("--upload-dp");
    if (uploadDp) {
      riskMark("profile_setup_started");
      await captureExitIp(page, "before_profile_edit");
      try {
        await setupInstagramProfile(page, username, null, email);
      } catch (err) {
        console.warn(`[Instagram Step 2] Note during profile setup: ${err.message}`);
      }
    } else {
      console.log("[Instagram Step 2] Profile picture upload strictly SKIPPED as requested (organic uncustomized state).");
    }

    // Step 3: Handle Two-Factor Authentication (TOTP App) Setup via Meta Accounts Center
    if (!skip2fa) {
      try {
        riskMark("twofa_started");
        await captureExitIp(page, "before_2fa");
        console.log("[Instagram] Proceeding to automated 2FA setup in Meta Accounts Center...");
        const twoFaResult = await setupInstagram2FA(page, email, clientId, refreshToken);
        riskEvent("2fa_result", { success: Boolean(twoFaResult.success), status: twoFaResult.status || null });
        if (!twoFaResult.success) {
          console.error(`[Instagram] WARNING: 2FA was NOT confirmed (${twoFaResult.status}): ${twoFaResult.error || "unknown reason"}. Treat this account as unprotected and retry.`);
        }
      } catch (err) {
        riskEvent("2fa_error", { message: err.message });
        console.warn(`[Instagram Step 3] Note during 2FA setup: ${err.message}`);
      }
    } else {
      console.log("[Instagram] Immediate 2FA setup skipped (--skip-2fa active). Recommended for new accounts to cool down first.");
    }

    riskMark("finished");
    await captureExitIp(page, "final");

    // Capture screenshot of the live home feed
    await page.screenshot({ path: "tests/test_artifacts/ig_latest_live.png", fullPage: true }).catch(() => {});

    // Keep browser window open for user inspection
    console.log("[Instagram] >>> SESSION IS LIVE ON YOUR SCREEN <<<");
    console.log("[Instagram] Browser will remain open. Close the browser window when you are done.");
    await new Promise((resolve) => browser.on("close", resolve));

  } finally {
    saveRiskLog();
    console.log("[Instagram] Script finished.");
  }
}

run().catch((err) => {
  console.error(`[Instagram Error]: ${err.stack || err}`);
  process.exit(1);
});
