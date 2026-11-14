// Envío a WhatsApp (canal y grupo) para La Voz Riojana vía Baileys: protocolo
// de WhatsApp por websocket, sin navegador ni pestañas. Proceso de una sola
// corrida: conecta, hace lo pedido y termina (no queda un servicio abierto).
//
//   node wa.mjs login --status <json> --qr-png <png> [--phone 549...]
//   node wa.mjs info  --out <json> [--channel-invite <código>] [--group-invite <código>]
//   node wa.mjs join  --group-invite <código> --out <json>
//   node wa.mjs create-channel --name <nombre> --description <texto> --out <json>
//   node wa.mjs send  --in <json> --out <jsonl>
//
// La sesión vive en ./auth (nunca se commitea). Los resultados de ``send`` se
// escriben de a uno (JSONL) apenas WhatsApp confirma cada mensaje: si el
// proceso se corta, lo ya enviado queda registrado y no se repite.
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import makeWASocket, { DisconnectReason, useMultiFileAuthState } from "@whiskeysockets/baileys";
import pino from "pino";
import QRCode from "qrcode";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const AUTH_DIR = process.env.LVR_WA_AUTH_DIR || path.join(HERE, "auth");
const CONNECT_TIMEOUT_MS = Number(process.env.LVR_WA_CONNECT_TIMEOUT_MS || 60000);
const SEND_TIMEOUT_MS = Number(process.env.LVR_WA_SEND_TIMEOUT_MS || 45000);
const DELAY_MIN_MS = Number(process.env.LVR_WA_DELAY_MIN_MS || 4000);
const DELAY_MAX_MS = Number(process.env.LVR_WA_DELAY_MAX_MS || 9000);

// Códigos de salida que lee meta/run_whatsapp.py.
const EXIT = { ok: 0, error: 1, needsAuth: 2, loggedOut: 3, timeout: 4, usage: 5 };

function args() {
  const out = { _: process.argv[2] };
  for (let i = 3; i < process.argv.length; i += 1) {
    const key = process.argv[i];
    if (key.startsWith("--")) {
      out[key.slice(2)] = process.argv[i + 1];
      i += 1;
    }
  }
  return out;
}

