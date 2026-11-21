#!/usr/bin/env node
/**
 * tools/refresh_facebook_session.mjs
 * ==================================
 * Opens the saved persistent Facebook profile, refreshes the page,
 * captures an updated screenshot, and reports the current URL and page state.
 */

import path from "node:path";

const CAMOUFOX_PATH = "file:///C:/Users/rudra/AppData/Roaming/npm/node_modules/camoufox-cli/node_modules/camoufox-js/dist/index.js";
const { Camoufox } = await import(CAMOUFOX_PATH);

const DEFAULT_PROXY = process.env.OXYLABS_PROXY || "";
const profileDir = path.resolve("output", "profiles facebook", "WilsonYurcak691555");

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

async function run() {
  console.log("[Camoufox] Opening saved profile WilsonYurcak691555...");
  const parsedProxy = parseProxy(DEFAULT_PROXY);

  const browser = await Camoufox({
    user_data_dir: profileDir,
    headless: false,
    os: "windows",
    humanize: true,
    proxy: parsedProxy,
    geoip: false,
  });

  const page = (browser.pages && browser.pages().length > 0) ? browser.pages()[0] : await browser.newPage();
  
  console.log("[Facebook] Navigating to https://www.facebook.com/...");
  await page.goto("https://www.facebook.com/", { waitUntil: "domcontentloaded", timeout: 30000 });
  await page.waitForTimeout(4000);

  console.log("[Facebook] Reloading page to fetch latest feed/state...");
  await page.reload({ waitUntil: "domcontentloaded", timeout: 30000 }).catch(() => {});
  await page.waitForTimeout(5000);

  const currentUrl = page.url();
  const title = await page.title();
  console.log(`[Facebook] Refreshed URL: ${currentUrl} | Title: '${title}'`);

  const ssPath = path.resolve("tests", "test_artifacts", "fb_refreshed.png");
  await page.screenshot({ path: ssPath, fullPage: true });
  console.log(`[Facebook] Saved fresh screenshot to ${ssPath}`);

  // Leave open for 10 minutes so user can see/interact
  console.log("[Facebook] Browser session refreshed and holding open for 10 minutes...");
  await page.waitForTimeout(600000);
}

run().catch((err) => {
  console.error(`[Error]: ${err.stack || err}`);
  process.exit(1);
});
