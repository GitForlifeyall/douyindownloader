#!/usr/bin/env node
/**
 * tools/setup_instagram_2fa.mjs
 * ==============================
 * Automated Instagram Two-Factor Authentication (TOTP Authenticator App) Setup
 * via Meta Accounts Center (https://accountscenter.instagram.com/password_and_security/?hl=en).
 *
 * State-Driven Robust Flow:
 * 1. Navigate to https://accountscenter.instagram.com/password_and_security/two_factor/?hl=en
 * 2. State 1 (Get started): Click "Get started" modal button
 * 3. State 2 (Email challenge): Poll Outlook REST API for 6-8 digit security code -> Type -> Click "Continue"
 * 4. State 3 (Choose method): Ensure "Authentication app" is selected -> Click "Continue"
 * 5. State 4 (Instructions): Extract Base32 TOTP secret key -> Click visible "Enter code" button
 * 6. State 5 (TOTP entry): Generate standard RFC 6238 6-digit TOTP code -> Type -> Click "Next"
 * 7. State 6 (Confirmation): Detect "Your two-factor authentication is set up" -> Save secret key & backup codes -> Click "Done"
 */

import fs from "node:fs";
import path from "node:path";
import crypto from "node:crypto";
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

// Same full-fingerprint persistence as the signup script, so standalone 2FA runs
// reuse the account's frozen device identity instead of generating a new one.
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

// Node's fetch has no default timeout; bound every OAuth/Graph call so a dead
// proxy or stuck endpoint cannot wedge the 2FA flow indefinitely.
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

// Default Proxy (Oxylabs Mobile Proxy)
const DEFAULT_PROXY = "customer-mobile_83bd2e52:DPD~dmUeZ1~p@pr.oxylabs.io:7777";
let proxyArg = getArg("--proxy");

const explicitAccount = getArg("--account");
const explicitEmail = getArg("--email");

let email = explicitEmail || (explicitAccount ? explicitAccount.split("|")[0] : "NevaehCaronia10625@outlook.in");
let refreshToken = getArg("--refresh-token") || getArg("--token");
let clientId = getArg("--client-id", "9e5f94bc-e8a4-4e73-b8be-63364c29d753");

