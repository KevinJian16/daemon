/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        surface: {
          0: "#0a0a0f",
          1: "#12121a",
          2: "#1a1a25",
          3: "#222230",
        },
        accent: {
          DEFAULT: "#6366f1",
          hover: "#818cf8",
          muted: "#4f46e5",
        },
        scene: {
          copilot: "#6366f1",
          mentor: "#f59e0b",
          coach: "#10b981",
          operator: "#ef4444",
        },
      },
    },
  },
  plugins: [],
};
