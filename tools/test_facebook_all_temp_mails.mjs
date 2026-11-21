#!/usr/bin/env node
/**
 * tools/test_facebook_all_temp_mails.mjs
 * =====================================
 * Tests Facebook registration across all saved temporary email providers
 * to discover which domains Meta accepts without "An error occurred".
 */

import fs from "node:fs";
import path from "node:path";
import crypto from "node:crypto";
import { execSync } from "node:child_process";

const CAMOUFOX_PATH = "file:///C:/Users/rudra/AppData/Roaming/npm/node_modules/camoufox-cli/node_modules/camoufox-js/dist/index.js";
const { Camoufox } = await import(CAMOUFOX_PATH);

const DEFAULT_PROXY = process.env.OXYLABS_PROXY || "";
const args = process.argv.slice(2);
const proxyArg = args.find((a, i) => args[i - 1] === "--proxy") || DEFAULT_PROXY;
const headless = args.includes("--headless");

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

// Load saved mailboxes from vault
const VAULT_FILE = path.resolve("output", "temp_mail_tokens.json");
let allAccounts = [];
if (fs.existsSync(VAULT_FILE)) {
  allAccounts = JSON.parse(fs.readFileSync(VAULT_FILE, "utf-8"));
}

// Select representative accounts from each provider
const testCandidates = [
  "xnmhzz3c@lnovic.com",
  "user_e3d39ea5@mailto.plus",
  "user_32b8ff7c@guerrillamailblock.com",
  "user_df6dad73@fldubai.com"
];

// Deduplicate and filter existing in vault or candidates
const targetEmails = [];
for (const em of testCandidates) {
  if (!targetEmails.includes(em)) targetEmails.push(em);
}

const FIRST_NAMES = ["Noah", "Ethan", "Lucas", "Liam", "Oliver", "Aiden", "Emma", "Olivia", "Ava", "Sophia"];
const LAST_NAMES = ["Bennett", "Vance", "Carter", "Hayes", "Brooks", "Reed", "Coleman", "Foster", "Wright"];

