import { useState, useEffect, useCallback, useRef } from 'react';
import { apiService } from '../services/api';
import type { HealthCheck } from '../types';

interface UseHealthCheckOptions {
  /** Polling interval in ms (default: 30000 = 30s) */
  interval?: number;
}

export function useHealthCheck(options: UseHealthCheckOptions = {}) {
  const { interval = 30000 } = options;
  const [health, setHealth] = useState<HealthCheck | null>(null);
  const [isOnline, setIsOnline] = useState<boolean | null>(null);
  const mountedRef = useRef(true);

  const check = useCallback(async () => {
    try {
      const data = await apiService.healthCheck();
      if (mountedRef.current) {
        setHealth(data);
        setIsOnline(true);
      }
    } catch {
      if (mountedRef.current) {
        setIsOnline(false);
      }
    }
  }, []);

  useEffect(() => {
    mountedRef.current = true;
    check(); // initial check

    const timer = setInterval(check, interval);
    return () => {
      mountedRef.current = false;
      clearInterval(timer);
    };
  }, [check, interval]);

  return { health, isOnline, refresh: check };
}
