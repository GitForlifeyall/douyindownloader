#!/usr/bin/env node
/**
 * tools/metricool_camoufox.mjs
 * ============================
 * Anti-Detect Metricool Automation using Camoufox Browser (Firefox Anti-Detect Engine).
 * 
 * Capabilities:
 * - Anti-detect browser automation: spoofed canvas, WebGL, fonts, humanized cursor/mouse movement, Windows OS fingerprint.
 * - Actions supported:
 *     * 'signup' (--signup / --action signup): Full automated registration, email verification (Outlook or Temp-Mail.io), and complete onboarding survey completion.
 *     * 'login'  (--login  / --action login) : Automated login, 2FA/OTP code extraction, and session restoration.
 *     * 'open'   (--open   / --action open)  : Headed persistent browser launch into saved Metricool profile.
 * - Stores complete persistent profiles in:
 *     * 'output/profiles metricool/<account>/'
 *     * mirrored to 'profiles metricool/<account>/'
 * - Exports cookies.json, session_info.json, and appends to metricool_registered_accounts.json.
 */

import fs from "node:fs";
import path from "node:path";
import crypto from "node:crypto";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

// Import camoufox-js from local node_modules
import { Camoufox } from "./node_modules/camoufox-js/dist/index.js";
import { logToSupabase } from "./supabase_logger.mjs";

// Parse CLI arguments
const args = process.argv.slice(2);
function getArg(name, defaultValue = null) {
  const idx = args.indexOf(name);
  return idx >= 0 && idx + 1 < args.length ? args[idx + 1] : defaultValue;
}
const hasFlag = (name) => args.includes(name);

let action = getArg("--action");
if (hasFlag("--signup") || hasFlag("--register")) action = "signup";
else if (hasFlag("--login")) action = "login";
else if (hasFlag("--open")) action = "open";
if (!action) action = "login";

let email = getArg("--email");
let password = getArg("--password");
const profileDirArg = getArg("--profile-dir");
const clientId = getArg("--client-id");
const refreshToken = getArg("--refresh-token");
const DEFAULT_PROXY = "customer-resi_4edb25d7:fo4ENfj4pMx+@pr.oxylabs.io:7777";
const proxyArg = getArg("--proxy", DEFAULT_PROXY);
const exitIp = getArg("--exit-ip");
const tempMailFlag = hasFlag("--temp-mail");
const headless = hasFlag("--headless");

// Safe navigation wrapper with retry & residential proxy timeout buffer
async function safeGoto(page, url, options = { waitUntil: "domcontentloaded", timeout: 60000 }, maxRetries = 3) {
  for (let attempt = 1; attempt <= maxRetries; attempt++) {
    try {
      console.log(`[Navigation] Navigating to: ${url} (attempt ${attempt}/${maxRetries}, timeout: ${options.timeout || 60000}ms)...`);
      const resp = await page.goto(url, options);
      const curUrl = page.url() || "";
      if (curUrl.startsWith("about:neterror") || curUrl.startsWith("about:certerror")) {
        console.warn(`[Navigation] Landed on browser network error (${curUrl}). Retrying...`);
        const tryAgainBtn = page.locator("#errorTryAgain, button:has-text('Try Again')").first();
        if ((await tryAgainBtn.count()) > 0) {
          await tryAgainBtn.click().catch(() => { });
          await page.waitForTimeout(4000);
        }
      }
      return resp;
    } catch (err) {
      console.warn(`[Navigation] Attempt ${attempt}/${maxRetries} failed: ${err.message}`);
      if (attempt === maxRetries) {
        throw err;
      }
      try {
        const tryAgainBtn = page.locator("#errorTryAgain, button:has-text('Try Again')").first();
        if ((await tryAgainBtn.count()) > 0 && (await tryAgainBtn.isVisible().catch(() => false))) {
          await tryAgainBtn.click().catch(() => { });
          await page.waitForTimeout(3000);
        }
      } catch (e) { }
      await page.waitForTimeout(3000);
    }
  }
}

// Helper to parse proxy string (user:pass@host:port)
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

const OUTPUT_PROFILES_DIR = path.resolve("output", "profiles metricool");
const ROOT_PROFILES_DIR = path.resolve("profiles metricool");
const REGISTERED_ACCOUNTS_FILE = path.resolve("output", "metricool_registered_accounts.json");
const TEMP_MAIL_TOKENS_FILE = path.resolve("output", "temp_mail_tokens.json");

// Generate secure random password
function generateSecurePassword() {
  const chars = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789!@#$%^&*";
  let pwd = "";
  for (let i = 0; i < 16; i++) {
    pwd += chars.charAt(crypto.randomInt(chars.length));
  }
  return pwd + "A1!";
}

