import { createStore } from "./store.js";
import type { SelectionScope, SelectionToken } from "./selection.js";

export interface DraftSnapshot<T> {
  readonly owner: SelectionToken;
  readonly value: T;
  readonly revision: number;
  readonly dirty: boolean;
  readonly saving: boolean;
  readonly error: unknown;
}
interface SaveTicket<T> {
  readonly owner: SelectionToken;
  readonly value: T;
  readonly revision: number;
  readonly edit: number;
}

/** Explicit single-document draft; never accepts a server response as an edit. */
export function createDraftStore<T>(scope: SelectionScope) {
  const store = createStore<DraftSnapshot<T> | null>(null);
  let edit = 0;
  let savedValue: T;
  let pending: SaveTicket<T> | null = null;
  return {
    getSnapshot: store.getSnapshot,
    subscribe: store.subscribe,
    canLeave: () => !store.getSnapshot()?.dirty && !pending,
    open(owner: SelectionToken, value: T, revision: number) {
      const previous = store.getSnapshot();
      if (!scope.isCurrent(owner) || pending || previous?.dirty) return false;
      savedValue = structuredClone(value);
      store.publish({
        owner,
        value: structuredClone(value),
        revision,
        dirty: false,
        saving: false,
        error: null,
      });
      ++edit;
      return true;
    },
    edit(update: (value: T) => T) {
      const state = store.getSnapshot();
      if (!state || !scope.isCurrent(state.owner)) return false;
      const value = update(structuredClone(state.value));
      ++edit;
      store.publish({
        ...state,
        value: structuredClone(value),
        dirty: true,
        error: null,
      });
      return true;
    },
    discard() {
      const state = store.getSnapshot();
      if (!state || pending || !scope.isCurrent(state.owner)) return false;
      ++edit;
      store.publish({
        ...state,
        value: structuredClone(savedValue),
        dirty: false,
        error: null,
      });
      return true;
    },
    beginSave(): SaveTicket<T> | null {
      const state = store.getSnapshot();
      if (!state || pending || !state.dirty || !scope.isCurrent(state.owner))
        return null;
      pending = Object.freeze({
        owner: state.owner,
        value: structuredClone(state.value),
        revision: state.revision,
        edit,
      });
      store.publish({ ...state, saving: true, error: null });
      return pending;
    },
    completeSave(ticket: SaveTicket<T>, revision: number, value: T) {
      const state = store.getSnapshot();
      if (pending !== ticket) return false;
      pending = null;
      if (
        !state ||
        state.owner !== ticket.owner ||
        !scope.isCurrent(ticket.owner)
      )
        return false;
      savedValue = structuredClone(value);
      const unchanged = edit === ticket.edit;
      store.publish({
        ...state,
        value: unchanged ? structuredClone(value) : state.value,
        revision,
        dirty: !unchanged,
        saving: false,
        error: null,
      });
      return true;
    },
    failSave(ticket: SaveTicket<T>, error: unknown) {
      const state = store.getSnapshot();
      if (pending !== ticket) return false;
      pending = null;
      if (
        !state ||
        state.owner !== ticket.owner ||
        !scope.isCurrent(ticket.owner)
      )
        return false;
      store.publish({ ...state, saving: false, error });
      return true;
    },
  };
}
