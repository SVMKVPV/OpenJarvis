import { apiFetch, getBase } from './api';
import type { ConnectorInfo, SyncStatus, ConnectRequest, ConnectResponse } from '../types/connectors';

// ---------------------------------------------------------------------------
// Connectors API
// ---------------------------------------------------------------------------
//
// Every call here must go through apiFetch() (not a bare fetch()) so the
// Bearer auth header is attached when OPENJARVIS_API_KEY is set -- direct
// fetch() calls silently 401 against an authenticated server, exactly the
// bug apiFetch was introduced to prevent elsewhere (#266). This file was
// missed when that fix landed.

export async function listConnectors(): Promise<ConnectorInfo[]> {
  const res = await apiFetch('/v1/connectors');
  if (!res.ok) throw new Error(`Failed to list connectors: ${res.status}`);
  const data = await res.json();
  return data.connectors || [];
}

export async function indexWorkflowEvidence(files: File[]): Promise<{
  chunks_added: number;
  reference?: string | null;
}> {
  const body = new FormData();
  for (const file of files) body.append('files', file);
  const response = await apiFetch('/v1/connectors/upload/ingest/files', { method: 'POST', body });
  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    throw new Error(typeof payload?.detail === 'string'
      ? payload.detail : `Evidence upload failed (${response.status}).`);
  }
  return response.json();
}

export async function indexGmailEvidence(messageId: string): Promise<{
  chunks_added: number;
  reference?: string | null;
}> {
  const response = await apiFetch(
    `/v1/connectors/upload/ingest/gmail/${encodeURIComponent(messageId)}`, { method: 'POST' },
  );
  const data = await response.json().catch(() => null);
  if (!response.ok || !data || !Number.isInteger(data.chunks_added)) {
    throw new Error(typeof data?.detail === 'string' ? data.detail : 'Could not import Gmail evidence.');
  }
  return data;
}

export async function getConnector(id: string, signal?: AbortSignal): Promise<ConnectorInfo> {
  const res = await apiFetch(`/v1/connectors/${encodeURIComponent(id)}`, { signal });
  if (!res.ok) throw new Error(`Failed to get connector ${id}: ${res.status}`);
  return res.json();
}

export async function connectSource(id: string, req: ConnectRequest): Promise<ConnectResponse> {
  const res = await apiFetch(`/v1/connectors/${encodeURIComponent(id)}/connect`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  });
  if (!res.ok) {
    // Surface the backend's actionable detail (e.g. malformed Client ID /
    // Secret) instead of a bare status code so the UI can render it.
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || `Failed to connect ${id}: ${res.status}`);
  }
  return res.json();
}

/** Open the server-side OAuth consent flow in a popup and resolve once the
 *  connector reports connected (or reject on timeout). Reused for any OAuth
 *  connector whose /connect returned `oauth_required` (issue #512). */
export function startServerOAuth(id: string, oauthStartPath?: string): Promise<void> {
  const path = oauthStartPath || `/v1/connectors/${encodeURIComponent(id)}/oauth/start`;
  const popup = window.open(`${getBase()}${path}`, '_blank', 'width=600,height=700');
  if (!popup) {
    return Promise.reject(new Error('Your browser blocked the sign-in window. Allow pop-ups for this site and try again.'));
  }
  return new Promise((resolve, reject) => {
    const controller = new AbortController();
    const poll = async () => {
      try {
        const info = await getConnector(id, controller.signal);
        if (info.connected) {
          clearTimeout(timer);
          resolve();
          return;
        }
      } catch {
        // ignore transient polling errors
      }
      if (!controller.signal.aborted) nextPoll = setTimeout(poll, 2000);
    };
    let nextPoll = setTimeout(poll, 2000);
    const timer = setTimeout(() => {
      clearTimeout(nextPoll);
      controller.abort();
      reject(new Error('Authorization timed out — please try again.'));
    }, 180000);
  });
}

export class ConnectorApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = 'ConnectorApiError';
  }
}

export async function disconnectSource(
  id: string,
  signal?: AbortSignal,
): Promise<void> {
  const res = await apiFetch(`/v1/connectors/${encodeURIComponent(id)}/disconnect`, {
    method: 'POST',
    signal,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new ConnectorApiError(
      err.detail || `Failed to disconnect ${id}: ${res.status}`,
      res.status,
    );
  }
}

export interface DisconnectUntilCompleteOptions {
  signal?: AbortSignal;
  retryDelayMs?: number;
  onPending?: (message: string) => void;
}

function waitForDisconnectRetry(delayMs: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(new DOMException('Disconnect cancelled', 'AbortError'));
      return;
    }

    const timer = setTimeout(() => {
      signal?.removeEventListener('abort', handleAbort);
      resolve();
    }, delayMs);
    const handleAbort = () => {
      clearTimeout(timer);
      reject(new DOMException('Disconnect cancelled', 'AbortError'));
    };
    signal?.addEventListener('abort', handleAbort, { once: true });
  });
}

/**
 * Finish a disconnect even when the backend first returns 409 while an active
 * sync is stopping. The server deliberately keeps credentials and indexed
 * data intact until that worker exits; retrying is what completes cleanup.
 */
export async function disconnectSourceUntilComplete(
  id: string,
  {
    signal,
    retryDelayMs = 1500,
    onPending,
  }: DisconnectUntilCompleteOptions = {},
): Promise<void> {
  while (true) {
    try {
      await disconnectSource(id, signal);
      return;
    } catch (err) {
      if (!(err instanceof ConnectorApiError) || err.status !== 409) {
        throw err;
      }
      onPending?.(err.message);
      await waitForDisconnectRetry(retryDelayMs, signal);
    }
  }
}

export async function getSyncStatus(id: string, signal?: AbortSignal): Promise<SyncStatus> {
  const res = await apiFetch(`/v1/connectors/${encodeURIComponent(id)}/sync`, { signal });
  if (!res.ok) throw new Error(`Failed to get sync status for ${id}: ${res.status}`);
  return res.json();
}

export async function triggerSync(id: string): Promise<{ connector_id: string; chunks_indexed: number; status: string }> {
  const res = await apiFetch(`/v1/connectors/${encodeURIComponent(id)}/sync`, {
    method: 'POST',
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || `Sync failed: ${res.status}`);
  }
  return res.json();
}
