/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: [
          "ui-sans-serif",
          "system-ui",
          "-apple-system",
          "BlinkMacSystemFont",
          "\"Segoe UI\"",
          "sans-serif"
        ],
        serif: [
          "\"Iowan Old Style\"",
          "\"Palatino Linotype\"",
          "\"Book Antiqua\"",
          "Georgia",
          "ui-serif",
          "serif"
        ]
      },
      boxShadow: {
        claude:
          "0 0.25rem 1.25rem rgba(0,0,0,0.035),0 0 0 0.5px rgba(0,0,0,0.08)",
        "claude-strong":
          "0 0.25rem 1.25rem rgba(0,0,0,0.075),0 0 0 0.5px rgba(0,0,0,0.15)"
      }
    }
  },
  plugins: []
};
