import { createStore } from "./store.js";

export interface PlaybackSnapshot {
  readonly mediaTime: number;
  readonly playing: boolean;
  // Exact source identity is supplied by a verified mapping, never inferred from fps.
  readonly sourceFrame: number | null;
  readonly sourceTime: number | null;
}
/** Imperative subscriber lane for video/canvas; do not subscribe the app root. */
export function createPlaybackStore() {
  const store = createStore<PlaybackSnapshot>({
    mediaTime: 0,
    playing: false,
    sourceFrame: null,
    sourceTime: null,
  });
  return {
    getSnapshot: store.getSnapshot,
    subscribe: store.subscribe,
    update(snapshot: PlaybackSnapshot) {
      store.publish(Object.freeze({ ...snapshot }));
    },
  };
}
