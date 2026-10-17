#!/usr/bin/env node
// Render de QA para la galería V1/V2 (Visual System V2). NO publica nada y
// no usa el servidor de render productivo: bundlea una vez en su propio
// directorio, renderiza cada trabajo con los mismos ajustes que producción
// (h264 CRF 18 para Reels, PNG + escala para stills) y mide el tiempo.
//
// Uso: node scripts/render_compare.mjs <jobs.json> <results.json>
//   jobs: [{id, kind: "still"|"video", compositionId, props, assetPaths, out, scale?}]
import { bundle } from "@remotion/bundler";
import { enableTailwind } from "@remotion/tailwind-v4";
import { openBrowser, renderMedia, renderStill, selectComposition } from "@remotion/renderer";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const REMOTION_DIR = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const [jobsPath, resultsPath] = process.argv.slice(2);
if (!jobsPath || !resultsPath) {
  console.error("uso: render_compare.mjs <jobs.json> <results.json>");
  process.exit(2);
}

const jobs = JSON.parse(fs.readFileSync(jobsPath, "utf-8"));
const only = process.env.ONLY ? new RegExp(process.env.ONLY) : null;

const log = (...a) => console.log("[render_compare]", new Date().toISOString(), ...a);

const bundleStarted = Date.now();
const serveUrl = await bundle({
  entryPoint: path.join(REMOTION_DIR, "src", "index.ts"),
  webpackOverride: enableTailwind,
  outDir: path.join(REMOTION_DIR, ".render-cache-gallery"),
});
log(`bundle listo en ${Date.now() - bundleStarted}ms`);
const browser = await openBrowser("chrome", { chromiumOptions: { gl: "angle" } });
const publicTmp = path.join(serveUrl, "public", "tmp");
fs.mkdirSync(publicTmp, { recursive: true });

const results = fs.existsSync(resultsPath) ? JSON.parse(fs.readFileSync(resultsPath, "utf-8")) : {};
for (const job of jobs) {
  if (only && !only.test(job.id)) continue;
  const props = { ...job.props };
  const copied = [];
  for (const [prop, local] of Object.entries(job.assetPaths || {})) {
    if (!local) continue;
    const rel = `tmp/${job.id}_${prop}${path.extname(local)}`;
    const dest = path.join(serveUrl, "public", rel);
    fs.copyFileSync(local, dest);
    copied.push(dest);
    props[prop] = rel;
  }
  fs.mkdirSync(path.dirname(job.out), { recursive: true });
  const started = Date.now();
  try {
    const composition = await selectComposition({ serveUrl, id: job.compositionId, inputProps: props, puppeteerInstance: browser });
    if (job.kind === "still") {
      await renderStill({
        composition,
        serveUrl,
        output: job.out,
        inputProps: props,
        imageFormat: "png",
        scale: job.scale || 1,
        puppeteerInstance: browser,
        chromiumOptions: { gl: "angle" },
      });
    } else {
      await renderMedia({
        composition,
        serveUrl,
        codec: "h264",
        crf: 18,
        outputLocation: job.out,
        inputProps: props,
        imageFormat: "jpeg",
        timeoutInMilliseconds: 30000,
        puppeteerInstance: browser,
        chromiumOptions: { gl: "angle" },
      });
    }
    const ms = Date.now() - started;
    results[job.id] = { ok: true, ms, frames: composition.durationInFrames, compositionId: job.compositionId };
    log(`OK ${job.id} (${job.compositionId}) ${ms}ms`);
  } catch (err) {
    results[job.id] = { ok: false, ms: Date.now() - started, error: String(err && err.message ? err.message : err).slice(0, 800) };
    log(`FALLÓ ${job.id}:`, results[job.id].error);
  } finally {
    for (const p of copied) {
      try {
        fs.unlinkSync(p);
      } catch {
        // best-effort
      }
    }
    fs.writeFileSync(resultsPath, JSON.stringify(results, null, 2));
  }
}
await browser.close({ silent: true });
log("listo");
