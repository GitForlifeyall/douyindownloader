import path from "node:path";

const CAMOUFOX_PATH = "file:///C:/Users/rudra/AppData/Roaming/npm/node_modules/camoufox-cli/node_modules/camoufox-js/dist/index.js";
const { Camoufox } = await import(CAMOUFOX_PATH);

const profileDir = path.resolve("output", "profiles facebook", "WilsonYurcak691555");
const proxyStr = process.env.OXYLABS_PROXY || "";

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
  console.log("[Facebook] Navigating to https://www.facebook.com/pages/create/...");
  await page.goto("https://www.facebook.com/pages/create/", { waitUntil: "domcontentloaded", timeout: 35000 });
  await page.waitForTimeout(4000);

  // 1. Page Name
  const pageName = "Velvet Reels Cinema";
  console.log(`[Facebook] Entering Page Name: "${pageName}"...`);
  const nameInput = page.locator("input[aria-label*='Page name' i], label:has-text('Page name') input").first();
  await nameInput.click();
  await nameInput.pressSequentially(pageName, { delay: 50 });
  await page.waitForTimeout(800);

  // 2. Category
  console.log("[Facebook] Entering Category: 'Personal blog'...");
  const catInput = page.locator("input[aria-label*='Category' i], label:has-text('Category') input").first();
  await catInput.click();
  await catInput.pressSequentially("Personal blog", { delay: 60 });
  await page.waitForTimeout(2000);

  console.log("[Facebook] Selecting 'Personal blog' from dropdown...");
  const catOpt = page.locator("[role='option']").filter({ hasText: /^Personal blog$/i }).first();
  if (await catOpt.count() > 0) {
    await catOpt.click();
    console.log("[Facebook] Category 'Personal blog' clicked!");
  } else {
    await page.keyboard.press("ArrowDown");
    await page.waitForTimeout(300);
    await page.keyboard.press("Enter");
  }
  await page.waitForTimeout(1000);

  // 3. Bio
  const bio = "Curating cinematic brilliance, stories, and thoughts.";
  console.log(`[Facebook] Entering Bio: "${bio}"...`);
  const bioInput = page.locator("textarea[aria-label*='Bio' i], textarea").first();
  if (await bioInput.count() > 0) {
    await bioInput.click();
    await bioInput.pressSequentially(bio, { delay: 35 });
  }
  await page.waitForTimeout(1000);

  // Unfocus/blur active inputs so React state updates
  await page.evaluate(() => {
    if (document.activeElement && document.activeElement.blur) {
      document.activeElement.blur();
    }
  });
  await page.waitForTimeout(1000);

  // Intercept GraphQL Page Creation Response
  page.on("response", async (res) => {
    if (res.url().includes("graphql")) {
      try {
        const text = await res.text();
        if (text.includes("page_create") || text.includes("PageCreate") || text.includes("errorDescription") || text.includes("errors")) {
          console.log("[GraphQL Page Event]:", text.slice(0, 350));
        }
      } catch (e) {}
    }
  });

  // 4. Click Create Page button
  const createBtn = page.locator("div[role='button'][aria-label='Create Page']").first();
  console.log("[Facebook] Checking 'Create Page' button status...");
  await createBtn.scrollIntoViewIfNeeded().catch(() => {});
  const disabled = await createBtn.getAttribute("aria-disabled");
  console.log(`[Facebook] Button aria-disabled: '${disabled}'`);

  console.log("[Facebook] Clicking 'Create Page' button...");
  await createBtn.hover();
  await page.waitForTimeout(300);
  await createBtn.click();

  // Also dispatch click on the span inside
  const span = createBtn.locator("span").first();
  if (await span.count() > 0) {
    await span.click().catch(() => {});
  }

  console.log("[Facebook] Waiting 15s for Facebook to process creation...");
  await page.waitForTimeout(15000);

  await page.screenshot({ path: "tests/test_artifacts/fb_page_final_created.png", fullPage: true });
  console.log("[Facebook] Saved post-creation screenshot to tests/test_artifacts/fb_page_final_created.png");

  // Verify in Your Pages
  console.log("[Facebook] Navigating to https://www.facebook.com/pages/?category=your_pages...");
  await page.goto("https://www.facebook.com/pages/?category=your_pages", { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(5000);

  const yourPagesText = await page.innerText("body");
  console.log("[Facebook] Your Pages content snippet:\n", yourPagesText.slice(0, 400).replace(/\n+/g, " | "));

  await page.screenshot({ path: "tests/test_artifacts/fb_your_pages_verified.png", fullPage: true });
  console.log("[Facebook] Saved verified pages screenshot to tests/test_artifacts/fb_your_pages_verified.png");

  await browser.close();
}

run().catch(console.error);
