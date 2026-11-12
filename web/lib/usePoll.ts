"use client";
import { useCallback, useEffect, useRef, useState } from "react";

/** Fetch now and every `ms` milliseconds. Returns data, error and a manual refresh. */
export function usePoll<T>(fn: () => Promise<T>, ms = 3000) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const fnRef = useRef(fn);
  fnRef.current = fn;

  const refresh = useCallback(async () => {
    try {
      setData(await fnRef.current());
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, ms);
    return () => clearInterval(t);
  }, [refresh, ms]);

  return { data, error, refresh };
}
