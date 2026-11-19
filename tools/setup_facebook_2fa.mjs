#!/usr/bin/env node
/**
 * tools/setup_facebook_2fa.mjs
 * =============================
 * Automated Facebook Two-Factor Authentication (TOTP Authenticator App) Setup
 * and Backup / Recovery Codes Retrieval via Meta Accounts Center:
 * (https://accountscenter.facebook.com/password_and_security/two_factor/?locale=en_US).
 *
 * Full Lifecycle:
 * 1. Organic UI Navigation:
 *    - Avatar Dropdown -> "Settings & privacy" -> "Settings"
 *    - Left Navigation: "Meta Account" (Accounts Center)
 *    - Accounts Center: "Login and security" -> "Two-factor authentication"
 *    - Direct URL fallback: https://accountscenter.facebook.com/password_and_security/two_factor/?locale=en_US
 * 2. Account Profile Selection:
 *    - Select the Facebook account item from the accounts list.
 * 3. Password Challenge Handler:
 *    - If prompted: "it may ask for your password, if it does then write pass else carry on"
 *    - Types password into `input[type='password']:visible` and submits.
 * 4. Email Security Code Challenge Handler (if triggered):
 *    - Polls Microsoft Graph / Outlook REST API for 6-8 digit code or prompts terminal.
 * 5. Method Selection ("Help protect your account"):
 *    - Ensures "Authentication app" (Recommended) radio is selected.
 *    - Clicks "Continue".
 * 6. Secret Key Extraction & Crash-Safe Persistence:
 *    - Extracts Base32 secret key from text / QR instructions.
 *    - Persists secret key to registry and profile immediately BEFORE submitting TOTP code.
 * 7. RFC 6238 Standard TOTP Generation & Submission:
 *    - Calculates 6-digit TOTP code aligned to 30-second epoch.
 *    - Enters code with human jittered typing.
 *    - Clicks "Next" / "Continue".
 * 8. Backup / Recovery Codes Extraction:
 *    - Navigates: "Two-factor authentication" -> "Manage authentication" -> "Recovery codes" / "Backup codes".
 *    - Handles secondary password challenge if presented.
 *    - Extracts 8 backup codes (8 digits each).
 *    - Saves to:
 *      1) output/facebook_registered_accounts.json
 *      2) output/facebook_backup_codes.json
 *      3) <profileDir>/backup_codes.txt
 *      4) <profileDir>/account_info.json
 */

import fs from "node:fs";
import path from "node:path";
import crypto from "node:crypto";
import readline from "node:readline";
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

const FP_GENERATOR_PATH = "file:///C:/Users/rudra/AppData/Roaming/npm/node_modules/camoufox-cli/node_modules/fingerprint-generator/index.mjs";
const { FingerprintGenerator } = await import(FP_GENERATOR_PATH);
const FP_GENERATOR = new FingerprintGenerator({ browsers: ["firefox"], operatingSystems: ["windows"] });

// Verified Camoufox Windows GPU pool
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

const CAMOUFOX_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:158.0) Gecko/20100101 Firefox/158.0";

// Bounded HTTP fetch for Outlook/Graph calls
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

// ----------------------------------------------------
// Base32 & RFC 6238 Standard TOTP Engine
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

  try {
    const res = await fetchWithTimeout(tokenUrl, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({ ...baseParams, scope: "https://graph.microsoft.com/Mail.Read" }).toString(),
    });
    const data = await res.json();
    if (data.access_token) return data.access_token;
  } catch (e) { }

  try {
    const res = await fetchWithTimeout(tokenUrl, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({ ...baseParams, scope: "https://outlook.office.com/Mail.Read" }).toString(),
    });
    const data = await res.json();
    if (data.access_token) return data.access_token;
  } catch (e) { }

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

export async function pollOutlookFor2FAEmailOtp(cId, rToken, startTimeMs, maxWaitSeconds = 60) {
  if (!rToken) return null;
  console.log(`[Outlook OTP] Polling Microsoft Graph & Outlook REST API for Meta security code (timeout: ${maxWaitSeconds}s)...`);
  const startTime = Date.now();
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
                from.includes("facebook") ||
                from.includes("meta") ||
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
    await new Promise((r) => setTimeout(r, 4000));
  }

  return null;
}

