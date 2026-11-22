import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const CONFIG_FILE = path.resolve(__dirname, "..", "config", "supabase_config.json");

/**
 * Reads Supabase configuration from environment or config file.
 */
export function getSupabaseConfig() {
  let supabaseUrl = process.env.SUPABASE_URL || "";
  let supabaseKey = process.env.SUPABASE_KEY || process.env.SUPABASE_SERVICE_ROLE_KEY || "";
  let tableName = "social_accounts";
  let enabled = true;

  if (fs.existsSync(CONFIG_FILE)) {
    try {
      const data = JSON.parse(fs.readFileSync(CONFIG_FILE, "utf-8"));
      if (data.supabase_url && !supabaseUrl) supabaseUrl = data.supabase_url.trim();
      if (data.supabase_key && !supabaseKey) supabaseKey = data.supabase_key.trim();
      if (data.table_name) tableName = data.table_name.trim();
      if (typeof data.enabled === "boolean") enabled = data.enabled;
    } catch (e) { }
  }

  // Remove trailing slashes
  if (supabaseUrl) supabaseUrl = supabaseUrl.replace(/\/+$/, "");

  return { supabaseUrl, supabaseKey, tableName, enabled };
}

/**
 * Saves Supabase config.
 */
export function setSupabaseConfig(supabaseUrl, supabaseKey, tableName = "social_accounts", enabled = true) {
  try {
    fs.mkdirSync(path.dirname(CONFIG_FILE), { recursive: true });
    fs.writeFileSync(CONFIG_FILE, JSON.stringify({
      supabase_url: (supabaseUrl || "").trim().replace(/\/+$/, ""),
      supabase_key: (supabaseKey || "").trim(),
      table_name: tableName.trim(),
      enabled
    }, null, 2), "utf-8");
    return true;
  } catch (err) {
    console.error(`[SupabaseLogger] Failed to write config: ${err.message}`);
    return false;
  }
}

/**
 * Logs or updates an account record in Supabase via PostgREST.
 * Uses 'resolution=merge-duplicates' on unique email column.
 */
export async function logToSupabase(accountData) {
  const { supabaseUrl, supabaseKey, tableName, enabled } = getSupabaseConfig();

  if (!enabled || !supabaseUrl || !supabaseKey || !supabaseUrl.startsWith("http")) {
    return { skipped: true, reason: "Supabase not configured or disabled" };
  }

  // Extract 2FA components
  const tf = accountData.two_factor || {};
  const tfSecret = accountData.two_factor_secret || accountData.totp_secret || tf.secret_key || "";
  let bCodes = accountData.backup_codes || tf.backup_codes || "";
  if (Array.isArray(bCodes)) {
    bCodes = bCodes.join(", ");
  }

  // Auto-resolve proxy if missing from caller
  let proxyVal = accountData.proxy || accountData.proxy_used || "";
  if (!proxyVal) {
    try {
      const identsFile = path.resolve(__dirname, "..", "output", "identities.json");
      if (fs.existsSync(identsFile)) {
        const idents = JSON.parse(fs.readFileSync(identsFile, "utf-8"));
        const targetEmail = (accountData.email || "").toLowerCase().trim();
        const match = Array.isArray(idents)
          ? idents.find(i => (i.email || "").toLowerCase() === targetEmail)
          : null;
        if (match && match.proxy) proxyVal = match.proxy;
      }
    } catch (e) { }
  }

  const payload = {
    platform: (accountData.platform || "Instagram").toUpperCase(),
    email: (accountData.email || "").toLowerCase().trim(),
    username: accountData.username || "",
    password: accountData.password || "",
    profile_url: accountData.profile_url || accountData.url || (accountData.username && accountData.platform === "Instagram" ? `https://www.instagram.com/${accountData.username}/` : ""),
    full_mail_string: accountData.full_mail_string || accountData.outlook_raw || accountData.account_string || "",
    two_factor_secret: tfSecret,
    backup_codes: bCodes,
    status: (accountData.status || (accountData.is_suspended ? "SUSPENDED" : "ACTIVE")).toUpperCase(),
    details: accountData.details || {},
    updated_at: new Date().toISOString()
  };

  // Only attach proxy if present to prevent wiping existing proxy on partial updates
  if (proxyVal) {
    payload.proxy = proxyVal;
  }

  if (!payload.email) {
    return { skipped: true, reason: "Email is required for Supabase upsert" };
  }

  console.log(`[SupabaseLogger] Syncing ${payload.platform} account (${payload.email}) to Supabase...`);

  try {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 10000);

    const endpoint = `${supabaseUrl}/rest/v1/${tableName}?on_conflict=email`;
    const resp = await fetch(endpoint, {
      method: "POST",
      headers: {
        "apikey": supabaseKey,
        "Authorization": `Bearer ${supabaseKey}`,
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates,return=representation"
      },
      body: JSON.stringify(payload),
      signal: controller.signal
    });
    clearTimeout(timeout);

    if (resp.ok) {
      const data = await resp.json().catch(() => []);
      console.log(`[SupabaseLogger] Successfully synced account (${payload.email}) to Supabase!`);

      // Also ensure email is saved in separate email_accounts table with existence check
      logEmailToSupabase({
        email: payload.email,
        password: payload.password,
        full_mail_string: payload.full_mail_string,
        platform: payload.platform.toLowerCase(),
        status: payload.status,
        details: { proxy: payload.proxy || "" }
      }).catch(() => { });

      return { success: true, data };
    } else {
      const errText = await resp.text();
      console.warn(`[SupabaseLogger] Supabase API error (HTTP ${resp.status}): ${errText}`);
      return { success: false, status: resp.status, error: errText };
    }
  } catch (err) {
    console.warn(`[SupabaseLogger] Network warning: Could not sync to Supabase (${err.message}). Local record is preserved.`);
    return { success: false, error: err.message };
  }
}

