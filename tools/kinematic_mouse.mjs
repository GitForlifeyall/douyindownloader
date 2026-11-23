/**
 * kinematic_mouse.mjs
 * 
 * High-fidelity human kinematic pointer simulation for Playwright / Camoufox.
 * Combines:
 *   1. Neural LSTM Trajectory Generation via ONNX model (jason-snell/humanized-cursor-trajectory-gen)
 *      trained on real human mouse recordings.
 *   2. Catmull-Rom spline densification & smoothing.
 *   3. Algorithmic Cubic Bézier & Fitts's Law fallback engine.
 *   4. Biological micro-tremors & physiological sub-pixel jitter.
 *   5. Non-central 2D Gaussian click targeting within element bounding boxes.
 *   6. Realistic physical mouse switch depression hold times (55ms - 130ms) & pre-click dwells.
 *   7. Inertial wheel scrolling with multi-frame velocity decay.
 */

import fs from "node:fs";
import path from "node:path";
import crypto from "node:crypto";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const MODEL_PATH = path.join(__dirname, "models", "cursor_trajectory.onnx");

// Check if fast mode was requested via CLI flags
export const IS_FAST_MODE = process.argv.includes("--fast") ||
  process.argv.includes("--no-trajectory") ||
  process.argv.includes("--skip-delays") ||
  process.argv.includes("--no-humanize");

let ort = null;
let onnxSession = null;
let onnxLoadAttempted = false;

async function getOnnxSession() {
  if (onnxSession) return onnxSession;
  if (onnxLoadAttempted) return null;
  onnxLoadAttempted = true;

  try {
    if (!fs.existsSync(MODEL_PATH)) {
      console.warn(`[KinematicMouse] ONNX model not found at ${MODEL_PATH}. Using algorithmic Bézier engine.`);
      return null;
    }
    ort = (await import("onnxruntime-node")).default;
    onnxSession = await ort.InferenceSession.create(MODEL_PATH);
    console.log("[KinematicMouse] Neural Cursor Trajectory Generator (ONNX) initialized.");
    return onnxSession;
  } catch (err) {
    console.warn("[KinematicMouse] ONNX runtime unavailable, falling back to Bézier:", err.message);
    return null;
  }
}

const pagePositions = new WeakMap();

function randomFloat(min, max) {
  return min + Math.random() * (max - min);
}

function gaussianRandom(mean = 0, stdev = 1) {
  let u = 1 - Math.random();
  let v = Math.random();
  let z = Math.sqrt(-2.0 * Math.log(u)) * Math.cos(2.0 * Math.PI * v);
  return z * stdev + mean;
}

function clamp(val, min, max) {
  return Math.max(min, Math.min(max, val));
}

function catmullRom(p0, p1, p2, p3, t) {
  const t2 = t * t;
  const t3 = t2 * t;

  const x = 0.5 * (
    (2 * p1.x) +
    (-p0.x + p2.x) * t +
    (2 * p0.x - 5 * p1.x + 4 * p2.x - p3.x) * t2 +
    (-p0.x + 3 * p1.x - 3 * p2.x + p3.x) * t3
  );

  const y = 0.5 * (
    (2 * p1.y) +
    (-p0.y + p2.y) * t +
    (2 * p0.y - 5 * p1.y + 4 * p2.y - p3.y) * t2 +
    (-p0.y + 3 * p1.y - 3 * p2.y + p3.y) * t3
  );

  return { x, y };
}

function interpolateCatmullRom(controlPoints, pointsPerSegment = 2) {
  if (!controlPoints || controlPoints.length < 2) return controlPoints;
  const result = [controlPoints[0]];

  for (let i = 0; i < controlPoints.length - 1; i++) {
    const p0 = controlPoints[Math.max(0, i - 1)];
    const p1 = controlPoints[i];
    const p2 = controlPoints[i + 1];
    const p3 = controlPoints[Math.min(controlPoints.length - 1, i + 2)];

    for (let j = 1; j <= pointsPerSegment; j++) {
      const t = j / pointsPerSegment;
      const pt = catmullRom(p0, p1, p2, p3, t);
      result.push({
        x: Number(pt.x.toFixed(2)),
        y: Number(pt.y.toFixed(2)),
      });
    }
  }
  return result;
}

