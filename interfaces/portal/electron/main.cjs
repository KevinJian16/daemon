/**
 * Daemon Desktop Client — Electron main process.
 *
 * Features:
 *   - Menu bar tray icon (green/yellow/red status)
 *   - Main window with React frontend (4 scene chat views)
 *   - OAuth login flow (Google / GitHub → JWT)
 *   - System status polling → tray icon color
 *
 * Reference: SYSTEM_DESIGN.md §4.1-4.2, §6.10.2, CLIENT_SPEC.md
 */

const { app, BrowserWindow, Tray, Menu, nativeImage, shell, ipcMain } = require("electron");
const path = require("path");
const fs = require("fs");

// Single instance lock
const gotLock = app.requestSingleInstanceLock();
if (!gotLock) {
  app.quit();
}

const isDev = !app.isPackaged;
const DAEMON_API = process.env.DAEMON_API_URL || "http://127.0.0.1:8100";
const DEV_SERVER = "http://localhost:5173";

let mainWindow = null;
let tray = null;
let currentStatus = "unknown"; // green | yellow | red | unknown

// ── Tray Icon ──────────────────────────────────────────────────────────────

function createTrayIcon(color) {
  // Create a simple colored circle icon (16x16)
  const canvas = nativeImage.createEmpty();
  // Use pre-built icons or generate dynamically
  const iconDir = path.join(__dirname, "icons");
  const iconFile = path.join(iconDir, `tray-${color}.png`);
  if (fs.existsSync(iconFile)) {
    return nativeImage.createFromPath(iconFile).resize({ width: 16, height: 16 });
  }
  // Fallback: use template image
  const fallback = path.join(iconDir, "tray-template.png");
  if (fs.existsSync(fallback)) {
    return nativeImage.createFromPath(fallback).resize({ width: 16, height: 16 });
  }
  return canvas;
}

function updateTray(status) {
  if (!tray) return;
  currentStatus = status;
  const icon = createTrayIcon(status);
  if (!icon.isEmpty()) {
    tray.setImage(icon);
  }
  const statusText = {
    green: "Daemon: Running",
    yellow: "Daemon: Degraded",
    red: "Daemon: Error",
    unknown: "Daemon: Connecting...",
  };
  tray.setToolTip(statusText[status] || "Daemon");
}

function buildTrayMenu() {
  return Menu.buildFromTemplate([
    {
      label: currentStatus === "unknown" ? "Connecting..." : `Status: ${currentStatus.toUpperCase()}`,
      enabled: false,
    },
    { type: "separator" },
    {
      label: "Open Daemon",
      click: () => showMainWindow(),
    },
    { type: "separator" },
    {
      label: "Langfuse Dashboard",
      click: () => shell.openExternal("http://localhost:3001"),
    },
    {
      label: "Temporal UI",
      click: () => shell.openExternal("http://localhost:8080"),
    },
    {
      label: "Plane",
      click: () => shell.openExternal("http://localhost:3000"),
    },
    { type: "separator" },
    {
      label: "Quit",
      click: () => {
        app.isQuitting = true;
        app.quit();
      },
    },
  ]);
}

// ── Main Window ────────────────────────────────────────────────────────────

function createMainWindow() {
  mainWindow = new BrowserWindow({
    width: 1200,
    height: 800,
    minWidth: 800,
    minHeight: 600,
    titleBarStyle: "hiddenInset",
    trafficLightPosition: { x: 16, y: 16 },
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
    },
    show: false,
  });

  if (isDev) {
    mainWindow.loadURL(DEV_SERVER);
    // Open DevTools in dev mode
    mainWindow.webContents.openDevTools({ mode: "detach" });
  } else {
    mainWindow.loadFile(path.join(__dirname, "..", "compiled", "index.html"));
  }

  mainWindow.on("ready-to-show", () => {
    mainWindow.show();
  });

  // Hide instead of close (stay in tray)
  mainWindow.on("close", (e) => {
    if (!app.isQuitting) {
      e.preventDefault();
      mainWindow.hide();
    }
  });

  return mainWindow;
}

function showMainWindow() {
  if (!mainWindow) {
    createMainWindow();
  } else {
    mainWindow.show();
    mainWindow.focus();
  }
}

// ── Status Polling ─────────────────────────────────────────────────────────

let statusInterval = null;

async function pollStatus() {
  try {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 5000);
    const res = await fetch(`${DAEMON_API}/status`, { signal: controller.signal });
    clearTimeout(timeout);
    if (res.ok) {
      const data = await res.json();
      const health = data.health || data.status || "unknown";
      if (health === "GREEN" || health === "healthy" || health === "ok") {
        updateTray("green");
      } else if (health === "YELLOW" || health === "degraded") {
        updateTray("yellow");
      } else if (health === "RED" || health === "error") {
        updateTray("red");
      } else {
        updateTray("green"); // API responding = at least green
      }
    } else {
      updateTray("yellow");
    }
  } catch {
    updateTray("red");
  }

  // Send status to renderer
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send("daemon-status", currentStatus);
  }
}

// ── OAuth IPC ──────────────────────────────────────────────────────────────

function setupIPC() {
  // OAuth login: open external browser for OAuth flow
  ipcMain.handle("oauth-login", async (_event, provider) => {
    const authUrl = `${DAEMON_API}/auth/${provider}`;
    shell.openExternal(authUrl);
    return { opened: true };
  });

  // Get stored JWT token
  ipcMain.handle("get-token", async () => {
    const tokenPath = path.join(app.getPath("userData"), "auth-token.json");
    try {
      const data = JSON.parse(fs.readFileSync(tokenPath, "utf-8"));
      return data.token || null;
    } catch {
      return null;
    }
  });

  // Store JWT token
  ipcMain.handle("set-token", async (_event, token) => {
    const tokenPath = path.join(app.getPath("userData"), "auth-token.json");
    fs.writeFileSync(tokenPath, JSON.stringify({ token, saved_at: new Date().toISOString() }));
    return true;
  });

  // Open URL in system browser
  ipcMain.handle("open-external", async (_event, url) => {
    shell.openExternal(url);
    return true;
  });

  // Open URL in BrowserView (embedded browser)
  ipcMain.handle("open-browser-view", async (_event, url) => {
    if (!mainWindow) return false;
    // For now, open in system browser; BrowserView is P2
    shell.openExternal(url);
    return true;
  });

  // Launch VS Code
  ipcMain.handle("launch-vscode", async (_event, filePath) => {
    const { exec } = require("child_process");
    exec(`code "${filePath}"`, (err) => {
      if (err) console.error("Failed to launch VS Code:", err);
    });
    return true;
  });
}

// ── App Lifecycle ──────────────────────────────────────────────────────────

app.on("ready", () => {
  // Create tray
  tray = new Tray(createTrayIcon("unknown"));
  tray.setContextMenu(buildTrayMenu());
  tray.on("click", () => showMainWindow());

  // Setup IPC handlers
  setupIPC();

  // Create main window
  createMainWindow();

  // Start status polling (every 30s)
  pollStatus();
  statusInterval = setInterval(() => {
    pollStatus();
    // Refresh tray menu with current status
    tray.setContextMenu(buildTrayMenu());
  }, 30000);
});

app.on("second-instance", () => {
  showMainWindow();
});

app.on("activate", () => {
  showMainWindow();
});

app.on("window-all-closed", () => {
  // Don't quit on macOS — stay in tray
  if (process.platform !== "darwin") {
    app.quit();
  }
});

app.on("before-quit", () => {
  app.isQuitting = true;
  if (statusInterval) clearInterval(statusInterval);
});
