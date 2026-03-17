/**
 * Electron preload script — exposes safe IPC bridge to renderer.
 *
 * Available in renderer via window.daemon.*
 */

const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("daemon", {
  // OAuth
  oauthLogin: (provider) => ipcRenderer.invoke("oauth-login", provider),
  getToken: () => ipcRenderer.invoke("get-token"),
  setToken: (token) => ipcRenderer.invoke("set-token", token),

  // External tools
  openExternal: (url) => ipcRenderer.invoke("open-external", url),
  openBrowserView: (url) => ipcRenderer.invoke("open-browser-view", url),
  launchVSCode: (filePath) => ipcRenderer.invoke("launch-vscode", filePath),

  // Status updates from main process
  onStatusUpdate: (callback) => {
    ipcRenderer.on("daemon-status", (_event, status) => callback(status));
  },

  // Platform info
  platform: process.platform,
  isElectron: true,
});
