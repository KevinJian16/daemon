import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  base: "/_portal/",
  plugins: [react()],
  build: {
    outDir: "compiled",
    emptyOutDir: true
  }
});
