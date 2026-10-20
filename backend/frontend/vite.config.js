import { defineConfig } from "vite";

// Development only. Production delivery/cutover is owned by phase 98.
export default defineConfig({
  base: "./",
  build: { outDir: "dist", emptyOutDir: true },
  server: { host: "127.0.0.1", strictPort: true },
  preview: { host: "127.0.0.1", strictPort: true },
});
