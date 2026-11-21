/**
 * tools/fb_graphql_client.mjs
 * ===========================
 * Lightweight Facebook Reverse GraphQL and Session Verification Helper.
 * Reverse-engineered from FBVerse Bot & modern Facebook Comet web client.
 *
 * Allows checking session validity, user IDs, and tokens without launching
 * a full browser process.
 */

import https from "node:https";
import { execFileSync } from "node:child_process";

/**
 * Calculates Facebook's jazoest token checksum from fb_dtsg.
 * Formula: '2' + sum of ASCII char codes of dtsg.
 */
export function calculateJazoest(dtsg) {
  if (!dtsg || typeof dtsg !== "string") return "";
  let sum = 0;
  for (let i = 0; i < dtsg.length; i++) {
    sum += dtsg.charCodeAt(i);
  }
  return `2${sum}`;
}

/**
 * Formats Playwright / Camoufox cookie arrays or raw strings into HTTP Cookie header string.
 */
export function formatCookieHeader(cookies) {
  if (typeof cookies === "string") return cookies.trim();
  if (Array.isArray(cookies)) {
    return cookies
      .map((c) => `${c.name}=${c.value}`)
      .join("; ");
  }
  if (typeof cookies === "object" && cookies !== null) {
    return Object.entries(cookies)
      .map(([k, v]) => `${k}=${v}`)
      .join("; ");
  }
  return "";
}

/**
 * Lightweight HTTP GET helper supporting optional proxy routing via curl
 * to eliminate home-IP / DNS leaks.
 */
function request(url, headers = {}, proxy = null) {
  if (proxy) {
    try {
      const curlArgs = ["-sS", "-i", "--connect-timeout", "10", "-x", String(proxy).trim()];
      for (const [k, v] of Object.entries(headers)) {
        curlArgs.push("-H", `${k}: ${v}`);
      }
      curlArgs.push(url);
      const rawOutput = execFileSync("curl.exe", curlArgs, { encoding: "utf-8", timeout: 20000 });
      const splitIdx = rawOutput.indexOf("\r\n\r\n") !== -1 ? rawOutput.indexOf("\r\n\r\n") : rawOutput.indexOf("\n\n");
      const rawHeaders = splitIdx !== -1 ? rawOutput.slice(0, splitIdx) : "";
      const body = splitIdx !== -1 ? rawOutput.slice(splitIdx).trimStart() : rawOutput;

      const headerLines = rawHeaders.split(/\r?\n/);
      const statusLine = headerLines[0] || "";
      const statusMatch = statusLine.match(/HTTP\/\S+\s+(\d+)/);
      const status = statusMatch ? parseInt(statusMatch[1], 10) : 200;
      const parsedHeaders = {};
      for (let i = 1; i < headerLines.length; i++) {
        const colon = headerLines[i].indexOf(":");
        if (colon !== -1) {
          const key = headerLines[i].slice(0, colon).trim().toLowerCase();
          const val = headerLines[i].slice(colon + 1).trim();
          parsedHeaders[key] = val;
        }
      }
      return Promise.resolve({ status, headers: parsedHeaders, body });
    } catch (err) {
      return Promise.reject(err);
    }
  }

  return new Promise((resolve, reject) => {
    const parsed = new URL(url);
    const req = https.request(
      {
        protocol: parsed.protocol,
        hostname: parsed.hostname,
        port: parsed.port || 443,
        path: parsed.pathname + parsed.search,
        method: "GET",
        headers: {
          "User-Agent":
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
          "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
          "Accept-Language": "en-US,en;q=0.9",
          ...headers,
        },
      },
      (res) => {
        let data = "";
        res.on("data", (chunk) => (data += chunk));
        res.on("end", () => resolve({ status: res.statusCode, headers: res.headers, body: data }));
      }
    );
    req.on("error", reject);
    req.setTimeout(15000, () => {
      req.destroy();
      reject(new Error("Request timed out after 15s"));
    });
    req.end();
  });
}

/**
 * Validates a Facebook session using cookies.
 * Returns: { authenticated: boolean, userId: string|null, dtsg: string|null, jazoest: string|null, checkpoint: boolean }
 */
export async function verifyFacebookSession(cookies, proxy = null) {
  const cookieStr = formatCookieHeader(cookies);
  if (!cookieStr) {
    return { authenticated: false, error: "Empty cookie input" };
  }

  try {
    const res = await request("https://www.facebook.com/", {
      Cookie: cookieStr,
    }, proxy);

    const body = res.body || "";
    const loc = String(res.headers?.location || "");

    // 1. Check for checkpoint / suspension
    const isCheckpoint =
      loc.includes("checkpoint") ||
      body.includes("/checkpoint/") ||
      body.includes("checkpointSubmitButton") ||
      body.includes("Account disabled") ||
      body.includes("Confirm your identity");

    if (isCheckpoint) {
      return { authenticated: false, checkpoint: true, error: "Account checkpoint detected" };
    }

    // 2. Extract c_user (User ID) from cookies or DOM
    let userId = null;
    const cUserMatch = cookieStr.match(/\bc_user=(\d+)/);
    if (cUserMatch) userId = cUserMatch[1];

    if (!userId) {
      const domUserMatch = body.match(/"USER_ID":"(\d+)"/) || body.match(/"actorID":"(\d+)"/);
      if (domUserMatch) userId = domUserMatch[1];
    }

    // 3. Extract fb_dtsg token from DOM
    let dtsg = null;
    const dtsgMatch =
      body.match(/"DTSGInitialData"[^>]*?"token":"([^"]+)"/) ||
      body.match(/name="fb_dtsg"\s+value="([^"]+)"/) ||
      body.match(/"dtsg":\{"token":"([^"]+)"/);
    if (dtsgMatch) dtsg = dtsgMatch[1];

    const isAuthenticated = Boolean(userId) && !body.includes('id="login_form"');

    return {
      authenticated: isAuthenticated,
      checkpoint: false,
      userId,
      dtsg,
      jazoest: dtsg ? calculateJazoest(dtsg) : null,
      status: isAuthenticated ? "ACTIVE" : "UNAUTHENTICATED",
    };
  } catch (err) {
    return { authenticated: false, error: err.message };
  }
}

/**
 * Validates an Instagram session using cookies.
 */
export async function verifyInstagramSession(cookies, proxy = null) {
  const cookieStr = formatCookieHeader(cookies);
  if (!cookieStr || !cookieStr.includes("sessionid")) {
    return { authenticated: false, error: "Missing sessionid cookie" };
  }

  try {
    const res = await request("https://www.instagram.com/", {
      Cookie: cookieStr,
    }, proxy);

    const body = res.body || "";
    const loc = String(res.headers?.location || "");
    const isSuspended =
      loc.includes("suspended") ||
      body.includes("/accounts/suspended/") ||
      body.includes("we suspended your account") ||
      body.includes("confirm you're human");

    const isLogin = body.includes("name=\"password\"") && !body.includes("\"viewer\":");

    return {
      authenticated: !isLogin && !isSuspended,
      suspended: isSuspended,
      status: isSuspended ? "SUSPENDED" : (!isLogin ? "ACTIVE" : "UNAUTHENTICATED"),
    };
  } catch (err) {
    return { authenticated: false, error: err.message };
  }
}