if (explicitAccount) {
  const parts = explicitAccount.split("|");
  email = (parts[0] || "").trim();
  if (parts.length >= 4) {
    refreshToken = (parts[2] || "").trim();
    let rawCId = (parts[3] || "").trim().replace(/["']/g, "");
    if (rawCId.startsWith("9e5f94bc") && rawCId.length === 35) {
      rawCId = "9e5f94bc-e8a4-4e73-b8be-63364c29d753";
    }
    clientId = rawCId || clientId;
  }
}

// Auto-fallback: check if account_info.json exists in profile directory
if (email) {
  const profileName = email.split("@")[0].replace(/[^A-Za-z0-9._-]/g, "");
  const infoPath = path.resolve("output", "profiles instagram", profileName, "account_info.json");
  if (fs.existsSync(infoPath)) {
    try {
      const info = JSON.parse(fs.readFileSync(infoPath, "utf-8"));
      refreshToken = info.refresh_token || refreshToken;
      clientId = info.client_id || clientId;
      if (!proxyArg && info.proxy_used) {
        proxyArg = info.proxy_used;
      }
      console.log(`[Instagram 2FA] Loaded Outlook OAuth tokens & proxy automatically from: ${infoPath}`);
    } catch (e) { }
  }

  // Older profiles may not have account_info.json; reuse the proxy recorded in
  // the master registry so 2FA does not run from a different exit IP than signup.
  if (!proxyArg) {
    const registryPath = path.resolve("output", "instagram_registered_accounts.json");
    if (fs.existsSync(registryPath)) {
      try {
        const list = JSON.parse(fs.readFileSync(registryPath, "utf-8"));
        if (Array.isArray(list)) {
          const record = list.find((a) => (a && a.email ? a.email : "").toLowerCase() === email.toLowerCase());
          if (record && typeof record.proxy_used === "string" && record.proxy_used.trim()) {
            proxyArg = record.proxy_used.trim();
            console.log("[Instagram 2FA] Reusing the signup proxy from the account registry.");
          }
        }
      } catch (e) { }
    }
  }
}
if (!proxyArg) {
  proxyArg = DEFAULT_PROXY;
  console.warn("[Instagram 2FA] WARNING: no saved proxy found for this account; using the shared default. This can link accounts and trigger a checkpoint.");
}

// ----------------------------------------------------
// Base32 & TOTP Generator (RFC 6238 Standard)
// ----------------------------------------------------
export function base32Decode(str) {
  const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";
  let clean = str.replace(/[\s=-]/g, "").toUpperCase();
  let bits = "";
  for (let i = 0; i < clean.length; i++) {
    const val = alphabet.indexOf(clean.charAt(i));
    if (val === -1) continue;
    bits += val.toString(2).padStart(5, "0");
  }
  const bytes = [];
  for (let i = 0; i + 8 <= bits.length; i += 8) {
    bytes.push(parseInt(bits.substr(i, 8), 2));
  }
  return Buffer.from(bytes);
}

export function generateTOTP(secretKey, step = 30) {
  const key = base32Decode(secretKey);
  const epoch = Math.floor(Date.now() / 1000);
  const counter = Math.floor(epoch / step);
  const buf = Buffer.alloc(8);
  buf.writeBigInt64BE(BigInt(counter));

  const hmac = crypto.createHmac("sha1", key);
  hmac.update(buf);
  const digest = hmac.digest();

  const offset = digest[digest.length - 1] & 0x0f;
  const code = (
    ((digest[offset] & 0x7f) << 24) |
    ((digest[offset + 1] & 0xff) << 16) |
    ((digest[offset + 2] & 0xff) << 8) |
    (digest[offset + 3] & 0xff)
  ) % 1000000;

  return code.toString().padStart(6, "0");
}

// Typing with a Gaussian per-key delay. A fixed 90-100ms delay is itself a
// timing signature, so vary it per character.
function keyDelay(mean = 38, stdDev = 12) {
  let u = 0;
  let v = 0;
  while (u === 0) u = Math.random();
  while (v === 0) v = Math.random();
  const z = Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v);
  return Math.max(16, Math.min(85, Math.round(mean + z * stdDev)));
}

async function typeJittered(locator, text, mean = 38, stdDev = 12) {
  for (const char of String(text)) {
    await locator.pressSequentially(char);
    await new Promise((resolve) => setTimeout(resolve, keyDelay(mean, stdDev)));
  }
}

// ----------------------------------------------------
// Outlook REST API Integration for 2FA Email Code
// ----------------------------------------------------
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

export async function pollOutlookFor2FAEmailOtp(cId, rToken, startTimeMs, maxWaitSeconds = 90) {
  console.log(`[Outlook OTP] Polling Microsoft Graph & Outlook REST API for Meta security code (timeout: ${maxWaitSeconds}s)...`);
  const startTime = Date.now();
  // Allow codes received within the last 15 minutes (Meta reuse window)
  const minTime = (startTimeMs || startTime) - 15 * 60 * 1000;

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
              if (receivedDate < minTime) continue;

              const subject = msg.subject || msg.Subject || "";
              const from = (msg.from?.emailAddress?.address || msg.From?.EmailAddress?.Address || "").toLowerCase();
              const preview = msg.bodyPreview || msg.BodyPreview || "";
              const fullContent = msg.body?.content || msg.Body?.Content || "";

              const isMetaSecurity =
                from.includes("account.meta.com") ||
                from.includes("instagram") ||
                from.includes("meta") ||
                from.includes("facebook") ||
                subject.toLowerCase().includes("authenticate") ||
                subject.toLowerCase().includes("security") ||
                subject.toLowerCase().includes("code") ||
                preview.toLowerCase().includes("code") ||
                preview.toLowerCase().includes("identity");

              if (isMetaSecurity) {
                const text = `${subject} ${preview} ${fullContent}`;
                const matchCode = text.match(/(?:code|identity|is|is:)\s*[:\s]*(\d{6,8})\b/i) || text.match(/\b(\d{6,8})\b/);
                if (matchCode) {
                  const code = matchCode[1];
                  console.log(`[Outlook OTP] Found Meta 2FA Code: >>> ${code} <<< (Received: ${rawDate})`);
                  return code;
                }
              }
            }
          }
        }
        if (groupSuccess) break;
      }
    } catch (err) {
      console.warn(`[Outlook OTP] Polling note: ${err.message}`);
    }

    const elapsed = Math.round((Date.now() - startTime) / 1000);
    console.log(`[Outlook OTP] Waiting 4s for security code to arrive... (${elapsed}s elapsed)`);
    await new Promise((r) => setTimeout(r, 4000));
  }

  return null;
}

// ----------------------------------------------------
// Proxy & Helper Utilities
// ----------------------------------------------------
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

