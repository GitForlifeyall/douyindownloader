/**
 * tools/oxylabs_chain.mjs
 * Runs the Oxylabs signup chain:
 *   for each email: register account -> create Residential Proxies instance in
 *   a random country with a sticky 120-min proxy -> use that proxy for the
 *   next email.
 */
import fs from "node:fs";
import path from "node:path";
import crypto from "node:crypto";
import { execFileSync } from "node:child_process";
import { DatabaseSync } from "node:sqlite";
import { openDatabase, DB_FILE } from "./oxylabs_accounts_db.mjs";

const accounts = [
  'AshleyKnappd8025h@outlook.com|x|M.C517_BL2.0.U.MsaArtifacts.-ChYkL9kAZZlEWjQp!MMQ!w3OJ7LkbanFnFFHxpoCOiw6b*4rCeLJO2b1uUOVYgiUjsiaSSSL7Dp2fqMih3ZMJVvdPFDYo8TDh0EXfj9nc1y9A25lTuB9znYyUrOQzIREvzVnzkL2UvsRPORauIBNIEVUVSWIeIjEVor8GU7wjNKjBvIzLzkgTSLSrPfRV7SisfaeQRaa4k9xIgJi8ibs0CZM1!Ucu0gtwkR9sK!asfeHuca6Tnxqft6nITsIEP75Um5ucBO!ad5A!HEsI5sZmyDjI6BxgPH326HuOyqyWR20AMJyZ!hcAHjyxcTK5RNSWiZnHNKpEexPuydsol6i9xXyLzdjSGEkVl7tmymmqF*3R4SDiH5u2cnv*edZtid0N7kEfUyvh4Ar89DZOWHpowlj!2*HvIrhPaQTjZzG*XXd|9e5f94bc-e8a4-4e73-b8be-63364c29d753',
  'BrianHicksJ185762fZs@outlook.it|x|M.C534_BL2.0.U.MsaArtifacts.-Csqo4UPCrjxZiv!WbdtefXrWqn!k51Yhnv8iI9VkqC35C6zco3j6OflwYIATZUA09VZc49ysHNDHBpWXYg1KbOXjqZ5mBMboGnGBQUU7Bc0fR9mhgkijJaU*4KfyEXZ8*HGkkghUHCMaa1Nd7cMNR57QFZGlvUethmQ07*11WKYGgr7aqBO2AWRBiACaG2Z5PiLkD*SPeo!Lf2qrGCzVHox6F3xxpQExw3gUSpX2vWU9LT0ovlTFjnDda4vwuWf7APfSmqGXU3UKVPJKxLAsSZY6blLiw0R!X90!KwftxxCL*i7CuKcgPU4iWNbFR0fQGyAfeHJHF!K3rpfCuJQEibpohos8KFeBwmgzkk!jbruSw8k*VxUjQjy8zWU8ax6WPWhjKqqezTAJkU74p5Vl8eSWCbd0Jd0E85Uhb6520UGCiRTnzU!KqOzXzCRKntFYBy4IbRhFhIuzGGjVibEuqJFa!O4hx9DSP2tQl**4rz5RowjD!4Ry04WH40WB!YzkHg$$|9e5f94bc-e8a4-4e73-b8be-63364c29d753',
  'CasonClairmont7374@hotmail.com|ffimzip33|M.C557_BAY.0.U.MsaArtifacts.-Chhy0*KD80E0cWppfIQSUYcoxYfrVIQ1t6eM!xu8y1qZ7hEUBZzUnX!BerB2SGLYBStAXVlsoOonj9L!XKGMomrm2YThHRBqeHp4FrQbXjeeO2FYdlmvSyINGSw4*DGvrvGkVdb7ZIyW7SsuyjUhbXfYw9cJArXydsmeZ*xJ!XMtwqzvpSHgG5euRovF4rJfclkE3Q3z!9thhQg0m9M8L4cRoVhnY5l15Gwk3RIc7vputdfPmQQ2LW0dsMLpSLtPG1!R8SxRHln*YNJxU5qCjIxq55YfT6jZ04zJHU2nYU6VioKHCWiJHJDcpa3!gcd!uYwQaXWeXMw1ukWLPBdlYkdbsjDC8rJOOVo07T6HUTwoq4*qt8QF5spFsTMk38OOexSQb4ZECnAd2P6l3QhruNX6piDOw4uTiX3HScxwskWlWJ4TuU8Ss7r9UOsHAo!OfpXHPvc0fID8aBt8ItRgYTw$|9e5f94bc-e8a4-4e73-b8be-63364c29d753',
  'LexieSavinon95096@outlook.in|qdugfp46949|M.C543_BAY.0.U.MsaArtifacts.-CiAmYMxnXgpEiInE1zXpduQiHUVdu3On8BsaKtW8!6RobsbFEPwgoszVGqYjIAi2A9jCIVlrEDhTFY82wl6lO4PtPSvfHHWeHkiF47Lkam*PbBr1EaKJwx1LZtOAJDeeaVZuF!wUnW3iSvGLYZDRpAuLdsYp3ixzUFH62SBR3h4w0oDqVzZ97ykxsRy*b0qQvazCKNPXYwART9L17idTTV8rAI6lZl5aqle89NPCEMsTf8QhbqxHYJHiY906W8v12P9sRZkqRjQbjMDQ8UIahHg250WBvOVTiyRSXafQWGOquqU2juwshLCF4MAhGC5rBaZHgsBgV02Y0PGQPYZdHbHbuEOMO1MvrTuSQwFzPz8plDnC5ot2dOz*v*jvLymuIynWVeCQXxoXQgaXsJZi0GI$|9e5f94bc-e8a4-4e73-b8be-63364c29d753',
  'AveryBeilharz39463@outlook.in|uluzo479885|M.C527_SN1.0.U.MsaArtifacts.-ComUGhuXYIImClefy8IduaIPNTjffX1IwW8!TrCqbVkGGiocS11eAC!miACZrjyDdViijpYkhHqNfeAlpTswOTe7QPdTebRFJip!vvTtif44gnklT8OjX4!0VN*EEoHtvy8WtWU6ms5IzDtPP87v!ESilB6NpxFXxISiPV*k*NB44n5GkvjIhnPZrwZA9F23pZanEmUQRrghoDn4u73aZWWGxL0Erw5aGtHvlpA10ogYYCM1SiIgJ775EyYaPr66ZblcwjUQUQFQ421dVQb5MVi1nHLfna40Bybpsz0XIk4*QS9PZycDCL18eIsAxYeAKKPPgINsKtgg8UXkwd7xlE!gvD3I*xFjNzcEIMOD3haDvRjW0aUXHp974nC3tEXO8cp*1f!O6sFnpsQ0wlVoXY4$|9e5f94bc-e8a4-4e73-b8be-63364c29d753',
  'NevaehCaronia10625@outlook.in|adyyr74476|M.C554_BL2.0.U.MsaArtifacts.-CvgICcAxFAeFmR*ZZ8!w4a*CkrbE!z1dcHchUFf5yyJchK8b5TFSR2UUmDKotbvsGK8KdzjP8ZyxYZuRQQVvZw13tohA9VRevfATZSMOhtTMD1YX!6z9y2ckNywQS1uei7vrM2!uZ6fqY4idsTZ2gujPaD8AqtdOt!lNB3DGJuSiCuC!siGCd4fASfj3FttB4vqCwk8wnLCpWkxsFwyjvTKruugFPe1IIDeP5DHHcSNFtsH2QyursAUzO5BbHgTSTlFdTPDbmV5A2br83g!uXsPw*L*!!6jqkQWXFnhsWzBj51EX2nPifnglMQzPkdtSvCrajx7m*Lbel1xrfkXGptn1H2DyoR0GsRR!gvXybu1YnxP32obaGHylkWOyRDGulISWwOC6VeFYgINAl*qXZrc$|9e5f94bc-e8a4-4e73-b8be-63364c29d753',
  'BosePontecorvo50630@outlook.in|mgyntx31342|M.C530_BL2.0.U.MsaArtifacts.-ComUZFhs7OgdsvcnQJIfKnFz0IfRks7SoVhVZMYOTXikmXbdbxktVYpKOW6avJl!TqUoC2yg1h8YV7zg2uVEZ1HwMq!AFWnv8UTlOftYE3lTCTlK9djlAAWaZ!vFUtCDkUcNIG9qsyNN6e9y0R5*Bl*E9tHYH4vwvQKUZem85elHlrzHCSUMl6PNTz5PCOlavq!CmDRyWFKqxUcV2v0JOo2bbAAQ9OFFaUwouqsTzhqJeZqzu3EqnWTSJLwtHqtEK7kBgyLg5MHvkS1CpG9BdnRq0ME8JaqVfcOOYxhZBNEdlx!zW3sfyZMgGypajdg5MuIqSDbYfl8xxLeJk9bBPd8wRREFqCvXaiJhIZ4SqLVg4TAVG*DuYTQpF*ddlWd994o4HbdhoCFKQzUIf*oUZfY$|9e5f94bc-e8a4-4e73-b8be-63364c29d753',
  'BurleighVandall804767@outlook.in|okfxpt31125|M.C531_BL2.0.U.MsaArtifacts.-CkDMo1ONcvzw5Iz1LhRaqjELCxPFQjBAp*nR3Gb1di7r7MfFDRE6yDb7BNRahRNvERMdtAfpEvv77dHMpLCagdXxr3WLxowogfHAHyKOMKx6JqbHN2bLsBfPn4GvjSO0*XXja86UX1Hx06eJIsMozO2fb23bFE2Hy4GeKhlUHiHVNQCVPzLPoeBBtNygzw3CoRqz3PMc2k8rPzBv*ohD!EK796WkXa0MxMxs6Dgk4e63vWGh*o8QqMN1A7rLTVJlWzTK1IElHTDHNGpwzP4I13cRc5D5o1WYMaFVhXq2B*A*0yipa2mCkLyXQBy7eow7CvBpWapuwZefQLDHigPaVMeUl8JEfSDR!WMd23Zc5bQ6o4rWezPWxgWkKoK7XM0eUIVqlS4KGDU*O1YcjzBbobBiq54WXVvpCF9ygwfnJP6u|9e5f94bc-e8a4-4e73-b8be-63364c29d753',
  'RolandHilfer962819@outlook.in|inbxa88966|M.C530_BL2.0.U.MsaArtifacts.-Cix7KZtxdgl8YaFYjbCfK*Zvrlrb2aPopFlESGOTFFWi54wy0l1CEa8DzgBi!WPYYrIpsych7H68tLpPLjFO93QZUH70bw!!pVfoEE2F83wkIdHn*6qO20d4yU4YjcnWhs!oIBVBJZ5w6GxfdZWYqPGDY8XlySQE6ybgW4JoOmCeEL8F9ahSpwJpAvglqAWv1pD5L!4FSie!em1juHg7iplbU!x4zDBhwls6eo9n8r6C2yGAWz3L*QUr0w0c6wfC6YGWKSxbOINyJbXsXgXQtaEXhecOCdRrl0cbJZFRnMDEZ27LZHBESP4he0fJ6XVCUaeLpsjk13tMYBQp*74Aodi6LcmSQnohzuntEPGfUwgmbAWDBo2cyAX1vdnhS2zRxTQNRQZiYdGuiulu1c!*DiM$|9e5f94bc-e8a4-4e73-b8be-63364c29d753',
  'GuinanMirra5222@hotmail.com|S7ysf0utFP|M.C504_BAY.0.U.MsaArtifacts.-Cj6b0bWFAO3mEF26CU3WcF9cijr7lCqjR5I9lFFcxf*YPAYpYb9STa*gm4X*8wnRQSxF4utlEMblr1ghygaBPepZrmwX8pcbJGLd41Bc92J4Y*v2VCztK9hIUT3wKTxH997FqBRIQx2iPfpPpbUxFcR64!cKBFsfPeF!CQmsawD0p0ARg3QdUPcHNjs1ZLyxSwMTyGSt2d5sSZYJwYu!2SwvWIO3A9!8xUpWb6vEC3StG*VJ9s1pBAfOJfGWW56H8VNhG3VlOtBokHMD!lNdC4X0UJbwDa7G!ZQma40uY1xM3h1aZyI5ZvRySlJMAY4Rc4qtAZ0vv*HAr5lDIs1qIl2SymGNN1r0MIi1y7Joq3NQzjg*aLfW5Tykl65lE91WXbu7GWw6QpZBe3KUiOH2*8QMNEqljt2JgaQbweCx2h0nc52unN62RXfSVkei1gbXecWqjW9Z8KcPq1RkQJ6xQXw$|9e5f94bc-e8a4-4e73-b8be-63364c29d753',
];

