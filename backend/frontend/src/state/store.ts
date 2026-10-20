export type Listener = () => void;
export interface ReadableStore<T> {
  getSnapshot(): T;
  subscribe(listener: Listener): () => void;
}

export function createStore<T>(initial: T) {
  let snapshot = initial;
  const listeners = new Set<Listener>();
  return {
    getSnapshot: () => snapshot,
    subscribe(listener: Listener) {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
    publish(next: T) {
      if (Object.is(snapshot, next)) return;
      snapshot = next;
      for (const listener of listeners) listener();
    },
  };
}
