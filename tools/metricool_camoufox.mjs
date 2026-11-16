#!/usr/bin/env node
/**
 * tools/metricool_camoufox.js
 * ===========================
 * Automated Metricool Login & Persistent Profile Manager using Camoufox Anti-Detect Browser.
 * 
 * Features:
 * - Uses Camoufox (stealth Firefox anti-detect engine with Windows fingerprint & humanized cursor).
 * - Stores complete persistent profile into 'output/profiles metricool/<account>/'.
 * - Automated 2FA/Email verification code polling via Microsoft Graph API.
 * - Exports cookies.json and session_info.json.
 * - Supports --open to launch directly into an existing logged-in session.
 */

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

// Import camoufox-js
const CAMOUFOX_PATH = "file:///C:/Users/rudra/AppData/Roaming/npm/node_modules/camoufox-cli/node_modules/camoufox-js/dist/index.js";
const { Camoufox } = await import(CAMOUFOX_PATH);

// Parse CLI arguments
const args = process.argv.slice(2);
function getArg(name, defaultValue = null) {
  const idx = args.indexOf(name);
  return idx >= 0 && idx + 1 < args.length ? args[idx + 1] : defaultValue;
}
const hasFlag = (name) => args.includes(name);

const email = getArg("--email");
const password = getArg("--password");
const profileDirArg = getArg("--profile-dir");
const clientId = getArg("--client-id");
const refreshToken = getArg("--refresh-token");
const headless = hasFlag("--headless");
const openOnly = hasFlag("--open");

if (!email && !profileDirArg) {
  console.error("Usage: node tools/metricool_camoufox.js --email <email> [--password <pwd>] [--profile-dir <dir>] [--client-id <id>] [--refresh-token <token>] [--headless] [--open]");
  process.exit(1);
}

const stem = email ? email.split("@")[0].replace(/[^\w\-]/g, "_") : "default";
const profileDir = path.resolve(profileDirArg || path.join("output", "profiles metricool", stem));
fs.mkdirSync(profileDir, { recursive: true });

// Mirror directory to root 'profiles metricool'
const rootMirrorDir = path.resolve(path.join("profiles metricool", stem));
fs.mkdirSync(rootMirrorDir, { recursive: true });

console.log(`[Camoufox] Target Profile Directory: ${profileDir}`);

async function getMsAccessToken(cId, rToken) {
  const tokenUrl = "https://login.microsoftonline.com/consumers/oauth2/v2.0/token";
  const params = new URLSearchParams({
    client_id: cId,
    grant_type: "refresh_token",
    refresh_token: rToken,
    scope: "https://graph.microsoft.com/Mail.Read offline_access",
  });
  const res = await fetch(tokenUrl, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: params.toString(),
  });
  const data = await res.json();
  return data.access_token;
}

