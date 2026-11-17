import { useEffect, useRef, useState } from 'react';
import { checkInferenceHealth } from '../lib/api';

const HEALTH_MESSAGES = {
  healthy: 'The inference engine reported healthy.',
  unhealthy: 'The backend responded, but its inference engine reported unhealthy.',
  unavailable: 'Could not verify inference health. Check your backend connection.',
};

export function WorkspaceInferenceHealth() {
  const [status, setStatus] = useState<keyof typeof HEALTH_MESSAGES | 'checking' | null>(null);
  const request = useRef<AbortController | null>(null);
  useEffect(() => () => request.current?.abort(), []);

  const check = async () => {
    request.current?.abort();
    const controller = new AbortController();
    request.current = controller;
    setStatus('checking');
    const timeout = window.setTimeout(() => {
      if (controller.signal.aborted) return;
      controller.abort();
      setStatus('unavailable');
    }, 10000);
    try {
      const result = await checkInferenceHealth(controller.signal);
      if (!controller.signal.aborted) setStatus(result);
    } catch {
      if (!controller.signal.aborted) setStatus('unavailable');
    } finally {
      window.clearTimeout(timeout);
    }
  };

  return <>
    <button type="button" disabled={status === 'checking'} onClick={() => void check()}>
      {status === 'checking' ? 'Checking inference…' : 'Check inference health'}
    </button>
    {status && status !== 'checking' && <small role="status">{HEALTH_MESSAGES[status]}</small>}
  </>;
}
