/**
 * tools/oxylabs_accounts_db.mjs
 * =============================
 * Durable SQLite store for Oxylabs accounts, their passwords, the proxies used
 * for signup and created from the dashboard, usage snapshots and risk events.
 *
 * Uses Node's built-in `node:sqlite` (Node >= 22.5, tested on Node 26). The
 * JSON registry in output/oxylabs_registered_accounts.json remains a mirror;
 * this database is the source of truth for "when was the account created" and
 * "when was the proxy created".
 *
 * Tables
 *   accounts         one row per email (password, persona/profile, dates)
 *   proxies          one row per distinct proxy endpoint (with created_at)
 *   usage_snapshots  every commitment-card reading
 *   risk_events      anonymity/coherence events per account
 *
 * Dates:
 *   accounts.first_seen_at   first time this script recorded the email
 *   accounts.created_at      when the registration was actually submitted
 *   accounts.activated_at    when the activation link was completed
 *   proxies.created_at       first time this proxy endpoint was seen
 *                            (for dashboard-generated proxies this is the day
 *                            the Residential Proxies instance was created)
 */

import fs from "node:fs";
import path from "node:path";
import crypto from "node:crypto";

export const DB_FILE = path.resolve("output", "oxylabs_accounts.db");

let DatabaseSync = null;
let db = null;
let warnedUnavailable = false;

try {
  ({ DatabaseSync } = await import("node:sqlite"));
} catch (err) {
  DatabaseSync = null;
}

function isAvailable() {
  return Boolean(DatabaseSync);
}

function warnUnavailable() {
  if (warnedUnavailable) return;
  warnedUnavailable = true;
  console.warn(
    "[Oxylabs DB] node:sqlite is unavailable on this Node build; records will only be written to the JSON registry."
  );
}

function nowIso() {
  return new Date().toISOString();
}

function dateOnly(value) {
  if (!value) return null;
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? null : d.toISOString().slice(0, 10);
}

function sha256Short(value, length = 16) {
  if (!value) return null;
  return crypto.createHash("sha256").update(String(value)).digest("hex").slice(0, length);
}

function md5Full(value) {
  return crypto.createHash("md5").update(String(value || "")).digest("hex");
}

function sha256Full(value) {
  return crypto.createHash("sha256").update(String(value || "")).digest("hex");
}

function createdDayLabel(value) {
  const d = new Date(value);
  if (!d || Number.isNaN(d.getTime())) return null;
  return d.toLocaleDateString("en-US", { weekday: "long", year: "numeric", month: "long", day: "numeric" });
}

function firstExitIp(record) {
  return record.proxy_ip
    || record.exit_ip
    || record.preflight?.info?.ip
    || record.exit_ips?.[0]?.ip
    || null;
}

/**
 * Parse a proxy URL/string into the fields worth indexing. The full proxy
 * string (including credentials) is stored for reuse, but only the host, port
 * and a username hash are indexed in clear text.
 */