// Asymmetric Fitts's Law pacing curve: fast acceleration, prolonged deceleration landing
function fittsEasing(t) {
  if (t <= 0) return 0;
  if (t >= 1) return 1;
  return Math.pow(t, 1.8) / (Math.pow(t, 1.8) + Math.pow(1 - t, 1.8));
}

export function getMousePosition(page) {
  let pos = pagePositions.get(page);
  if (!pos) {
    const vp = page.viewportSize() || { width: 1280, height: 800 };
    pos = {
      x: Math.round(randomFloat(vp.width * 0.25, vp.width * 0.6)),
      y: Math.round(randomFloat(40, 75)),
    };
    pagePositions.set(page, pos);
  }
  return pos;
}

export function setMousePosition(page, x, y) {
  pagePositions.set(page, { x, y });
}

/**
 * Generate human trajectory using trained LSTM ONNX model + Catmull-Rom spline.
 */
async function generateNeuralTrajectory(p0, p3, options = {}) {
  const sess = await getOnnxSession();
  if (!sess) return null;

  try {
    const randomness = options.randomness ?? 0.9;
    const density = options.density ?? 1;

    let largest = Math.max(p0.x, p0.y, p3.x, p3.y);
    largest += largest / 2.0;
    if (largest === 0) largest = 1000;

    const inData = new Float32Array([
      (p0.x + (Math.random() * 2 * randomness - randomness)) / largest,
      (p0.y + (Math.random() * 2 * randomness - randomness)) / largest,
      (p3.x + (Math.random() * 2 * randomness - randomness)) / largest,
      (p3.y + (Math.random() * 2 * randomness - randomness)) / largest,
    ]);

    const tensor = new ort.Tensor("float32", inData, [1, 2, 2]);
    const outputs = await sess.run({ [sess.inputNames[0]]: tensor });
    const rawOutput = outputs[sess.outputNames[0]].data;

    const controlPoints = [{ x: p0.x, y: p0.y }];
    const maxDistance = 6;

    for (let i = 0; i < rawOutput.length / 2; i++) {
      const px = rawOutput[i * 2] * largest;
      const py = rawOutput[i * 2 + 1] * largest;

      if (Math.abs(px - p3.x) <= maxDistance && Math.abs(py - p3.y) <= maxDistance) {
        break;
      }
      controlPoints.push({ x: px, y: py });
    }
    controlPoints.push({ x: p3.x, y: p3.y });

    const smoothed = interpolateCatmullRom(controlPoints, density);
    const timedPoints = [];

    for (let i = 0; i < smoothed.length; i++) {
      const pt = smoothed[i];
      const prev = i > 0 ? smoothed[i - 1] : pt;
      const stepDist = Math.hypot(pt.x - prev.x, pt.y - prev.y);

      // Natural brisk human pacing (2-6ms per point with micro-jitter)
      const delay = Math.max(2, Math.min(8, Math.round(randomFloat(2, 5) + (stepDist < 2.5 ? 2 : 0))));

      let mx = pt.x;
      let my = pt.y;
      if (i > 0 && i < smoothed.length - 1) {
        mx += gaussianRandom(0, 0.25);
        my += gaussianRandom(0, 0.25);
      }

      timedPoints.push({
        x: Number(mx.toFixed(2)),
        y: Number(my.toFixed(2)),
        delay,
      });
    }

    return timedPoints;
  } catch (err) {
    console.warn("[KinematicMouse] Neural trajectory error, falling back:", err.message);
    return null;
  }
}

/**
 * Fallback algorithmic Bézier trajectory generator (agile human pacing).
 */
