import { createRoot } from "react-dom/client";
import { EditorApp } from "./editor/EditorApp.js";
import { LibraryApp } from "./library/LibraryApp.js";
import "./style.css";

const root = document.getElementById("root");
if (!root) throw new Error("Missing application root");
const route = location.pathname.replace(/\/$/, "") || "/";
createRoot(root).render(
  route === "/editor" ? (
    <EditorApp />
  ) : route === "/" || route === "/library" ? (
    <LibraryApp />
  ) : (
    <main>
      <h1>Page not found</h1>
      <p>This application route is not available.</p>
      <a href="/">Open the match library</a>
    </main>
  ),
);
