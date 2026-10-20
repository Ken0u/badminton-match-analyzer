import { defineConfig } from "vite";

// Optional development proxy only; never point this server at a live catalog.
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
export default defineConfig(({ mode }) => ({
  base: "/",
  plugins:
    mode === "foundation"
      ? [
          {
            name: "foundation-entry",
            transformIndexHtml: {
              order: "pre",
              handler: (html) =>
                html.replace("/src/main.tsx", "/src/foundation.tsx"),
            },
          },
        ]
      : [],
  build: {
    outDir: "dist",
    emptyOutDir: true,
    rollupOptions: {
      output: {
        entryFileNames: "app.js",
        assetFileNames: (asset) =>
          asset.names?.some((name) => name.endsWith(".css"))
            ? "style.css"
            : "assets/[name]-[hash][extname]",
        chunkFileNames: "assets/[name]-[hash].js",
      },
    },
  },
  server: { host: "127.0.0.1", strictPort: true, proxy },
  preview: { host: "127.0.0.1", strictPort: true, proxy },
}));