function generateBezierTrajectory(p0, p3, options = {}) {
  const dx = p3.x - p0.x;
  const dy = p3.y - p0.y;
  const dist = Math.hypot(dx, dy);

  if (dist < 3) {
    return [{ x: p3.x, y: p3.y, delay: Math.round(randomFloat(8, 16)) }];
  }

  const baseSteps = Math.max(8, Math.min(32, Math.round(dist / randomFloat(16, 26))));
  const nx = -dy / dist;
  const ny = dx / dist;
  const side = Math.random() < 0.5 ? 1 : -1;
  const curveMagnitude = dist * randomFloat(0.05, 0.18) * side;

  const p1 = {
    x: p0.x + dx * randomFloat(0.2, 0.38) + nx * curveMagnitude * randomFloat(0.7, 1.1),
    y: p0.y + dy * randomFloat(0.2, 0.38) + ny * curveMagnitude * randomFloat(0.7, 1.1),
  };
  const p2 = {
    x: p0.x + dx * randomFloat(0.62, 0.82) + nx * curveMagnitude * randomFloat(0.4, 0.85),
    y: p0.y + dy * randomFloat(0.62, 0.82) + ny * curveMagnitude * randomFloat(0.4, 0.85),
  };

  const points = [];
  for (let i = 1; i <= baseSteps; i++) {
    const rawT = i / baseSteps;
    const t = fittsEasing(rawT);

    const oneMinusT = 1 - t;
    let bx =
      Math.pow(oneMinusT, 3) * p0.x +
      3 * Math.pow(oneMinusT, 2) * t * p1.x +
      3 * oneMinusT * Math.pow(t, 2) * p2.x +
      Math.pow(t, 3) * p3.x;

    let by =
      Math.pow(oneMinusT, 3) * p0.y +
      3 * Math.pow(oneMinusT, 2) * t * p1.y +
      3 * oneMinusT * Math.pow(t, 2) * p2.y +
      Math.pow(t, 3) * p3.y;

    if (i < baseSteps) {
      bx += gaussianRandom(0, 0.3);
      by += gaussianRandom(0, 0.3);
    } else {
      bx = p3.x;
      by = p3.y;
    }

    const velocityFactor = 1 - Math.abs(t - 0.42);
    const stepDelay = Math.round(randomFloat(2, 5) + (1 - velocityFactor) * 3);

    points.push({ x: Number(bx.toFixed(2)), y: Number(by.toFixed(2)), delay: stepDelay });
  }

  return points;
}

export async function generateKinematicPath(p0, p3, options = {}) {
  const dist = Math.hypot(p3.x - p0.x, p3.y - p0.y);
  // For medium to long distances, use neural ONNX trajectory
  if (dist >= 20) {
    const neuralPath = await generateNeuralTrajectory(p0, p3, options);
    if (neuralPath && neuralPath.length >= 2) {
      return neuralPath;
    }
  }
  return generateBezierTrajectory(p0, p3, options);
}

/**
 * Glide mouse cursor smoothly from current position to (targetX, targetY).
 */
export async function humanGlide(page, targetX, targetY, options = {}) {
  try {
    const currentPos = getMousePosition(page);
    const vp = page.viewportSize() || { width: 1280, height: 800 };
    const safeTarget = {
      x: clamp(Math.round(targetX), 2, vp.width - 2),
      y: clamp(Math.round(targetY), 2, vp.height - 2),
    };

    if (IS_FAST_MODE || options.fast) {
      setMousePosition(page, safeTarget.x, safeTarget.y);
      await page.mouse.move(safeTarget.x, safeTarget.y).catch(() => {});
      return;
    }

    const path = await generateKinematicPath(currentPos, safeTarget, options);
    for (const pt of path) {
      await page.mouse.move(pt.x, pt.y);
      if (pt.delay > 0) {
        await new Promise((r) => setTimeout(r, pt.delay));
      }
    }
    setMousePosition(page, safeTarget.x, safeTarget.y);
  } catch (err) {
    try {
      await page.mouse.move(targetX, targetY);
      setMousePosition(page, targetX, targetY);
    } catch (_) {}
  }
}

/**
 * Click an element or locator with full human kinematic fidelity.
 */
