import { useEffect, useState } from 'react';

/** Persist a local UI preference and tolerate disabled or invalid storage. */
export function useLocalPreference<T>(
  key: string,
  defaults: () => T,
  isValid: (value: unknown) => boolean,
) {
  const [value, setValue] = useState<T>(() => {
    try {
      const stored = window.localStorage.getItem(key);
      if (stored !== null) {
        const parsed: unknown = JSON.parse(stored);
        if (isValid(parsed)) return parsed as T;
      }
    } catch {
      // Storage may be unavailable in a restricted browser session.
    }
    return defaults();
  });

  useEffect(() => {
    try {
      window.localStorage.setItem(key, JSON.stringify(value));
    } catch {
      // Keep the preference usable for the current session.
    }
  }, [key, value]);

  return [value, setValue] as const;
}
