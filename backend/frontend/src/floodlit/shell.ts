// Routing and the toast, shared by every Floodlit screen.
import { createContext, useContext } from "react";

/* ---------- hash routes: #/, #/matches, #/upload, #/match/<id>/<view> ---------- */
export interface Route {
  view:
    | "landing"
    | "matches"
    | "upload"
    | "processing"
    | "names"
    | "match"
    | "missing";
  id?: string;
  tab?: "watch" | "analysis";
}
export function parseRoute(hash: string): Route {
  const path = hash.replace(/^#\/?/, "").split("?")[0] ?? "";
  const [first, id, sub, extra] = path.split("/").filter(Boolean);
  if (!first) return { view: "landing" };
  if (extra) return { view: "missing" };
  if (first === "matches" && !id) return { view: "matches" };
  if (first === "upload" && !id) return { view: "upload" };
  if (first === "match" && id && /^[0-9a-f]{16}$/.test(id)) {
    if (sub === "processing") return { view: "processing", id };
    if (sub === "names") return { view: "names", id };
    if (!sub || sub === "watch") return { view: "match", id, tab: "watch" };
    if (sub === "analysis") return { view: "match", id, tab: "analysis" };
  }
  return { view: "missing" };
}
/** Change the route; ``replace`` keeps the history entry (a renamed match). */
export function go(hash: string, replace = false) {
  if (location.hash === hash) return;
  if (replace) location.replace(hash);
  else location.hash = hash;
}

export const ToastContext = createContext<(text: string) => void>(() => {});
export const useToast = () => useContext(ToastContext);