export const EMAILS_TABLE = "email_accounts";

/**
 * Checks if an email already exists in Supabase email_accounts table.
 * Returns { exists: boolean, record: object | null, tableMissing?: boolean }
 */
export async function checkEmailExists(email) {
  const { supabaseUrl, supabaseKey, enabled } = getSupabaseConfig();
  if (!enabled || !supabaseUrl || !supabaseKey) {
    return { exists: false, error: "Supabase not configured or disabled" };
  }

  const cleanEmail = (email || "").toLowerCase().trim();
  if (!cleanEmail) {
    return { exists: false, error: "Empty email provided" };
  }

  try {
    const endpoint = `${supabaseUrl}/rest/v1/${EMAILS_TABLE}?email=eq.${encodeURIComponent(cleanEmail)}&select=id,email,provider,status,used_in_platforms,last_used_platform,last_used_at,created_at`;
    const resp = await fetch(endpoint, {
      method: "GET",
      headers: {
        "apikey": supabaseKey,
        "Authorization": `Bearer ${supabaseKey}`,
        "Accept": "application/json"
      }
    });

    if (resp.ok) {
      const records = await resp.json().catch(() => []);
      if (Array.isArray(records) && records.length > 0) {
        return { exists: true, record: records[0] };
      }
      return { exists: false, record: null };
    } else {
      const errText = await resp.text();
      if (resp.status === 404 && errText.includes("Could not find the table")) {
        return { exists: false, tableMissing: true, error: errText };
      }
      return { exists: false, error: errText };
    }
  } catch (err) {
    return { exists: false, error: err.message };
  }
}

/**
 * Saves/registers an email into the separate email_accounts table in Supabase.
 * Checks before appending if it already exists:
 * - If exists: merges platform into used_in_platforms and updates last_used_at / credentials.
 * - If new: appends a fresh record into email_accounts.
 */