async function runTest() {
  console.log("=" * 60);
  console.log(`TESTING FACEBOOK SIGN-UP ACROSS ${targetEmails.length} TEMP-MAIL DOMAINS`);
  console.log("=" * 60);
  targetEmails.forEach((e, idx) => console.log(` ${idx + 1}. ${e}`));
  console.log("=" * 60);

  const parsedProxy = parseProxy(proxyArg);
  const results = [];

  for (const email of targetEmails) {
    console.log(`\n============================================================`);
    console.log(`>>> Testing Registration for: ${email} <<<`);
    console.log(`============================================================`);

    const safeStem = email.replace(/[@.]/g, "_");
    const profileDir = path.resolve("output", "profiles facebook", safeStem);
    fs.mkdirSync(profileDir, { recursive: true });

    const browserConfig = {
      user_data_dir: profileDir,
      headless: headless,
      os: "windows",
      humanize: true,
    };
    if (parsedProxy) {
      browserConfig.proxy = parsedProxy;
      browserConfig.geoip = true;
    }

    const browser = await Camoufox(browserConfig);
    const page = await browser.newPage();

    try {
      await page.goto("https://www.facebook.com/reg/?entry_point=login&locale=en_US", { waitUntil: "domcontentloaded" });
      await page.waitForTimeout(3000);

      // Cookie banner dismissal
      const cookieBtn = page.locator("button:has-text('Allow all cookies'), button:has-text('Allow essential and optional cookies'), button:has-text('Decline optional cookies'), [aria-label='Allow all cookies']");
      if ((await cookieBtn.count()) > 0 && (await cookieBtn.first().isVisible())) {
        await cookieBtn.first().click({ force: true }).catch(() => {});
        await page.waitForTimeout(1000);
      }

      const fn = FIRST_NAMES[crypto.randomInt(FIRST_NAMES.length)];
      const ln = LAST_NAMES[crypto.randomInt(LAST_NAMES.length)];
      const gender = Math.random() < 0.5 ? "Female" : "Male";

      // 1. Fill Name
      const fnInput = page.locator("input[type='text'], input:not([type])").nth(0);
      await fnInput.click();
      await fnInput.pressSequentially(fn, { delay: 40 });
      await page.waitForTimeout(200);

      const lnInput = page.locator("input[type='text'], input:not([type])").nth(1);
      await lnInput.click();
      await lnInput.pressSequentially(ln, { delay: 40 });
      await page.waitForTimeout(200);

      // 2. Select DOB (05 February 2000)
      const comboboxes = page.locator("[role='combobox']");
      const comboCount = await comboboxes.count();

      async function selectExactOption(comboIndex, regex) {
        if (comboCount > comboIndex) {
          const combo = comboboxes.nth(comboIndex);
          await combo.click();
          await page.waitForTimeout(350);
          const opt = page.locator("[role='option']").filter({ hasText: regex }).first();
          await opt.click();
          await page.waitForTimeout(350);
        }
      }

      // Combobox 0: Month (February)
      await selectExactOption(0, /^(?:february|फ़रवरी|फरवरी)$/i);
      // Combobox 1: Day (5)
      await selectExactOption(1, /^(?:5|05|५)$/);
      // Combobox 2: Year (2000)
      await selectExactOption(2, /^(?:2000|२०००)$/);
      // Combobox 3: Gender
      await selectExactOption(3, gender === "Female" ? /^(?:female|महिला)$/i : /^(?:male|पुरुष)$/i);

      // 3. Fill Email
      const emInput = page.locator("input[type='text'], input:not([type])").nth(2);
      await emInput.click();
      await emInput.pressSequentially(email, { delay: 35 });
      await page.waitForTimeout(300);

      // 4. Fill Password
      const pwInput = page.locator("input[type='password']");
      await pwInput.click();
      await pwInput.pressSequentially("Beliver123@", { delay: 40 });
      await page.waitForTimeout(800);

      await page.screenshot({ path: `tests/test_artifacts/fb_fill_${safeStem}.png` });

      // 5. Submit Form
      console.log(`[Facebook] Submitting form for ${email}...`);
      const submitBtn = page.locator("button:has-text('Submit'), [role='button']:has-text('Submit'), button:has-text('Sign Up')").first();
      if ((await submitBtn.count()) > 0) {
        await submitBtn.click();
      } else {
        await page.evaluate(() => {
          const btns = Array.from(document.querySelectorAll("button, [role='button']"));
          const s = btns.find(b => (b.innerText || "").toLowerCase().includes("submit") || (b.innerText || "").toLowerCase().includes("sign up"));
          if (s) s.click();
        });
      }

      console.log("[Facebook] Waiting 8s for Meta response...");
      await page.waitForTimeout(8000);

      const currentUrl = page.url();
      const postHtml = await page.content();
      await page.screenshot({ path: `tests/test_artifacts/fb_result_${safeStem}.png` });

      let outcome = "Unknown";

      if (postHtml.includes("An error occurred during your registration") || postHtml.includes("Please try again")) {
        outcome = "BLOCKED: 'An error occurred during your registration'";
        console.log(`[Facebook Result for ${email}]: ❌ ${outcome}`);
      } else if (currentUrl.includes("checkpoint") || currentUrl.includes("confirmemail") || postHtml.includes("Enter the code") || postHtml.includes("confirmation code")) {
        outcome = `SUCCESS / CHECKPOINT: Created & redirected to ${currentUrl}`;
        console.log(`[Facebook Result for ${email}]: ✅ ${outcome}`);
        
        // Poll inbox via temp_mail_manager.py
        try {
          console.log(`[Facebook] Polling inbox for code: python tools/temp_mail_manager.py --inbox ${email}`);
          const out = execSync(`python tools/temp_mail_manager.py --inbox ${email}`, { timeout: 20000, encoding: "utf-8" });
          console.log(`[Inbox Poll Output]:\n${out.trim()}`);
        } catch (pe) {
          console.log(`[Inbox Poll Note]: ${pe.message}`);
        }
      } else {
        outcome = `Response URL: ${currentUrl}`;
        console.log(`[Facebook Result for ${email}]: ℹ️ ${outcome}`);
      }

      results.push({ email, outcome, url: currentUrl });

    } catch (err) {
      console.error(`[Error on ${email}]: ${err.message}`);
      results.push({ email, outcome: `Script Error: ${err.message}` });
    } finally {
      await browser.close();
    }

    await new Promise(r => setTimeout(r, 2000));
  }

  console.log("\n" + "=" * 60);
  console.log("FACEBOOK MULTI-DOMAIN TEMP-MAIL SUMMARY RESULTS:");
  console.log("=" * 60);
  results.forEach((r, idx) => {
    console.log(`${idx + 1}. ${r.email.padEnd(35)} -> ${r.outcome}`);
  });
  console.log("=" * 60);
}

runTest().catch(e => {
  console.error("Test runner failed:", e);
  process.exit(1);
});
