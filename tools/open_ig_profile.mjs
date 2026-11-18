#!/usr/bin/env node
/**
 * tools/open_ig_profile.mjs
 * =========================
 * Opens a saved Instagram profile in Camoufox with proxy, WebRTC protection,
 * the profile's frozen persona seeds and its full frozen fingerprint.
 */

import fs from "node:fs";
import path from "node:path";
import crypto from "node:crypto";

const CAMOUFOX_PATH = "file:///C:/Users/rudra/AppData/Roaming/npm/node_modules/camoufox-cli/node_modules/camoufox-js/dist/index.js";
const { Camoufox } = await import(CAMOUFOX_PATH);

const FP_GENERATOR_PATH = "file:///C:/Users/rudra/AppData/Roaming/npm/node_modules/camoufox-cli/node_modules/fingerprint-generator/index.mjs";
const { FingerprintGenerator } = await import(FP_GENERATOR_PATH);
const FP_GENERATOR = new FingerprintGenerator({ browsers: ["firefox"], operatingSystems: ["windows"] });

const args = process.argv.slice(2);
function getArg(name, def = null) {
  const i = args.indexOf(name);
  return i >= 0 && i + 1 < args.length ? args[i + 1] : def;
}

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
  { width: 1440, height: 900 },
  { width: 1920, height: 1200 },
  { width: 2560, height: 1440 },
];

// Determine profile name (from --profile, --email, or the latest registered account)
let defaultProfile = "BosePontecorvo50630";
const accountsFile = path.resolve("output", "instagram_registered_accounts.json");
if (fs.existsSync(accountsFile)) {
  try {
    const list = JSON.parse(fs.readFileSync(accountsFile, "utf-8"));
    if (list && list.length > 0) {
      const latest = list[list.length - 1];
      defaultProfile = latest.email ? latest.email.split("@")[0] : latest.username || defaultProfile;
    }
  } catch (e) { }
}

const rawProfile = getArg("--profile") || getArg("--email", defaultProfile);
const profileName = (rawProfile.includes("@") ? rawProfile.split("@")[0] : rawProfile).replace(/[^A-Za-z0-9._-]/g, "");
if (!profileName || profileName === "." || profileName === "..") {
  console.error(`[Instagram] Invalid profile name: ${rawProfile}`);
  process.exit(1);
}

const DEFAULT_PROXY = "customer-mobile_83bd2e52:DPD~dmUeZ1~p@pr.oxylabs.io:7777";
let proxyStr = getArg("--proxy");

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

const profilesRoot = path.resolve("output", "profiles instagram");
const profileDir = path.resolve(profilesRoot, profileName);
if (!profileDir.startsWith(profilesRoot + path.sep)) {
  console.error(`[Instagram] Refusing to use a profile directory outside ${profilesRoot}`);
  process.exit(1);
}
fs.mkdirSync(profileDir, { recursive: true });

// Reopen the account through the exact proxy it was created with. Falling back
// to a shared default here would put every account back on one exit IP (and a
// different IP than signup), which is a strong account-linking / checkpoint
// signal even when every signup used a fresh proxy.
if (!proxyStr) {
  const infoPath = path.join(profileDir, "account_info.json");
  if (fs.existsSync(infoPath)) {
    try {
      const info = JSON.parse(fs.readFileSync(infoPath, "utf-8"));
      if (typeof info.proxy_used === "string" && info.proxy_used.trim()) {
        proxyStr = info.proxy_used.trim();
        console.log(`[Instagram] Reusing the proxy this account was created with: ${proxyStr.replace(/^.*@/, "***@")}`);
      }
    } catch (e) { }
  }
}

// Fallback for older profiles that predate account_info.json: the master
// registry also stores the exact proxy used at signup.
if (!proxyStr) {
  const registryPath = path.resolve("output", "instagram_registered_accounts.json");
  if (fs.existsSync(registryPath)) {
    try {
      const list = JSON.parse(fs.readFileSync(registryPath, "utf-8"));
      if (Array.isArray(list)) {
        const record = list.find((a) => {
          const stem = String(a && a.email ? a.email : "").split("@")[0].replace(/[^A-Za-z0-9._-]/g, "");
          return stem === profileName || (a && a.username) === profileName;
        });
        if (record && typeof record.proxy_used === "string" && record.proxy_used.trim()) {
          proxyStr = record.proxy_used.trim();
          console.log(`[Instagram] Reusing the signup proxy from the account registry: ${proxyStr.replace(/^.*@/, "***@")}`);
        }
      }
    } catch (e) { }
  }
}

if (!proxyStr) {
  proxyStr = DEFAULT_PROXY;
  console.warn("[Instagram] WARNING: no saved proxy found for this account; using the shared default. This can link accounts and trigger a checkpoint.");
}

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
  } catch (e) { }
}

