"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError } from "./api";

export interface Resource<T> {
  data: T | null;
  error: string | null;
  loading: boolean;
  /** True while a background refresh is in flight over existing data. */
  refreshing: boolean;
  reload: () => void;
}

/**
 * Loads a value and optionally polls it.
 *
 * Polling is how the UI follows a running job: the worker writes progress to
 * the metadata store and this re-reads it. The interval is only armed while the
 * caller asks for it, so a finished run stops generating requests.
 */
export function useResource<T>(
  load: () => Promise<T>,
  options: { intervalMs?: number; enabled?: boolean; deps?: unknown[] } = {},
): Resource<T> {
  const { intervalMs = 0, enabled = true, deps = [] } = options;
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(enabled);
  const [refreshing, setRefreshing] = useState(false);

  const loadRef = useRef(load);
  loadRef.current = load;
  const hasData = useRef(false);
  const mounted = useRef(true);

  const run = useCallback(async () => {
    if (hasData.current) setRefreshing(true);
    try {
      const value = await loadRef.current();
      if (!mounted.current) return;
      setData(value);
      setError(null);
      hasData.current = true;
    } catch (failure) {
      if (!mounted.current) return;
      setError(
        failure instanceof ApiError
          ? failure.message
          : failure instanceof Error
            ? failure.message
            : "the request failed",
      );
    } finally {
      if (mounted.current) {
        setLoading(false);
        setRefreshing(false);
      }
    }
  }, []);

  useEffect(() => {
    mounted.current = true;
    if (!enabled) {
      setLoading(false);
      return () => {
        mounted.current = false;
      };
    }
    void run();
    if (intervalMs > 0) {
      const timer = setInterval(() => void run(), intervalMs);
      return () => {
        mounted.current = false;
        clearInterval(timer);
      };
    }
    return () => {
      mounted.current = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [run, intervalMs, enabled, ...deps]);

  return { data, error, loading, refreshing, reload: () => void run() };
}

/** Tracks an async action's pending state and error, for buttons and forms. */
export function useAction<Args extends unknown[], Result>(
  action: (...args: Args) => Promise<Result>,
) {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = useCallback(
    async (...args: Args): Promise<Result | null> => {
      setPending(true);
      setError(null);
      try {
        return await action(...args);
      } catch (failure) {
        setError(
          failure instanceof ApiError
            ? failure.message
            : failure instanceof Error
              ? failure.message
              : "the action failed",
        );
        return null;
      } finally {
        setPending(false);
      }
    },
    [action],
  );

  return { run, pending, error, clearError: () => setError(null) };
}