export async function humanClick(page, target, options = {}) {
  if (IS_FAST_MODE || options.fast) {
    const loc = typeof target === "string" ? page.locator(target).first() : target;
    await loc.scrollIntoViewIfNeeded().catch(() => {});
    await loc.click({ force: true }).catch(async () => {
      await loc.dispatchEvent("click").catch(() => {});
    });
    return;
  }
  try {
    const locator = typeof target === "string" ? page.locator(target).first() : target;
    await locator.waitFor({ state: "visible", timeout: options.timeout || 10000 });
    await locator.scrollIntoViewIfNeeded().catch(() => {});

    const box = await locator.boundingBox();
    if (!box) {
      await locator.click();
      return;
    }

    // 2D Gaussian targeting centered inside the element
    const gx = clamp(gaussianRandom(0.5, 0.12), 0.2, 0.8);
    const gy = clamp(gaussianRandom(0.5, 0.12), 0.2, 0.8);
    const targetX = box.x + box.width * gx;
    const targetY = box.y + box.height * gy;

    // 1. Natural neural glide to element
    await humanGlide(page, targetX, targetY, options);

    // 2. Pre-click dwell (crisp biological reflex: 25-65ms)
    const preClickDwell = Math.round(randomFloat(25, 65));
    await new Promise((r) => setTimeout(r, preClickDwell));

    // 3. Mouse down (switch depress)
    await page.mouse.down();

    // 4. Click hold duration (physical microswitch: 35-75ms)
    const holdDuration = Math.round(randomFloat(35, 75));
    await new Promise((r) => setTimeout(r, holdDuration));

    // 5. Mouse up (switch release)
    await page.mouse.up();

    // 6. Post-click reaction delay (30-80ms)
    const postClickDelay = Math.round(randomFloat(30, 80));
    await new Promise((r) => setTimeout(r, postClickDelay));
  } catch (err) {
    try {
      const loc = typeof target === "string" ? page.locator(target).first() : target;
      await loc.click();
    } catch (_) {}
  }
}

/**
 * Hover over an element with smooth human kinematic glide.
 */
export async function humanHover(page, target, options = {}) {
  if (IS_FAST_MODE || options.fast) {
    const loc = typeof target === "string" ? page.locator(target).first() : target;
    await loc.hover().catch(() => {});
    return;
  }
  try {
    const locator = typeof target === "string" ? page.locator(target).first() : target;
    await locator.waitFor({ state: "visible", timeout: options.timeout || 8000 });
    await locator.scrollIntoViewIfNeeded().catch(() => {});

    const box = await locator.boundingBox();
    if (!box) {
      await locator.hover().catch(() => {});
      return;
    }

    const gx = clamp(gaussianRandom(0.5, 0.14), 0.25, 0.75);
    const gy = clamp(gaussianRandom(0.5, 0.14), 0.25, 0.75);
    const targetX = box.x + box.width * gx;
    const targetY = box.y + box.height * gy;

    await humanGlide(page, targetX, targetY, options);
    await new Promise((r) => setTimeout(r, Math.round(randomFloat(25, 75))));
  } catch (e) {
    try {
      const loc = typeof target === "string" ? page.locator(target).first() : target;
      await loc.hover().catch(() => {});
    } catch (_) {}
  }
}

/**
 * Natural cursor wander / drift across the screen to simulate reading eyes.
 */
export async function humanWander(page, options = {}) {
  if (IS_FAST_MODE || options.fast) return;
  try {
    const vp = page.viewportSize() || { width: 1280, height: 800 };
    const cur = getMousePosition(page);

    const targetX = cur.x + randomFloat(-vp.width * 0.25, vp.width * 0.25);
    const targetY = cur.y + randomFloat(-vp.height * 0.2, vp.height * 0.2);

    const safeX = clamp(targetX, vp.width * 0.1, vp.width * 0.85);
    const safeY = clamp(targetY, vp.height * 0.12, vp.height * 0.85);

    await humanGlide(page, safeX, safeY, options);
  } catch (e) {}
}

/**
 * Human wheel scrolling with inertia decay over multiple frames.
 */
export async function humanScroll(page, deltaY, options = {}) {
  try {
    const chunks = Math.max(4, Math.min(12, Math.round(Math.abs(deltaY) / 60)));
    let remaining = deltaY;

    for (let i = 1; i <= chunks; i++) {
      const fraction = (chunks - i + 1) / ((chunks * (chunks + 1)) / 2);
      const stepDelta = Math.round(deltaY * fraction + gaussianRandom(0, 3));
      remaining -= stepDelta;

      await page.mouse.wheel(0, stepDelta);
      await new Promise((r) => setTimeout(r, Math.round(randomFloat(14, 38))));
    }

    if (Math.abs(remaining) > 0) {
      await page.mouse.wheel(0, remaining);
    }
  } catch (e) {}
}

export default {
  getMousePosition,
  setMousePosition,
  generateKinematicPath,
  humanGlide,
  humanClick,
  humanHover,
  humanWander,
  humanScroll,
};
