import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

// Regression for #266: the frontend must send the local API key as a Bearer
// token on /v1 + /api requests, or `jarvis serve` with a key configured 401s
// every data-plane call. These tests cover the pure helpers (getApiKey,
// authHeaders) that source the key and build the header.

const SETTINGS_KEY = 'openjarvis-settings';
const fetchMock = vi.fn<typeof fetch>();

// Minimal in-memory localStorage stub so the helpers can run under node
// (no jsdom dependency).
class MemoryStorage {
  private store = new Map<string, string>();
  getItem(k: string): string | null {
    return this.store.has(k) ? (this.store.get(k) as string) : null;
  }
  setItem(k: string, v: string): void {
    this.store.set(k, String(v));
  }
  removeItem(k: string): void {
    this.store.delete(k);
  }
  clear(): void {
    this.store.clear();
  }
}

beforeEach(() => {
  vi.resetModules();
  vi.stubEnv('VITE_SUPABASE_ANON_KEY', 'test-anon-key');
  fetchMock.mockReset();
  globalThis.fetch = fetchMock;
  (globalThis as unknown as { localStorage: MemoryStorage }).localStorage =
    new MemoryStorage();
});

afterEach(() => {
  vi.unstubAllEnvs();
  (globalThis as unknown as { localStorage?: MemoryStorage }).localStorage =
    undefined;
});

async function freshApi() {
  // Re-import to pick up the current localStorage stub.
  return await import('./api');
}

describe('getApiKey', () => {
  it('returns empty string when no key is configured', async () => {
    const { getApiKey } = await freshApi();
    expect(getApiKey()).toBe('');
  });

  it('reads apiKey from the openjarvis-settings localStorage blob', async () => {
    localStorage.setItem(
      SETTINGS_KEY,
      JSON.stringify({ apiUrl: 'http://x', apiKey: 'sk-local-123' }),
    );
    const { getApiKey } = await freshApi();
    expect(getApiKey()).toBe('sk-local-123');
  });

  it('returns empty string when the blob has no apiKey field', async () => {
    localStorage.setItem(SETTINGS_KEY, JSON.stringify({ apiUrl: 'http://x' }));
    const { getApiKey } = await freshApi();
    expect(getApiKey()).toBe('');
  });
});

describe('authHeaders', () => {
  it('omits Authorization when no key is set (keyless default unchanged)', async () => {
    const { authHeaders } = await freshApi();
    expect(authHeaders()).toEqual({});
  });

  it('adds a Bearer Authorization header when a key is set', async () => {
    localStorage.setItem(SETTINGS_KEY, JSON.stringify({ apiKey: 'sk-local-123' }));
    const { authHeaders } = await freshApi();
    expect(authHeaders()).toEqual({ Authorization: 'Bearer sk-local-123' });
  });

  it('merges extra headers alongside Authorization', async () => {
    localStorage.setItem(SETTINGS_KEY, JSON.stringify({ apiKey: 'sk-local-123' }));
    const { authHeaders } = await freshApi();
    expect(authHeaders({ 'Content-Type': 'application/json' })).toEqual({
      'Content-Type': 'application/json',
      Authorization: 'Bearer sk-local-123',
    });
  });
});

describe('managed agent channels', () => {
  beforeEach(() => {
    localStorage.setItem(
      SETTINGS_KEY,
      JSON.stringify({ apiUrl: 'https://jarvis.example', apiKey: 'test-key' }),
    );
  });

  it('authenticates channel binding against the configured server', async () => {
    fetchMock.mockResolvedValue(new Response('{}', { status: 200 }));
    const { bindAgentChannel } = await freshApi();

    await bindAgentChannel('agent-1', 'sendblue', { phone: '+15555550123' });

    expect(fetchMock).toHaveBeenCalledWith(
      'https://jarvis.example/v1/managed-agents/agent-1/channels',
      {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: 'Bearer test-key',
        },
        body: JSON.stringify({
          channel_type: 'sendblue',
          config: { phone: '+15555550123' },
          routing_mode: 'dedicated',
        }),
      },
    );
  });

  it('authenticates channel removal', async () => {
    fetchMock.mockResolvedValue(new Response(null, { status: 204 }));
    const { unbindAgentChannel } = await freshApi();

    await unbindAgentChannel('agent-1', 'binding-1');

    expect(fetchMock).toHaveBeenCalledWith(
      'https://jarvis.example/v1/managed-agents/agent-1/channels/binding-1',
      { method: 'DELETE', headers: { Authorization: 'Bearer test-key' } },
    );
  });
});

