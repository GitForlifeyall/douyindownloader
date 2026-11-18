#!/usr/bin/env node
/**
 * tools/fetch_outlook_otp.mjs
 * ===========================
 * Standalone utility to fetch the latest Facebook 5-digit OTP confirmation code
 * from an Outlook / Hotmail account using the Microsoft OAuth2 refresh token
 * and Outlook REST API (https://outlook.office.com/api/v2.0/me/messages).
 *
 * Usage:
 *   node tools/fetch_outlook_otp.mjs
 *   node tools/fetch_outlook_otp.mjs --account "<email>|<pass>|<refreshToken>|<clientId>"
 */

const DEFAULT_ACCOUNT = "CasonClairmont7374@hotmail.com|ffimzip33|M.C557_BAY.0.U.MsaArtifacts.-Chhy0*KD80E0cWppfIQSUYcoxYfrVIQ1t6eM!xu8y1qZ7hEUBZzUnX!BerB2SGLYBStAXVlsoOonj9L!XKGMomrm2YThHRBqeHp4FrQbXjeeO2FYdlmvSyINGSw4*DGvrvGkVdb7ZIyW7SsuyjUhbXfYw9cJArXydsmeZ*xJ!XMtwqzvpSHgG5euRovF4rJfclkE3Q3z!9thhQg0m9M8L4cRoVhnY5l15Gwk3RIc7vputdfPmQQ2LW0dsMLpSLtPG1!R8SxRHln*YNJxU5qCjIxq55YfT6jZ04zJHU2nYU6VioKHCWiJHJDcpa3!gcd!uYwQaXWeXMw1ukWLPBdlYkdbsjDC8rJOOVo07T6HUTwoq4*qt8QF5spFsTMk38OOexSQb4ZECnAd2P6l3QhruNX6piDOw4uTiX3HScxwskWlWJ4TuU8Ss7r9UOsHAo!OfpXHPvc0fID8aBt8ItRgYTw$|9e5f94bc-e8a4-4e73-b8be-63364c29d753";

const args = process.argv.slice(2);
function getArg(name, def = null) {
  const i = args.indexOf(name);
  return i >= 0 && i + 1 < args.length ? args[i + 1] : def;
}

const accountStr = getArg("--account", DEFAULT_ACCOUNT);
const parts = accountStr.split("|");
const email = (parts[0] || "").trim();
const refreshToken = (parts[2] || "").trim();
let rawCId = (parts[3] || "").trim().replace(/["']/g, "");
if (rawCId.startsWith("9e5f94bc") && rawCId.length === 35) {
  rawCId = "9e5f94bc-e8a4-4e73-b8be-63364c29d753";
}
const clientId = rawCId || "9e5f94bc-e8a4-4e73-b8be-63364c29d753";

if (!refreshToken || !clientId) {
  console.error("Error: Valid refresh token and client ID are required.");
  process.exit(1);
}

// 1. Exchange Refresh Token for Access Token
export async function getMsAccessToken(cId, rToken) {
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

  // Tier 1: Explicitly request Microsoft Graph Mail.Read scope (required for mailbox reading)
  try {
    const res = await fetch(tokenUrl, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({ ...baseParams, scope: "https://graph.microsoft.com/Mail.Read" }).toString(),
    });
    const data = await res.json();
    if (data.access_token) return data.access_token;
  } catch (e) {}

  // Tier 2: Explicitly request legacy Outlook Mail.Read scope
  try {
    const res = await fetch(tokenUrl, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({ ...baseParams, scope: "https://outlook.office.com/Mail.Read" }).toString(),
    });
    const data = await res.json();
    if (data.access_token) return data.access_token;
  } catch (e) {}

  // Tier 3: Omit scope and inherit consented default scopes
  let res = await fetch(tokenUrl, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams(baseParams).toString(),
  });
  let data = await res.json();
  if (data.access_token) return data.access_token;

  if (data.error) throw new Error(data.error_description || data.error);
  return data.access_token;
}