async function pollOutlookOtp(cId, rToken, maxWaitSec = 60) {
  console.log("[Camoufox] Polling Outlook for Metricool verification OTP code...");
  const startTime = Date.now();
  while (Date.now() - startTime < maxWaitSec * 1000) {
    try {
      const accessToken = await getMsAccessToken(cId, rToken);
      const url = "https://graph.microsoft.com/v1.0/me/messages?$top=3&$select=subject,bodyPreview,body&$orderby=receivedDateTime%20desc";
      const resp = await fetch(url, {
        headers: { Authorization: `Bearer ${accessToken}`, Accept: "application/json" },
      });
      const data = await resp.json();
      for (const m of data.value || []) {
        const text = `${m.subject || ""} ${m.bodyPreview || ""} ${m.body?.content || ""}`;
        if (text.toLowerCase().includes("verify your email") || text.toLowerCase().includes("metricool")) {
          const match = text.match(/\b(\d{6})\b/);
          if (match) {
            console.log(`[Camoufox] Found OTP code: ${match[1]}`);
            return match[1];
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

async function run() {
  console.log(`[Camoufox] Launching Camoufox anti-detect browser (headless=${headless})...`);
  const context = await Camoufox({
    user_data_dir: profileDir,
    headless: headless,
    os: "windows",
    humanize: true,
  });

  const page = await context.newPage();

  if (openOnly) {
    console.log("[Camoufox] Opening active profile dashboard: https://app.metricool.com/");
    await page.goto("https://app.metricool.com/", { waitUntil: "domcontentloaded" });
    console.log(`[Camoufox] Session active: ${page.url()} (${await page.title()})`);
    console.log("[Camoufox] Keep window open for manual browsing. Press Ctrl+C in terminal when done.");
    await new Promise((r) => setTimeout(r, 60000));
    await context.close();
    return;
  }

  console.log("[Camoufox] Navigating to https://app.metricool.com/login...");
  await page.goto("https://app.metricool.com/login", { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(3000);

  const emailField = page.locator("input.v-field__input[name='email']");
  const passField = page.locator("input.v-field__input[name='password']");
  const accessBtn = page.locator("button:has-text('Access')");

  if (await emailField.isVisible() && await passField.isVisible()) {
    console.log(`[Camoufox] Entering credentials for: ${email}...`);
    await emailField.click();
    await emailField.fill(email);
    await page.waitForTimeout(300);

    await passField.click();
    await passField.fill(password);
    await page.waitForTimeout(400);

    console.log("[Camoufox] Submitting login form...");
    await accessBtn.click({ force: true }).catch(() => { });
    await page.waitForTimeout(4000);
  }

  // Check if OTP / 2FA is needed
  const otpInput = page.locator("input[name='otp'], input.v-otp-input__field");
  if (await otpInput.count() > 0 || page.url().includes("login")) {
    console.log("[Camoufox] Email verification challenge detected.");
    if (clientId && refreshToken) {
      const code = await pollOutlookOtp(clientId, refreshToken, 60);
      if (code) {
        console.log(`[Camoufox] Auto-typing OTP code: ${code}...`);

        // Focus or click the OTP input area (with force: true to bypass Vuetify custom wrapper styling)
        try {
          const otpContainer = page.locator(".v-otp-input, .v-field").first();
          if (await otpContainer.count() > 0 && await otpContainer.isVisible()) {
            await otpContainer.click({ force: true });
          } else if (await otpInput.count() > 0) {
            await otpInput.first().focus().catch(() => { });
            await otpInput.first().click({ force: true }).catch(() => { });
          }
        } catch (e) {
          console.log("[Camoufox] Note focusing OTP container:", e.message);
        }

        // Native DOM dispatch into OTP inputs
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

        // Also type via keyboard to trigger all Vue synthetic key listeners
        await page.keyboard.type(code, { delay: 120 });
        await page.waitForTimeout(1000);

        // Submit OTP code
        const confirmBtn = page.locator("button:has-text('Confirm code'), button:has-text('Verify'), button[type='submit']");
        if ((await confirmBtn.count()) > 0) {
          console.log("[Camoufox] Submitting Confirm code...");
          await confirmBtn.first().click({ force: true }).catch(async () => {
            await page.keyboard.press("Enter");
          });
          await page.waitForTimeout(5000);
        } else {
          console.log("[Camoufox] Pressing Enter to confirm OTP...");
          await page.keyboard.press("Enter");
          await page.waitForTimeout(5000);
        }
      }
    } else {
      console.log("[Camoufox] No OAuth token provided for OTP. Complete code confirmation in browser.");
      await page.waitForTimeout(15000);
    }
  }

  await page.waitForTimeout(4000);
  const finalUrl = page.url();
  const finalTitle = await page.title();
  console.log(`[Camoufox] Final URL: ${finalUrl} | Title: '${finalTitle}'`);

  // Export cookies
  const cookies = await context.cookies();
  const cookiesPath = path.join(profileDir, "cookies.json");
  fs.writeFileSync(cookiesPath, JSON.stringify(cookies, null, 2), "utf-8");
  console.log(`[Camoufox] Saved ${cookies.length} session cookies to: ${cookiesPath}`);

  // Save session metadata
  const sessionData = {
    email,
    status: finalUrl.includes("login") ? "partial" : "logged_in",
    dashboard_url: finalUrl,
    cookies_count: cookies.length,
    profile_path: profileDir,
    saved_at: new Date().toISOString(),
    engine: "camoufox",
  };
  fs.writeFileSync(path.join(profileDir, "session_info.json"), JSON.stringify(sessionData, null, 2), "utf-8");

  // Mirror to root 'profiles metricool'
  try {
    fs.writeFileSync(path.join(rootMirrorDir, "cookies.json"), JSON.stringify(cookies, null, 2), "utf-8");
    fs.writeFileSync(path.join(rootMirrorDir, "session_info.json"), JSON.stringify(sessionData, null, 2), "utf-8");
  } catch (e) { }

  console.log("============================================================");
  console.log("CAMOUFOX METRICOOL LOGIN COMPLETE:");
  console.log(`Email:        ${email}`);
  console.log(`Status:       ${sessionData.status}`);
  console.log(`Cookies:      ${cookies.length}`);
  console.log(`Profile Dir:  ${profileDir}`);
  console.log(`Dashboard:    ${finalUrl}`);
  console.log("============================================================");

  await context.close();
}

run().catch((err) => {
  console.error(`[Camoufox Error]: ${err.stack || err}`);
  process.exit(1);
});