// ----------------------------------------------------
// Database & Master Vault Persistence
// ----------------------------------------------------
export function updateFacebookAccountWith2FA(emailTarget, twoFactorData, explicitProfileDir = null) {
  const profileName = emailTarget.split("@")[0].replace(/[^A-Za-z0-9._-]/g, "");
  const accountsFile = path.resolve("output", "facebook_registered_accounts.json");
  const masterBackupFile = path.resolve("output", "facebook_backup_codes.json");
  const profileDir = explicitProfileDir || path.resolve("output", "profiles facebook", profileName);

  const incomingSecret = twoFactorData.secret_key || null;
  const incomingCodes = Array.isArray(twoFactorData.backup_codes) ? twoFactorData.backup_codes : [];
  const enabled = twoFactorData.enabled === true;
  const status = twoFactorData.status || (enabled ? "ACTIVE" : "PENDING");

  // 1. Update master accounts database (facebook_registered_accounts.json)
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
          configured_at: enabled ? (existing.configured_at || new Date().toISOString()) : (existing.configured_at || null),
          last_attempt_at: new Date().toISOString(),
        };
        fs.writeFileSync(accountsFile, JSON.stringify(list, null, 2), "utf-8");
        console.log(`[Database] Saved Facebook 2FA state (enabled=${list[idx].two_factor.enabled}, status=${status}) to ${accountsFile}`);
      } else {
        console.warn(`[Database] Account ${emailTarget} not yet in ${accountsFile}; backup registry will persist it.`);
      }
    } catch (err) {
      console.warn(`[Database] Error updating 2FA in Facebook accounts file: ${err.message}`);
    }
  }

  // 2. Save dedicated backup_codes.txt in profile directory
  if (incomingCodes.length > 0) {
    try {
      fs.mkdirSync(profileDir, { recursive: true });
      const txtPath = path.join(profileDir, "backup_codes.txt");
      const content = [
        `FACEBOOK BACKUP CODES FOR: ${emailTarget}`,
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
      console.log(`[Database] Saved Facebook backup codes text file to: ${txtPath}`);
    } catch (err) {
      console.warn(`[Database] Note saving profile backup_codes.txt: ${err.message}`);
    }
  }

  // 3. Update master backup codes registry (output/facebook_backup_codes.json)
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
      platform: "facebook",
      enabled: enabled || existing.enabled === true,
      status,
      secret_key: incomingSecret || existing.secret_key || null,
      backup_codes: backupCodes,
      backup_codes_saved: backupCodes.length > 0,
      updated_at: new Date().toISOString(),
    };
    fs.writeFileSync(masterBackupFile, JSON.stringify(masterVault, null, 2), "utf-8");
    console.log(`[Database] Updated Facebook master backup registry: ${masterBackupFile}`);
  } catch (err) { }

  // 4. Update profile account_info.json if present
  try {
    const accountInfoPath = path.join(profileDir, "account_info.json");
    if (fs.existsSync(accountInfoPath)) {
      const info = JSON.parse(fs.readFileSync(accountInfoPath, "utf-8"));
      info.two_factor = {
        enabled: enabled || info.two_factor?.enabled === true,
        status,
        method: "TOTP_AUTHENTICATOR_APP",
        secret_key: incomingSecret || info.two_factor?.secret_key || null,
        backup_codes: incomingCodes.length > 0 ? incomingCodes : (info.two_factor?.backup_codes || []),
        backup_codes_saved: (incomingCodes.length > 0) || Boolean(info.two_factor?.backup_codes_saved),
        updated_at: new Date().toISOString(),
      };
      fs.writeFileSync(accountInfoPath, JSON.stringify(info, null, 2), "utf-8");
      console.log(`[Database] Updated ${accountInfoPath} with 2FA state.`);
    }
  } catch (e) { }
}

// ----------------------------------------------------
// UI Helpers
// ----------------------------------------------------
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

