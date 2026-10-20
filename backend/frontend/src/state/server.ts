import { createStore } from "./store.js";
import type { SelectionScope, SelectionToken } from "./selection.js";

/** Unvalidated server shapes remain unknown until a feature validates them. */
export interface ServerSnapshot {
  readonly records: Readonly<Record<string, unknown>>;
  readonly jobs: Readonly<Record<string, unknown>>;
}
export function createServerStore(scope: SelectionScope) {
  const store = createStore<ServerSnapshot>({ records: {}, jobs: {} });
  return {
    getSnapshot: store.getSnapshot,
    subscribe: store.subscribe,
    setRecord(owner: SelectionToken, value: unknown) {
      if (!scope.isCurrent(owner)) return false;
      store.publish({
        ...store.getSnapshot(),
        records: { ...store.getSnapshot().records, [owner.id]: value },
      });
      return true;
    },
    // Job polling owns a separate read lane; a job response is not an annotation.
    setJobs(owner: SelectionToken, value: unknown) {
      if (!scope.isCurrent(owner)) return false;
      store.publish({
        ...store.getSnapshot(),
        jobs: { ...store.getSnapshot().jobs, [owner.id]: value },
      });
      return true;
    },
  };
}