async function safeGoto(page, url, options = { waitUntil: "domcontentloaded", timeout: 45000 }, maxRetries = 3) {
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

export function updateAccountWith2FA(emailTarget, twoFactorData) {
  const profileName = emailTarget.split("@")[0].replace(/[^A-Za-z0-9._-]/g, "");
  const accountsFile = path.resolve("output", "instagram_registered_accounts.json");
  const masterBackupFile = path.resolve("output", "instagram_backup_codes.json");
  const profileDir = path.resolve("output", "profiles instagram", profileName);

  const incomingSecret = twoFactorData.secret_key || null;
  const incomingCodes = Array.isArray(twoFactorData.backup_codes) ? twoFactorData.backup_codes : [];
  const enabled = twoFactorData.enabled === true;
  const status = twoFactorData.status || (enabled ? "ACTIVE" : "PENDING");

  // 1. Update master accounts database
  if (fs.existsSync(accountsFile)) {
    try {
      const list = JSON.parse(fs.readFileSync(accountsFile, "utf-8"));
      const idx = list.findIndex((a) => (a.email || "").toLowerCase() === emailTarget.toLowerCase());
      if (idx >= 0) {
        const existing = (list[idx].two_factor && typeof list[idx].two_factor === "object") ? list[idx].two_factor : {};
        const existingCodes = Array.isArray(existing.backup_codes) ? existing.backup_codes : [];
        const backupCodes = incomingCodes.length > 0 ? incomingCodes : existingCodes;
        list[idx].two_factor = {
          enabled: enabled || existing.enabled === true,
          status,
          method: "TOTP_AUTHENTICATOR_APP",
          secret_key: incomingSecret || existing.secret_key || null,
          backup_codes: backupCodes,
          backup_codes_saved: backupCodes.length > 0,
          configured_at: enabled ? new Date().toISOString() : (existing.configured_at || null),
          last_attempt_at: new Date().toISOString(),
        };
        fs.writeFileSync(accountsFile, JSON.stringify(list, null, 2), "utf-8");
        console.log(`[Database] Saved 2FA state (enabled=${list[idx].two_factor.enabled}, status=${status}) to ${accountsFile}`);
      } else {
        console.warn(`[Database] Account ${emailTarget} not found in ${accountsFile}; updating the backup registry only.`);
      }
    } catch (err) {
      console.warn(`[Database] Error updating 2FA in accounts file: ${err.message}`);
    }
  }

  // 2. Save dedicated backup_codes.txt in profile directory if codes are available
  if (incomingCodes.length > 0) {
    try {
      fs.mkdirSync(profileDir, { recursive: true });
      const txtPath = path.join(profileDir, "backup_codes.txt");
      const content = [
        `INSTAGRAM BACKUP CODES FOR: ${emailTarget}`,
        `Status: ${status}`,
        `Configured At: ${new Date().toISOString()}`,
        `TOTP Secret Key: ${incomingSecret || "N/A"}`,
        "",
        "BACKUP CODES (8 digits each):",
        ...incomingCodes.map((code, idx) => `  [${idx + 1}] ${code}`),
        "",
        "Note: Each backup code can only be used once if you lose access to your authenticator app.",
      ].join("\n");
      fs.writeFileSync(txtPath, content, "utf-8");
      console.log(`[Database] Saved backup codes text file to: ${txtPath}`);
    } catch (err) {
      console.warn(`[Database] Note saving profile backup_codes.txt: ${err.message}`);
    }
  }

  // 3. Update master backup codes registry
  try {
    let masterVault = {};
    if (fs.existsSync(masterBackupFile)) {
      try { masterVault = JSON.parse(fs.readFileSync(masterBackupFile, "utf-8")); } catch (e) { }
    }
    const existing = (masterVault[emailTarget] && typeof masterVault[emailTarget] === "object") ? masterVault[emailTarget] : {};
    const existingCodes = Array.isArray(existing.backup_codes) ? existing.backup_codes : [];
    const backupCodes = incomingCodes.length > 0 ? incomingCodes : existingCodes;
    masterVault[emailTarget] = {
      username: profileName,
      enabled: enabled || existing.enabled === true,
      status,
      secret_key: incomingSecret || existing.secret_key || null,
      backup_codes: backupCodes,
      backup_codes_saved: backupCodes.length > 0,
      updated_at: new Date().toISOString(),
    };
    fs.writeFileSync(masterBackupFile, JSON.stringify(masterVault, null, 2), "utf-8");
    console.log(`[Database] Updated master backup registry: ${masterBackupFile}`);
  } catch (err) { }
}

// Helper to get the truly active foreground dialog (ignoring background loading overlays)
async function getActiveDialog(page) {
  const dialogs = await page.locator("[role='dialog']:visible").all();
  if (dialogs.length === 0) return null;
  // If multiple, prioritize the one not marked aria-hidden and having non-loading text
  for (let i = dialogs.length - 1; i >= 0; i--) {
    const d = dialogs[i];
    const isAriaHidden = await d.getAttribute("aria-hidden");
    const childHidden = await d.locator("> div").first().getAttribute("aria-hidden").catch(() => null);
    const txt = (await d.innerText()).trim();
    if (isAriaHidden !== "true" && childHidden !== "true" && txt !== "Loading...") {
      return d;
    }
  }
  return dialogs[dialogs.length - 1];
}

// Dedicated fallback pass to ensure Backup Codes are retrieved
function extractBackupCodesFromText(text) {
  // Meta renders codes either as "1234 5678" or as an 8-digit run.
  const matches = text.match(/\b(?:\d{4}\s+\d{4}|\d{8})\b/g) || [];
  return [...new Set(matches.map((code) => code.replace(/\s+/g, "")))];
}

async function extractBackupCodesPass(page, maxTries = 8) {
  for (let t = 1; t <= maxTries; t++) {
    await page.waitForTimeout(2000);
    const bodyText = (await page.locator("body").innerText().catch(() => "")).replace(/\s+/g, " ");

    // 1. Check if backup codes are currently displayed on page or in modal
    if (bodyText.includes("Download codes") || bodyText.includes("Get new codes") || bodyText.includes("Save your backup codes")) {
      const codes = extractBackupCodesFromText(bodyText);
      if (codes.length > 0) {
        console.log(`[Instagram 2FA] Extracted ${codes.length} Backup Codes (values hidden).`);
        const closeBtn = page.locator("div[role='button'][aria-label='Close'], div[role='button']:has-text('Close')").first();
        if ((await closeBtn.count()) > 0 && (await closeBtn.isVisible())) {
          await closeBtn.click().catch(() => {});
        }
        return codes;
      }
    }

    // 2. Check for "Backup codes" button
    const backupBtn = page.locator("div[role='button']:visible:has-text('Backup codes')").first();
    if ((await backupBtn.count()) > 0 && (await backupBtn.isVisible())) {
      console.log("[Instagram 2FA] Clicking 'Backup codes' navigation button...");
      await backupBtn.click().catch(() => {});
      await page.waitForTimeout(3000);
      continue;
    }

    // 3. Check for "Manage authentication" button
    const manageBtn = page.locator("div[role='button']:visible:has-text('Manage authentication'), button:visible:has-text('Manage authentication')").first();
    if ((await manageBtn.count()) > 0 && (await manageBtn.isVisible())) {
      console.log("[Instagram 2FA] Clicking 'Manage authentication' button...");
      await manageBtn.click().catch(() => {});
      await page.waitForTimeout(3000);
      continue;
    }

    // 4. Check for account profile item in 2FA list
    const profileItem = page.locator("div[role='listitem'] div[role='button']").first();
    if ((await profileItem.count()) > 0 && (await profileItem.isVisible())) {
      console.log("[Instagram 2FA] Clicking account profile item in 2FA list...");
      await profileItem.click().catch(() => {});
      await page.waitForTimeout(3000);
      continue;
    }

    // 5. If still not found by attempt 3, re-navigate to 2FA page directly
    if (t === 3) {
      console.log("[Instagram 2FA] Re-navigating to 2FA page directly...");
      await safeGoto(page, "https://accountscenter.instagram.com/password_and_security/two_factor/?hl=en").catch(() => {});
      await page.waitForTimeout(4000);
    }
  }
  return [];
}

// ----------------------------------------------------
// Core 2FA Setup Routine
// ----------------------------------------------------
export async function setupInstagram2FA(page, emailTarget, cId, rToken) {
  console.log("=".repeat(60));
  console.log(`[Instagram 2FA] Starting Two-Factor Authentication Setup for: ${emailTarget}`);
  console.log("=".repeat(60));

  const twoFaUrl = "https://accountscenter.instagram.com/password_and_security/two_factor/?hl=en";
  let reached2fa = false;

  // 1. Organic in-app UI navigation to 2FA via Options -> Accounts Center -> Password and security
  try {
    console.log("[Instagram 2FA] Starting organic in-app navigation to Two-Factor Authentication...");

    // Check if we are on profile or need to click profile avatar first
    const optionsSelector = "a[href*='/accounts/settings'], a:has(svg[aria-label='Options']), [aria-label='Options'], svg[aria-label='Options']";
    let optionsBtn = page.locator(optionsSelector).first();

    if ((await optionsBtn.count()) === 0 || !(await optionsBtn.isVisible())) {
      const profileNav = page.locator("a:has(img[alt*='profile picture']), [aria-label*='Profile']").first();
      if ((await profileNav.count()) > 0 && (await profileNav.isVisible())) {
        console.log("[Instagram 2FA] Clicking Profile navigation icon to reach profile...");
        await profileNav.click().catch(() => {});
        await page.waitForTimeout(3000);
      }
    }

    // Step A: Click Options (gear) icon
    optionsBtn = page.locator(optionsSelector).first();
    if ((await optionsBtn.count()) > 0 && (await optionsBtn.isVisible())) {
      console.log("[Instagram 2FA] Step A: Clicking Options (gear) icon...");
      await optionsBtn.hover().catch(() => {});
      await page.waitForTimeout(300);
      await optionsBtn.click().catch(() => {});
      await page.waitForTimeout(3500);
    }

    // Step B: Click 'Accounts Center' card in Settings
    const acSelector = "a[href*='accountscenter.instagram.com'], a:has-text('Accounts Center'), div:has-text('Accounts Center'):has-text('Password, security')";
    let acBtn = page.locator(acSelector).first();
    for (let i = 0; i < 4; i++) {
      if ((await acBtn.count()) > 0 && (await acBtn.isVisible())) {
        console.log("[Instagram 2FA] Step B: Clicking 'Accounts Center' card...");
        await acBtn.hover().catch(() => {});
        await page.waitForTimeout(300);
        await acBtn.click().catch(() => {});
        await page.waitForTimeout(4000);
        break;
      }
      await page.waitForTimeout(1000);
    }

    // Step C: Click 'Password and security' in Accounts Center
    const pwSecSelector = "div:has-text('Password and security'), a:has-text('Password and security'), span:text-is('Password and security')";
    let pwSecBtn = page.locator(pwSecSelector).last();
    for (let i = 0; i < 4; i++) {
      if ((await pwSecBtn.count()) > 0 && (await pwSecBtn.isVisible())) {
        console.log("[Instagram 2FA] Step C: Clicking 'Password and security'...");
        await pwSecBtn.hover().catch(() => {});
        await page.waitForTimeout(300);
        await pwSecBtn.click().catch(() => {});
        await page.waitForTimeout(3500);
        break;
      }
      await page.waitForTimeout(1000);
    }

    // Step D: Click 'Two-factor authentication'
    const twoFaBtnSelector = "div[role='button']:has-text('Two-factor authentication'), div:has-text('Two-factor authentication'), a:has-text('Two-factor authentication')";
    let twoFaBtn = page.locator(twoFaBtnSelector).first();
    for (let i = 0; i < 4; i++) {
      if ((await twoFaBtn.count()) > 0 && (await twoFaBtn.isVisible())) {
        console.log("[Instagram 2FA] Step D: Clicking 'Two-factor authentication'...");
        await twoFaBtn.hover().catch(() => {});
        await page.waitForTimeout(300);
        await twoFaBtn.click().catch(() => {});
        await page.waitForTimeout(3500);
        break;
      }
      await page.waitForTimeout(1000);
    }

    // Step E: Select account from list if presented
    const profileItem = page.locator("div[role='listitem'] div[role='button']").first();
    if ((await profileItem.count()) > 0 && (await profileItem.isVisible())) {
      console.log("[Instagram 2FA] Step E: Selecting account profile from list...");
      await profileItem.click().catch(() => {});
      await page.waitForTimeout(3000);
    }

    if (page.url().includes("two_factor") || (await getActiveDialog(page)) !== null) {
      console.log("[Instagram 2FA] Successfully reached 2FA screen via organic UI navigation!");
      reached2fa = true;
    }
  } catch (err) {
    console.warn(`[Instagram 2FA] Note during organic UI navigation: ${err.message}`);
  }

  // Graceful fallback to direct URL if organic navigation did not reach 2FA
  if (!reached2fa && !page.url().includes("two_factor")) {
    console.log(`[Instagram 2FA] Fallback: Navigating directly to ${twoFaUrl}...`);
    await safeGoto(page, twoFaUrl, { waitUntil: "domcontentloaded", timeout: 45000 });
    await page.waitForTimeout(4000);
  }

  let secretKey = null;
  let backupCodes = [];
  let isDone = false;
  let secretPersisted = false;
  let totpSubmitted = false;
  let confirmedOn = false;

  const maxLoops = 35;
  for (let loop = 1; loop <= maxLoops && !isDone; loop++) {
    console.log(`--- [2FA Flow Loop ${loop}/${maxLoops}] Inspecting current dialog screen ---`);
    await page.waitForTimeout(1500);

    const dialog = await getActiveDialog(page);
    if (!dialog) {
      console.log("[Instagram 2FA] No modal dialog visible. Checking page elements...");
      // Check if backup codes are visible on the page
      const bodyText = (await page.locator("body").innerText().catch(() => "")).replace(/\s+/g, " ");
      if (bodyText.includes("Download codes") || bodyText.includes("Get new codes") || bodyText.includes("Save your backup codes")) {
        const codes = extractBackupCodesFromText(bodyText);
        if (codes.length > 0) {
          backupCodes = codes;
          confirmedOn = true; // codes are only shown after 2FA is active
          console.log(`[Instagram 2FA] Extracted ${backupCodes.length} Backup Codes (values hidden).`);
          isDone = true;
          break;
        }
      }

      // Check if Backup codes navigation button is on page
      const backupBtn = page.locator("div[role='button']:visible:has-text('Backup codes')").first();
      if ((await backupBtn.count()) > 0 && (await backupBtn.isVisible())) {
        console.log("[Instagram 2FA] Clicking 'Backup codes' button on page...");
        await backupBtn.click().catch(() => {});
        await page.waitForTimeout(3000);
        continue;
      }

      // Check if Manage authentication is on page
      const manageBtn = page.locator("div[role='button']:visible:has-text('Manage authentication'), button:visible:has-text('Manage authentication')").first();
      if ((await manageBtn.count()) > 0 && (await manageBtn.isVisible())) {
        console.log("[Instagram 2FA] Clicking 'Manage authentication' button on page...");
        await manageBtn.click().catch(() => {});
        await page.waitForTimeout(3000);
        continue;
      }

      // Check if Two-factor authentication button on main page
      const start2faBtn = page.locator("div[role='listitem'] div[role='button']:has-text('Two-factor authentication'), div[role='button']:has-text('Two-factor authentication')").first();
      if ((await start2faBtn.count()) > 0 && (await start2faBtn.isVisible())) {
        console.log("[Instagram 2FA] Clicking 'Two-factor authentication' button on main page...");
        await start2faBtn.click().catch(() => {});
        await page.waitForTimeout(3000);
        continue;
      }

      // If transitioning, wait and continue - NEVER prematurely break!
      await page.waitForTimeout(2000);
      continue;
    }

    const dText = (await dialog.innerText()).replace(/\s+/g, " ");
    console.log(`[Instagram 2FA] Active Dialog Text: "${dText.slice(0, 140)}..."`);

    if (dText.includes("Two-factor authentication is on")
      || dText.includes("Your two-factor authentication is set up")
      || dText.includes("How you get login codes")) {
      confirmedOn = true;
    }

    // Screen 8: "Backup codes" modal -> Extract codes immediately if open
    if (dText.includes("Download codes") || dText.includes("Get new codes") || dText.includes("Save your backup codes")) {
      console.log("[Instagram 2FA - State 8] Backup codes modal opened! Extracting backup codes...");
      const codes = extractBackupCodesFromText(dText);
      if (codes.length > 0) {
        backupCodes = codes;
        confirmedOn = true; // codes are only shown after 2FA is active
        console.log(`[Instagram 2FA] Extracted ${backupCodes.length} Backup Codes (values hidden).`);
      } else {
        console.warn("[Instagram 2FA] Backup codes screen is open but no codes matched; continuing to look for the actual list...");
      }

      // Close modal cleanly via X button
      const closeBtn = dialog.locator("div[role='button'][aria-label='Close'], div[role='button']:has-text('Close')").first();
      if ((await closeBtn.count()) > 0 && (await closeBtn.isVisible())) {
        await closeBtn.click().catch(() => {});
        await page.waitForTimeout(2000);
      }

      if (backupCodes.length > 0) {
        isDone = true;
        break;
      }
      continue;
    }

    // Screen 6: "Your two-factor authentication is set up" -> Click "Manage authentication"
    if (dText.includes("Your two-factor authentication is set up") || dText.includes("Manage authentication")) {
      confirmedOn = true;
      console.log("[Instagram 2FA - State 6] 2FA set up screen detected. Clicking 'Manage authentication'...");
      const manageBtn = page.locator("div[role='button']:visible:has-text('Manage authentication'), button:visible:has-text('Manage authentication')").first();
      if ((await manageBtn.count()) > 0 && (await manageBtn.isVisible())) {
        await humanClick(page, manageBtn);
        await page.waitForTimeout(4000);
        continue;
      }
    }

    // Screen 7: "Two-factor authentication is on" -> Click "Backup codes"
    if (dText.includes("Two-factor authentication is on") || dText.includes("How you get login codes")) {
      confirmedOn = true;
      console.log("[Instagram 2FA - State 7] 'Two-factor authentication is on' screen detected. Opening 'Backup codes'...");
      const backupBtn = page.locator("div[role='button']:visible:has-text('Backup codes')").first();
      if ((await backupBtn.count()) > 0 && (await backupBtn.isVisible())) {
        await humanClick(page, backupBtn);
        await page.waitForTimeout(4000);
        continue;
      }
    }

    // Screen 1: "Set up extra protection for your Meta Account"
    if (dText.includes("Set up extra protection") || (dText.includes("Get started") && !dText.includes("Check your email"))) {
      console.log("[Instagram 2FA - State 1] Found 'Get started' screen. Clicking...");
      const getStartedBtn = dialog.locator("div[role='button']:visible:has-text('Get started'), button:visible:has-text('Get started')").first();
      await humanClick(page, getStartedBtn);
      console.log("[Instagram 2FA - State 1] Clicked 'Get started'. Waiting for next screen...");
      await page.waitForTimeout(4000);
      continue;
    }

    // Screen 2: "Check your email" (Email OTP verification)
    if (dText.includes("Check your email") || dText.includes("Enter the code we sent") || dText.includes("send a new code")) {
      console.log("[Instagram 2FA - State 2] Found 'Check your email' screen. Retrieving email security code...");
      const textInput = dialog.locator("input[type='text']:visible, input:visible:not([type='submit']):not([type='radio']):not([type='checkbox'])").first();
      await textInput.waitFor({ state: "visible", timeout: 20000 });

      const emailCode = await pollOutlookFor2FAEmailOtp(cId, rToken, Date.now() - 10 * 60 * 1000, 90);
      if (!emailCode) throw new Error("Could not retrieve email code from Outlook");

      console.log(`[Instagram 2FA] Typing email verification code: ${emailCode}...`);
      await humanClick(page, textInput);
      await textInput.fill("");
      await typeJittered(textInput, emailCode, 90, 20);
      await page.waitForTimeout(800);

      const continueBtn = dialog.locator("div[role='button']:visible:has-text('Continue'), button:visible:has-text('Continue')").first();
      console.log("[Instagram 2FA] Clicking 'Continue'...");
      await humanClick(page, continueBtn);
      await page.waitForTimeout(5000);
      continue;
    }

    // Screen 3: "Choose how to confirm it's you" (Select Authentication app)
    if (dText.includes("Choose how to confirm it's you") || dText.includes("Authentication app") && dText.includes("Get a code from an app") || dText.includes("Help protect your account")) {
      console.log("[Instagram 2FA - State 3] Found 'Choose how to confirm it's you' screen.");
      const authAppOption = dialog.locator("input[value='TOTP'], div[role='button']:has-text('Authentication app'), label:has-text('Authentication app')").first();
      if ((await authAppOption.count()) > 0) {
        await humanClick(page, authAppOption);
        await page.waitForTimeout(800);
      }
      const continueBtn = dialog.locator("div[role='button']:visible:has-text('Continue'), button:visible:has-text('Continue'), div[role='button']:visible:has-text('Next')").first();
      console.log("[Instagram 2FA] Clicking 'Continue'...");
      await humanClick(page, continueBtn);
      await page.waitForTimeout(5000);
      continue;
    }

    // Screen 4: "Instructions for setup" (Extract Secret Key)
    if (dText.includes("Instructions for setup") || dText.includes("Scan this barcode") || dText.includes("Copy key")) {
      console.log("[Instagram 2FA - State 4] Found 'Instructions for setup' screen. Extracting Secret Key...");

      const keyMatch = dText.match(/\b([A-Z2-7]{4}\s+[A-Z2-7]{4}\s+[A-Z2-7]{4}\s+[A-Z2-7]{4}(?:\s+[A-Z2-7]{4})*)\b/);
      if (keyMatch) {
        secretKey = keyMatch[1].replace(/\s+/g, "").toUpperCase();
        console.log(`[Instagram 2FA] Extracted Secret Key (value hidden; persisted before submit).`);
      }

      // Persist the secret BEFORE submitting a TOTP code. If anything crashes
      // after Meta enables 2FA, the account must still be recoverable.
      if (secretKey && !secretPersisted) {
        updateAccountWith2FA(emailTarget, {
          secret_key: secretKey,
          backup_codes: [],
          enabled: false,
          status: "SECRET_CAPTURED",
        });
        secretPersisted = true;
        console.log("[Instagram 2FA] Secret key persisted before TOTP submission (crash-safe).");
      }

      // Also click 'Copy key' button
      const copyKeyBtn = dialog.locator("span:has-text('Copy key'), div[role='button']:has-text('Copy key')").first();
      if ((await copyKeyBtn.count()) > 0 && (await copyKeyBtn.isVisible())) {
        await humanClick(page, copyKeyBtn);
        await page.waitForTimeout(800);
      }

      // Click visible 'Enter code' button
      const enterCodeBtn = dialog.locator("div[role='button']:visible:has-text('Enter code'), button:visible:has-text('Enter code'), div[role='button']:visible:has-text('Next'), div[role='button']:visible:has-text('Continue')").first();
      console.log("[Instagram 2FA] Clicking visible 'Enter code' button...");
      await humanClick(page, enterCodeBtn);
      await page.waitForTimeout(4000);
      continue;
    }

    // Screen 5: "Get your code from your authentication app" (Enter 6-digit TOTP)
    if (dText.includes("Get your code from your authentication app") || dText.includes("Enter the 6-digit code")) {
      console.log("[Instagram 2FA - State 5] Found TOTP Entry screen!");
      if (!secretKey) throw new Error("Missing secret key for TOTP code generation!");

      // Wait for fresh 30-second window if near end
      const epochSec = Math.floor(Date.now() / 1000);
      const rem = 30 - (epochSec % 30);
      if (rem < 4) {
        console.log(`[Instagram 2FA] Waiting ${rem + 1}s for next fresh TOTP window...`);
        await page.waitForTimeout((rem + 1) * 1000);
      }

      const totpCode = generateTOTP(secretKey);
      console.log(`[Instagram 2FA] Generated TOTP Code (hidden).`);

      const textInput = dialog.locator("input[type='text']:visible, input:visible:not([type='submit']):not([type='radio']):not([type='checkbox'])").first();
      await textInput.waitFor({ state: "visible", timeout: 15000 });
      await humanClick(page, textInput);
      await textInput.fill("");
      await typeJittered(textInput, totpCode, 100, 24);
      await page.waitForTimeout(1000);

      const nextBtn = dialog.locator("div[role='button']:visible:has-text('Next'), button:visible:has-text('Next'), div[role='button']:visible:has-text('Continue')").first();
      console.log("[Instagram 2FA] Clicking 'Next' to verify TOTP code...");
      await humanClick(page, nextBtn);
      totpSubmitted = true;
      await page.waitForTimeout(6000);

      const afterDialog = await getActiveDialog(page);
      const afterText = afterDialog ? (await afterDialog.innerText().catch(() => "")) : "";
      if (/(incorrect|invalid|wrong|try again|couldn['’]t|expired)/i.test(afterText)) {
        throw new Error(`TOTP code was rejected: "${afterText.replace(/\s+/g, " ").slice(0, 120)}"`);
      }
      continue;
    }

    // Generic Done fallback (ONLY IF backup codes were already retrieved!)
    if (dText.includes("Done") && backupCodes.length > 0) {
      const doneBtn = dialog.locator("div[role='button']:visible:has-text('Done'), button:visible:has-text('Done')").first();
      if ((await doneBtn.count()) > 0 && (await doneBtn.isVisible())) {
        await humanClick(page, doneBtn);
        await page.waitForTimeout(2000);
      }
      isDone = true;
      break;
    }

    console.log(`[Instagram 2FA] Unrecognized dialog state: "${dText.slice(0, 100)}...". Waiting 3s...`);
    await page.screenshot({ path: "tests/test_artifacts/ig_2fa_unrecognized.png" }).catch(() => {});
    await page.waitForTimeout(3000);
  }

  // Final check: if backup codes are still missing, execute dedicated retrieval pass
  if (backupCodes.length === 0) {
    console.log("[Instagram 2FA] Running final dedicated Backup Codes retrieval pass...");
    backupCodes = await extractBackupCodesPass(page);
  }
  if (backupCodes.length > 0) confirmedOn = true;

  // The confirmation dialog can disappear after the final click; check the page
  // body once more before declaring the flow complete.
  if (!confirmedOn) {
    const bodyText = (await page.locator("body").innerText().catch(() => "")).replace(/\s+/g, " ");
    if (/Two-factor authentication is on|Your two-factor authentication is set up|How you get login codes/i.test(bodyText)) {
      confirmedOn = true;
    }
  }

  // Fail closed: the account is only "protected" when we hold the TOTP secret
  // AND Instagram confirmed activation. Missing backup codes is a loud warning,
  // never a silent success.
  const enabled = Boolean(secretKey && confirmedOn);
  const status = enabled
    ? (backupCodes.length > 0 ? "ACTIVE" : "ACTIVE_NO_BACKUP_CODES")
    : (confirmedOn && !secretKey
      ? "ALREADY_ENABLED_UNKNOWN_SECRET"
      : (secretKey && totpSubmitted ? "FAILED_VERIFICATION" : "FAILED_INCOMPLETE"));

  updateAccountWith2FA(emailTarget, {
    secret_key: secretKey,
    backup_codes: backupCodes,
    enabled,
    status,
  });

  await page.screenshot({ path: "tests/test_artifacts/ig_2fa_final_success.png" }).catch(() => {});
  console.log("=".repeat(60));

  if (!enabled) {
    const reason = !secretKey
      ? "the TOTP secret key was never captured"
      : (confirmedOn
        ? "2FA appears already active but the secret key is unknown"
        : "Instagram never showed the 2FA-active confirmation");
    console.error(`[Instagram 2FA] NOT CONFIRMED (${status}): ${reason}.`);
    console.error("[Instagram 2FA] Do NOT treat this account as protected; inspect it manually and retry.");
    console.log("=".repeat(60));
    return {
      success: false,
      status,
      secret_key: secretKey,
      backup_codes: backupCodes,
      error: reason,
    };
  }

  if (backupCodes.length === 0) {
    console.error("[Instagram 2FA] CRITICAL: 2FA is active but no backup codes were captured.");
    console.error("[Instagram 2FA] Open Accounts Center > Password and security > Two-factor authentication > Backup codes and save them now.");
  }

  console.log("[Instagram 2FA] TWO-FACTOR AUTHENTICATION CONFIRMED ACTIVE.");
  console.log(`Status:       ${status}`);
  console.log(`Secret Key:   [persisted, value hidden]`);
  console.log(`Backup Codes: ${backupCodes.length ? `${backupCodes.length} saved (values hidden)` : "None shown"}`);
  console.log("=".repeat(60));

  return {
    success: true,
    status,
    secret_key: secretKey,
    backup_codes: backupCodes,
  };
}

// ----------------------------------------------------
// Standalone Runner
// ----------------------------------------------------
async function main() {
  const profileName = email.split("@")[0].replace(/[^A-Za-z0-9._-]/g, "");
  const profileDir = path.resolve("output", "profiles instagram", profileName);

  if (!fs.existsSync(profileDir)) {
    console.error(`[Error] Profile directory not found: ${profileDir}`);
    console.error(`Please create or log into the account first.`);
    process.exit(1);
  }

// Verified authentic Windows GPU pairs strictly matching Camoufox's internal
// WebGL hardware database (dist/data-files/webgl_data.db).
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
      if (persona.webgl_config && !GPU_CONFIGURATIONS.some(([v, r]) => v === persona.webgl_config[0] && r === persona.webgl_config[1])) {
        persona.webgl_config = GPU_CONFIGURATIONS[Math.floor(Math.random() * GPU_CONFIGURATIONS.length)];
        fs.writeFileSync(personaPath, JSON.stringify(persona, null, 2));
      }
    } catch (e) { }
  }

  console.log("============================================================");
  console.log(`STARTING INSTAGRAM 2FA SETUP FOR: ${email}`);
  console.log(`Profile: ${profileDir}`);
  console.log(`Proxy:   ${String(proxyArg).replace(/^.*@/, "***@")}`);
  console.log("============================================================");

  const scr = persona?.screen_resolution || { width: 1920, height: 1080 };
  const browserConfig = {
    user_data_dir: profileDir,
    headless: hasFlag("--headless"),
    os: "windows",
    humanize: 0.85,
    block_webrtc: true,
    exclude_addons: ["UBO"],     // Exclude bundled ad-blocker to prevent CSP data: injection violations & CDN script drops
    screen: { maxWidth: scr.width, maxHeight: scr.height },
    proxy: parseProxy(ensureStickyProxy(proxyArg, email)),
    webgl_config: persona?.webgl_config || undefined,
    i_know_what_im_doing: true,
  };
  if (persona && persona["canvas:seed"]) {
    browserConfig.config = {
      "canvas:seed": persona["canvas:seed"],
      "canvas:aaOffset": 0,
      "canvas:aaCapOffset": false,
      "audio:seed": persona["audio:seed"],
      "fonts:spacing_seed": persona["fonts:spacing_seed"],
      timezone: persona.timezone || "America/Chicago",
      "locale:region": persona["locale:region"] || "US",
      "locale:language": persona["locale:language"] || "en",
    };
  }

  // Reuse (or create once) the profile's frozen full fingerprint.
  const fingerprintPath = path.join(profileDir, "fingerprint.json");
  let fingerprint = null;
  if (fs.existsSync(fingerprintPath)) {
    try {
      const fp = JSON.parse(fs.readFileSync(fingerprintPath, "utf-8"));
      if (fp && fp.navigator && fp.screen) fingerprint = fp;
    } catch (e) { }
  }
  if (!fingerprint) {
    let generated = null;
    try {
      const res = FP_GENERATOR.getFingerprint({
        screen: { minWidth: scr.width, maxWidth: scr.width, minHeight: scr.height, maxHeight: scr.height },
        operatingSystems: ["windows"],
      });
      generated = res.fingerprint;
    } catch (e) { }
    if (!generated) {
      const res = FP_GENERATOR.getFingerprint({ operatingSystems: ["windows"] });
      generated = res.fingerprint;
      persona.screen_resolution = { width: generated.screen.width, height: generated.screen.height };
      try { fs.writeFileSync(personaPath, JSON.stringify(persona, null, 2)); } catch (e) { }
    }
    fingerprint = generated;
    try {
      fs.writeFileSync(fingerprintPath, JSON.stringify(fingerprint, null, 2));
    } catch (e) { }
  }

  // Keep the fingerprint's videoCard coherent with the explicit WebGL pair.
  if (persona?.webgl_config) {
    const expectedCard = { vendor: persona.webgl_config[0], renderer: persona.webgl_config[1] };
    if (!fingerprint.videoCard
      || fingerprint.videoCard.vendor !== expectedCard.vendor
      || fingerprint.videoCard.renderer !== expectedCard.renderer) {
      fingerprint.videoCard = expectedCard;
      try { fs.writeFileSync(fingerprintPath, JSON.stringify(fingerprint, null, 2)); } catch (e) { }
    }
  }
  browserConfig.fingerprint = fingerprint;

  const browser = await Camoufox(browserConfig);
  const page = (browser.pages && browser.pages().length > 0) ? browser.pages()[0] : await browser.newPage();
  await page.bringToFront().catch(() => {});

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

  try {
    const result = await setupInstagram2FA(page, email, clientId, refreshToken);
    console.log("[Instagram 2FA] Result:", JSON.stringify(result, null, 2));
    if (!result.success) process.exitCode = 1;
    console.log("[Instagram 2FA] Keeping browser open for 15s to allow user review...");
    await page.waitForTimeout(15000);
  } finally {
    await browser.close().catch(() => {});
    console.log("[Instagram 2FA] Script finished.");
  }
}

// Execute if run directly (path.basename is robust to wrappers/case on Windows)
if (process.argv[1] && path.basename(process.argv[1]) === "setup_instagram_2fa.mjs") {
  main().catch((err) => {
    console.error(`[Instagram 2FA Error]: ${err.stack || err}`);
    process.exit(1);
  });
}
