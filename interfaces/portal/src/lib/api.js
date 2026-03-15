/**
 * Daemon API client — talks to FastAPI backend via Vite proxy.
 *
 * All HTTP goes through /api → http://127.0.0.1:8100
 * WebSocket goes through /ws → ws://127.0.0.1:8100
 */

// In dev mode (Vite), /api gets proxied to the daemon API.
// In production (served by FastAPI at /portal/), no prefix needed.
const API = import.meta.env.DEV ? "/api" : "";

async function request(method, path, body) {
  const opts = {
    method,
    headers: { "Content-Type": "application/json" },
  };
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
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  const wsPrefix = import.meta.env.DEV ? "/ws" : "";
  const url = `${proto}//${window.location.host}${wsPrefix}/scenes/${scene}/chat/stream`;
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
