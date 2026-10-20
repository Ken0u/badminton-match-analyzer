import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { createDraftStore } from "./state/draft.js";
import { createPlaybackStore } from "./state/playback.js";
import { createLatestTask, createSelectionScope } from "./state/selection.js";
import { createServerStore } from "./state/server.js";
import {
  Button,
  ErrorFeedback,
  Feedback,
  Field,
  Loading,
} from "./ui/controls.js";

// This deliberately synthetic sandbox never reads or writes annotation records.
const selection = createSelectionScope();
const server = createServerStore(selection);
const drafts = createDraftStore<{ note: string }>(selection);
const playback = createPlaybackStore();
const loading = createLatestTask(selection);
const initial = selection.select("sample-a");
server.setRecord(initial, { title: "Sample A", synthetic: true });
drafts.open(initial, { note: "" }, 0);

function PlaybackProbe() {
  const output = useRef<HTMLOutputElement>(null);
  useEffect(() => {
    let ticks = 0;
    return playback.subscribe(() => {
      if (output.current)
        output.current.textContent = `Playback ticks: ${++ticks}`;
    });
  }, []);
  return (
    <div className="probe">
      <Button
        onClick={() => {
          for (let tick = 1; tick <= 600; ++tick)
            playback.update({
              mediaTime: tick / 60,
              playing: false,
              sourceFrame: null,
              sourceTime: null,
            });
        }}
      >
        Publish 600 playback ticks
      </Button>
      <output ref={output} aria-label="Playback probe count">
        Playback ticks: 0
      </output>
      <p>
        The imperative subscriber receives ticks. Source frame and PTS remain
        unknown in this synthetic probe.
      </p>
    </div>
  );
}

export function App() {
  const draft = useSyncExternalStore(drafts.subscribe, drafts.getSnapshot);
  const records = useSyncExternalStore(server.subscribe, server.getSnapshot);
  const [pending, setPending] = useState(false);
  const [notice, setNotice] = useState("Synthetic sample A ready.");
  const [showError, setShowError] = useState(false);
  const note = useRef<HTMLInputElement>(null);
  const errorButton = useRef<HTMLButtonElement>(null);
  const renders = useRef(0);
  ++renders.current;

  async function load(id: string) {
    if (!drafts.canLeave()) {
      setNotice("Save or discard the draft before selecting another sample.");
      return;
    }
    const owner = selection.select(id);
    setPending(true);
    setNotice(`Loading ${id}…`);
    const result = await loading.run(
      owner,
      () =>
        new Promise<{ title: string; synthetic: true }>((resolve) => {
          // Deliberately ignores cancellation: ownership still fences late responses.
          window.setTimeout(
            () =>
              resolve({
                title: id === "sample-a" ? "Sample A" : "Sample B",
                synthetic: true,
              }),
            id === "sample-a" ? 300 : 60,
          );
        }),
      (record) => {
        server.setRecord(owner, record);
        drafts.open(owner, { note: "" }, 0);
      },
    );
    if (result.status === "committed") {
      setPending(false);
      setNotice(`${result.value.title} ready.`);
    }
  }

  async function save() {
    const ticket = drafts.beginSave();
    if (!ticket) return;
    // Local demonstration only; real mutations must use the API revision and its response.
    await new Promise<void>((resolve) => window.setTimeout(resolve, 250));
    if (drafts.completeSave(ticket, ticket.revision + 1, ticket.value)) {
      setNotice(
        drafts.getSnapshot()?.dirty
          ? "Saved snapshot; newer edits remain unsaved."
          : "Sample draft saved locally.",
      );
      window.requestAnimationFrame(() => note.current?.focus());
    }
  }

  return (
    <main>
      <header>
        <p className="eyebrow">Badminton match analyzer · Phase 95</p>
        <h1>Frontend foundation</h1>
        <p>
          A development sandbox for typed requests, safe state ownership and
          reusable controls.
        </p>
        <p className="boundary">
          Synthetic local samples only. The existing match review application
          remains the default. Automatic annotation accuracy is not established.
        </p>
      </header>
      <section aria-labelledby="state-heading">
        <h2 id="state-heading">State boundaries</h2>
        <div className="actions">
          <Button
            onClick={() => {
              void load("sample-a");
            }}
            disabled={Boolean(draft?.dirty || draft?.saving)}
          >
            Load sample A
          </Button>
          <Button
            onClick={() => {
              void load("sample-b");
            }}
            disabled={Boolean(draft?.dirty || draft?.saving)}
          >
            Load sample B
          </Button>
        </div>
        {pending && <Loading>Loading synthetic sample…</Loading>}
        <p>
          Selected sample:{" "}
          <strong data-testid="selected-sample">
            {draft?.owner.id ?? "none"}
          </strong>
        </p>
        <p>
          Server records cached:{" "}
          <span data-testid="record-count">
            {Object.keys(records.records).length}
          </span>
          . Jobs remain in a separate server collection.
        </p>
        <Field
          ref={note}
          label="Sandbox note"
          value={draft?.value.note ?? ""}
          disabled={pending}
          help="This local draft is separate from server records and playback."
          onChange={(event) => {
            drafts.edit(() => ({ note: event.target.value }));
          }}
        />
        <div className="actions">
          <Button
            onClick={() => {
              void save();
            }}
            busy={Boolean(draft?.saving)}
            disabled={!draft?.dirty || pending}
          >
            Save sample draft
          </Button>
          <Button
            disabled={!draft?.dirty || Boolean(draft?.saving) || pending}
            onClick={() => {
              if (drafts.discard()) {
                setNotice("Sample draft discarded.");
                note.current?.focus();
              }
            }}
          >
            Discard sample draft
          </Button>
        </div>
        <p data-testid="draft-state">
          Revision {draft?.revision ?? 0} ·{" "}
          {draft?.dirty ? "Unsaved changes" : "No unsaved changes"}
          {draft?.saving ? " · Saving snapshot…" : ""}
        </p>
        <Feedback>{notice}</Feedback>
      </section>
      <section aria-labelledby="playback-heading">
        <h2 id="playback-heading">Playback boundary</h2>
        <p>
          App renders:{" "}
          <output data-testid="app-renders">{renders.current}</output>
        </p>
        <PlaybackProbe />
      </section>
      <section aria-labelledby="feedback-heading">
        <h2 id="feedback-heading">Feedback controls</h2>
        <Button ref={errorButton} onClick={() => setShowError(true)}>
          Show example error
        </Button>
        {showError && (
          <ErrorFeedback
            retry={() => {
              setShowError(false);
              setNotice("Example error cleared.");
              window.requestAnimationFrame(() => errorButton.current?.focus());
            }}
          >
            Example only: the request could not be completed. Your draft is
            preserved.
          </ErrorFeedback>
        )}
      </section>
    </main>
  );
}
