import "@fontsource-variable/anybody/standard.css";
import "@fontsource-variable/archivo/standard.css";
import "./floodlit.css";
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  useSyncExternalStore,
} from "react";
import { createRoot } from "react-dom/client";
import { Landing } from "./Landing.js";
import { Matches } from "./Matches.js";
import { Upload } from "./Upload.js";
import { Processing } from "./Processing.js";
import { Names } from "./Names.js";
import { MatchPage } from "./MatchPage.js";
import { parseRoute, ToastContext } from "./shell.js";

export function mountFloodlit(root: HTMLElement) {
  document.title = "Floodlit, badminton match analyzer";
  createRoot(root).render(<FloodlitApp />);
}

const subscribeHash = (fn: () => void) => {
  addEventListener("hashchange", fn);
  return () => removeEventListener("hashchange", fn);
};

function FloodlitApp() {
  const hash = useSyncExternalStore(subscribeHash, () => location.hash);
  const route = parseRoute(hash);
  const mainRef = useRef<HTMLElement>(null);
  const [toast, setToast] = useState({ text: "", shown: false });
  const timer = useRef(0);
  const showToast = useCallback((text: string) => {
    setToast({ text, shown: true });
    clearTimeout(timer.current);
    timer.current = window.setTimeout(
      () => setToast((t) => ({ ...t, shown: false })),
      3200,
    );
  }, []);
  useEffect(() => () => clearTimeout(timer.current), []);

  const key = `${route.view}/${route.id ?? ""}`;
  useEffect(() => {
    document.body.dataset.view =
      route.view === "missing" ? "matches" : route.view;
    window.scrollTo(0, 0);
    if (route.view !== "landing")
      mainRef.current?.focus({ preventScroll: true });
    // Keyed on the screen, not the tab, so switching tabs keeps the scroll.
  }, [key]); // eslint-disable-line react-hooks/exhaustive-deps

  // The hall lights strike once per visit; later screens find them already on.
  const [lit, setLit] = useState(false);
  const hallStarted = useRef(false);
  const onHallStart = () => {
    if (hallStarted.current) return;
    hallStarted.current = true;
    window.setTimeout(() => setLit(true), 2000);
  };

  let screen;
  switch (route.view) {
    case "landing":
      screen = <Landing />;
      break;
    case "matches":
      screen = <Matches />;
      break;
    case "upload":
      screen = <Upload />;
      break;
    case "processing":
      screen = <Processing key={route.id} id={route.id!} />;
      break;
    case "names":
      screen = <Names key={route.id} id={route.id!} />;
      break;
    case "match":
      screen = (
        <MatchPage key={route.id} id={route.id!} tab={route.tab ?? "watch"} />
      );
      break;
    default:
      screen = (
        <section className="page">
          <h1 className="page-title">Nothing here</h1>
          <p className="lede page-lede">
            This link does not lead to a screen of the analyzer.
          </p>
          <p className="page-actions">
            <a className="btn btn-flood" href="#/matches">
              Your matches
            </a>
          </p>
        </section>
      );
  }

  return (
    <ToastContext.Provider value={showToast}>
      <a
        className="skip"
        href="#main"
        onClick={(e) => {
          e.preventDefault();
          mainRef.current?.focus();
        }}
      >
        Skip to content
      </a>
      <header className="topbar" id="topbar">
        <a className="wordmark" href="#/" aria-label="Floodlit home">
          <svg viewBox="0 0 28 28" aria-hidden="true">
            <path
              d="M14 3 L22 22 H6 Z"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.6"
            />
            <circle cx="14" cy="23" r="3" fill="currentColor" />
          </svg>
          <span>Floodlit</span>
        </a>
        <nav className="topnav" aria-label="Main">
          <a
            href="#/matches"
            className="topnav-matches"
            aria-current={route.view === "matches" ? "page" : undefined}
          >
            <span className="long">Your matches</span>
            <span className="short">Matches</span>
          </a>
          <a
            href="#/upload"
            className="topnav-cta"
            aria-current={route.view === "upload" ? "page" : undefined}
          >
            Analyse a match
          </a>
        </nav>
        <div
          className={`hall${lit ? " lit" : ""}`}
          aria-hidden="true"
          onAnimationStart={onHallStart}
        >
          <i></i>
          <i></i>
          <i></i>
          <i></i>
        </div>
      </header>
      <main id="main" tabIndex={-1} ref={mainRef}>
        {screen}
      </main>
      <div
        className={`toast${toast.shown ? " show" : ""}`}
        role="status"
        aria-live="polite"
      >
        {toast.text}
      </div>
    </ToastContext.Provider>
  );
}