describe('workstation messages', () => {
  it('queues a message without asking the backend to run it immediately', async () => {
    const message = { id: 'message-1', status: 'pending', mode: 'queued' };
    fetchMock.mockResolvedValue(Response.json(message));
    const { askAgent } = await freshApi();

    await expect(askAgent('agent-1', 'Review this next run', 'queued')).resolves.toEqual(message);
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/v1/managed-agents/agent-1/messages'),
      expect.objectContaining({
        body: JSON.stringify({ content: 'Review this next run', mode: 'queued', stream: false }),
      }),
    );
  });
});

describe('approval decisions', () => {
  it('preserves the status of a stale decision for the approval inbox', async () => {
    fetchMock.mockResolvedValue(Response.json(
      { detail: 'Action is no longer pending' }, { status: 409 },
    ));
    const { ApprovalDecisionError, approveAction } = await freshApi();

    await expect(approveAction('stale-approval')).rejects.toEqual(
      new ApprovalDecisionError(409, 'Action is no longer pending'),
    );
  });
});

describe('workflow definitions', () => {
  it('explains how to save edits when the backend rejects definition updates', async () => {
    fetchMock.mockResolvedValue(Response.json({ detail: 'Method Not Allowed' }, { status: 405 }));
    const { saveWorkflowDefinition } = await freshApi();
    const definition = { name: 'Review', nodes: [{ id: 'review', type: 'approval' }] };

    await expect(saveWorkflowDefinition(definition, 'saved-1')).rejects.toThrow('Save as copy');
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});

describe('workflow run actions', () => {
  it('returns the new run and its original run ID after a retry', async () => {
    const retry = { id: 'retry-run', parent_run_id: 'original/run', status: 'queued' };
    fetchMock.mockResolvedValue(Response.json(retry, { status: 202 }));
    const { requestWorkflowRunAction } = await freshApi();

    await expect(requestWorkflowRunAction('original/run', 'retry')).resolves.toEqual(retry);
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringMatching(/\/v1\/workflows\/runs\/original%2Frun\/retry$/),
      expect.objectContaining({ method: 'POST' }),
    );
  });
});

describe('tool credentials', () => {
  it('reads credential status from the local server', async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ TAVILY_API_KEY: true }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    );
    const { fetchToolCredentialStatus } = await freshApi();

    await expect(fetchToolCredentialStatus('web_search')).resolves.toEqual({
      TAVILY_API_KEY: true,
    });
    expect(fetchMock).toHaveBeenCalledWith(
      '/v1/tools/web_search/credentials/status',
      { headers: {} },
    );
  });

  it('saves a tool credential through the local server', async () => {
    fetchMock.mockResolvedValue(new Response('{}', { status: 200 }));
    const { saveToolCredentials } = await freshApi();

    await saveToolCredentials('web_search', {
      TAVILY_API_KEY: 'tvly-test',
    });

    expect(fetchMock).toHaveBeenCalledWith('/v1/tools/web_search/credentials', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ TAVILY_API_KEY: 'tvly-test' }),
    });
  });

  it('deletes a tool credential through the local server', async () => {
    fetchMock.mockResolvedValue(new Response('{}', { status: 200 }));
    const { deleteToolCredential } = await freshApi();

    await deleteToolCredential('web_search', 'TAVILY_API_KEY');

    expect(fetchMock).toHaveBeenCalledWith(
      '/v1/tools/web_search/credentials/TAVILY_API_KEY',
      { method: 'DELETE', headers: {} },
    );
  });
});
