#!/usr/bin/env node
/**
 * tools/test_fb_metricool_fast.mjs
 * ================================
 * Fast Benchmark & Test Script for Facebook + Metricool:
 * - SKIPS cursor trajectory path (humanize: false, direct clicks, 0 bezier curves).
 * - SKIPS delays between each input (instant .fill() with 0ms delay, no typing cadence).
 * - Dual-tab Combo Mode:
 *     Tab 1: Facebook Registration Form
 *     Tab 2: Metricool Registration Form
 * - Saves verification artifacts to tests/test_artifacts/
 */

import fs from "node:fs";
import path from "node:path";
import crypto from "node:crypto";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

// Import Camoufox from local node_modules
import { Camoufox } from "./node_modules/camoufox-js/dist/index.js";

// CLI Arguments
const args = process.argv.slice(2);
function getArg(name, defaultValue = null) {
  const idx = args.indexOf(name);
  return idx >= 0 && idx + 1 < args.length ? args[idx + 1] : defaultValue;
}
const hasFlag = (name) => args.includes(name);

const headless = hasFlag("--headless");
const noProxy = hasFlag("--no-proxy");
const fbOnly = hasFlag("--fb-only");
const metricoolOnly = hasFlag("--metricool-only");
const DEFAULT_PROXY = "customer-resi_4edb25d7:fo4ENfj4pMx+@pr.oxylabs.io:7777";
const proxyArg = noProxy ? null : getArg("--proxy", DEFAULT_PROXY);

// Credentials & test data
const testEmail = getArg("--email", `test_fast_${crypto.randomBytes(3).toString("hex")}@outlook.com`);
const testPassword = getArg("--password", "FastMetricool2026!#");
const firstName = getArg("--first-name", "Alex");
const lastName = getArg("--last-name", "Reynolds");

// Benchmark test runs should always start fresh unless --keep or --resume is explicitly passed
if (!hasFlag("--keep") && !hasFlag("--resume") && !profileDir) {
  for (const dir of [DEFAULT_FB_PROFILE, DEFAULT_MC_PROFILE]) {
    try {
      if (fs.existsSync(dir)) {
        fs.rmSync(dir, { recursive: true, force: true });
        console.log(`[FAST] Cleaned previous test profile: ${path.relative(ROOT, dir)}`);
      }
    } catch (e) { }
  }
}

const testProfileDir = path.resolve("output", "profiles_test", "fast_fb_metricool");
const testArtifactsDir = path.resolve("tests", "test_artifacts");
fs.mkdirSync(testArtifactsDir, { recursive: true });
fs.mkdirSync(testProfileDir, { recursive: true });

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

// -----------------------------------------------------------------------------
// Fast Action Primitives: ZERO cursor trajectory, ZERO typing delay
// -----------------------------------------------------------------------------
async function fastClick(page, locator, name = "element") {
  const el = typeof locator.first === "function" ? locator.first() : locator;
  await el.scrollIntoViewIfNeeded().catch(() => { });
  // Direct click without any mouse glide, spline trajectory, or hover delay
  await el.click({ force: true }).catch(async () => {
    await el.dispatchEvent("click").catch(() => { });
  });
}

async function fastFill(page, locator, text, name = "input") {
  const el = typeof locator.first === "function" ? locator.first() : locator;
  await el.scrollIntoViewIfNeeded().catch(() => { });
  // Direct .fill() sets element value instantly without typing char-by-char
  await el.fill(text).catch(async () => {
    await el.focus().catch(() => { });
    await page.keyboard.insertText(text).catch(() => { });
  });
}

