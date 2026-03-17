/**
 * Daemon API client — talks to FastAPI backend via Vite proxy.
 *
 * All HTTP goes through /api → http://127.0.0.1:8100
 * WebSocket goes through /ws → ws://127.0.0.1:8100
 *
 * Includes JWT token in Authorization header when available.
 */

import { getStoredToken } from "./platform";

// In dev mode (Vite), /api gets proxied to the daemon API.
// In Tauri, request daemon API directly at localhost:8100.
// In production web (if ever), no prefix needed.
const API = import.meta.env.DEV
  ? "/api"
  : window.__TAURI_INTERNALS__
    ? "http://127.0.0.1:8100"
    : "";

async function request(method, path, body) {
  const token = await getStoredToken();
  const headers = { "Content-Type": "application/json" };
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }
  const opts = { method, headers };
  if (body) opts.body = JSON.stringify(body);
  const res = await fetch(`${API}${path}`, opts);
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`${res.status}: ${text.slice(0, 200)}`);
  }
  return res.json();
}

// ── Scene Chat ────────────────────────────────────────────────────────────

export async function sendMessage(scene, content, metadata = null) {
  return request("POST", `/scenes/${scene}/chat`, { content, metadata });
}

export async function getPanel(scene) {
  return request("GET", `/scenes/${scene}/panel`);
}

// ── Jobs & Tasks ──────────────────────────────────────────────────────────

export async function listJobs(status = "", limit = 20) {
  const qs = new URLSearchParams();
  if (status) qs.set("status", status);
  if (limit !== 20) qs.set("limit", String(limit));
  const q = qs.toString();
  return request("GET", `/jobs${q ? `?${q}` : ""}`);
}

export async function getTask(taskId) {
  return request("GET", `/tasks/${taskId}`);
}

export async function getTaskActivity(taskId, limit = 50) {
  return request("GET", `/tasks/${taskId}/activity?limit=${limit}`);
}

// ── System ────────────────────────────────────────────────────────────────

export async function getStatus() {
  return request("GET", "/status");
}

export async function getHealth() {
  return request("GET", "/health");
}

// ── WebSocket ─────────────────────────────────────────────────────────────

export function connectStream(scene, { onReply, onAction, onError, onClose }) {
  const isTauri = !!window.__TAURI_INTERNALS__;
  const wsBase = import.meta.env.DEV
    ? `ws://${window.location.host}/ws`
    : isTauri
      ? "ws://127.0.0.1:8100"
      : `${window.location.protocol === "https:" ? "wss:" : "ws:"}//${window.location.host}`;
  const url = `${wsBase}/scenes/${scene}/chat/stream`;
  const ws = new WebSocket(url);

  ws.onmessage = (event) => {
    try {
      const msg = JSON.parse(event.data);
      if (msg.type === "reply" && onReply) onReply(msg);
      else if (msg.type === "action" && onAction) onAction(msg);
      else if (msg.type === "error" && onError) onError(msg.error);
    } catch {
      // ignore non-JSON frames
    }
  };

  ws.onclose = () => onClose?.();
  ws.onerror = () => onError?.("WebSocket connection error");

  return {
    send: (content) => ws.send(JSON.stringify({ content })),
    close: () => ws.close(),
    get readyState() {
      return ws.readyState;
    },
  };
}
