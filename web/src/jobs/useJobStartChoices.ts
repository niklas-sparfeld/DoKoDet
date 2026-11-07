import { useEffect, useRef, useState } from "react";

type ChoiceState<T> = {
  key: string;
  choices: T[];
  loading: boolean;
  error: string | null;
};

/** Loads dependent choices and ignores results from an earlier dependency/context. */
export function useJobStartChoices<T>(
  key: string,
  load: (signal: AbortSignal) => Promise<T[]>,
) {
  const sequence = useRef(0);
  const loadRef = useRef(load);
  useEffect(() => {
    loadRef.current = load;
  }, [load]);
  const [state, setState] = useState<ChoiceState<T>>({
    key,
    choices: [],
    loading: true,
    error: null,
  });

  useEffect(() => {
    const request = ++sequence.current;
    const controller = new AbortController();
    void loadRef.current(controller.signal).then(
      (choices) => {
        if (!controller.signal.aborted && request === sequence.current)
          setState({ key, choices, loading: false, error: null });
      },
      () => {
        if (!controller.signal.aborted && request === sequence.current)
          setState({
            key,
            choices: [],
            loading: false,
            error: "Unable to load compatible choices. Try again.",
          });
      },
    );
    return () => controller.abort();
  }, [key]);

  return state.key === key
    ? state
    : { key, choices: [] as T[], loading: true, error: null };
}