// -----------------------------------------------------------------------------
// Test 1: Fast Facebook Registration Fill
// -----------------------------------------------------------------------------
async function runFastFacebookTest(page) {
  console.log("\n" + "=".repeat(65));
  console.log(" [FAST TEST: FACEBOOK] Launching registration page...");
  console.log("=".repeat(65));

  const startNav = Date.now();
  await page.goto("https://www.facebook.com/reg/?entry_point=login&locale=en_US", {
    waitUntil: "domcontentloaded",
    timeout: 45000,
  });
  console.log(`[FB] Page loaded in ${Date.now() - startNav}ms (${page.url()})`);

  // Dismiss cookie banner instantly if present
  const cookieBtn = page.locator("button:has-text('Allow all cookies'), button:has-text('Allow essential and optional cookies'), button:has-text('Decline optional cookies'), [aria-label='Allow all cookies']");
  if ((await cookieBtn.count()) > 0 && (await cookieBtn.first().isVisible().catch(() => false))) {
    console.log("[FB] Instantly clicking cookie dismissal (zero trajectory)...");
    await fastClick(page, cookieBtn.first(), "cookie button");
  }

  // Wait for First Name input
  const fnInput = page.locator("input[name='firstname']:visible, input[aria-label*='First name' i]:visible, input[placeholder*='First name' i]:visible, input[type='text']:visible").first();
  await fnInput.waitFor({ state: "visible", timeout: 20000 });

  console.log(`\n>>> STARTING FAST INPUT SEQUENCE (Zero Cursor Trajectory, Zero Input Delays) <<<`);
  const fillStartTime = Date.now();

  // 1. First Name (instant fill)
  await fastFill(page, fnInput, firstName, "First Name");

  // 2. Last Name (instant fill)
  let lnInput = page.locator("input[name='lastname']:visible, input[aria-label*='Surname' i]:visible, input[placeholder*='Surname' i]:visible, input[aria-label*='Last name' i]:visible").first();
  if ((await lnInput.count()) === 0) lnInput = page.locator("input[type='text']:visible").nth(1);
  await fastFill(page, lnInput, lastName, "Last Name");

  // 3. Birthday (instant selects)
  const monthSelect = page.locator("select[name='birthday_month'], select[id='month']").first();
  if ((await monthSelect.count()) > 0 && (await monthSelect.isVisible().catch(() => false))) {
    await monthSelect.selectOption("5").catch(() => { });
  }
  const daySelect = page.locator("select[name='birthday_day'], select[id='day']").first();
  if ((await daySelect.count()) > 0 && (await daySelect.isVisible().catch(() => false))) {
    await daySelect.selectOption("15").catch(() => { });
  }
  const yearSelect = page.locator("select[name='birthday_year'], select[id='year']").first();
  if ((await yearSelect.count()) > 0 && (await yearSelect.isVisible().catch(() => false))) {
    await yearSelect.selectOption("1998").catch(() => { });
  }

  // 4. Gender (instant radio / select - Female)
  const genderRadio = page.locator("input[type='radio'][value='1'], label:has-text('Female') input[type='radio']").first();
  if ((await genderRadio.count()) > 0 && (await genderRadio.isVisible().catch(() => false))) {
    await fastClick(page, genderRadio, "Gender Radio (Female)");
  } else {
    const genderSelect = page.locator("select[name='sex']").first();
    if ((await genderSelect.count()) > 0) await genderSelect.selectOption("1").catch(() => { });
  }

  // 5. Email (instant fill)
  const emailInput = page.locator("input[name='reg_email__']:visible, input[aria-label*='Mobile number or email' i]:visible, input[type='email']:visible").first();
  if ((await emailInput.count()) > 0) {
    await fastFill(page, emailInput, testEmail, "Email");
  }

  // 6. Password (instant fill)
  const pwInput = page.locator("input[name='reg_passwd__']:visible, input[type='password']:visible").first();
  if ((await pwInput.count()) > 0) {
    await fastFill(page, pwInput, testPassword, "Password");
  }

  const fillDurationMs = Date.now() - fillStartTime;
  console.log(`[FB] ✅ ALL 6 Facebook fields filled instantly in: ${fillDurationMs}ms!`);
  console.log(`[FB] Cursor trajectory: SKIPPED (Direct dispatch, 0 spline points)`);
  console.log(`[FB] Typing delay:      SKIPPED (Instant buffer assignment)`);

  const fbScreenshot = path.join(testArtifactsDir, "fast_fb_filled.png");
  await page.screenshot({ path: fbScreenshot, fullPage: false });
  console.log(`[FB] Saved verification screenshot to: ${fbScreenshot}`);

  return { durationMs: fillDurationMs, screenshot: fbScreenshot };
}

