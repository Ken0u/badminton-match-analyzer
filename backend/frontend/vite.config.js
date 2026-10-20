import { defineConfig } from "vite";

// Optional development proxy only; never point this preview at a live catalog.
const backend = new URL(
  process.env.BADMINTON_FRONTEND_BACKEND_URL ?? "http://127.0.0.1:8000/",
);
if (
  !["http:", "https:"].includes(backend.protocol) ||
  !["localhost", "127.0.0.1", "[::1]"].includes(backend.hostname) ||
  backend.username ||
  backend.password ||
  backend.pathname !== "/" ||
  backend.search ||
  backend.hash
)
  throw new Error(
    "BADMINTON_FRONTEND_BACKEND_URL must be a loopback backend origin",
  );
const proxy = process.env.BADMINTON_FRONTEND_BACKEND_URL
  ? { "/api": { target: backend.origin } }
  : undefined;
export default defineConfig({
  base: "/",
  define: { __LEGACY_EDITOR_URL__: JSON.stringify(backend.href) },
  build: { outDir: "dist", emptyOutDir: true },
  server: { host: "127.0.0.1", strictPort: true, proxy },
  preview: { host: "127.0.0.1", strictPort: true, proxy },
});
