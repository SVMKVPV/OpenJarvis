import { afterEach, describe, expect, it, vi } from 'vitest';
import { checkBackendConnection, checkHealth } from './api';

afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

describe('browser backend health', () => {
  it('rejects a hosting fallback that returns the frontend HTML with status 200', async () => {
    const fetchMock = vi.fn(async () => new Response('<!doctype html><title>OpenJarvis</title>'));
    vi.stubEnv('VITE_API_URL', '');
    vi.stubGlobal('fetch', fetchMock);
    expect(await checkHealth()).toBe(false);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it('accepts a real health response from the configured backend', async () => {
    const fetchMock = vi.fn(async () => Response.json({ status: 'ok' }));
    vi.stubEnv('VITE_API_URL', 'https://backend.example.test/');
    vi.stubGlobal('fetch', fetchMock);
    expect(await checkHealth()).toBe(true);
    expect(fetchMock).toHaveBeenCalledOnce();
    expect(fetchMock).toHaveBeenCalledWith('https://backend.example.test/health', { cache: 'no-store' });
  });

  it('recognizes the same-origin connector fallback after a failed health probe', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response('unavailable', { status: 503 }))
      .mockResolvedValueOnce(Response.json({ connectors: [] }));
    vi.stubEnv('VITE_API_URL', '');
    vi.stubGlobal('fetch', fetchMock);
    expect(await checkHealth()).toBe(true);
  });
});

describe('saved backend connection', () => {
  it('checks the saved origin with its key and rejects redirects', async () => {
    vi.stubGlobal('localStorage', {
      getItem: () => JSON.stringify({ apiUrl: 'https://backend.example.test', apiKey: 'test-key' }),
    });
    const fetchMock = vi.fn(async () => Response.json({ engine: 'ollama', model: 'test-model' }));
    vi.stubGlobal('fetch', fetchMock);
    const signal = new AbortController().signal;
    expect(await checkBackendConnection(signal)).toBe('connected');
    expect(fetchMock).toHaveBeenCalledWith('https://backend.example.test/v1/info', {
      cache: 'no-store', signal, redirect: 'error', headers: { Authorization: 'Bearer test-key' },
    });
  });

  it('distinguishes rejected credentials from a static frontend response', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(null, { status: 401 }))
      .mockResolvedValueOnce(new Response('<!doctype html>'));
    vi.stubGlobal('fetch', fetchMock);
    const signal = new AbortController().signal;
    expect(await checkBackendConnection(signal)).toBe('unauthorized');
    expect(await checkBackendConnection(signal)).toBe('unexpected-response');
  });
});