const seedProxy = "http://customer-resi_f5539868-cc-in-city-mumbai:bna764L_5+w5@pr.oxylabs.io:7777";
const countries = [
  "United States", "United Kingdom", "Germany", "France", "Canada",
  "Australia", "Japan", "Brazil", "Netherlands", "Spain", "Italy",
  "Mexico", "South Africa", "India",
];

const logDir = path.resolve("tests", "test_artifacts", "chain_logs");
fs.mkdirSync(logDir, { recursive: true });

const script = path.resolve("tools", "oxylabs_signup_camoufox.mjs");
const summaryFile = path.join(logDir, "chain_summary.json");

function runOxylabs(args, logFile, timeoutMs = 600000) {
  let out = "";
  try {
    out = execFileSync(process.execPath, [script, ...args], {
      encoding: "utf8",
      timeout: timeoutMs,
      maxBuffer: 20 * 1024 * 1024,
    });
  } catch (err) {
    out = `${err.stdout || ""}\n${err.stderr || ""}\nERROR: ${err.message}`;
  }
  fs.writeFileSync(logFile, out, "utf-8");
  return out;
}

function newestDashboardProxy(db, email) {
  const row = db.prepare(`
    SELECT proxy_string, proxy_country, proxy_city, created_at
    FROM proxies
    WHERE account_email = ? AND source = 'dashboard-generated'
    ORDER BY created_at DESC LIMIT 1
  `).get(String(email).toLowerCase());
  return row || null;
}

