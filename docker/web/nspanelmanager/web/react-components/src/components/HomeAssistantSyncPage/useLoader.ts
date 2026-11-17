import { useCallback, useEffect, useState } from "react";

export type Loaded<T> = { status: "loading" } | { status: "error"; message: string } | { status: "loaded"; data: T };

/** Runs `load` on mount and whenever `reload()` is called. A failed load is an error state, not empty data. */
export function useLoader<T>(load: () => Promise<T>, deps: unknown[] = []) {
  const [state, setState] = useState<Loaded<T>>({ status: "loading" });
  const [generation, setGeneration] = useState(0);
  const reload = useCallback(() => setGeneration((value) => value + 1), []);

  useEffect(() => {
    let current = true;
    load()
      .then((data) => current && setState({ status: "loaded", data }))
      .catch((error) => current && setState({ status: "error", message: error instanceof Error ? error.message : String(error) }));
    return () => {
      current = false;
    };
    // Re-running is driven by `generation` and the caller's `deps`; `load` itself is recreated every render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [generation, ...deps]);

  return { state, reload };
}
