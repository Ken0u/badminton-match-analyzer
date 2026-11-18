import "./base.css";

// Floodlit (upload, names, match pages) is the application. The older
// library and review editor stay reachable at their own paths. Each loads
// with its own stylesheet, so neither restyles the other.
const root = document.getElementById("root");
if (!root) throw new Error("Missing application root");
const route = location.pathname.replace(/\/$/, "") || "/";
if (route === "/editor" || route === "/library") {
  void import("./legacy.js").then(({ mountLegacy }) =>
    mountLegacy(root, route),
  );
} else {
  document.documentElement.dataset.app = "floodlit";
  void import("./floodlit/FloodlitApp.js").then(({ mountFloodlit }) =>
    mountFloodlit(root),
  );
}