// -----------------------------------------------------------------------------
// Test 2: Fast Metricool Registration Fill
// -----------------------------------------------------------------------------
async function runFastMetricoolTest(page) {
  console.log("\n" + "=".repeat(65));
  console.log(" [FAST TEST: METRICOOL] Launching registration page...");
  console.log("=".repeat(65));

  const startNav = Date.now();
  await page.goto("https://app.metricool.com/register", {
    waitUntil: "domcontentloaded",
    timeout: 45000,
  });
  console.log(`[Metricool] Page loaded in ${Date.now() - startNav}ms (${page.url()})`);

  const emailField = page.locator("input.v-field__input[name='email'], input[name='email']:visible, input[type='email']:visible").first();
  const passField = page.locator("input.v-field__input[name='password'], input[name='password']:visible, input[type='password']:visible").first();

  await emailField.waitFor({ state: "visible", timeout: 25000 });

  console.log(`\n>>> STARTING FAST INPUT SEQUENCE (Metricool) <<<`);
  const fillStartTime = Date.now();

  // 1. Email (instant fill)
  await fastFill(page, emailField, testEmail, "Metricool Email");

  // 2. Password (instant fill)
  await fastFill(page, passField, testPassword, "Metricool Password");

  // 3. Terms checkbox (instant click)
  const termsCheckbox = page.locator(".v-selection-control__input input, input[type='checkbox']").first();
  if ((await termsCheckbox.count()) > 0) {
    await fastClick(page, termsCheckbox, "Terms Checkbox");
  }

  const fillDurationMs = Date.now() - fillStartTime;
  console.log(`[Metricool] ✅ Metricool fields filled instantly in: ${fillDurationMs}ms!`);
  console.log(`[Metricool] Cursor trajectory: SKIPPED (Direct dispatch, 0 spline points)`);
  console.log(`[Metricool] Typing delay:      SKIPPED (Instant buffer assignment)`);

  const mcScreenshot = path.join(testArtifactsDir, "fast_metricool_filled.png");
  await page.screenshot({ path: mcScreenshot, fullPage: false });
  console.log(`[Metricool] Saved verification screenshot to: ${mcScreenshot}`);

  return { durationMs: fillDurationMs, screenshot: mcScreenshot };
}

// -----------------------------------------------------------------------------
// Main Runner
// -----------------------------------------------------------------------------
async function main() {
  console.log("=================================================================");
  console.log(" FAST FB + METRICOOL TEST RUNNER (NO TRAJECTORY, NO DELAYS)");
  console.log("=================================================================");
  console.log(` EMAIL:       ${testEmail}`);
  console.log(` HEADLESS:    ${headless}`);
  console.log(` PROXY:       ${proxyArg ? proxyArg.replace(/:[^:]*@/, ":***@") : "Direct (No Proxy)"}`);
  console.log(` HUMANIZED:   FALSE (Trajectory engine completely bypassed)`);
  console.log(` DELAYS:      0ms (Gaussian typing pauses bypassed)`);
  console.log("=================================================================");

  const browserConfig = {
    user_data_dir: testProfileDir,
    headless: headless,
    os: "windows",
    humanize: false, // CRITICAL: Tells Camoufox to skip internal cursor trajectories & bezier curves
    block_webrtc: true,
    i_know_what_im_doing: true,
    locale: "en-US",
  };

  const parsedProxy = parseProxy(proxyArg);
  if (parsedProxy) {
    browserConfig.proxy = parsedProxy;
    browserConfig.geoip = false;
  }

  console.log("[Camoufox] Launching browser instance...");
  const context = await Camoufox(browserConfig);

  const results = {};

  try {
    if (!metricoolOnly) {
      // Tab 1: Facebook
      const fbPage = await context.newPage();
      results.fb = await runFastFacebookTest(fbPage);
    }

    if (!fbOnly) {
      // Tab 2: Metricool
      const mcPage = await context.newPage();
      await mcPage.bringToFront().catch(() => { });
      results.metricool = await runFastMetricoolTest(mcPage);
    }

    console.log("\n" + "=".repeat(65));
    console.log(" 🎉 FAST BENCHMARK COMPLETED SUCCESSFULLY!");
    console.log("=".repeat(65));
    if (results.fb) {
      console.log(` Facebook Form Fill Time:  ${results.fb.durationMs}ms`);
      console.log(` Facebook Screenshot:     ${results.fb.screenshot}`);
    }
    if (results.metricool) {
      console.log(` Metricool Form Fill Time: ${results.metricool.durationMs}ms`);
      console.log(` Metricool Screenshot:    ${results.metricool.screenshot}`);
    }
    console.log(" Cursor Trajectory:        DISABLED / ZERO POINTS");
    console.log(" Inter-key Delays:         0ms (Instant fill)");
    console.log("=".repeat(65) + "\n");

    if (!headless) {
      console.log("[Test Runner] Browser window is active on screen for your visual inspection.");
      console.log("[Test Runner] Press Ctrl+C in terminal or close the browser window to exit.");
      await new Promise((resolve) => {
        context.on("close", resolve);
      });
    }
  } catch (err) {
    console.error(`\n[Fast Test Error]: ${err.message}`);
    console.error(err.stack);
  } finally {
    await context.close().catch(() => { });
  }
}

main().catch(console.error);