const isGpuValid = Boolean(persona?.webgl_config) && GPU_CONFIGURATIONS.some(
  ([vendor, renderer]) => vendor === persona.webgl_config[0] && renderer === persona.webgl_config[1]
);

if (!persona || !persona["canvas:seed"] || !isGpuValid) {
  const previous = persona || {};
  const chosenGpu = isGpuValid ? previous.webgl_config : GPU_CONFIGURATIONS[crypto.randomInt(GPU_CONFIGURATIONS.length)];
  const chosenRes = previous.screen_resolution || SCREEN_RESOLUTIONS[crypto.randomInt(SCREEN_RESOLUTIONS.length)];
  persona = {
    "canvas:seed": previous["canvas:seed"] || crypto.randomInt(1, 4000000000),
    "audio:seed": previous["audio:seed"] || crypto.randomInt(1, 4000000000),
    "fonts:spacing_seed": previous["fonts:spacing_seed"] || crypto.randomInt(1, 4000000000),
    webgl_config: chosenGpu,
    screen_resolution: chosenRes,
  };
  fs.writeFileSync(personaPath, JSON.stringify(persona, null, 2));
}

// Load the full frozen fingerprint; generate it only once per profile.
const fingerprintPath = path.join(profileDir, "fingerprint.json");
let fingerprint = null;
if (fs.existsSync(fingerprintPath)) {
  try {
    const fp = JSON.parse(fs.readFileSync(fingerprintPath, "utf-8"));
    if (fp && fp.navigator && fp.screen) fingerprint = fp;
  } catch (e) { }
}
if (!fingerprint) {
  const scr = persona.screen_resolution;
  let generated = null;
  try {
    generated = FP_GENERATOR.getFingerprint({
      screen: { minWidth: scr.width, maxWidth: scr.width, minHeight: scr.height, maxHeight: scr.height },
      operatingSystems: ["windows"],
    }).fingerprint;
  } catch (e) { }
  if (!generated) {
    generated = FP_GENERATOR.getFingerprint({ operatingSystems: ["windows"] }).fingerprint;
    persona.screen_resolution = { width: generated.screen.width, height: generated.screen.height };
    fs.writeFileSync(personaPath, JSON.stringify(persona, null, 2));
  }
  fingerprint = generated;
  fs.writeFileSync(fingerprintPath, JSON.stringify(fingerprint, null, 2));
}

// Keep the fingerprint's videoCard coherent with the explicit WebGL pair.
if (persona.webgl_config) {
  const expectedCard = { vendor: persona.webgl_config[0], renderer: persona.webgl_config[1] };
  if (!fingerprint.videoCard
    || fingerprint.videoCard.vendor !== expectedCard.vendor
    || fingerprint.videoCard.renderer !== expectedCard.renderer) {
    fingerprint.videoCard = expectedCard;
    fs.writeFileSync(fingerprintPath, JSON.stringify(fingerprint, null, 2));
  }
}

const scr = persona.screen_resolution || fingerprint.screen || { width: 1920, height: 1080 };

console.log("============================================================");
console.log(`LAUNCHING INSTAGRAM PROFILE: ${profileName}`);
console.log(`Profile Directory: ${profileDir}`);
console.log(`Frozen Persona:    Loaded (canvas & audio frozen)`);
console.log(`Frozen Fingerprint: Loaded (${fingerprintPath})`);
console.log(`WebRTC:            blocked (proxy-only ICE candidates)`);
console.log("============================================================");

const browserConfig = {
  user_data_dir: profileDir,
  headless: false,
  os: "windows",
  humanize: true,
  block_webrtc: true,
  screen: { maxWidth: scr.width, maxHeight: scr.height },
  webgl_config: persona.webgl_config || undefined,
  proxy: parseProxy(ensureStickyProxy(proxyStr, profileName)),
  geoip: true,
  fingerprint,
  i_know_what_im_doing: true,
  config: {
    "canvas:seed": persona["canvas:seed"],
    "audio:seed": persona["audio:seed"],
    "fonts:spacing_seed": persona["fonts:spacing_seed"],
  },
};

const browser = await Camoufox(browserConfig);
const page = (browser.pages && browser.pages().length > 0) ? browser.pages()[0] : await browser.newPage();
try {
  await page.goto("https://www.instagram.com/?hl=en", { waitUntil: "domcontentloaded", timeout: 45000 });
} catch (err) {
  console.warn(`[Navigation] Initial load note: ${err.message}. Retrying...`);
  await page.goto("https://www.instagram.com/?hl=en", { waitUntil: "domcontentloaded", timeout: 45000 }).catch(() => {});
}
await page.bringToFront().catch(() => {});

console.log("[Instagram] Profile is loaded and live on your screen.");
console.log("[Instagram] Close the browser window when you are done.");

await new Promise((resolve) => browser.on("close", resolve));