export function proxyParts(proxyString) {
  const clean = String(proxyString || "").trim().replace(/^https?:\/\//i, "");
  if (!clean) {
    return { host: null, port: null, username: null, username_hash: null, session: null, session_type: null, session_minutes: null, country: null, city: null };
  }
  const at = clean.lastIndexOf("@");
  const auth = at >= 0 ? clean.slice(0, at) : "";
  const hostPort = at >= 0 ? clean.slice(at + 1) : clean;
  const colon = auth.indexOf(":");
  const username = colon >= 0 ? auth.slice(0, colon) : auth;

  const hostMatch = hostPort.match(/^([^:]+)(?::(\d+))?$/);
  const host = hostMatch ? hostMatch[1] : hostPort;
  const port = hostMatch && hostMatch[2] ? Number(hostMatch[2]) : null;

  const sessionMatch = username.match(/(?:^|[-_])(sessid_oneip|sessid|session|sess)[-_]([A-Za-z0-9._]+)/i);
  const sessionType = sessionMatch ? sessionMatch[1].toLowerCase() : null;
  const session = sessionMatch ? sessionMatch[2] : null;
  const sessionTimeMatch = username.match(/-sesstime-(\d+)/i);
  const countryMatch = username.match(/-cc-([a-z]{2})(?:[-_]|$)/i);
  const cityMatch = username.match(/-city-([a-z0-9_]+)(?:[-_]|$)/i);

  return {
    host: host || null,
    port,
    username: username || null,
    username_hash: sha256Short(username),
    session,
    session_type: sessionType,
    session_minutes: sessionTimeMatch ? Number(sessionTimeMatch[1]) : null,
    country: countryMatch ? countryMatch[1].toUpperCase() : null,
    city: cityMatch ? cityMatch[1] : null,
  };
}

export function openDatabase() {
  if (db) return db;
  if (!DatabaseSync) {
    warnUnavailable();
    return null;
  }

  try {
    fs.mkdirSync(path.dirname(DB_FILE), { recursive: true });
    db = new DatabaseSync(DB_FILE);
    db.exec("PRAGMA journal_mode = WAL;");
    db.exec("PRAGMA synchronous = NORMAL;");
    db.exec("PRAGMA foreign_keys = ON;");

    db.exec(`
      CREATE TABLE IF NOT EXISTS accounts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        email TEXT NOT NULL UNIQUE COLLATE NOCASE,
        password TEXT,
        first_name TEXT,
        surname TEXT,
        instance_name TEXT,
        profile_dir TEXT,
        status TEXT,
        final_url TEXT,
        submitted INTEGER NOT NULL DEFAULT 0,
        first_seen_at TEXT NOT NULL,
        created_at TEXT,
        submitted_at TEXT,
        activated_at TEXT,
        updated_at TEXT NOT NULL,
        last_usage_check_at TEXT,
        plan_name TEXT,
        spent_usd REAL,
        commitment_usd REAL,
        usage_left_usd REAL,
        usage_left_percent REAL,
        proxy_username_hash TEXT,
        email_domain TEXT,
        email_hash_sha256 TEXT,
        email_hash_md5 TEXT,
        created_day TEXT,
        proxy_ip TEXT,
        persona_hash TEXT,
        fingerprint_hash TEXT,
        notes TEXT
      );

      CREATE TABLE IF NOT EXISTS proxies (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        account_email TEXT NOT NULL COLLATE NOCASE,
        proxy_string TEXT NOT NULL,
        proxy_host TEXT,
        proxy_port INTEGER,
        proxy_username_hash TEXT,
        proxy_session TEXT,
        proxy_session_type TEXT,
        proxy_session_minutes INTEGER,
        proxy_country TEXT,
        proxy_city TEXT,
        source TEXT NOT NULL DEFAULT 'unknown',
        used_for_signup INTEGER NOT NULL DEFAULT 0,
        instance_name TEXT,
        created_at TEXT NOT NULL,
        last_seen_at TEXT NOT NULL,
        active INTEGER NOT NULL DEFAULT 1,
        UNIQUE(account_email, proxy_string)
      );

      CREATE TABLE IF NOT EXISTS usage_snapshots (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        account_email TEXT NOT NULL COLLATE NOCASE,
        checked_at TEXT NOT NULL,
        plan_name TEXT,
        spent_usd REAL,
        commitment_usd REAL,
        usage_left_usd REAL,
        used_percent REAL,
        usage_left_percent REAL,
        source TEXT
      );

      CREATE TABLE IF NOT EXISTS risk_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        account_email TEXT NOT NULL COLLATE NOCASE,
        event_at TEXT NOT NULL,
        step TEXT,
        level TEXT NOT NULL DEFAULT 'info',
        message TEXT,
        details_json TEXT
      );

      CREATE INDEX IF NOT EXISTS idx_proxies_account ON proxies(account_email, last_seen_at DESC);
      CREATE INDEX IF NOT EXISTS idx_usage_account ON usage_snapshots(account_email, checked_at DESC);
      CREATE INDEX IF NOT EXISTS idx_risk_account ON risk_events(account_email, event_at DESC);
    `);

    // Migration for accounts tables created before the FB/IG-parity columns.
    for (const col of [
      "email_hash_sha256",
      "email_hash_md5",
      "created_day",
      "proxy_ip",
      "persona_hash",
      "fingerprint_hash",
    ]) {
      try {
        db.exec(`ALTER TABLE accounts ADD COLUMN ${col} TEXT`);
      } catch (err) {
        // column already exists
      }
    }

    // Backfill account hashes/day for rows created before these columns existed.
    const existingAccounts = db.prepare("SELECT email, created_at FROM accounts").all();
    for (const row of existingAccounts) {
      const normalized = String(row.email || "").trim().toLowerCase();
      db.prepare(`
        UPDATE accounts
           SET email_hash_sha256 = COALESCE(email_hash_sha256, ?),
               email_hash_md5 = COALESCE(email_hash_md5, ?),
               created_day = COALESCE(created_day, ?)
         WHERE email = ?
      `).run(
        sha256Full(normalized),
        md5Full(normalized),
        createdDayLabel(row.created_at),
        normalized
      );
    }

    // Backfill spoof hashes from the profile files for rows created before
    // these columns existed (persona.json / risk_log.json).
    const spoofRows = db.prepare(`
      SELECT email, profile_dir FROM accounts
       WHERE persona_hash IS NULL OR fingerprint_hash IS NULL OR proxy_ip IS NULL
    `).all();
    for (const row of spoofRows) {
      if (!row.profile_dir) continue;
      try {
        const personaPath = path.join(row.profile_dir, "persona.json");
        if (fs.existsSync(personaPath)) {
          const persona = JSON.parse(fs.readFileSync(personaPath, "utf-8"));
          const personaHash = crypto.createHash("sha256").update(JSON.stringify(persona)).digest("hex").slice(0, 16);
          db.prepare("UPDATE accounts SET persona_hash = COALESCE(persona_hash, ?) WHERE email = ?")
            .run(personaHash, row.email);
        }
        const riskPath = path.join(row.profile_dir, "risk_log.json");
        if (fs.existsSync(riskPath)) {
          const risk = JSON.parse(fs.readFileSync(riskPath, "utf-8"));
          const fingerprintHash = risk?.fingerprint?.hash || null;
          if (fingerprintHash) {
            db.prepare("UPDATE accounts SET fingerprint_hash = COALESCE(fingerprint_hash, ?) WHERE email = ?")
              .run(fingerprintHash, row.email);
          }
          const firstIp = (risk?.exit_ips || []).find((x) => x?.ip)?.ip || risk?.preflight?.ip || null;
          if (firstIp) {
            db.prepare("UPDATE accounts SET proxy_ip = COALESCE(proxy_ip, ?) WHERE email = ?")
              .run(firstIp, row.email);
          }
        }
      } catch (err) {
        // ignore per-profile backfill failures
      }
    }

    return db;
  } catch (err) {
    console.warn(`[Oxylabs DB] Could not open ${DB_FILE}: ${err.message}`);
    db = null;
    return null;
  }
}

function safe(fn, fallback = null) {
  try {
    return fn();
  } catch (err) {
    console.warn(`[Oxylabs DB] Write failed: ${err.message}`);
    return fallback;
  }
}

/**
 * Insert/update one proxy row. `created_at` is only set on first insert and is
 * never overwritten. It is the global earliest first-seen date for that proxy
 * string, so the best available "day the proxy was made" survives even when
 * the same proxy is reused across accounts. Returns the stored row (or null).
 */
function upsertProxy(database, {
  email,
  proxyString,
  source = "unknown",
  usedForSignup = false,
  instanceName = null,
  country = null,
  city = null,
}) {
  if (!proxyString) return null;
  const parts = proxyParts(proxyString);
  const now = nowIso();

  const existing = database
    .prepare("SELECT * FROM proxies WHERE account_email = ? AND proxy_string = ?")
    .get(email, proxyString);

  if (existing) {
    database.prepare(`
      UPDATE proxies
         SET last_seen_at = ?,
             used_for_signup = MAX(used_for_signup, ?),
             active = 1,
             source = CASE WHEN source = 'unknown' THEN ? ELSE source END
       WHERE id = ?
    `).run(now, usedForSignup ? 1 : 0, source, existing.id);
    return database.prepare("SELECT * FROM proxies WHERE id = ?").get(existing.id);
  }

  const firstSeen = database
    .prepare("SELECT MIN(created_at) AS first_created FROM proxies WHERE proxy_string = ?")
    .get(proxyString);
  const proxyCreatedAt = firstSeen?.first_created || now;

  database.prepare(`
    INSERT INTO proxies (
      account_email, proxy_string, proxy_host, proxy_port,
      proxy_username_hash, proxy_session, proxy_session_type,
      proxy_session_minutes, proxy_country, proxy_city,
      source, used_for_signup, instance_name, created_at, last_seen_at, active
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
  `).run(
    email,
    proxyString,
    parts.host,
    parts.port,
    parts.username_hash,
    parts.session,
    parts.session_type,
    parts.session_minutes,
    country || parts.country,
    city || parts.city,
    source,
    usedForSignup ? 1 : 0,
    instanceName,
    proxyCreatedAt,
    now
  );

  return database
    .prepare("SELECT * FROM proxies WHERE account_email = ? AND proxy_string = ?")
    .get(email, proxyString);
}

/**
 * Persist a registry record into SQLite.
 *
 * Returns the durable dates so the JSON mirror can carry the same values:
 *   { first_seen_at, account_created_at, account_activated_at,
 *     proxy_created_at, proxy_first_seen_at }
 */
export function persistRecord(record, { proxyIdentity = null, effectiveProxy = null } = {}) {
  const database = openDatabase();
  if (!database || !record || !record.email) return {};

  return safe(() => {
    const email = String(record.email).trim().toLowerCase();
    const now = nowIso();
    const existing = database.prepare("SELECT * FROM accounts WHERE email = ?").get(email);

    const firstSeenAt = existing ? existing.first_seen_at : now;
    const submittedAt = record.submitted
      ? existing?.submitted_at || now
      : existing?.submitted_at || null;
    const accountCreatedAt = record.submitted
      ? existing?.created_at || now
      : existing?.created_at || null;
    const activatedAt = record.activation_completed
      ? existing?.activated_at || now
      : existing?.activated_at || null;

    const domain = email.includes("@") ? email.split("@")[1].toLowerCase() : null;
    const usage = record.usage || null;

    const emailHashSha256 = sha256Full(email);
    const emailHashMd5 = md5Full(email);
    const createdDay = record.created_day || createdDayLabel(accountCreatedAt || record.created_at || firstSeenAt);
    const proxyIp = firstExitIp(record);

    database.prepare(`
      INSERT INTO accounts (
        email, password, first_name, surname, instance_name, profile_dir,
        status, final_url, submitted, first_seen_at, created_at, submitted_at,
        activated_at, updated_at, last_usage_check_at, plan_name,
        spent_usd, commitment_usd, usage_left_usd, usage_left_percent,
        proxy_username_hash, email_domain,
        email_hash_sha256, email_hash_md5, created_day, proxy_ip,
        persona_hash, fingerprint_hash
      ) VALUES (
        :email, :password, :first_name, :surname, :instance_name, :profile_dir,
        :status, :final_url, :submitted, :first_seen_at, :created_at, :submitted_at,
        :activated_at, :updated_at, :last_usage_check_at, :plan_name,
        :spent_usd, :commitment_usd, :usage_left_usd, :usage_left_percent,
        :proxy_username_hash, :email_domain,
        :email_hash_sha256, :email_hash_md5, :created_day, :proxy_ip,
        :persona_hash, :fingerprint_hash
      )
      ON CONFLICT(email) DO UPDATE SET
        password = COALESCE(excluded.password, accounts.password),
        first_name = COALESCE(excluded.first_name, accounts.first_name),
        surname = COALESCE(excluded.surname, accounts.surname),
        instance_name = COALESCE(excluded.instance_name, accounts.instance_name),
        profile_dir = COALESCE(excluded.profile_dir, accounts.profile_dir),
        status = COALESCE(excluded.status, accounts.status),
        final_url = COALESCE(excluded.final_url, accounts.final_url),
        submitted = MAX(accounts.submitted, excluded.submitted),
        created_at = COALESCE(accounts.created_at, excluded.created_at),
        submitted_at = COALESCE(accounts.submitted_at, excluded.submitted_at),
        activated_at = COALESCE(accounts.activated_at, excluded.activated_at),
        updated_at = excluded.updated_at,
        last_usage_check_at = COALESCE(excluded.last_usage_check_at, accounts.last_usage_check_at),
        plan_name = COALESCE(excluded.plan_name, accounts.plan_name),
        spent_usd = COALESCE(excluded.spent_usd, accounts.spent_usd),
        commitment_usd = COALESCE(excluded.commitment_usd, accounts.commitment_usd),
        usage_left_usd = COALESCE(excluded.usage_left_usd, accounts.usage_left_usd),
        usage_left_percent = COALESCE(excluded.usage_left_percent, accounts.usage_left_percent),
        proxy_username_hash = COALESCE(excluded.proxy_username_hash, accounts.proxy_username_hash),
        email_domain = COALESCE(excluded.email_domain, accounts.email_domain),
        email_hash_sha256 = COALESCE(excluded.email_hash_sha256, accounts.email_hash_sha256),
        email_hash_md5 = COALESCE(excluded.email_hash_md5, accounts.email_hash_md5),
        created_day = COALESCE(excluded.created_day, accounts.created_day),
        proxy_ip = COALESCE(excluded.proxy_ip, accounts.proxy_ip),
        persona_hash = COALESCE(excluded.persona_hash, accounts.persona_hash),
        fingerprint_hash = COALESCE(excluded.fingerprint_hash, accounts.fingerprint_hash)
    `).run({
      email,
      password: record.password || null,
      first_name: record.first_name || null,
      surname: record.surname || null,
      instance_name: record.instance_name || null,
      profile_dir: record.profile_dir || null,
      status: record.status || null,
      final_url: record.final_url || null,
      submitted: record.submitted ? 1 : 0,
      first_seen_at: firstSeenAt,
      created_at: accountCreatedAt,
      submitted_at: submittedAt,
      activated_at: activatedAt,
      updated_at: now,
      last_usage_check_at: usage ? now : null,
      plan_name: usage?.plan_name || null,
      spent_usd: usage ? Number(usage.spent_usd) || 0 : null,
      commitment_usd: usage ? Number(usage.commitment_usd) || 0 : null,
      usage_left_usd: usage ? Number(usage.usage_left_usd) || 0 : null,
      usage_left_percent: usage ? Number(usage.usage_left_percent) || 0 : null,
      proxy_username_hash: proxyIdentity?.username_hash || null,
      email_domain: domain,
      email_hash_sha256: emailHashSha256,
      email_hash_md5: emailHashMd5,
      created_day: createdDay,
      proxy_ip: proxyIp,
      persona_hash: record.persona_hash || null,
      fingerprint_hash: record.fingerprint_hash || null,
    });

    // The proxy that was actually used for this run.
    if (effectiveProxy) {
      upsertProxy(database, {
        email,
        proxyString: effectiveProxy,
        source: record.proxy_source || "cli",
        usedForSignup: Boolean(record.submitted || record.status === "started"),
        instanceName: record.instance_name || null,
      });
    }

    // The endpoint copied from the Oxylabs dashboard (the account's own proxy).
    let dashboardProxyRow = null;
    if (record.proxy_string) {
      dashboardProxyRow = upsertProxy(database, {
        email,
        proxyString: record.proxy_string,
        source: "dashboard-generated",
        usedForSignup: false,
        instanceName: record.instance_name || null,
        country: record.endpoint_country || null,
        city: record.endpoint_city || null,
      });
    }

    if (usage) {
      database.prepare(`
        INSERT INTO usage_snapshots (
          account_email, checked_at, plan_name, spent_usd, commitment_usd,
          usage_left_usd, used_percent, usage_left_percent, source
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
      `).run(
        email,
        now,
        usage.plan_name || null,
        Number(usage.spent_usd) || 0,
        Number(usage.commitment_usd) || 0,
        Number(usage.usage_left_usd) || 0,
        Number(usage.used_percent) || 0,
        Number(usage.usage_left_percent) || 0,
        record.status || null
      );
    }

    const row = database.prepare("SELECT * FROM accounts WHERE email = ?").get(email);

    return {
      first_seen_at: row?.first_seen_at || firstSeenAt,
      account_created_at: row?.created_at || accountCreatedAt,
      account_created_date: dateOnly(row?.created_at || accountCreatedAt),
      account_submitted_at: row?.submitted_at || submittedAt,
      account_activated_at: row?.activated_at || activatedAt,
      proxy_created_at: dashboardProxyRow?.created_at || null,
      proxy_created_date: dateOnly(dashboardProxyRow?.created_at),
      proxy_first_seen_at: dashboardProxyRow?.created_at || null,
    };
  }, {});
}

export function persistRiskEvents(email, events = []) {
  const database = openDatabase();
  if (!database || !email || !Array.isArray(events) || events.length === 0) return 0;

  return safe(() => {
    const stmt = database.prepare(`
      INSERT INTO risk_events (account_email, event_at, step, level, message, details_json)
      VALUES (?, ?, ?, ?, ?, ?)
    `);
    let count = 0;
    const normalized = String(email).trim().toLowerCase();
    for (const event of events) {
      if (!event) continue;
      stmt.run(
        normalized,
        event.at || nowIso(),
        event.step || null,
        event.level || "info",
        event.message || null,
        event.details === undefined ? null : JSON.stringify(event.details)
      );
      count += 1;
    }
    return count;
  }, 0);
}

export function getAccount(email) {
  const database = openDatabase();
  if (!database || !email) return null;
  return safe(() => {
    const row = database.prepare("SELECT * FROM accounts WHERE email = ?").get(String(email).trim().toLowerCase());
    return row || null;
  }, null);
}

/** Latest/strongest proxy for an email; signup proxy first, then dashboard proxy. */
export function getPreferredProxy(email) {
  const database = openDatabase();
  if (!database || !email) return null;
  return safe(() => {
    const row = database
      .prepare(`
        SELECT * FROM proxies
         WHERE account_email = ? AND active = 1
         ORDER BY used_for_signup DESC,
                  CASE source WHEN 'dashboard-generated' THEN 0 ELSE 1 END,
                  last_seen_at DESC
         LIMIT 1
      `)
      .get(String(email).trim().toLowerCase());
    return row || null;
  }, null);
}

export function getProxyHistory(email) {
  const database = openDatabase();
  if (!database || !email) return [];
  return safe(() => {
    return database
      .prepare("SELECT * FROM proxies WHERE account_email = ? ORDER BY created_at ASC")
      .all(String(email).trim().toLowerCase());
  }, []);
}

export function closeDatabase() {
  if (!db) return;
  try {
    db.close();
  } catch (err) {
    // ignore
  }
  db = null;
}

export { isAvailable as isDatabaseAvailable, DB_FILE as DATABASE_FILE };