// 2. Fetch Latest Facebook / Instagram OTP Code
export async function fetchFacebookOtp(cId, rToken, maxWaitSeconds = 90) {
  console.log(`[OTP] Polling Microsoft Graph & Outlook for OTP (${email}) for up to ${maxWaitSeconds}s...`);
  const startTime = Date.now();

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
          const res = await fetch(url, {
            headers: {
              Authorization: `Bearer ${accessToken}`,
              Accept: "application/json",
            },
          });

          if (res.ok) {
            groupSuccess = true;
            const json = await res.json();
            const messages = json.value || [];

            for (const msg of messages) {
              const subject = msg.subject || msg.Subject || "";
              const from = (msg.from?.emailAddress?.address || msg.From?.EmailAddress?.Address || "").toLowerCase();
              const preview = msg.bodyPreview || msg.BodyPreview || "";
              const body = msg.body?.content || msg.Body?.Content || "";
              const time = msg.receivedDateTime || msg.ReceivedDateTime || "";

              const isFbOrIg = from.includes("facebook") ||
                from.includes("instagram") ||
                subject.toLowerCase().includes("facebook") ||
                subject.toLowerCase().includes("instagram") ||
                preview.toLowerCase().includes("facebook") ||
                preview.toLowerCase().includes("instagram") ||
                subject.toLowerCase().includes("code");

              if (isFbOrIg) {
                console.log(`[OTP] Found Meta/Instagram/Facebook message!`);
                console.log(`      From:    ${from}`);
                console.log(`      Subject: ${subject}`);
                console.log(`      Time:    ${time}`);

                // Check 6-digit (Instagram) or 5-digit (Facebook)
                const matchSub = subject.match(/\b(\d{5,6})\b/);
                if (matchSub) return matchSub[1];

                const matchPrev = preview.match(/(?:code|is|is:|कोड|है|FB-)\s*[:\s]*(\d{5,6})\b/i) || preview.match(/\b(\d{5,6})\b/);
                if (matchPrev) return matchPrev[1];

                const matchBody = body.match(/(?:code|is|is:|कोड|है|FB-)\s*[:\s]*(\d{5,6})\b/i) || body.match(/\b(\d{5,6})\b/);
                if (matchBody) return matchBody[1];
              }
            }
          }
        }
        if (groupSuccess) break;
      }
    } catch (e) {
      console.warn(`[OTP] Polling note: ${e.message}`);
    }

    const elapsed = Math.round((Date.now() - startTime) / 1000);
    console.log(`[OTP] Waiting for new message... (${elapsed}s elapsed)`);
    await new Promise((r) => setTimeout(r, 4000));
  }

  return null;
}

// 3. Playwright/Camoufox Function to Submit OTP into the page
export async function submitOtpToPage(page, otpCode) {
  console.log(`[Facebook] Entering OTP code: ${otpCode}...`);
  const input = page.locator("input[name='code'], input[aria-label*='code' i], input[aria-label*='कोड' i], input[placeholder*='code' i], input[placeholder*='कोड' i], input[placeholder*='Confirmation code' i], input[type='text'], input:not([type])").first();
  await input.click();
  await input.pressSequentially(otpCode, { delay: 100 });
  await page.waitForTimeout(500);

  console.log("[Facebook] Clicking 'Continue' button...");
  const continueBtn = page.locator("button:has-text('Continue'), [role='button']:has-text('Continue'), button:has-text('जारी रखें'), button:has-text('आगे बढ़ें'), button[type='submit']").first();
  if ((await continueBtn.count()) > 0) {
    await continueBtn.click();
  } else {
    await page.keyboard.press("Enter");
  }

  console.log("[Facebook] OTP submitted successfully.");
}

// Run standalone if executed directly
if (process.argv[1]?.endsWith("fetch_outlook_otp.mjs")) {
  fetchFacebookOtp(clientId, refreshToken)
    .then((otp) => {
      if (otp) {
        console.log("=========================================");
        console.log(`SUCCESS! 5-Digit Facebook OTP Code: ${otp}`);
        console.log("=========================================");
      } else {
        console.log("No new Facebook OTP message found within timeout.");
      }
    })
    .catch((err) => {
      console.error("Error:", err.message);
    });
}