// Ensures password strictly satisfies Metricool policy: 8-20 chars, uppercase, lowercase, digit, symbol
function ensureMetricoolPasswordPolicy(pwd) {
  if (!pwd || pwd.length < 8) return generateSecurePassword();
  let res = pwd;
  if (!/[A-Z]/.test(res)) res = "M" + res;
  if (!/[a-z]/.test(res)) res = res + "a";
  if (!/[0-9]/.test(res)) res = res + "1";
  if (!/[!@#$%^&*()_+\-=\[\]{};':"\\|,.<>\/?]/.test(res)) res = res + "!";
  if (res.length > 20) res = res.substring(0, 19) + "!";
  return res;
}

// Helper to take and mirror debug screenshots
async function saveScreenshot(page, name) {
  try {
    const dir1 = path.resolve(process.cwd(), "tests", "test_artifacts");
    if (!fs.existsSync(dir1)) fs.mkdirSync(dir1, { recursive: true });
    const p1 = path.join(dir1, name);
    await page.screenshot({ path: p1, fullPage: true });
    console.log(`[Screenshot] Saved: ${p1}`);

    const brainDir = "C:\\Users\\shahi\\.gemini\\antigravity\\brain\\cb9ddda6-74f0-4932-b420-96a452c83d2b";
    if (fs.existsSync(brainDir)) {
      const p2 = path.join(brainDir, name);
      fs.copyFileSync(p1, p2);
    }
  } catch (err) {
    console.warn(`[Screenshot Warning]: Failed to capture ${name}: ${err.message}`);
  }
}

// Generate temp mailbox on clean domain via Temp-Mail.io
async function createTempMailbox() {
  console.log("[Camoufox] Generating clean temporary mailbox on @lnovic.com...");
  const name = "user_" + crypto.randomBytes(4).toString("hex");
  const payload = { name, domain: "lnovic.com" };

  const res = await fetch("https://api.internal.temp-mail.io/api/v3/email/new", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
      "Accept": "application/json, text/plain, */*",
    },
    body: JSON.stringify(payload),
  });
  const data = await res.json();
  const address = data.email;
  const token = data.token;
  const pwd = generateSecurePassword();

  // Save to temp_mail_tokens.json
  try {
    fs.mkdirSync(path.dirname(TEMP_MAIL_TOKENS_FILE), { recursive: true });
    let vault = [];
    if (fs.existsSync(TEMP_MAIL_TOKENS_FILE)) {
      vault = JSON.parse(fs.readFileSync(TEMP_MAIL_TOKENS_FILE, "utf-8"));
    }
    vault = vault.filter((v) => v.address !== address);
    vault.push({
      address,
      password: pwd,
      token,
      account_id: token,
      domain: "lnovic.com",
      created_at: new Date().toISOString(),
      service: "temp-mail.io",
    });
    fs.writeFileSync(TEMP_MAIL_TOKENS_FILE, JSON.stringify(vault, null, 2), "utf-8");
  } catch (err) {
    console.warn(`[Camoufox] Note saving temp token: ${err.message}`);
  }

  return { email: address, password: pwd, token };
}

