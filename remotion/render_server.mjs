#!/usr/bin/env node
// Servidor de render persistente — resuelve docs/KNOWN_ISSUES.md #69
// (cada `npx remotion still` re-bundlea el proyecto desde cero, ~19s por
// render). Este proceso bundlea UNA vez al arrancar, abre un browser
// Chromium UNA vez, y sirve renders sucesivos vía HTTP local reusando
// ambos — sólo loopback (127.0.0.1), sin auth (mismo criterio que la UI
// manual del proyecto: confiado porque es local, ver docs/DECISIONS.md).
//
// utils/remotion_renderer.py lo levanta bajo demanda (spawn detached) si no
// está corriendo, y cae al subprocess "npx remotion still" viejo si este
// servidor no puede levantar por cualquier motivo — nunca es un punto único
// de falla para el pipeline real.
//
// Protocolo:
//   GET  /health           -> 200 {ok, pid, bundleLocation}
//   POST /render           -> body {compositionId, inputProps, assetPaths}
//                              assetPaths: {propName: rutaAbsolutaLocal}
//                              devuelve el PNG crudo (Content-Type image/png,
//                              header X-Render-Duration-Ms).
//
// Apagado por inactividad (RENDER_SERVER_IDLE_MS, default 20min) para no
// dejar un proceso Node vivo indefinidamente en un host 24/7.

import { bundle } from "@remotion/bundler";
import { enableTailwind } from "@remotion/tailwind-v4";
import { openBrowser, renderStill, selectComposition } from "@remotion/renderer";
import { randomUUID } from "crypto";
import fs from "fs";
import http from "http";
import path from "path";
import { fileURLToPath } from "url";

const REMOTION_DIR = path.dirname(fileURLToPath(import.meta.url));
const BUNDLE_OUT_DIR = path.join(REMOTION_DIR, ".render-cache");
const SERVER_INFO_PATH = path.join(REMOTION_DIR, ".render-server.json");
const IDLE_MS = Number(process.env.RENDER_SERVER_IDLE_MS || 20 * 60 * 1000);
const REQUESTED_PORT = Number(process.argv.find((a) => a.startsWith("--port="))?.split("=")[1] || 0);

function log(...args) {
  console.log(`[render_server]`, new Date().toISOString(), ...args);
}

function writeServerInfo(port) {
  fs.writeFileSync(
    SERVER_INFO_PATH,
    JSON.stringify({ pid: process.pid, port, startedAt: new Date().toISOString() }, null, 2),
  );
}

function removeServerInfo() {
  try {
    fs.unlinkSync(SERVER_INFO_PATH);
  } catch {
    // ya no existía — no es un error.
  }
}

async function readBody(req) {
  const chunks = [];
  for await (const chunk of req) chunks.push(chunk);
  return Buffer.concat(chunks);
}

// Cola secuencial simple: el pipeline real pide un render a la vez (una
// card automática o un slide premium por llamada), así que no hace falta
// paralelizar contra el mismo browser — prioriza simplicidad/corrección.
let queue = Promise.resolve();
function enqueue(task) {
  const result = queue.then(task, task);
  queue = result.then(
    () => undefined,
    () => undefined,
  );
  return result;
}

async function main() {
  log("bundleando el proyecto una sola vez...");
  const bundleStarted = Date.now();
  const bundleLocation = await bundle({
    entryPoint: path.join(REMOTION_DIR, "src", "index.ts"),
    webpackOverride: enableTailwind,
    outDir: BUNDLE_OUT_DIR,
  });
  log(`bundle listo en ${Date.now() - bundleStarted}ms ->`, bundleLocation);

  const browser = await openBrowser("chrome", { chromiumOptions: { gl: "angle" } });
  log("browser Chromium abierto y listo para reusar entre renders");

  const publicTmpDir = path.join(bundleLocation, "public", "tmp");
  fs.mkdirSync(publicTmpDir, { recursive: true });

  let lastActivity = Date.now();
  let closing = false;

  const server = http.createServer((req, res) => {
    lastActivity = Date.now();

    if (req.method === "GET" && req.url === "/health") {
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ ok: true, pid: process.pid, bundleLocation }));
      return;
    }

    if (req.method === "POST" && req.url === "/render") {
      enqueue(async () => {
        const started = Date.now();
        const copiedAssets = [];
        try {
          const raw = await readBody(req);
          const { compositionId, inputProps, assetPaths } = JSON.parse(raw.toString("utf-8"));
          if (!compositionId) throw new Error("falta compositionId");

          const workingProps = { ...(inputProps || {}) };
          const renderId = randomUUID();
          for (const [propName, localPath] of Object.entries(assetPaths || {})) {
            if (!localPath) continue;
            const ext = path.extname(localPath) || ".jpg";
            const relPath = `tmp/${renderId}_${propName}${ext}`;
            const dest = path.join(bundleLocation, "public", relPath);
            fs.copyFileSync(localPath, dest);
            copiedAssets.push(dest);
            workingProps[propName] = relPath;
          }

          const composition = await selectComposition({
            serveUrl: bundleLocation,
            id: compositionId,
            inputProps: workingProps,
            puppeteerInstance: browser,
          });

          const { buffer } = await renderStill({
            composition,
            serveUrl: bundleLocation,
            output: null,
            inputProps: workingProps,
            imageFormat: "png",
            puppeteerInstance: browser,
            chromiumOptions: { gl: "angle" },
          });

          const durationMs = Date.now() - started;
          res.writeHead(200, {
            "Content-Type": "image/png",
            "Content-Length": buffer.length,
            "X-Render-Duration-Ms": String(durationMs),
          });
          res.end(buffer);
          log(`render OK ${compositionId} en ${durationMs}ms`);
        } catch (err) {
          const message = err instanceof Error ? err.message : String(err);
          log("render FALLÓ:", message);
          res.writeHead(500, { "Content-Type": "application/json" });
          res.end(JSON.stringify({ error: message }));
        } finally {
          for (const p of copiedAssets) {
            try {
              fs.unlinkSync(p);
            } catch {
              // best-effort
            }
          }
        }
      });
      return;
    }

    res.writeHead(404, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ error: "not_found" }));
  });

  server.listen(REQUESTED_PORT, "127.0.0.1", () => {
    const { port } = server.address();
    writeServerInfo(port);
    log(`escuchando en 127.0.0.1:${port} (idle timeout ${IDLE_MS}ms)`);
  });

  const idleCheck = setInterval(() => {
    if (closing) return;
    if (Date.now() - lastActivity > IDLE_MS) {
      closing = true;
      log("inactivo, apagando...");
      clearInterval(idleCheck);
      removeServerInfo();
      server.close(() => {
        browser.close().finally(() => process.exit(0));
      });
    }
  }, 30_000);

  const shutdown = () => {
    if (closing) return;
    closing = true;
    log("señal de apagado recibida...");
    clearInterval(idleCheck);
    removeServerInfo();
    server.close(() => {
      browser.close().finally(() => process.exit(0));
    });
  };
  process.on("SIGTERM", shutdown);
  process.on("SIGINT", shutdown);
}

main().catch((err) => {
  log("no se pudo iniciar:", err);
  removeServerInfo();
  process.exit(1);
});