async function getActiveDialog(page) {
  const dialogs = await page.locator("[role='dialog']:visible").all();
  if (dialogs.length === 0) return null;
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

export function extractBackupCodesFromText(text) {
  const matches = text.match(/\b(?:\d{4}\s+\d{4}|\d{8})\b/g) || [];
  return [...new Set(matches.map((code) => code.replace(/\s+/g, "")))];
}

/**
 * Handle password challenge if prompted anywhere during 2FA setup:
 * "it may ask for your password, if it does then write pass else carry on"
 */
async function handlePasswordChallengeIfPresent(container, password, page = null) {
  if (!password) return false;
  try {
    const pwInput = container.locator("input[type='password']:visible").first();
    if ((await pwInput.count()) > 0 && (await pwInput.isVisible().catch(() => false))) {
      console.log("[Facebook 2FA] Detected password challenge prompt. Entering password...");
      await humanClick(page || container, pwInput).catch(() => pwInput.click());
      await pwInput.fill("");
      await typeJittered(pwInput, password, 45, 15);
      await new Promise((r) => setTimeout(r, 600));

      const submitBtn = container.locator("button:has-text('Continue'), button:has-text('Submit'), [role='button']:has-text('Continue'), [role='button']:has-text('Submit'), button[type='submit']:visible").first();
      if ((await submitBtn.count()) > 0 && (await submitBtn.isVisible().catch(() => false))) {
        console.log("[Facebook 2FA] Submitting password challenge...");
        await humanClick(page || container, submitBtn).catch(() => submitBtn.click());
        await new Promise((r) => setTimeout(r, 4000));
        return true;
      }
    }
  } catch (err) {
    console.warn(`[Facebook 2FA] Note during password challenge check: ${err.message}`);
  }
  return false;
}

// ----------------------------------------------------
// Dedicated Backup Codes Extraction Pass
// ----------------------------------------------------
async function extractFacebookBackupCodesPass(page, password = null, maxTries = 8) {
  console.log("[Facebook 2FA] Running dedicated Backup Codes retrieval pass...");
  for (let t = 1; t <= maxTries; t++) {
    await page.waitForTimeout(2000);

    // Check if password challenge appeared
    await handlePasswordChallengeIfPresent(page, password, page);

    const bodyText = (await page.locator("body").innerText().catch(() => "")).replace(/\s+/g, " ");

    // Dismiss "Your two-factor authentication is set up" modal if still open
    if (bodyText.includes("Your two-factor authentication is set up")) {
      const doneModalBtn = page.locator("div[role='dialog'] div[role='button']:visible:has-text('Done'), div[role='dialog'] button:visible:has-text('Done')").first();
      if ((await doneModalBtn.count()) > 0 && (await doneModalBtn.isVisible().catch(() => false))) {
        console.log("[Facebook 2FA] Dismissing setup completion dialog in recovery pass...");
        await humanClick(page, doneModalBtn).catch(() => doneModalBtn.click());
        await page.waitForTimeout(3000);
        continue;
      }
    }

    // 1. Check if backup codes are currently visible
    if (bodyText.includes("Download codes") || bodyText.includes("Get new codes") || bodyText.includes("Save your backup codes") || bodyText.includes("Recovery codes")) {
      const codes = extractBackupCodesFromText(bodyText);
      if (codes.length > 0) {
        console.log(`[Facebook 2FA] Extracted ${codes.length} Backup Codes (values hidden).`);
        const closeBtn = page.locator("div[role='button'][aria-label='Close'], div[role='button']:has-text('Close'), button:has-text('Done')").first();
        if ((await closeBtn.count()) > 0 && (await closeBtn.isVisible())) {
          await closeBtn.click().catch(() => {});
        }
        return codes;
      }
    }

    // 2. Check for "Recovery codes" or "Backup codes" button
    const recoveryBtn = page.locator("div[role='button']:visible:has-text('Recovery codes'), div[role='button']:visible:has-text('Backup codes'), a:visible:has-text('Recovery codes'), a:visible:has-text('Backup codes'), span:visible:has-text('Recovery codes'), span:visible:has-text('Backup codes')").first();
    if ((await recoveryBtn.count()) > 0 && (await recoveryBtn.isVisible())) {
      console.log("[Facebook 2FA] Clicking 'Recovery codes' / 'Backup codes' button...");
      await humanClick(page, recoveryBtn).catch(() => recoveryBtn.click());
      await page.waitForTimeout(3000);
      continue;
    }

    // 2.5 Check for "Additional methods" item
    const addMethodsBtn = page.locator("div[role='button']:visible:has-text('Additional methods'), a:visible:has-text('Additional methods'), div:visible:has-text('Additional methods')").first();
    if ((await addMethodsBtn.count()) > 0 && (await addMethodsBtn.isVisible().catch(() => false))) {
      console.log("[Facebook 2FA] Clicking 'Additional methods' in recovery pass...");
      await humanClick(page, addMethodsBtn).catch(() => addMethodsBtn.click());
      await page.waitForTimeout(3000);
      continue;
    }

    // 3. Check for "Manage authentication" button
    const manageBtn = page.locator("div[role='button']:visible:has-text('Manage authentication'), button:visible:has-text('Manage authentication'), a:visible:has-text('Manage authentication')").first();
    if ((await manageBtn.count()) > 0 && (await manageBtn.isVisible())) {
      console.log("[Facebook 2FA] Clicking 'Manage authentication' button...");
      await humanClick(page, manageBtn).catch(() => manageBtn.click());
      await page.waitForTimeout(3000);
      continue;
    }

    // 4. Check for account row item in 2FA list
    const profileItem = page.locator("div[role='listitem'] div[role='button'], div[role='listitem'] a").first();
    if ((await profileItem.count()) > 0 && (await profileItem.isVisible())) {
      console.log("[Facebook 2FA] Clicking account row in 2FA list...");
      await humanClick(page, profileItem).catch(() => profileItem.click());
      await page.waitForTimeout(3000);
      continue;
    }

    // 5. If still not found by attempt 3, re-navigate to 2FA page directly
    if (t === 3) {
      console.log("[Facebook 2FA] Re-navigating to 2FA page directly...");
      await safeGoto(page, "https://accountscenter.facebook.com/password_and_security/two_factor/?locale=en_US").catch(() => {});
      await page.waitForTimeout(4000);
    }
  }
  return [];
}

// ----------------------------------------------------
// Core Facebook 2FA Setup Routine
// ----------------------------------------------------
export async function setupFacebook2FA(page, emailTarget, password = null, explicitProfileDir = null, cId = null, rToken = null) {
  console.log("=".repeat(60));
  console.log(`[Facebook 2FA] Starting Two-Factor Authentication Setup for: ${emailTarget}`);
  console.log("=".repeat(60));

  const twoFaUrl = "https://accountscenter.facebook.com/password_and_security/two_factor/?locale=en_US";
  let reached2fa = false;

  // 1. Organic in-app UI navigation to 2FA
  try {
    console.log("[Facebook 2FA] Starting organic in-app navigation: Avatar -> Settings & privacy -> Settings -> Meta Account -> Login and security -> Two-factor authentication...");

    // Step A: Avatar Dropdown
    const avatarSelector = "div[role='banner'] div[aria-label*='Your profile' i], div[role='banner'] [role='button'][aria-label*='profile' i], div[role='banner'] div[aria-label*='Account controls and settings' i], [aria-label*='Your profile' i], div[role='banner'] [aria-label='Account controls and settings']";
    let avatarBtn = page.locator(avatarSelector).first();

    if ((await avatarBtn.count()) > 0 && (await avatarBtn.isVisible())) {
      console.log("[Facebook 2FA] Step A: Clicking Profile Avatar / Account menu button...");
      await humanHover(page, avatarBtn).catch(() => {});
      await page.waitForTimeout(300);
      await humanClick(page, avatarBtn).catch(() => avatarBtn.click());
      await page.waitForTimeout(2000);

      // Step A.1: "Settings & privacy"
      const settingsAndPrivacyBtn = page.locator("div[role='listitem']:has-text('Settings & privacy'), div[role='button']:has-text('Settings & privacy'), span:text-is('Settings & privacy'), div:text-is('Settings & privacy')").first();
      if ((await settingsAndPrivacyBtn.count()) > 0 && (await settingsAndPrivacyBtn.isVisible())) {
        console.log("[Facebook 2FA] Step A.1: Clicking 'Settings & privacy' in menu...");
        await humanHover(page, settingsAndPrivacyBtn).catch(() => {});
        await page.waitForTimeout(200);
        await humanClick(page, settingsAndPrivacyBtn).catch(() => settingsAndPrivacyBtn.click());
        await page.waitForTimeout(2000);

        // Step A.2: "Settings"
        const settingsBtn = page.locator("div[role='listitem']:has-text('Settings'), div[role='button']:has-text('Settings'), a[href*='/settings'], span:text-is('Settings')").first();
        if ((await settingsBtn.count()) > 0 && (await settingsBtn.isVisible())) {
          console.log("[Facebook 2FA] Step A.2: Clicking 'Settings'...");
          await humanHover(page, settingsBtn).catch(() => {});
          await page.waitForTimeout(200);
          await humanClick(page, settingsBtn).catch(() => settingsBtn.click());
          await page.waitForTimeout(3500);
        }
      }
    }

    // Step B: Locate 'Meta Account' (Accounts Center) card in Settings
    const metaAccountSelector = "a[href*='accountscenter.facebook.com'], a:has-text('Meta Account'), div:has-text('Meta Account'):has-text('Password, security'), [aria-label*='Meta Account' i]";
    let metaAccountBtn = page.locator(metaAccountSelector).first();

    if ((await metaAccountBtn.count()) === 0 || !(await metaAccountBtn.isVisible().catch(() => false))) {
      if (!page.url().includes("settings") && !page.url().includes("accountscenter")) {
        console.log("[Facebook 2FA] Navigating to /settings/?locale=en_US to expose Accounts Center...");
        await safeGoto(page, "https://www.facebook.com/settings/?locale=en_US", { waitUntil: "domcontentloaded", timeout: 25000 });
        await page.waitForTimeout(3000);
        metaAccountBtn = page.locator(metaAccountSelector).first();
      }
    }

    if ((await metaAccountBtn.count()) > 0 && (await metaAccountBtn.isVisible())) {
      console.log("[Facebook 2FA] Step B: Clicking 'Meta Account' (Accounts Center)...");
      await humanHover(page, metaAccountBtn).catch(() => {});
      await page.waitForTimeout(300);
      await humanClick(page, metaAccountBtn).catch(() => metaAccountBtn.click());
      await page.waitForTimeout(4000);
    }

    // Step C: Click 'Login and security' in Accounts Center
    const loginSecSelector = "a[href*='password_and_security'], div:has-text('Login and security'), a:has-text('Login and security'), span:text-is('Login and security'), div:text-is('Login and security')";
    let loginSecBtn = page.locator(loginSecSelector).first();
    for (let i = 0; i < 4; i++) {
      if ((await loginSecBtn.count()) > 0 && (await loginSecBtn.isVisible())) {
        console.log("[Facebook 2FA] Step C: Clicking 'Login and security'...");
        await humanHover(page, loginSecBtn).catch(() => {});
        await page.waitForTimeout(300);
        await humanClick(page, loginSecBtn).catch(() => loginSecBtn.click());
        await page.waitForTimeout(3500);
        break;
      }
      await page.waitForTimeout(1000);
    }

    // Step D: Click 'Two-factor authentication'
    const twoFaBtnSelector = "a[href*='two_factor'], div[role='button']:has-text('Two-factor authentication'), div:has-text('Two-factor authentication'), span:has-text('Two-factor authentication')";
    let twoFaBtn = page.locator(twoFaBtnSelector).first();
    for (let i = 0; i < 4; i++) {
      if ((await twoFaBtn.count()) > 0 && (await twoFaBtn.isVisible())) {
        console.log("[Facebook 2FA] Step D: Clicking 'Two-factor authentication'...");
        await humanHover(page, twoFaBtn).catch(() => {});
        await page.waitForTimeout(300);
        await humanClick(page, twoFaBtn).catch(() => twoFaBtn.click());
        await page.waitForTimeout(3500);
        break;
      }
      await page.waitForTimeout(1000);
    }

    if (page.url().includes("two_factor") || (await getActiveDialog(page)) !== null) {
      console.log("[Facebook 2FA] Successfully reached 2FA screen via organic UI navigation!");
      reached2fa = true;
    }
  } catch (err) {
    console.warn(`[Facebook 2FA] Note during organic UI navigation: ${err.message}`);
  }

  // Fallback to direct URL if organic navigation did not land on 2FA
  if (!reached2fa && !page.url().includes("two_factor")) {
    console.log(`[Facebook 2FA] Fallback: Navigating directly to ${twoFaUrl}...`);
    await safeGoto(page, twoFaUrl, { waitUntil: "domcontentloaded", timeout: 45000 });
    await page.waitForTimeout(4000);
  }

  let secretKey = null;
  let backupCodes = [];
  let isDone = false;
  let secretPersisted = false;
  let totpSubmitted = false;
  let confirmedOn = false;

  const maxLoops = 40;
  for (let loop = 1; loop <= maxLoops && !isDone; loop++) {
    console.log(`--- [Facebook 2FA Loop ${loop}/${maxLoops}] Inspecting active screen state ---`);
    await page.waitForTimeout(1500);

    // Check for password challenge at page or modal level first
    const pwHandled = await handlePasswordChallengeIfPresent(page, password, page);
    if (pwHandled) {
      console.log("[Facebook 2FA] Handled password challenge. Waiting for next screen...");
      await page.waitForTimeout(3000);
      continue;
    }

    const dialog = await getActiveDialog(page);
    const container = dialog || page;
    const currentText = ((dialog ? await dialog.innerText() : await page.locator("body").innerText().catch(() => "")) || "").replace(/\s+/g, " ");

    console.log(`[Facebook 2FA] Active Container Text: "${currentText.slice(0, 140)}..."`);

    // State A: Account Selection list on 2FA page
    if (currentText.includes("Choose an account to set up two-factor authentication") ||
        (currentText.includes("Two-factor authentication") && (currentText.includes("profile") || currentText.includes("Facebook")) && !currentText.includes("Help protect your account") && !currentText.includes("Instructions for setup"))) {
      const accountItem = page.locator("div[role='listitem'] div[role='button'], div[role='listitem'] a, div[role='button']:has-text('profile')").first();
      if ((await accountItem.count()) > 0 && (await accountItem.isVisible())) {
        console.log("[Facebook 2FA - State 0] Clicking account row to proceed into 2FA setup...");
        await humanClick(page, accountItem).catch(() => accountItem.click());
        await page.waitForTimeout(3500);
        continue;
      }
    }

    if (currentText.includes("Two-factor authentication is on")
      || currentText.includes("Your two-factor authentication is set up")
      || currentText.includes("How you get login codes")) {
      confirmedOn = true;
    }

    // State 8: "Backup / Recovery codes" modal -> Extract codes immediately
    if (currentText.includes("Download codes") || currentText.includes("Get new codes") || currentText.includes("Save your backup codes") || currentText.includes("Recovery codes")) {
      const codes = extractBackupCodesFromText(currentText);
      if (codes.length > 0) {
        backupCodes = codes;
        confirmedOn = true;
        console.log(`[Facebook 2FA - State 8] Extracted ${backupCodes.length} Backup Codes (values hidden).`);

        // Close modal cleanly via Close / Done button
        const closeBtn = container.locator("div[role='button'][aria-label='Close'], div[role='button']:has-text('Close'), button:has-text('Done')").first();
        if ((await closeBtn.count()) > 0 && (await closeBtn.isVisible())) {
          await closeBtn.click().catch(() => {});
          await page.waitForTimeout(2000);
        }

        isDone = true;
        break;
      }
    }

    // State 6: "Your two-factor authentication is set up" -> Click "Done" to close modal and reveal settings
    if (currentText.includes("Your two-factor authentication is set up") || currentText.includes("two-factor authentication is set up") || currentText.includes("Manage authentication")) {
      confirmedOn = true;
      console.log("[Facebook 2FA - State 6] 'Your two-factor authentication is set up' detected! Dismissing dialog via 'Done' / 'Manage authentication'...");

      const manageBtn = page.locator("div[role='dialog'] div[role='button']:visible:has-text('Manage authentication'), div[role='button']:visible:has-text('Manage authentication'), button:visible:has-text('Manage authentication')").first();
      if ((await manageBtn.count()) > 0 && (await manageBtn.isVisible().catch(() => false))) {
        await humanClick(page, manageBtn).catch(() => manageBtn.click());
        await page.waitForTimeout(4000);
        continue;
      }

      // Robust dismissal of the "Your two-factor authentication is set up" modal via "Done" button
      let doneClicked = false;
      const doneSelectors = [
        "div[role='dialog'] div[role='button']:visible:has-text('Done')",
        "div[role='dialog'] button:visible:has-text('Done')",
        "div[role='dialog'] [aria-label='Done']",
        "div[role='dialog'] span:text-is('Done')",
        "div[role='button']:visible:has-text('Done')",
        "button:visible:has-text('Done')",
        "[aria-label='Done']",
        "span:text-is('Done')"
      ];
      for (const sel of doneSelectors) {
        const btn = page.locator(sel).first();
        if ((await btn.count()) > 0 && (await btn.isVisible().catch(() => false))) {
          console.log(`[Facebook 2FA - State 6] Clicking 'Done' button via selector: ${sel}...`);
          await humanClick(page, btn).catch(() => btn.click({ force: true }));
          doneClicked = true;
          await page.waitForTimeout(2000);
          break;
        }
      }

      if (!doneClicked) {
        // Direct DOM evaluation click fallback
        doneClicked = await page.evaluate(() => {
          const els = Array.from(document.querySelectorAll("div[role='button'], button, span, div[tabindex]"));
          for (const el of els) {
            if ((el.innerText || el.textContent || "").trim().toLowerCase() === "done") {
              const rect = el.getBoundingClientRect();
              if (rect.width > 0 && rect.height > 0) {
                el.click();
                return true;
              }
            }
          }
          return false;
        }).catch(() => false);
      }

      // Fallback: Check if dialog is still visible and use Close (X) or Enter
      const dialogStillVisible = await page.evaluate(() => {
        const txt = (document.body ? document.body.innerText : "");
        return txt.includes("Your two-factor authentication is set up");
      }).catch(() => false);

      if (dialogStillVisible) {
        console.log("[Facebook 2FA - State 6] Setup modal still visible; attempting keyboard Enter and Close (X) button...");
        await page.keyboard.press("Enter").catch(() => {});
        await page.waitForTimeout(1000);

        const closeBtn = page.locator("div[role='dialog'] [aria-label='Close'], div[role='dialog'] div[role='button']:has(svg), div[role='dialog'] svg[aria-label='Close']").first();
        if ((await closeBtn.count()) > 0 && (await closeBtn.isVisible().catch(() => false))) {
          console.log("[Facebook 2FA - State 6] Clicking 'Close' (X) to dismiss setup modal...");
          await humanClick(page, closeBtn).catch(() => closeBtn.click({ force: true }));
          await page.waitForTimeout(3000);
        }
      }

      await page.waitForTimeout(3000);
      continue;
    }

    // State 7: "Two-factor authentication is on" -> Click "Recovery codes" / "Backup codes" / "Additional methods"
    if (currentText.includes("Two-factor authentication is on") || currentText.includes("How you get login codes") || currentText.includes("Additional methods") || currentText.includes("Recovery codes")) {
      confirmedOn = true;
      console.log("[Facebook 2FA - State 7] 'Two-factor authentication is on' screen detected. Opening 'Recovery codes' / 'Backup codes'...");
      const recoveryBtn = page.locator("div[role='button']:visible:has-text('Recovery codes'), div[role='button']:visible:has-text('Backup codes'), a:visible:has-text('Recovery codes'), a:visible:has-text('Backup codes'), span:visible:has-text('Recovery codes'), span:visible:has-text('Backup codes')").first();
      if ((await recoveryBtn.count()) > 0 && (await recoveryBtn.isVisible().catch(() => false))) {
        await humanClick(page, recoveryBtn).catch(() => recoveryBtn.click());
        await page.waitForTimeout(4000);
        continue;
      }

      const addMethodsBtn = page.locator("div[role='button']:visible:has-text('Additional methods'), a:visible:has-text('Additional methods'), div:visible:has-text('Additional methods')").first();
      if ((await addMethodsBtn.count()) > 0 && (await addMethodsBtn.isVisible().catch(() => false))) {
        console.log("[Facebook 2FA - State 7] Clicking 'Additional methods'...");
        await humanClick(page, addMethodsBtn).catch(() => addMethodsBtn.click());
        await page.waitForTimeout(3000);
        continue;
      }

      const manageBtn = page.locator("div[role='button']:visible:has-text('Manage authentication'), button:visible:has-text('Manage authentication')").first();
      if ((await manageBtn.count()) > 0 && (await manageBtn.isVisible().catch(() => false))) {
        await humanClick(page, manageBtn).catch(() => manageBtn.click());
        await page.waitForTimeout(3000);
        continue;
      }
    }

    // State 1: "Set up extra protection" / "Get started"
    if (currentText.includes("Set up extra protection") || (currentText.includes("Get started") && !currentText.includes("Check your email"))) {
      console.log("[Facebook 2FA - State 1] Found 'Get started' screen. Clicking...");
      const getStartedBtn = container.locator("div[role='button']:visible:has-text('Get started'), button:visible:has-text('Get started')").first();
      if ((await getStartedBtn.count()) > 0 && (await getStartedBtn.isVisible())) {
        await humanClick(page, getStartedBtn).catch(() => getStartedBtn.click());
        console.log("[Facebook 2FA - State 1] Clicked 'Get started'. Waiting for next screen...");
        await page.waitForTimeout(4000);
        continue;
      }
    }

    // State 2: "Check your email" (Email OTP verification if triggered)
    if (currentText.includes("Check your email") || currentText.includes("Enter the code we sent") || currentText.includes("send a new code")) {
      console.log("[Facebook 2FA - State 2] Found 'Check your email' security screen. Retrieving email security code...");
      const textInput = container.locator("input[type='text']:visible, input:visible:not([type='submit']):not([type='radio']):not([type='checkbox']):not([type='password'])").first();
      await textInput.waitFor({ state: "visible", timeout: 20000 });

      let emailCode = null;
      if (rToken) {
        console.log("[Facebook 2FA] Polling Outlook for security code (Round 1/2, timeout: 35s)...");
        emailCode = await pollOutlookFor2FAEmailOtp(cId, rToken, Date.now() - 10 * 60 * 1000, 35);
        if (!emailCode) {
          console.log("[Facebook 2FA] ⚠️ Code not received in 35s. Triggering 'Send a new code'...");
          const resend2FaBtn = container.locator("button:has-text('Send a new code'), [role='button']:has-text('Send a new code'), a:has-text('Send a new code'), button:has-text('Resend'), a:has-text('Resend'), [role='button']:has-text('Resend')").first();
          if ((await resend2FaBtn.count()) > 0 && (await resend2FaBtn.isVisible().catch(() => false))) {
            await humanClick(page, resend2FaBtn).catch(() => resend2FaBtn.click());
            await page.waitForTimeout(2000);
          }
          console.log("[Facebook 2FA] Polling Outlook for security code (Round 2/2, timeout: 35s)...");
          emailCode = await pollOutlookFor2FAEmailOtp(cId, rToken, Date.now() - 10 * 60 * 1000, 35);
        }
      }

      if (emailCode) {
        console.log(`[Facebook 2FA] Typing email verification code: ${emailCode}...`);
        await humanClick(page, textInput).catch(() => textInput.click());
        await textInput.fill("");
        await typeJittered(textInput, emailCode, 90, 20);
        await page.waitForTimeout(800);

        const continueBtn = container.locator("div[role='button']:visible:has-text('Continue'), button:visible:has-text('Continue')").first();
        console.log("[Facebook 2FA] Clicking 'Continue'...");
        await humanClick(page, continueBtn).catch(() => continueBtn.click());
        await page.waitForTimeout(5000);
        continue;
      }
    }

    // State 3: "Help protect your account" / "Choose how to confirm that it's you" (Select Authentication app)
    if (currentText.includes("Help protect your account") || (currentText.includes("Authentication app") && currentText.includes("Duo Mobile or Google Authenticator")) || currentText.includes("Choose how to confirm")) {
      console.log("[Facebook 2FA - State 3] Found 'Help protect your account' screen (Method selection).");
      const authAppOption = container.locator("div[role='button']:has-text('Authentication app'), label:has-text('Authentication app'), input[value='TOTP'], div:has-text('Authentication app') input[type='radio']").first();
      if ((await authAppOption.count()) > 0) {
        await humanClick(page, authAppOption).catch(() => authAppOption.click());
        await page.waitForTimeout(800);
      }

      const continueBtn = container.locator("div[role='button']:visible:has-text('Continue'), button:visible:has-text('Continue'), div[role='button']:visible:has-text('Next')").first();
      console.log("[Facebook 2FA] Clicking 'Continue'...");
      await humanClick(page, continueBtn).catch(() => continueBtn.click());
      await page.waitForTimeout(5000);
      continue;
    }

    // State 4: "Instructions for setup" (Extract Secret Key)
    if (currentText.includes("Instructions for setup") || currentText.includes("Scan this barcode") || currentText.includes("Copy key") || currentText.includes("enter this text code")) {
      console.log("[Facebook 2FA - State 4] Found 'Instructions for setup' screen. Extracting Secret Key...");

      const keyMatch = currentText.match(/\b([A-Z2-7]{4}\s+[A-Z2-7]{4}\s+[A-Z2-7]{4}\s+[A-Z2-7]{4}(?:\s+[A-Z2-7]{4})*)\b/) || currentText.match(/\b([A-Z2-7]{16,32})\b/);
      if (keyMatch) {
        secretKey = keyMatch[1].replace(/\s+/g, "").toUpperCase();
        console.log(`[Facebook 2FA] Extracted Secret Key (value hidden; persisted before submit).`);
      }

      // Persist the secret BEFORE submitting a TOTP code (crash-safe!)
      if (secretKey && !secretPersisted) {
        updateFacebookAccountWith2FA(emailTarget, {
          secret_key: secretKey,
          backup_codes: [],
          enabled: false,
          status: "SECRET_CAPTURED",
        }, explicitProfileDir);
        secretPersisted = true;
        console.log("[Facebook 2FA] Secret key persisted before TOTP submission (crash-safe).");
      }

      // Also click 'Copy key' button if present
      const copyKeyBtn = container.locator("span:has-text('Copy key'), div[role='button']:has-text('Copy key'), button:has-text('Copy key')").first();
      if ((await copyKeyBtn.count()) > 0 && (await copyKeyBtn.isVisible())) {
        await humanClick(page, copyKeyBtn).catch(() => copyKeyBtn.click());
        await page.waitForTimeout(800);
      }

      // Click visible 'Enter code' / 'Next' / 'Continue' button
      const enterCodeBtn = container.locator("div[role='button']:visible:has-text('Enter code'), button:visible:has-text('Enter code'), div[role='button']:visible:has-text('Next'), button:visible:has-text('Next'), div[role='button']:visible:has-text('Continue')").first();
      console.log("[Facebook 2FA] Clicking visible 'Enter code' / 'Next' button...");
      await humanClick(page, enterCodeBtn).catch(() => enterCodeBtn.click());
      await page.waitForTimeout(4000);
      continue;
    }

    // State 5: "Get your code from your authentication app" (Enter 6-digit TOTP)
    if (currentText.includes("Get your code from your authentication app") || currentText.includes("Enter the 6-digit code") || currentText.includes("confirmation code")) {
      console.log("[Facebook 2FA - State 5] Found TOTP Entry screen!");
      if (!secretKey) throw new Error("Missing secret key for TOTP code generation!");

      // Wait for fresh 30-second window if near expiration (< 4s)
      const epochSec = Math.floor(Date.now() / 1000);
      const rem = 30 - (epochSec % 30);
      if (rem < 4) {
        console.log(`[Facebook 2FA] Waiting ${rem + 1}s for next fresh TOTP window...`);
        await page.waitForTimeout((rem + 1) * 1000);
      }

      const totpCode = generateTOTP(secretKey);
      console.log(`[Facebook 2FA] Generated TOTP Code (hidden).`);

      const textInput = container.locator("input[type='text']:visible, input:visible:not([type='submit']):not([type='radio']):not([type='checkbox']):not([type='password'])").first();
      await textInput.waitFor({ state: "visible", timeout: 15000 });
      await humanClick(page, textInput).catch(() => textInput.click());
      await textInput.fill("");
      await typeJittered(textInput, totpCode, 100, 24);
      await page.waitForTimeout(1000);

      const nextBtn = container.locator("div[role='button']:visible:has-text('Next'), button:visible:has-text('Next'), div[role='button']:visible:has-text('Continue'), button:visible:has-text('Continue')").first();
      console.log("[Facebook 2FA] Clicking 'Next' to verify TOTP code...");
      await humanClick(page, nextBtn).catch(() => nextBtn.click());
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
    if (currentText.includes("Done") && backupCodes.length > 0) {
      const doneBtn = container.locator("div[role='button']:visible:has-text('Done'), button:visible:has-text('Done')").first();
      if ((await doneBtn.count()) > 0 && (await doneBtn.isVisible())) {
        await humanClick(page, doneBtn).catch(() => doneBtn.click());
        await page.waitForTimeout(2000);
      }
      isDone = true;
      break;
    }

    console.log(`[Facebook 2FA] Waiting on screen state: "${currentText.slice(0, 100)}..."`);
    await page.waitForTimeout(3000);
  }

  // Final check: if backup codes are still missing, execute dedicated retrieval pass
  if (backupCodes.length === 0) {
    console.log("[Facebook 2FA] Backup codes not yet captured; executing dedicated pass...");
    backupCodes = await extractFacebookBackupCodesPass(page, password);
  }
  if (backupCodes.length > 0) confirmedOn = true;

  if (!confirmedOn) {
    const bodyText = (await page.locator("body").innerText().catch(() => "")).replace(/\s+/g, " ");
    if (/Two-factor authentication is on|Your two-factor authentication is set up|How you get login codes/i.test(bodyText)) {
      confirmedOn = true;
    }
  }

  const enabled = Boolean(secretKey && confirmedOn);
  const status = enabled
    ? (backupCodes.length > 0 ? "ACTIVE" : "ACTIVE_NO_BACKUP_CODES")
    : (confirmedOn && !secretKey
      ? "ALREADY_ENABLED_UNKNOWN_SECRET"
      : (secretKey && totpSubmitted ? "FAILED_VERIFICATION" : "FAILED_INCOMPLETE"));

  const finalRecord = {
    secret_key: secretKey,
    backup_codes: backupCodes,
    enabled,
    status,
  };

  updateFacebookAccountWith2FA(emailTarget, finalRecord, explicitProfileDir);

  await page.screenshot({ path: "tests/test_artifacts/fb_2fa_final_success.png" }).catch(() => {});
  console.log("=".repeat(60));
  console.log(`[Facebook 2FA] Completed! Enabled: ${enabled} | Status: ${status} | Backup Codes: ${backupCodes.length}`);
  console.log("=".repeat(60));

  return finalRecord;
}

// ----------------------------------------------------
// Standalone CLI Execution Mode
// ----------------------------------------------------
if (process.argv[1] && (process.argv[1].endsWith("setup_facebook_2fa.mjs") || process.argv[1].endsWith("setup_facebook_2fa"))) {
  const args = process.argv.slice(2);
  function getArg(name, defaultValue = null) {
    const idx = args.indexOf(name);
    return idx >= 0 && idx + 1 < args.length ? args[idx + 1] : defaultValue;
  }

  const explicitEmail = getArg("--email");
  const explicitPassword = getArg("--password");
  const explicitProxy = getArg("--proxy");
  const explicitProfile = getArg("--profile");

  let email = explicitEmail || "BurleighVandall804767@outlook.in";
  let password = explicitPassword || "Vandall$4767";

  const profileName = explicitProfile || email.split("@")[0].replace(/[^A-Za-z0-9._-]/g, "");
  const profileDir = path.resolve("output", "profiles facebook", profileName);

  let proxyArg = explicitProxy;
  let refreshToken = getArg("--refresh-token") || getArg("--token");
  let clientId = getArg("--client-id", "9e5f94bc-e8a4-4e73-b8be-63364c29d753");

  const accountInfoPath = path.join(profileDir, "account_info.json");
  if (fs.existsSync(accountInfoPath)) {
    try {
      const info = JSON.parse(fs.readFileSync(accountInfoPath, "utf-8"));
      password = password || info.password;
      refreshToken = info.refresh_token || refreshToken;
      clientId = info.client_id || clientId;
      proxyArg = proxyArg || info.proxy_used;
    } catch (e) { }
  }

  if (!proxyArg) {
    const accountsFile = path.resolve("output", "facebook_registered_accounts.json");
    if (fs.existsSync(accountsFile)) {
      try {
        const list = JSON.parse(fs.readFileSync(accountsFile, "utf-8"));
        const record = list.find((a) => (a && a.email ? a.email.toLowerCase() : "") === email.toLowerCase());
        if (record) {
          password = password || record.password;
          proxyArg = proxyArg || record.proxy_used;
        }
      } catch (e) { }
    }
  }

  if (!proxyArg) {
    proxyArg = "customer-resi_66c2a9b7-cc-in-city-ahmedabad:oMw6GpW~=ghV@pr.oxylabs.io:7777";
  }

  console.log(`[Facebook 2FA Standalone] Target: ${email} | Profile: ${profileDir}`);

  // Launch Camoufox
  let persona = {
    screen: SCREEN_RESOLUTIONS[0],
    webgl_config: GPU_CONFIGURATIONS[0],
    timezone: "Asia/Kolkata",
    locale: "en-US",
  };
  const personaFile = path.join(profileDir, "persona.json");
  if (fs.existsSync(personaFile)) {
    try {
      persona = JSON.parse(fs.readFileSync(personaFile, "utf-8"));
    } catch (e) { }
  }

  const browserConfig = {
    headless: false,
    locale: "en-US",
    geoip: false,
    os: "windows",
    screen: persona.screen,
    webgl_config: persona.webgl_config,
    firefox_user_prefs: {
      "intl.accept_languages": "en-US, en",
      "javascript.use_us_english_locale": true,
      "browser.toolbars.bookmarks.visibility": "always",
      "network.trr.mode": 5,
      "network.proxy.socks_remote_dns": true,
    },
  };

  if (proxyArg) {
    let clean = proxyArg.replace(/^https?:\/\//i, "");
    if (clean.includes("@")) {
      const [auth, hostPort] = clean.split("@");
      const [u, p] = auth.split(":");
      browserConfig.proxy = {
        server: `http://${hostPort}`,
        username: decodeURIComponent(u),
        password: decodeURIComponent(p),
      };
    } else {
      browserConfig.proxy = { server: `http://${clean}` };
    }
  }

  const browser = await Camoufox(browserConfig);
  const context = await browser.newContext({
    viewport: persona.screen,
    locale: "en-US",
  });
  const page = await context.newPage();

  try {
    await setupFacebook2FA(page, email, password, profileDir, clientId, refreshToken);
  } finally {
    console.log("[Facebook 2FA Standalone] Browser open for manual inspection.");
    await new Promise((r) => browser.on("close", r));
  }
}