function writeJson(file, value) {
  if (!file) return;
  const tmp = `${file}.tmp`;
  fs.writeFileSync(tmp, JSON.stringify(value, null, 2), "utf-8");
  fs.renameSync(tmp, file);
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

function withTimeout(promise, ms, label) {
  return Promise.race([promise, sleep(ms).then(() => { throw new Error(`timeout:${label}`); })]);
}

async function openSocket({ onQr, phone } = {}) {
  fs.mkdirSync(AUTH_DIR, { recursive: true });
  const { state, saveCreds } = await useMultiFileAuthState(AUTH_DIR);
  const sock = makeWASocket({
    auth: state,
    logger: pino({ level: "silent" }),
    printQRInTerminal: false,
    markOnlineOnConnect: false,
    syncFullHistory: false,
    shouldSyncHistoryMessage: () => false,
    generateHighQualityLinkPreview: false,
  });
  sock.ev.on("creds.update", saveCreds);
  // Vinculada por QR o por código: la cuenta queda guardada en ``creds.me``.
  const registered = Boolean(state.creds.me?.id);
  const opened = new Promise((resolve, reject) => {
    sock.ev.on("connection.update", async (update) => {
      const { connection, lastDisconnect, qr } = update;
      if (qr && onQr) await onQr(qr);
      if (connection === "open") resolve();
      if (connection === "close") {
        const code = lastDisconnect?.error?.output?.statusCode;
        reject(Object.assign(new Error(`closed:${code}`), { code }));
      }
    });
  });
  if (phone && !registered) {
    await sleep(2000);
    const code = await sock.requestPairingCode(String(phone).replace(/\D/g, ""));
    if (onQr) await onQr(null, code);
  }
  return { sock, opened, registered, saveCreds };
}

async function close(sock) {
  await sleep(1500);
  try {
    sock.end(undefined);
  } catch {
    // cierre best-effort
  }
}

// ── login ───────────────────────────────────────────────────────────────
async function login(opts) {
  const deadline = Date.now() + Number(opts.minutes || 5) * 60000;
  const status = (value) => writeJson(opts.status, { ...value, at: new Date().toISOString() });
  status({ state: "starting" });
  while (Date.now() < deadline) {
    const { sock, opened } = await openSocket({
      phone: opts.phone,
      onQr: async (qr, pairingCode) => {
        if (qr && opts["qr-png"]) await QRCode.toFile(opts["qr-png"], qr, { width: 640, margin: 2 });
        status(pairingCode ? { state: "pairing_code", pairing_code: pairingCode } : { state: "qr", qr_png: opts["qr-png"] });
      },
    });
    try {
      await withTimeout(opened, deadline - Date.now(), "login");
      // Deja que lleguen y se guarden las credenciales finales.
      await sleep(5000);
      const me = sock.user?.id || "";
      status({ state: "ready", account: me.split(":")[0].split("@")[0] });
      await close(sock);
      return EXIT.ok;
    } catch (error) {
      await close(sock);
      if (error.code === DisconnectReason.loggedOut) {
        status({ state: "logged_out" });
        return EXIT.loggedOut;
      }
      // 515 (restartRequired) es normal justo después de escanear: se reconecta.
      if (String(error.message).startsWith("timeout")) break;
    }
  }
  status({ state: "timeout" });
  return EXIT.timeout;
}

async function connected() {
  const bundle = await openSocket();
  if (!bundle.registered) {
    await close(bundle.sock);
    return { exit: EXIT.needsAuth };
  }
  try {
    await withTimeout(bundle.opened, CONNECT_TIMEOUT_MS, "connect");
  } catch (error) {
    await close(bundle.sock);
    return { exit: error.code === DisconnectReason.loggedOut ? EXIT.loggedOut : EXIT.timeout };
  }
  return { sock: bundle.sock };
}

// ── info / create-channel ───────────────────────────────────────────────
async function info(opts) {
  const { sock, exit } = await connected();
  if (!sock) return exit;
  const groups = Object.values(await sock.groupFetchAllParticipating()).map((g) => ({
    jid: g.id,
    subject: g.subject,
    participants: (g.participants || []).length,
    announce: Boolean(g.announce),
    is_community: Boolean(g.isCommunity),
  }));
  let channel = null;
  if (opts["channel-invite"]) {
    const meta = await sock.newsletterMetadata("invite", opts["channel-invite"]);
    channel = meta ? { jid: meta.id, name: meta.name, invite: meta.invite, subscribers: meta.subscribers } : null;
  }
  let group = null;
  if (opts["group-invite"]) {
    const meta = await sock.groupGetInviteInfo(opts["group-invite"]);
    group = meta ? { jid: meta.id, subject: meta.subject, size: meta.size, announce: Boolean(meta.announce) } : null;
  }
  writeJson(opts.out, { account: (sock.user?.id || "").split(":")[0], groups, channel, group });
  await close(sock);
  return EXIT.ok;
}

async function join(opts) {
  const { sock, exit } = await connected();
  if (!sock) return exit;
  const jid = await sock.groupAcceptInvite(opts["group-invite"]);
  const meta = await sock.groupMetadata(jid);
  const me = (sock.user?.id || "").split(":")[0];
  const self = (meta.participants || []).find((p) => String(p.id).startsWith(me));
  writeJson(opts.out, { jid, subject: meta.subject, announce: Boolean(meta.announce), admin: self?.admin || null });
  await close(sock);
  return EXIT.ok;
}

async function createChannel(opts) {
  const { sock, exit } = await connected();
  if (!sock) return exit;
  const meta = await sock.newsletterCreate(opts.name, opts.description || "");
  writeJson(opts.out, { jid: meta.id, name: meta.name, invite: meta.invite });
  await close(sock);
  return EXIT.ok;
}

// ── send ────────────────────────────────────────────────────────────────
function content(message) {
  if (!message.preview) return { text: message.text };
  const p = message.preview;
  const linkPreview = {
    "canonical-url": p.url,
    "matched-text": p.url,
    title: p.title || "",
    description: p.description || "",
  };
  if (p.thumb_b64) linkPreview.jpegThumbnail = Buffer.from(p.thumb_b64, "base64");
  return { text: message.text, linkPreview };
}

async function send(opts) {
  const messages = JSON.parse(fs.readFileSync(opts.in, "utf-8"));
  const { sock, exit } = await connected();
  if (!sock) return exit;
  for (let i = 0; i < messages.length; i += 1) {
    const message = messages[i];
    // Antes de enviar: si el proceso muere acá, el resultado es incierto.
    fs.appendFileSync(opts.out, `${JSON.stringify({ key: message.key, phase: "sending" })}\n`, "utf-8");
    try {
      const sent = await withTimeout(sock.sendMessage(message.jid, content(message)), SEND_TIMEOUT_MS, "send");
      fs.appendFileSync(opts.out, `${JSON.stringify({ key: message.key, phase: "sent", message_id: sent?.key?.id || "" })}\n`, "utf-8");
    } catch (error) {
      const timedOut = String(error.message).startsWith("timeout");
      fs.appendFileSync(opts.out, `${JSON.stringify({
        key: message.key, phase: timedOut ? "unknown" : "failed", error: String(error.message).slice(0, 200),
      })}\n`, "utf-8");
      if (timedOut) break; // la conexión quedó en duda: no se sigue a ciegas
    }
    if (i < messages.length - 1) await sleep(DELAY_MIN_MS + Math.random() * (DELAY_MAX_MS - DELAY_MIN_MS));
  }
  await close(sock);
  return EXIT.ok;
}

const opts = args();
const commands = { login, info, join, "create-channel": createChannel, send };
const run = commands[opts._];
if (!run) {
  console.error("uso: node wa.mjs login|info|create-channel|send ...");
  process.exit(EXIT.usage);
}
run(opts).then(
  (code) => process.exit(code),
  (error) => {
    console.error(String(error?.message || error).slice(0, 300));
    process.exit(EXIT.error);
  },
);