export async function logEmailToSupabase(mailData) {
  const { supabaseUrl, supabaseKey, enabled } = getSupabaseConfig();
  if (!enabled || !supabaseUrl || !supabaseKey) {
    return { skipped: true, reason: "Supabase not configured or disabled" };
  }

  const cleanEmail = (mailData.email || "").toLowerCase().trim();
  if (!cleanEmail) {
    return { skipped: true, reason: "Email is required" };
  }

  // Parse email|password|refresh_token|client_id if full_mail_string is provided
  let password = mailData.password || "";
  let refreshToken = mailData.refresh_token || "";
  let clientId = mailData.client_id || "";
  const fullMailString = mailData.full_mail_string || mailData.account_string || "";
  if (fullMailString && fullMailString.includes("|")) {
    const parts = fullMailString.split("|");
    if (parts.length >= 2 && !password) password = parts[1].trim();
    if (parts.length >= 3 && !refreshToken) refreshToken = parts[2].trim();
    if (parts.length >= 4 && !clientId) clientId = parts[3].trim();
  }

  // Derive email provider
  let provider = mailData.provider || "";
  if (!provider) {
    const domain = cleanEmail.split("@")[1] || "";
    if (domain.includes("outlook") || domain.includes("hotmail") || domain.includes("live") || domain.includes("msn")) provider = "outlook";
    else if (domain.includes("gmail") || domain.includes("google")) provider = "gmail";
    else if (domain.includes("yahoo")) provider = "yahoo";
    else if (domain.includes("lnovic") || domain.includes("temp-mail")) provider = "temp-mail";
    else provider = domain.split(".")[0] || "other";
  }

  const platform = (mailData.platform || mailData.last_used_platform || "").toLowerCase();

  // 1. Check if email already exists in Supabase
  const check = await checkEmailExists(cleanEmail);
  if (check.tableMissing) {
    console.warn(`[SupabaseLogger] Note: table '${EMAILS_TABLE}' not created in Supabase yet. Please run tools/supabase_schema.sql in your Supabase SQL Editor.`);
    return { skipped: true, tableMissing: true, reason: `Table ${EMAILS_TABLE} not created in Supabase` };
  }

  const now = new Date().toISOString();

  if (check.exists && check.record) {
    console.log(`[SupabaseLogger] Email (${cleanEmail}) already exists in Supabase. Merging platform info...`);
    let existingPlatforms = check.record.used_in_platforms || [];
    if (!Array.isArray(existingPlatforms)) {
      existingPlatforms = typeof existingPlatforms === "string" ? existingPlatforms.split(",").map(p => p.trim()) : [];
    }
    if (platform && !existingPlatforms.includes(platform)) {
      existingPlatforms.push(platform);
    }

    const patchPayload = {
      used_in_platforms: existingPlatforms,
      last_used_platform: platform || check.record.last_used_platform || "",
      last_used_at: now,
      updated_at: now
    };
    if (password && !check.record.password) patchPayload.password = password;
    if (refreshToken && !check.record.refresh_token) patchPayload.refresh_token = refreshToken;
    if (clientId && !check.record.client_id) patchPayload.client_id = clientId;
    if (fullMailString) patchPayload.full_mail_string = fullMailString;
    if (mailData.status) patchPayload.status = mailData.status;

    try {
      const patchEndpoint = `${supabaseUrl}/rest/v1/${EMAILS_TABLE}?email=eq.${encodeURIComponent(cleanEmail)}`;
      const resp = await fetch(patchEndpoint, {
        method: "PATCH",
        headers: {
          "apikey": supabaseKey,
          "Authorization": `Bearer ${supabaseKey}`,
          "Content-Type": "application/json",
          "Prefer": "return=representation"
        },
        body: JSON.stringify(patchPayload)
      });
      if (resp.ok) {
        const updated = await resp.json().catch(() => []);
        return { success: true, isNew: false, data: updated[0] || patchPayload };
      }
    } catch (err) {
      console.warn(`[SupabaseLogger] Error updating existing email: ${err.message}`);
    }
    return { success: true, isNew: false, data: check.record };
  } else {
    // Brand new email: append
    console.log(`[SupabaseLogger] Email (${cleanEmail}) is new. Appending to '${EMAILS_TABLE}' in Supabase...`);
    const platforms = platform ? [platform] : [];
    const insertPayload = {
      email: cleanEmail,
      password: password,
      refresh_token: refreshToken,
      client_id: clientId,
      full_mail_string: fullMailString,
      provider: provider,
      status: mailData.status || "ACTIVE",
      used_in_platforms: platforms,
      last_used_platform: platform || "",
      last_used_at: now,
      created_at: now,
      updated_at: now,
      details: mailData.details || {}
    };

    try {
      const insertEndpoint = `${supabaseUrl}/rest/v1/${EMAILS_TABLE}`;
      const resp = await fetch(insertEndpoint, {
        method: "POST",
        headers: {
          "apikey": supabaseKey,
          "Authorization": `Bearer ${supabaseKey}`,
          "Content-Type": "application/json",
          "Prefer": "return=representation"
        },
        body: JSON.stringify(insertPayload)
      });
      if (resp.ok) {
        const created = await resp.json().catch(() => []);
        console.log(`[SupabaseLogger] Successfully appended new email (${cleanEmail}) to Supabase!`);
        return { success: true, isNew: true, data: created[0] || insertPayload };
      } else {
        const errText = await resp.text();
        console.warn(`[SupabaseLogger] Error inserting email: ${errText}`);
        return { success: false, isNew: true, error: errText };
      }
    } catch (err) {
      console.warn(`[SupabaseLogger] Failed to insert email: ${err.message}`);
      return { success: false, error: err.message };
    }
  }
}

// Standalone CLI test
if (process.argv.includes("--test")) {
  const { supabaseUrl, supabaseKey } = getSupabaseConfig();
  console.log("Supabase URL:", supabaseUrl || "(none configured)");
  if (!supabaseUrl || !supabaseKey) {
    console.log("Please configure Supabase URL and Key in config/supabase_config.json");
    process.exit(1);
  }
  logToSupabase({
    platform: "Test-Node",
    email: "test_verification@outlook.com",
    username: "test_bot_node",
    password: "TestPassword123!",
    profile_url: "https://instagram.com/test_bot_node",
    full_mail_string: "test_verification@outlook.com|pass|token|clientId",
    two_factor_secret: "JBSWY3DPEHPK3PXP",
    backup_codes: ["1234 5678", "8765 4321"],
    status: "TEST_VERIFIED"
  }).then(r => console.log("Test result:", r));
}
