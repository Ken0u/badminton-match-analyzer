import { createRoot } from "react-dom/client";
import { EditorApp } from "./editor/EditorApp.js";
import { LibraryApp } from "./library/LibraryApp.js";
import "./style.css";

/** The previous library and review editor, kept off the main path. */
export function mountLegacy(root: HTMLElement, route: string) {
  createRoot(root).render(route === "/editor" ? <EditorApp /> : <LibraryApp />);
}
