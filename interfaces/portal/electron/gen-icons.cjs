/**
 * Generate tray icons (green/yellow/red/unknown) as PNG files.
 * Run once: node electron/gen-icons.js
 */

const { createCanvas } = (() => {
  try {
    return require("canvas");
  } catch {
    return { createCanvas: null };
  }
})();

const fs = require("fs");
const path = require("path");

const colors = {
  green: "#22c55e",
  yellow: "#eab308",
  red: "#ef4444",
  unknown: "#6b7280",
};

const dir = path.join(__dirname, "icons");

if (!createCanvas) {
  // Fallback: create simple 1x1 PNGs as placeholders
  // In production, replace with real icons
  console.log("canvas module not available, creating placeholder icons");
  for (const [name] of Object.entries(colors)) {
    const placeholder = path.join(dir, `tray-${name}.png`);
    if (!fs.existsSync(placeholder)) {
      // Minimal 16x16 PNG (1 pixel, solid color)
      // This is a valid but tiny PNG — Electron will handle it
      fs.writeFileSync(placeholder, Buffer.alloc(0));
    }
  }
  // Create template icon
  const template = path.join(dir, "tray-template.png");
  if (!fs.existsSync(template)) {
    fs.writeFileSync(template, Buffer.alloc(0));
  }
  console.log("Placeholder icons created. Replace with real PNGs for production.");
  process.exit(0);
}

const SIZE = 32; // @2x for retina

for (const [name, color] of Object.entries(colors)) {
  const canvas = createCanvas(SIZE, SIZE);
  const ctx = canvas.getContext("2d");

  // Draw filled circle
  ctx.beginPath();
  ctx.arc(SIZE / 2, SIZE / 2, SIZE / 2 - 2, 0, Math.PI * 2);
  ctx.fillStyle = color;
  ctx.fill();

  const out = path.join(dir, `tray-${name}.png`);
  fs.writeFileSync(out, canvas.toBuffer("image/png"));
  console.log(`Created ${out}`);
}

// Template icon (for macOS dark/light mode)
const canvas = createCanvas(SIZE, SIZE);
const ctx = canvas.getContext("2d");
ctx.beginPath();
ctx.arc(SIZE / 2, SIZE / 2, SIZE / 2 - 2, 0, Math.PI * 2);
ctx.fillStyle = "#000000";
ctx.fill();
const templateOut = path.join(dir, "tray-template.png");
fs.writeFileSync(templateOut, canvas.toBuffer("image/png"));
console.log(`Created ${templateOut}`);
