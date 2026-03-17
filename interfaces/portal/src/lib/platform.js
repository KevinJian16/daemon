/**
 * Platform detection and bridge to Electron IPC.
 *
 * In Electron: window.daemon is available via preload.cjs.
 * In browser: falls back to standard web APIs.
 */

export const isElectron = typeof window !== "undefined" && !!window.daemon?.isElectron;

export function oauthLogin(provider) {
  if (isElectron) {
    return window.daemon.oauthLogin(provider);
  }
  // Browser: redirect to OAuth endpoint
  window.location.href = `/api/auth/${provider}`;
}

export async function getStoredToken() {
  if (isElectron) {
    return window.daemon.getToken();
  }
  return localStorage.getItem("daemon_token");
}

export async function setStoredToken(token) {
  if (isElectron) {
    return window.daemon.setToken(token);
  }
  localStorage.setItem("daemon_token", token);
}

export function openExternal(url) {
  if (isElectron) {
    return window.daemon.openExternal(url);
  }
  window.open(url, "_blank");
}

export function openBrowserView(url) {
  if (isElectron) {
    return window.daemon.openBrowserView(url);
  }
  window.open(url, "_blank");
}

export function launchVSCode(filePath) {
  if (isElectron) {
    return window.daemon.launchVSCode(filePath);
  }
  // In browser, VS Code URL scheme
  window.open(`vscode://file/${filePath}`);
}

export function onStatusUpdate(callback) {
  if (isElectron && window.daemon.onStatusUpdate) {
    window.daemon.onStatusUpdate(callback);
  }
}
