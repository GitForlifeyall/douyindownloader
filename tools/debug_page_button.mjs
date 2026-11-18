import path from "node:path";

const CAMOUFOX_PATH = "file:///C:/Users/rudra/AppData/Roaming/npm/node_modules/camoufox-cli/node_modules/camoufox-js/dist/index.js";
const { Camoufox } = await import(CAMOUFOX_PATH);

const profileDir = path.resolve("output", "profiles facebook", "WilsonYurcak691555");
const proxyStr = "customer-mobile_1465757f:WG0F=DD_9q=E@pr.oxylabs.io:7777";

function parseProxy(p) {
  let clean = p.replace(/^https?:\/\//i, "");
  const [auth, hostPort] = clean.split("@");
  const [u, pass] = auth.split(":");
  return {
    server: `http://${hostPort}`,
    username: decodeURIComponent(u),
    password: decodeURIComponent(pass),
  };
}

async function run() {
  const browser = await Camoufox({
    user_data_dir: profileDir,
    headless: false,
    proxy: parseProxy(proxyStr),
    geoip: false,
  });

  const page = (browser.pages && browser.pages().length > 0) ? browser.pages()[0] : await browser.newPage();
  console.log("Navigating to https://www.facebook.com/pages/create/...");
  await page.goto("https://www.facebook.com/pages/create/", { waitUntil: "domcontentloaded", timeout: 35000 });
  await page.waitForTimeout(4000);

  // Dismiss any popups
  try {
    const closeBtn = page.locator("[aria-label='Close'], [aria-label='Not Now']").first();
    if (await closeBtn.isVisible()) await closeBtn.click();
  } catch (e) {}

  // 1. Name
  console.log("Typing name...");
  const nameInput = page.locator("input[type='text']").first();
  await nameInput.click();
  await nameInput.pressSequentially("EchoSphere Media", { delay: 60 });
  await page.waitForTimeout(1000);

  // 2. Category
  console.log("Typing category...");
  const catInput = page.locator("input[type='text']").nth(1);
  await catInput.click();
  await catInput.pressSequentially("Personal blog", { delay: 60 });
  await page.waitForTimeout(2000);

  const catOpt = page.locator("[role='option']").filter({ hasText: /^Personal blog$/i }).first();
  if (await catOpt.count() > 0) {
    await catOpt.click();
    console.log("Category clicked!");
  }
  await page.waitForTimeout(1000);

  // 3. Bio
  console.log("Typing bio...");
  const bioInput = page.locator("textarea").first();
  if (await bioInput.count() > 0) {
    await bioInput.click();
    await bioInput.pressSequentially("Exploring daily stories and inspirations.", { delay: 40 });
  }
  await page.waitForTimeout(1000);

  // 4. Click Create Page
  const createBtn = page.locator("[role='button']:has-text('Create Page'), button:has-text('Create Page')").first();
  console.log("Button visible:", await createBtn.isVisible(), "enabled:", await createBtn.isEnabled());
  const box = await createBtn.boundingBox();
  console.log("Button box:", box);

  // Listen to network errors or GraphQL responses
  page.on("response", async (res) => {
    if (res.url().includes("graphql")) {
      try {
        const text = await res.text();
        if (text.includes("errorDescription") || text.includes("error_summary") || text.includes("page_create") || text.includes("PageCreate") || text.includes("errors")) {
          console.log("[GraphQL]:", text.slice(0, 300));
        }
      } catch (e) {}
    }
  });

  if (box) {
    console.log("Clicking with page.mouse...");
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
    await page.mouse.down();
    await page.waitForTimeout(150);
    await page.mouse.up();
  } else {
    await createBtn.click({ force: true });
  }

  console.log("Waiting 15 seconds to observe result...");
  await page.waitForTimeout(15000);

  await page.screenshot({ path: "tests/test_artifacts/fb_page_submit_debug.png", fullPage: true });
  console.log("Saved debug screenshot to tests/test_artifacts/fb_page_submit_debug.png");
  console.log("Current URL:", page.url(), "| Title:", await page.title());

  await browser.close();
}

run().catch(console.error);