// Poll Temp-Mail.io for verification link or OTP code
async function pollTempMailVerification(targetEmail, maxWaitSec = 60) {
  console.log(`[Camoufox] Polling Temp-Mail inbox for ${targetEmail}...`);
  const startTime = Date.now();

  while (Date.now() - startTime < maxWaitSec * 1000) {
    try {
      const url = `https://api.internal.temp-mail.io/api/v3/email/${targetEmail}/messages`;
      const res = await fetch(url, {
        headers: {
          "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
          "Accept": "application/json, text/plain, */*",
        },
      });
      const msgs = await res.json();

      if (Array.isArray(msgs) && msgs.length > 0) {
        for (const m of msgs) {
          const subject = m.subject || "";
          const body = (m.body_text || "") + " " + (m.body_html || "") + " " + (m.intro || "");
          const full = `${subject} ${body}`;

          if (full.toLowerCase().includes("metricool")) {
            console.log(`[Camoufox] Received Metricool email: '${subject}'`);

            // 1. Activation Link
            const linkMatch = body.match(/https?:\/\/[^\s"'<>]*(?:verify|confirm|activate|register|token)[^\s"'<>]*/i);
            if (linkMatch) {
              const cleanLink = linkMatch[0].replace(/&amp;/g, "&");
              console.log(`[Camoufox] Extracted activation link: ${cleanLink}`);
              return { type: "link", data: cleanLink };
            }

            // 2. OTP Code (6 digits)
            const codeMatch = full.match(/\b(\d{6})\b/);
            if (codeMatch) {
              console.log(`[Camoufox] Extracted 6-digit OTP code: ${codeMatch[1]}`);
              return { type: "code", data: codeMatch[1] };
            }
          }
        }
      }
    } catch (e) {
      console.warn(`[Camoufox] Inbox poll note: ${e.message}`);
    }
    await new Promise((r) => setTimeout(r, 3000));
  }
  return null;
}

// MS OAuth2 helpers for Outlook
async function getMsAccessToken(cId, rToken) {
  const tokenUrl = "https://login.microsoftonline.com/consumers/oauth2/v2.0/token";
  const params = new URLSearchParams({
    client_id: cId,
    grant_type: "refresh_token",
    refresh_token: rToken,
  });
  const res = await fetch(tokenUrl, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: params.toString(),
  });
  const data = await res.json();
  if (data.error) {
    throw new Error(`Microsoft OAuth error: ${data.error_description || data.error}`);
  }
  const scope = data.scope || "";
  const isOutlookApi = scope.includes("outlook.office.com");
  return { token: data.access_token, isOutlookApi };
}

async function pollOutlookVerification(cId, rToken, maxWaitSec = 60) {
  console.log("[Camoufox] Polling Outlook inbox for verification email...");
  const startTime = Date.now();

  while (Date.now() - startTime < maxWaitSec * 1000) {
    try {
      const { token, isOutlookApi } = await getMsAccessToken(cId, rToken);
      const url = isOutlookApi
        ? "https://outlook.office.com/api/v2.0/me/messages?$top=5&$select=Subject,BodyPreview,Body&$orderby=ReceivedDateTime%20desc"
        : "https://graph.microsoft.com/v1.0/me/messages?$top=5&$select=subject,bodyPreview,body&$orderby=receivedDateTime%20desc";
      const resp = await fetch(url, {
        headers: { Authorization: `Bearer ${token}`, Accept: "application/json" },
      });
      const data = await resp.json();
      const messages = data.value || [];

      for (const m of messages) {
        const subject = m.Subject || m.subject || "";
        const preview = m.BodyPreview || m.bodyPreview || "";
        const bodyObj = m.Body || m.body;
        const content = typeof bodyObj === "object" ? (bodyObj.Content || bodyObj.content || "") : (bodyObj || "");
        const full = `${subject} ${preview} ${content}`;

        if (full.toLowerCase().includes("metricool")) {
          console.log(`[Camoufox] Received Outlook email: '${subject}'`);

          // 1. Activation link
          const linkMatch = (content || preview).match(/https?:\/\/[^\s"'<>]*(?:verify|confirm|activate|register|token)[^\s"'<>]*/i);
          if (linkMatch) {
            const cleanLink = linkMatch[0].replace(/&amp;/g, "&");
            return { type: "link", data: cleanLink };
          }

          // 2. OTP Code
          const codeMatch = full.match(/\b(\d{6})\b/);
          if (codeMatch) {
            return { type: "code", data: codeMatch[1] };
          }
        }
      }
    } catch (err) {
      console.warn(`[Camoufox] Outlook poll note: ${err.message}`);
    }
    await new Promise((r) => setTimeout(r, 4000));
  }
  return null;
}

// Complete all Metricool multi-step onboarding survey dialogs
async function handleMetricoolOnboarding(page, maxWaitMs = 35000) {
  console.log("[Camoufox] Checking for Metricool onboarding survey dialogs...");
  const startTime = Date.now();
  await page.waitForTimeout(2000);

  while (Date.now() - startTime < maxWaitMs) {
    const pageHtml = await page.content();

    // Dialog 4 confirmation check first (in case it appeared over Dialog 3)
    if (pageHtml.includes("Wait! Are you sure you want to leave?") || (pageHtml.includes("Cancel") && pageHtml.includes("Accept"))) {
      console.log("[Onboarding] Dialog 4 confirmation modal detected...");
      const acceptBtn = page.locator("button:has-text('Accept')").first();
      if ((await acceptBtn.count()) > 0 && (await acceptBtn.isVisible())) {
        console.log("[Onboarding] Clicking Accept button...");
        await acceptBtn.click({ force: true });
        await page.waitForTimeout(3000);
        continue;
      }
    }

    // Dialog 1: "What describes you best?"
    if (pageHtml.includes("What describes you best?")) {
      console.log("[Onboarding] Dialog 1 detected: 'What describes you best?'");

      const agencyCard = page.locator("text='Marketing agency'").first();
      const creatorCard = page.locator("text='Content creator'").first();
      if ((await agencyCard.count()) > 0 && (await agencyCard.isVisible())) {
        await agencyCard.click({ force: true });
      } else if ((await creatorCard.count()) > 0 && (await creatorCard.isVisible())) {
        await creatorCard.click({ force: true });
      }
      await page.waitForTimeout(400);

      const justMe = page.locator("text='Just me'").first();
      if ((await justMe.count()) > 0 && (await justMe.isVisible())) {
        await justMe.click({ force: true });
      }
      await page.waitForTimeout(400);

      const contBtn = page.locator("button:has-text('Continue')").first();
      if ((await contBtn.count()) > 0 && (await contBtn.isVisible())) {
        console.log("[Onboarding] Clicking Continue on Dialog 1...");
        await contBtn.click({ force: true });
        await page.waitForTimeout(3000);
      }
      continue;
    }

    // Dialog 2: "How are you going to use Metricool?"
    if (pageHtml.includes("How are you going to use Metricool?")) {
      console.log("[Onboarding] Dialog 2 detected: 'How are you going to use Metricool?'");
      const prog = page.locator("text='Programming and publishing of content'").first();
      if ((await prog.count()) > 0 && (await prog.isVisible())) {
        await prog.click({ force: true });
        await page.waitForTimeout(400);
      }

      const cont2 = page.locator("button:has-text('Continue')").last();
      if ((await cont2.count()) > 0 && (await cont2.isVisible())) {
        console.log("[Onboarding] Clicking Continue on Dialog 2...");
        await cont2.click({ force: true });
        await page.waitForTimeout(3000);
      }
      continue;
    }

    // Dialog 3: "Connect your social networks"
    if (pageHtml.includes("Connect your social networks")) {
      console.log("[Onboarding] Dialog 3 detected: 'Connect your social networks'");
      const finishBtn = page.locator("button:has-text('Finish')").last();
      if ((await finishBtn.count()) > 0 && (await finishBtn.isVisible())) {
        console.log("[Onboarding] Clicking Finish on Dialog 3...");
        await finishBtn.click({ force: true });
        await page.waitForTimeout(3000);
      }
      continue;
    }

    // Dismiss tour and welcome modals
    let tourDismissed = false;
    for (const text of ["Skip tour", "Skip", "Got it", "Understood", "Close", "Accept all"]) {
      const btn = page.locator(`button:has-text('${text}')`).first();
      if ((await btn.count()) > 0 && (await btn.isVisible())) {
        console.log(`[Onboarding] Dismissing modal with button: '${text}'`);
        await btn.click({ force: true });
        await page.waitForTimeout(1000);
        tourDismissed = true;
        break;
      }
    }
    if (tourDismissed) continue;

    // Check if overlays are gone
    const activeOverlays = page.locator(".v-overlay--active .v-dialog");
    if ((await activeOverlays.count()) === 0) {
      console.log("[Onboarding] All onboarding dialogs dismissed.");
      break;
    }

    await page.waitForTimeout(1500);
  }
}

// Save account to output/metricool_registered_accounts.json
function saveRegisteredAccount(rec) {
  try {
    fs.mkdirSync(path.dirname(REGISTERED_ACCOUNTS_FILE), { recursive: true });
    let existing = [];
    if (fs.existsSync(REGISTERED_ACCOUNTS_FILE)) {
      existing = JSON.parse(fs.readFileSync(REGISTERED_ACCOUNTS_FILE, "utf-8"));
      if (!Array.isArray(existing)) existing = [];
    }
    existing = existing.filter((a) => a.email !== rec.email);
    existing.push(rec);
    fs.writeFileSync(REGISTERED_ACCOUNTS_FILE, JSON.stringify(existing, null, 2), "utf-8");
    console.log(`[Camoufox] Saved credentials to: ${REGISTERED_ACCOUNTS_FILE}`);
  } catch (err) {
    console.warn(`[Camoufox] Note saving registered account: ${err.message}`);
  }
}

// Open Facebook in a second tab and click "Sign Up" / "Create new account"
async function openFacebookSignUpTab(context) {
  console.log("[Camoufox] Opening second tab for Facebook (https://www.facebook.com)...");
  const fbPage = await context.newPage();
  await safeGoto(fbPage, "https://www.facebook.com/");
  await fbPage.waitForTimeout(2500);

  // Cookie banner dismissal
  const cookieBtn = fbPage.locator("button:has-text('Allow all cookies'), button:has-text('Allow essential and optional cookies'), button:has-text('Decline optional cookies'), [aria-label='Allow all cookies']");
  if ((await cookieBtn.count()) > 0 && (await cookieBtn.first().isVisible())) {
    console.log("[Facebook] Dismissing cookie dialog...");
    await cookieBtn.first().click({ force: true }).catch(() => { });
    await fbPage.waitForTimeout(1500);
  }

  // Click "Create new account" / Sign Up
  const signUpBtn = fbPage.locator("a:has-text('Create new account'), button:has-text('Create new account'), a:has-text('Sign Up'), [data-testid='open-registration-form-button']");
  if ((await signUpBtn.count()) > 0) {
    console.log("[Facebook] Clicking 'Create new account' button...");
    await signUpBtn.first().click({ force: true }).catch(() => { });
    await fbPage.waitForTimeout(3000);
  } else {
    console.log("[Facebook] Navigating to registration page directly...");
    await safeGoto(fbPage, "https://www.facebook.com/reg/?entry_point=login");
    await fbPage.waitForTimeout(3000);
  }

  console.log(`[Facebook] Registration tab active: ${fbPage.url()} (${await fbPage.title()})`);
  return fbPage;
}

async function main() {
  let tempToken = null;

  // If signup mode and no email provided or temp-mail requested
  if (action === "signup" && (!email || tempMailFlag)) {
    const mb = await createTempMailbox();
    email = mb.email;
    password = mb.password;
    tempToken = mb.token;
  }

  if (!email && action !== "open") {
    console.error("Error: --email or --temp-mail required.");
    process.exit(1);
  }

  const stem = email ? email.split("@")[0].replace(/[^\w\-]/g, "_") : "default";
  const profileDir = path.resolve(profileDirArg || path.join(OUTPUT_PROFILES_DIR, stem));
  const rootMirrorDir = path.resolve(ROOT_PROFILES_DIR, stem);

  fs.mkdirSync(profileDir, { recursive: true });
  fs.mkdirSync(rootMirrorDir, { recursive: true });

  const explicitTz = getArg("--timezone");
  const derivedTz = deriveTimezoneFromProxy(proxyArg);
  const chosenTz = explicitTz || (proxyArg.includes("-cc-") ? derivedTz.tz : derivedTz.tz);
  const chosenRegion = derivedTz.region;
  const chosenLang = derivedTz.lang;

  const personaPath = path.join(profileDir, "persona.json");
  let persona = null;
  if (fs.existsSync(personaPath)) {
    try {
      persona = JSON.parse(fs.readFileSync(personaPath, "utf-8"));
      if (persona.timezone !== chosenTz) {
        persona.timezone = chosenTz;
        persona["locale:region"] = chosenRegion;
        persona["locale:language"] = chosenLang;
        fs.writeFileSync(personaPath, JSON.stringify(persona, null, 2), "utf-8");
      }
    } catch (e) { }
  }

  console.log("=".repeat(60));
  console.log(`[Camoufox] ACTION:       ${action.toUpperCase()}`);
  console.log(`[Camoufox] EMAIL:        ${email}`);
  console.log(`[Camoufox] PROFILE DIR:  ${profileDir}`);
  console.log(`[Camoufox] TIMEZONE:     ${chosenTz} (${chosenRegion})`);
  console.log(`[Camoufox] HEADLESS:     ${headless}`);
  console.log("=".repeat(60));

  console.log("[Camoufox] Launching Camoufox anti-detect browser (Windows OS fingerprint & humanized cursor)...");
  const browserConfig = {
    user_data_dir: profileDir,
    headless: headless,
    os: "windows",
    humanize: true,
    block_webrtc: true,
    iKnowWhatImDoing: true,
    locale: `${chosenLang}-${chosenRegion}`,
    config: {
      timezone: chosenTz,
      "locale:region": chosenRegion,
      "locale:language": chosenLang,
      "locale:all": `${chosenLang}-${chosenRegion}, ${chosenLang}`,
      ...(persona && persona["canvas:seed"] ? {
        "canvas:seed": persona["canvas:seed"],
        "audio:seed": persona["audio:seed"],
        "fonts:spacing_seed": persona["fonts:spacing_seed"],
      } : {})
    }
  };
  const parsedProxy = parseProxy(proxyArg);
  if (parsedProxy) {
    console.log(`[Camoufox] Activating Residential Proxy: ${parsedProxy.server} (User: ${parsedProxy.username})...`);
    browserConfig.proxy = parsedProxy;
    if (exitIp) {
      console.log(`[Camoufox] Pinned verified exit IP: ${exitIp} (local GeoIP database alignment)`);
      browserConfig.geoip = exitIp;
    } else {
      browserConfig.geoip = false; // Timezone & locale already explicitly aligned above; avoids external Impit IP check timeouts
    }
  }
  const context = await Camoufox(browserConfig);

  const page = await context.newPage();

  try {
    // =========================================================================
    // ACTION: OPEN (Interactive Profile Viewer)
    // =========================================================================
    if (action === "open") {
      console.log("[Camoufox] Tab 1: Launching directly into saved dashboard: https://app.metricool.com/...");
      await safeGoto(page, "https://app.metricool.com/");
      console.log(`[Camoufox] Tab 1 ready: ${page.url()} (${await page.title()})`);

      // Tab 2: Open Facebook and click Sign Up
      await openFacebookSignUpTab(context);

      console.log("[Camoufox] Both tabs are active (Tab 1: Metricool, Tab 2: Facebook Sign Up).");
      console.log("[Camoufox] Browser will remain open for your inspection. Close the browser window when you are done.");
      await new Promise((resolve) => {
        context.on("close", resolve);
        page.on("close", () => {
          try {
            if (context.pages().length === 0) resolve();
          } catch (e) {
            resolve();
          }
        });
      });
      await context.close();
      return;
    }

    // =========================================================================
    // ACTION: SIGNUP
    // =========================================================================
    if (action === "signup") {
      console.log("[Camoufox] Navigating to registration page: https://app.metricool.com/register...");
      await safeGoto(page, "https://app.metricool.com/register");
      await page.waitForTimeout(3000);
      await saveScreenshot(page, "metricool_01_initial_page.png");

      const emailField = page.locator("input.v-field__input[name='email']");
      const passField = page.locator("input.v-field__input[name='password']");
      const submitBtn = page.locator("button:has-text('Start for free')");

      password = ensureMetricoolPasswordPolicy(password);

      await emailField.waitFor({ state: "visible", timeout: 35000 });
      console.log(`[Camoufox] Entering signup credentials for: ${email}...`);
      await emailField.click({ force: true }).catch(() => emailField.focus());
      await emailField.fill("");
      await page.keyboard.type(email, { delay: 40 });
      await page.waitForTimeout(300);

      await passField.click({ force: true }).catch(() => passField.focus());
      await passField.fill("");
      await page.keyboard.type(password, { delay: 50 });
      await page.waitForTimeout(500);

      // Verify no password validation warning
      const errorMsg = page.locator(".v-messages__message, .v-input--error");
      if ((await errorMsg.count()) > 0 && (await errorMsg.first().isVisible())) {
        const text = await errorMsg.first().textContent();
        if (text && text.toLowerCase().includes("password")) {
          console.warn(`[Camoufox] Detected password field requirement note: '${text.trim()}'. Regenerating strict password...`);
          password = generateSecurePassword();
          await passField.click({ force: true }).catch(() => passField.focus());
          await passField.fill("");
          await page.keyboard.type(password, { delay: 50 });
          await page.waitForTimeout(500);
        }
      }

      await saveScreenshot(page, "metricool_02_filled_credentials.png");

      // Check consent checkboxes by clicking the Vuetify selection control once
      await page.waitForTimeout(500);
      const isCheckedBefore = await page.evaluate(() => {
        const input = document.querySelector(".v-checkbox input[type='checkbox']");
        return input ? input.checked : false;
      });
      console.log(`[Camoufox] Consent checkbox checked before click: ${isCheckedBefore}`);
      if (!isCheckedBefore) {
        const cbControl = page.locator(".v-checkbox .v-selection-control").first();
        if (await cbControl.count() > 0) {
          console.log("[Camoufox] Clicking Vuetify .v-selection-control...");
          await cbControl.click({ force: true }).catch(() => { });
        } else {
          const cbLabel = page.locator("label:has-text('Legal Terms')").first();
          if (await cbLabel.count() > 0) {
            console.log("[Camoufox] Clicking Vuetify Legal Terms label...");
            await cbLabel.click({ force: true }).catch(() => { });
          }
        }
      }
      await page.waitForTimeout(600);

      // Verify button is enabled
      let btnState = await page.evaluate(() => {
        const b = Array.from(document.querySelectorAll("button")).find(x => x.innerText.includes("Start for free"));
        return { disabled: b?.disabled, classes: b?.className };
      });
      console.log(`[Camoufox] 'Start for free' button state: disabled=${btnState?.disabled}`);
      if (btnState?.disabled) {
        console.warn("[Camoufox] Button still disabled! Trying alternate click on checkbox label...");
        const label = page.locator(".v-checkbox label, label:has-text('Legal Terms')").first();
        if (await label.count() > 0) {
          await label.click({ force: true }).catch(() => { });
          await page.waitForTimeout(600);
          btnState = await page.evaluate(() => {
            const b = Array.from(document.querySelectorAll("button")).find(x => x.innerText.includes("Start for free"));
            return { disabled: b?.disabled, classes: b?.className };
          });
          console.log(`[Camoufox] Retried button state: disabled=${btnState?.disabled}`);
        }
      }

      await saveScreenshot(page, "metricool_03_checkbox_clicked.png");

      console.log("[Camoufox] Submitting registration form ('Start for free')...");
      if ((await submitBtn.count()) > 0) {
        await submitBtn.click({ force: true }).catch(() => { });
      }
      await page.keyboard.press("Enter");
      await page.evaluate(() => {
        const form = document.querySelector("form");
        if (form) form.requestSubmit();
      }).catch(() => { });
      await page.waitForTimeout(5000);

      await saveScreenshot(page, "metricool_04_submitted.png");

      console.log(`[Camoufox] Form submitted. Current URL: ${page.url()}`);

      // Poll verification (Temp-Mail or Outlook)
      let verification = null;
      if (clientId && refreshToken) {
        verification = await pollOutlookVerification(clientId, refreshToken, 60);
      } else {
        verification = await pollTempMailVerification(email, 60);
      }

      if (verification && verification.type === "link") {
        console.log(`[Camoufox] Navigating to activation link: ${verification.data}...`);
        await safeGoto(page, verification.data);
        await page.waitForTimeout(5000);
      } else if (verification && verification.type === "code") {
        console.log(`[Camoufox] Injecting 6-digit OTP code: ${verification.data}...`);
        await page.evaluate((otp) => {
          const inputs = document.querySelectorAll("input[name='otp'], .v-otp-input input, input.v-field__input");
          if (inputs.length >= 6) {
            for (let i = 0; i < 6; i++) {
              inputs[i].value = otp[i];
              inputs[i].dispatchEvent(new Event("input", { bubbles: true }));
              inputs[i].dispatchEvent(new Event("change", { bubbles: true }));
            }
          } else if (inputs.length > 0) {
            inputs[0].value = otp;
            inputs[0].dispatchEvent(new Event("input", { bubbles: true }));
            inputs[0].dispatchEvent(new Event("change", { bubbles: true }));
          }
        }, verification.data);
        await page.keyboard.type(verification.data, { delay: 100 });
        await page.waitForTimeout(1000);

        const confirmBtn = page.locator("button:has-text('Confirm code'), button:has-text('Verify')");
        if ((await confirmBtn.count()) > 0) {
          await confirmBtn.first().click({ force: true });
        } else {
          await page.keyboard.press("Enter");
        }
        await page.waitForTimeout(4000);
      }

      // Complete all 4 onboarding survey dialogs
      await handleMetricoolOnboarding(page);
    }

    // =========================================================================
    // ACTION: LOGIN
    // =========================================================================
    if (action === "login") {
      console.log("[Camoufox] Navigating to login page: https://app.metricool.com/login...");
      await safeGoto(page, "https://app.metricool.com/login");
      await page.waitForTimeout(3000);

      const emailField = page.locator("input.v-field__input[name='email']");
      const passField = page.locator("input.v-field__input[name='password']");
      const accessBtn = page.locator("button:has-text('Access')");

      if ((await emailField.isVisible()) && (await passField.isVisible())) {
        console.log(`[Camoufox] Entering login credentials for: ${email}...`);
        await emailField.click({ force: true }).catch(() => emailField.focus());
        await emailField.fill(email);
        await page.waitForTimeout(300);

        await passField.click({ force: true }).catch(() => passField.focus());
        await passField.fill(password);
        await page.waitForTimeout(400);

        console.log("[Camoufox] Submitting login form ('Access')...");
        await accessBtn.click({ force: true }).catch(() => { });
        await page.waitForTimeout(4000);
      }

      // 2FA / Email OTP challenge
      const otpContainer = page.locator("input[name='otp'], .v-otp-input, input.v-otp-input__field");
      if ((await otpContainer.count()) > 0 || page.url().includes("login")) {
        console.log("[Camoufox] Email verification challenge detected.");
        let code = null;
        if (clientId && refreshToken) {
          const res = await pollOutlookVerification(clientId, refreshToken, 60);
          code = res?.data;
        } else {
          const res = await pollTempMailVerification(email, 60);
          code = res?.data;
        }

        if (code) {
          console.log(`[Camoufox] Auto-injecting OTP code: ${code}...`);
          await page.evaluate((otp) => {
            const inputs = document.querySelectorAll("input[name='otp'], .v-otp-input input, input.v-field__input");
            if (inputs.length >= 6) {
              for (let i = 0; i < 6; i++) {
                inputs[i].value = otp[i];
                inputs[i].dispatchEvent(new Event("input", { bubbles: true }));
                inputs[i].dispatchEvent(new Event("change", { bubbles: true }));
              }
            } else if (inputs.length > 0) {
              inputs[0].value = otp;
              inputs[0].dispatchEvent(new Event("input", { bubbles: true }));
              inputs[0].dispatchEvent(new Event("change", { bubbles: true }));
            }
          }, code);

          await page.keyboard.type(code, { delay: 100 });
          await page.waitForTimeout(1000);

          const confirmBtn = page.locator("button:has-text('Confirm code'), button:has-text('Verify')");
          if ((await confirmBtn.count()) > 0) {
            await confirmBtn.first().click({ force: true }).catch(() => { });
          } else {
            await page.keyboard.press("Enter");
          }
          await page.waitForTimeout(5000);
        } else {
          console.log("[Camoufox] No OTP received. Waiting 15s for manual confirmation...");
          await page.waitForTimeout(15000);
        }
      }

      // Dismiss any onboarding dialogs if they appear on login
      await handleMetricoolOnboarding(page);
    }

    // =========================================================================
    // EXPORT PERSISTENT PROFILE & COOKIES
    // =========================================================================
    const finalUrl = page.url();
    const finalTitle = await page.title();
    console.log(`[Camoufox] Final URL: ${finalUrl} | Title: '${finalTitle}'`);

    const cookies = await context.cookies();
    const cookiesPath = path.join(profileDir, "cookies.json");
    fs.writeFileSync(cookiesPath, JSON.stringify(cookies, null, 2), "utf-8");
    console.log(`[Camoufox] Saved ${cookies.length} session cookies to: ${cookiesPath}`);

    const status = finalUrl.includes("brandSummary") || (finalUrl.includes("app.metricool.com") && !finalUrl.includes("login") && !finalUrl.includes("register"))
      ? "logged_in"
      : "partial";

    const sessionData = {
      email,
      password,
      status,
      dashboard_url: finalUrl,
      cookies_count: cookies.length,
      profile_path: profileDir,
      saved_at: new Date().toISOString(),
      engine: "camoufox_antidetect",
    };
    if (tempToken) sessionData.temp_mail_token = tempToken;

    fs.writeFileSync(path.join(profileDir, "session_info.json"), JSON.stringify(sessionData, null, 2), "utf-8");

    // Mirror to root 'profiles metricool'
    try {
      fs.writeFileSync(path.join(rootMirrorDir, "cookies.json"), JSON.stringify(cookies, null, 2), "utf-8");
      fs.writeFileSync(path.join(rootMirrorDir, "session_info.json"), JSON.stringify(sessionData, null, 2), "utf-8");
    } catch (e) { }

    // Save to master accounts registry
    saveRegisteredAccount(sessionData);

    // Synchronize to Supabase cloud database
    try {
      await logToSupabase({
        platform: "METRICOOL",
        email,
        username: email.split("@")[0],
        password,
        profile_url: finalUrl,
        full_mail_string: (clientId && refreshToken) ? `${email}|${password}|${refreshToken}|${clientId}` : "",
        proxy: proxyArg,
        status: status === "logged_in" ? "ACTIVE" : "FAILED",
        details: sessionData
      });
    } catch (err) {
      console.warn(`[Supabase] Metricool sync note: ${err.message}`);
    }

    console.log("\n" + "=".repeat(60));
    console.log("CAMOUFOX METRICOOL AUTOMATION RESULT:");
    console.log("=".repeat(60));
    console.log(`Email:        ${email}`);
    console.log(`Password:     ${password}`);
    console.log(`Status:       ${status}`);
    console.log(`Cookies:      ${cookies.length}`);
    console.log(`Dashboard:    ${finalUrl}`);
    console.log(`Profile Dir:  ${profileDir}`);
    console.log(`Mirrored:     ${rootMirrorDir}`);
    console.log("=".repeat(60));

    // Keep browser open for user inspection
    if (!headless) {
      console.log("\n" + "=".repeat(60));
      console.log("[Camoufox] Browser will remain open for your inspection.");
      console.log("[Camoufox] Check the Metricool profile, settings, and connections.");
      console.log("[Camoufox] Close the browser window when you are done.");
      console.log("=".repeat(60) + "\n");
      await new Promise((resolve) => {
        context.on("close", resolve);
        page.on("close", () => {
          try {
            if (context.pages().length === 0) resolve();
          } catch (e) {
            resolve();
          }
        });
      });
    }

  } catch (err) {
    console.error(`[Camoufox Error]: ${err.message || err}`);
    if (!headless && context) {
      console.log("\n" + "=".repeat(60));
      console.log("[Camoufox] An issue occurred, but browser will stay open for inspection.");
      console.log("[Camoufox] You can inspect the screen or complete any manual steps.");
      console.log("[Camoufox] Close the browser window when you are done.");
      console.log("=".repeat(60) + "\n");
      await new Promise((resolve) => {
        context.on("close", resolve);
        page.on("close", () => {
          try {
            if (context.pages().length === 0) resolve();
          } catch (e) {
            resolve();
          }
        });
      });
    }
    throw err;
  } finally {
    await context.close().catch(() => { });
  }
}

main().catch(async (err) => {
  console.error(`[Camoufox Error]: ${err.stack || err}`);
  try {
    if (email) {
      await logToSupabase({
        platform: "METRICOOL",
        email,
        proxy: proxyArg,
        status: "FAILED",
        details: { error: err.message || String(err) }
      }).catch(() => { });
    }
  } catch (e) { }
  process.exit(1);
});
