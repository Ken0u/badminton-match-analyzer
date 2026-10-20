export interface SelectionToken {
  readonly id: string;
  readonly epoch: number;
  readonly signal: AbortSignal;
}

export function createSelectionScope() {
  let epoch = 0;
  let current: SelectionToken | null = null;
  let controller = new AbortController();
  return {
    select(id: string): SelectionToken {
      controller.abort();
      controller = new AbortController();
      current = Object.freeze({
        id,
        epoch: ++epoch,
        signal: controller.signal,
      });
      return current;
    },
    current: () => current,
    isCurrent: (token: SelectionToken) =>
      current === token && !token.signal.aborted,
    clear() {
      controller.abort();
      current = null;
    },
  };
}

export type SelectionScope = ReturnType<typeof createSelectionScope>;
export type TaskResult<T> =
  { status: "committed"; value: T } | { status: "stale" };

/** One read lane per resource. Independent reads require independent lanes. */
export function createLatestTask(scope: SelectionScope) {
  let sequence = 0;
  let controller: AbortController | null = null;
  return {
    cancel() {
      ++sequence;
      controller?.abort();
    },
    async run<T>(
      owner: SelectionToken,
      task: (signal: AbortSignal) => Promise<T>,
      commit: (value: T) => void,
    ): Promise<TaskResult<T>> {
      controller?.abort();
      const active = new AbortController();
      controller = active;
      const ticket = ++sequence;
      const abort = () => active.abort();
      owner.signal.addEventListener("abort", abort, { once: true });
      if (!scope.isCurrent(owner)) active.abort();
      try {
        if (active.signal.aborted) return { status: "stale" };
        const value = await task(active.signal);
        if (
          ticket !== sequence ||
          active.signal.aborted ||
          !scope.isCurrent(owner)
        )
          return { status: "stale" };
        commit(value);
        return { status: "committed", value };
      } catch (error) {
        // A late error has the same ownership constraints as a late success.
        if (
          ticket !== sequence ||
          active.signal.aborted ||
          !scope.isCurrent(owner)
        )
          return { status: "stale" };
        throw error;
      } finally {
        owner.signal.removeEventListener("abort", abort);
        if (controller === active) controller = null;
      }
    },
  };
}
