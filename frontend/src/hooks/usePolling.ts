import { useCallback, useEffect, useRef } from 'react';

interface UsePollingOptions {
  /** Initial polling interval in ms (default: 1000) */
  initialInterval?: number;
  /** Maximum polling interval in ms (default: 3000) */
  maxInterval?: number;
  /** Multiplier for exponential backoff (default: 1.3) */
  backoffFactor?: number;
  /** Whether polling is currently active */
  enabled: boolean;
}

/**
 * Adaptive polling hook — starts fast for quick feedback,
 * gradually backs off to reduce load on long-running jobs.
 */
export function usePolling(
  callback: () => Promise<boolean>, // return true to stop polling
  options: UsePollingOptions,
) {
  const {
    initialInterval = 1000,
    maxInterval = 3000,
    backoffFactor = 1.3,
    enabled,
  } = options;

  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const intervalRef = useRef(initialInterval);
  const callbackRef = useRef(callback);
  const mountedRef = useRef(true);

  // Keep callback ref fresh without triggering re-effects
  useEffect(() => {
    callbackRef.current = callback;
  }, [callback]);

  const stop = useCallback(() => {
    if (timerRef.current) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
    intervalRef.current = initialInterval;
  }, [initialInterval]);

  const poll = useCallback(async () => {
    if (!mountedRef.current) return;

    try {
      const shouldStop = await callbackRef.current();
      if (shouldStop || !mountedRef.current) {
        stop();
        return;
      }
    } catch {
      // On error, continue polling but back off faster
      intervalRef.current = Math.min(
        intervalRef.current * backoffFactor * 1.5,
        maxInterval,
      );
    }

    // Schedule next poll with adaptive interval
    intervalRef.current = Math.min(
      intervalRef.current * backoffFactor,
      maxInterval,
    );

    timerRef.current = setTimeout(poll, intervalRef.current);
  }, [backoffFactor, maxInterval, stop]);

  useEffect(() => {
    if (enabled) {
      intervalRef.current = initialInterval;
      // Fire immediately, then schedule
      poll();
    } else {
      stop();
    }

    return stop;
  }, [enabled, poll, stop, initialInterval]);

  // Cleanup on unmount
  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  return { stop };
}
