import { createRoot } from "react-dom/client";
import { App } from "./App.js";
import { EditorApp } from "./editor/EditorApp.js";
import { LibraryApp } from "./library/LibraryApp.js";
import "./style.css";

const root = document.getElementById("root");
if (!root) throw new Error("Missing application root");
createRoot(root).render(
  location.pathname.replace(/\/$/, "") === "/editor" ? (
    <EditorApp />
  ) : location.pathname.replace(/\/$/, "") === "/library" ? (
    <LibraryApp />
  ) : (
    <App />
  ),
);