function accountState(db, email) {
  const account = db.prepare(`
    SELECT submitted, activated_at FROM accounts WHERE email = ?
  `).get(String(email).toLowerCase());
  return {
    submitted: Boolean(account?.submitted),
    activated: Boolean(account?.activated_at),
    proxyRow: newestDashboardProxy(db, email),
  };
}

async function main() {
  openDatabase();
  const db = new DatabaseSync(DB_FILE);
  let currentProxy = seedProxy;
  const results = [];

  for (let i = 0; i < accounts.length; i++) {
    const acct = accounts[i];
    const email = acct.split("|")[0];
    const country = countries[crypto.randomInt(countries.length)];
    const safe = email.replace(/[^a-z0-9]/gi, "_");
    console.log(`[chain] ${i + 1}/${accounts.length} ${email} country=${country} proxy=${currentProxy.replace(/:[^:@]+@/, ":***@")}`);

    const state = accountState(db, email);
    let out = "";
    let proxyRow = state.proxyRow;

    if (proxyRow) {
      console.log(`[chain] ${email}: already has a dashboard proxy; reusing it.`);
    } else if (state.submitted || state.activated) {
      console.log(`[chain] ${email}: already registered/activated; running --continue only.`);
      out = runOxylabs([
        "--continue", "--email", email, "--proxy", currentProxy,
        "--country", country, "--city", "Any", "--no-pause",
      ], path.join(logDir, `${i + 1}_${safe}_continue.log`));
      proxyRow = newestDashboardProxy(db, email);
    } else {
      out = runOxylabs([
        "--submit", "--account", acct, "--proxy", currentProxy,
        "--country", country, "--city", "Any", "--no-pause",
      ], path.join(logDir, `${i + 1}_${safe}_submit.log`));
      proxyRow = newestDashboardProxy(db, email);
      if (!proxyRow) {
        console.log(`[chain] ${email}: no proxy after submit; running --continue.`);
        out += "\n--- CONTINUE ---\n" + runOxylabs([
          "--continue", "--email", email, "--proxy", currentProxy,
          "--country", country, "--city", "Any", "--no-pause",
        ], path.join(logDir, `${i + 1}_${safe}_continue.log`));
        proxyRow = newestDashboardProxy(db, email);
      }
    }

    if (!proxyRow) {
      results.push({ index: i + 1, email, country, status: "FAILED_NO_PROXY", tail: out.slice(-1200) });
      console.error(`[chain] ${email}: FAILED (no proxy created). Continuing with the last working proxy.`);
      fs.writeFileSync(summaryFile, JSON.stringify(results, null, 2), "utf-8");
      continue;
    }

    const sticky = /sessid|sesstime/.test(proxyRow.proxy_string || "");
    results.push({
      index: i + 1,
      email,
      country,
      status: "OK",
      proxy_country: proxyRow.proxy_country,
      proxy_city: proxyRow.proxy_city,
      sticky,
      proxy: proxyRow.proxy_string,
    });
    currentProxy = proxyRow.proxy_string;
    console.log(`[chain] ${email}: OK sticky=${sticky} exit-country=${proxyRow.proxy_country}/${proxyRow.proxy_city}`);
    fs.writeFileSync(summaryFile, JSON.stringify(results, null, 2), "utf-8");
  }

  fs.writeFileSync(summaryFile, JSON.stringify(results, null, 2), "utf-8");
  db.close();
  console.log(`[chain] Done. Summary: ${summaryFile}`);
}

main().catch((err) => {
  console.error(err.stack || err.message);
  process.exit(1);
});
