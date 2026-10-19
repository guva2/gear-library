import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

const backend = {
  target: "http://backend:8000",
  // Pass the browser's Host header through, so the backend sees the origin the browser
  // sees.
  changeOrigin: false,
};

export default defineConfig({
  plugins: [react()],
  server: {
    // All interfaces, so the dev server is reachable from outside its container.
    host: "0.0.0.0",
    port: 5173,
    strictPort: true,
    proxy: {
      // Whole path segments only, so `/apiary` and `/administrator` stay with Vite.
      "^/(api|admin|static)(/|$)": backend,
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test-setup.ts"],
    unstubGlobals: true,
  },
});
