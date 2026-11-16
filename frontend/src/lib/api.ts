import type { ModelInfo, SavingsData, ServerInfo } from '../types';
import { SUPABASE_ANON_KEY, SUPABASE_URL } from './supabase';
import { serializeToolCallArguments } from './tool-call';
import { timeZoneHeaders } from './timezone';

// ---------------------------------------------------------------------------
// Supabase config
// ---------------------------------------------------------------------------

declare global {
  interface Window {
    __TAURI_INTERNALS__?: unknown;
  }
}

export const isTauri = () => typeof window !== 'undefined' && !!window.__TAURI_INTERNALS__;

export type CloudKeyStatus = Record<string, boolean>;

export async function getCloudKeyStatus(): Promise<CloudKeyStatus> {
  if (!isTauri()) return {};
  try {
    const { invoke } = await import('@tauri-apps/api/core');
    const rows = await invoke<Array<{ key: string; set: boolean }>>('get_cloud_key_status');
    return Object.fromEntries(rows.map((row) => [row.key, row.set]));
  } catch (e: any) {
    throw new Error(e?.message ?? e ?? 'Failed to read cloud key status');
  }
}

export async function saveCloudKey(keyName: string, keyValue: string): Promise<void> {
  if (!isTauri()) {
    throw new Error('Cloud API keys can be saved in the desktop app only.');
  }
  try {
    const { invoke } = await import('@tauri-apps/api/core');
    await invoke('save_cloud_key', { keyName, keyValue });
  } catch (e: any) {
    throw new Error(e?.message ?? e ?? 'Failed to save cloud key');
  }
}

// Cached API base URL fetched from the Tauri backend at startup.
// This avoids hardcoding the port — the Rust backend is the single
// source of truth for JARVIS_PORT.
let _tauriApiBase: string | null = null;

/** Pre-fetch the API base URL from the Tauri backend (call once at init). */
export async function initApiBase(): Promise<void> {
  if (!isTauri()) return;
  try {
    const { invoke } = await import('@tauri-apps/api/core');
    _tauriApiBase = await invoke<string>('get_api_base');
  } catch {
    // Command may not exist on older builds; fall through to default.
  }
}

const DESKTOP_API_FALLBACK = 'http://127.0.0.1:8000';

const getSettingsApiUrl = (): string => {
  try {
    const raw = localStorage.getItem('openjarvis-settings');
    if (raw) {
      const parsed = JSON.parse(raw);
      if (parsed.apiUrl) return parsed.apiUrl.replace(/\/+$/, '');
    }
  } catch {}
  return '';
};

export const getBase = (): string => {
  const settingsUrl = getSettingsApiUrl();
  if (settingsUrl) return settingsUrl;
  if (import.meta.env.VITE_API_URL) return import.meta.env.VITE_API_URL;
  if (isTauri()) return _tauriApiBase || DESKTOP_API_FALLBACK;
  return '';
};

// Resolve the local server API key (OPENJARVIS_API_KEY). When `jarvis serve`
// is started with a key, AuthMiddleware 401s every /v1 and /api request that
// lacks a Bearer token — so the frontend must send it (#266). Sourced from the
// same settings blob as the API URL, with an optional build-time env override.
// Returns '' when unset, so a keyless local server keeps working unchanged.
export const getApiKey = (): string => {
  try {
    const raw = localStorage.getItem('openjarvis-settings');
    if (raw) {
      const parsed = JSON.parse(raw);
      if (parsed.apiKey) return String(parsed.apiKey);
    }
  } catch {}
  if (import.meta.env.VITE_OPENJARVIS_API_KEY) {
    return import.meta.env.VITE_OPENJARVIS_API_KEY as string;
  }
  return '';
};

// Build request headers with the Bearer Authorization token when a local key
// is configured, merging any caller-supplied headers. Adds no Authorization
// header when no key is set, so keyless local dev is byte-for-byte unchanged.
export const authHeaders = (
  extra: Record<string, string> = {},
): Record<string, string> => {
  const key = getApiKey();
  return key ? { ...extra, Authorization: `Bearer ${key}` } : { ...extra };
};

// Centralized fetch for the local server: prepends getBase() and injects the
// Bearer auth header (when a key is set) on every call. Using this everywhere
// guarantees no /v1 or /api request is sent without auth — the bug in #266 was
// that direct fetch() calls omitted the header and 401'd. `path` is the
// server-relative path (e.g. "/v1/savings").
export const apiFetch = (
  path: string,
  init: RequestInit = {},
): Promise<Response> => {
  const headers = authHeaders(
    (init.headers as Record<string, string> | undefined) ?? {},
  );
  return fetch(`${getBase()}${path}`, { ...init, headers });
};

export interface SharedBrainBrief {
  context: string;
  revision: number;
}

export class SharedBrainConflict extends Error {}

async function readSharedBrainBrief(response: Response): Promise<SharedBrainBrief> {
  if (response.status === 409) throw new SharedBrainConflict();
  if (!response.ok) throw new Error(`Shared Brain backend request failed (${response.status}).`);
  const data = await response.json().catch(() => null);
  if (typeof data?.context !== 'string' || !Number.isInteger(data?.revision) || data.revision < 0) {
    throw new Error('This backend does not provide a shared brief.');
  }
  return data;
}

export async function fetchSharedBrainBrief(signal?: AbortSignal): Promise<SharedBrainBrief> {
  return readSharedBrainBrief(await apiFetch('/v1/shared-brain/brief', { signal }));
}

export async function saveSharedBrainBrief(brief: SharedBrainBrief): Promise<SharedBrainBrief> {
  return readSharedBrainBrief(await apiFetch('/v1/shared-brain/brief', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(brief),
  }));
}

export type RuntimePlugin = {
  id: string;
  name: string;
  kind: 'connector' | 'channel' | 'tool' | 'agent' | 'engine' | 'mcp';
  source: 'built-in' | 'extension' | 'configuration';
  installed: boolean;
  enabled: boolean;
  auth_type: string;
  description: string;
  package: string;
  version: string;
};

export async function discoverMcpTools(): Promise<number> {
  const response = await apiFetch('/v1/plugins/mcp/discover', { method: 'POST' });
  if (!response.ok) throw new Error(`MCP tool discovery failed (${response.status}).`);
  const payload = await response.json();
  return payload.tool_count;
}

export async function fetchRuntimePlugins(): Promise<RuntimePlugin[]> {
  const response = await apiFetch('/v1/plugins');
  if (!response.ok) {
    throw new Error(`Plugin catalog request failed (${response.status})`);
  }
  const payload = await response.json();
  return Array.isArray(payload.plugins) ? payload.plugins : [];
}

async function tauriInvoke<T>(command: string, args: Record<string, unknown> = {}): Promise<T> {
  const { invoke } = await import('@tauri-apps/api/core');
  const apiUrl = getBase();
  return invoke<T>(command, { apiUrl, ...args });
}

// ---------------------------------------------------------------------------
// Setup status (desktop only)
// ---------------------------------------------------------------------------

export interface SetupStatus {
  phase: string;
  detail: string;
  ollama_ready: boolean;
  server_ready: boolean;
  model_ready: boolean;
  error: string | null;
  source: 'unconfigured' | 'ollama' | 'custom';
  requires_source: boolean;
}

export async function getSetupStatus(): Promise<SetupStatus | null> {
  if (!isTauri()) return null;
  try {
    const { invoke } = await import('@tauri-apps/api/core');
    return await invoke<SetupStatus>('get_setup_status');
  } catch {
    return null;
  }
}

/** Start desktop services after an inference source has been persisted. */
export async function startBackend(): Promise<void> {
  if (!isTauri()) throw new Error('The desktop backend is available in the desktop app only.');
  try {
    const { invoke } = await import('@tauri-apps/api/core');
    await invoke<void>('start_backend');
  } catch (e: any) {
    throw new Error(e?.message ?? e ?? 'Failed to start the desktop backend');
  }
}

/** Stop an in-flight setup and return the desktop to its inert source chooser. */
export async function resetInferenceSource(): Promise<void> {
  if (!isTauri()) throw new Error('Inference setup recovery is available in the desktop app only.');
  try {
    const { invoke } = await import('@tauri-apps/api/core');
    await invoke<void>('reset_inference_source');
  } catch (e: any) {
    throw new Error(e?.message ?? e ?? 'Failed to reset inference setup');
  }
}

// ---------------------------------------------------------------------------
// API functions
// ---------------------------------------------------------------------------

export async function fetchModels(): Promise<ModelInfo[]> {
  if (isTauri()) {
    try {
      const result = await tauriInvoke<{ data?: ModelInfo[] }>('fetch_models');
      return result?.data || [];
    } catch {
      // Fall through to fetch
    }
  }
  const res = await apiFetch(`/v1/models`);
  if (!res.ok) throw new Error(`Failed to fetch models: ${res.status}`);
  const data = await res.json();
  return data.data || [];
}

export async function fetchRecommendedModel(): Promise<{ model: string; reason: string }> {
  const res = await apiFetch(`/v1/recommended-model`);
  if (!res.ok) return { model: '', reason: 'Failed to fetch' };
  return res.json();
}

export async function pullModel(modelName: string): Promise<void> {
  // In Tauri, go through the Rust backend directly (avoids CORS / timeout
  // issues with long model downloads via fetch).
  if (isTauri()) {
    try {
      const { invoke } = await import('@tauri-apps/api/core');
      await invoke('pull_ollama_model', { modelName });
      return;
    } catch (e: any) {
      throw new Error(e?.message || e || 'Download failed');
    }
  }
  const res = await apiFetch(`/v1/models/pull`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ model: modelName }),
  });
  if (!res.ok) {
    const detail = await res.text().catch(() => res.statusText);
    throw new Error(`Failed to pull model: ${detail}`);
  }
}

export async function deleteModel(modelName: string): Promise<void> {
  if (isTauri()) {
    try {
      const { invoke } = await import('@tauri-apps/api/core');
      await invoke('delete_ollama_model', { modelName });
      return;
    } catch (e: any) {
      throw new Error(e?.message || e || 'Delete failed');
    }
  }
  const res = await apiFetch(`/v1/models/${encodeURIComponent(modelName)}`, {
    method: 'DELETE',
  });
  if (!res.ok) {
    const detail = await res.text().catch(() => res.statusText);
    throw new Error(`Failed to delete model: ${detail}`);
  }
}

const _CLOUD_PREFIXES = ['gpt-', 'o1-', 'o3-', 'o4-', 'claude-', 'gemini-', 'openrouter/'];

export async function preloadModel(modelName: string, owner?: string): Promise<void> {
  // Cloud models don't need Ollama preloading
  if (owner === 'litellm' || _CLOUD_PREFIXES.some(p => modelName.startsWith(p))) {
    return;
  }
  // Trigger Ollama to load the model into memory (empty prompt, no generation).
  const ollamaUrl = 'http://127.0.0.1:11434';
  try {
    const res = await fetch(`${ollamaUrl}/api/generate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ model: modelName, prompt: '', keep_alive: '5m' }),
      signal: AbortSignal.timeout(120_000),
    });
    if (!res.ok) throw new Error(`Preload failed: ${res.status}`);
  } catch (e: any) {
    if (e.name === 'TimeoutError') throw new Error('Model load timed out (120s)');
    throw e;
  }
}

export async function fetchSavings(): Promise<SavingsData> {
  const res = await apiFetch(`/v1/savings`);
  if (!res.ok) throw new Error(`Failed to fetch savings: ${res.status}`);
  return res.json();
}

export async function fetchServerInfo(): Promise<ServerInfo> {
  const res = await apiFetch(`/v1/info`);
  if (!res.ok) throw new Error(`Failed to fetch server info: ${res.status}`);
  return res.json();
}

export async function checkHealth(): Promise<boolean> {
  if (isTauri()) {
    try {
      await tauriInvoke('check_health', { apiUrl: getBase() });
      return true;
    } catch {
      return false;
    }
  }
  // In the browser, hit /health relative to the page origin so the request
  // flows through whatever path is already serving the SPA — the Vite
  // proxy in dev, FastAPI's static mount in prod. This avoids the
  // false-negative "Cannot reach backend" banner when getBase() points at
  // an absolute URL the browser can't reach directly.
  //
  // If /health itself fails for any reason (proxy quirk, stale service
  // worker, etc.) fall back to an arbitrary API endpoint we know the rest
  // of the app polls successfully. If THAT also fails we genuinely can't
  // reach the backend.
  const probe = async (url: string): Promise<boolean> => {
    try {
      const res = await fetch(url, { cache: 'no-store' });
      return res.ok;
    } catch {
      return false;
    }
  };
  // In browser mode Vite serves the SPA on a different port than the API.
  // Probe the configured API base first; the relative fallback supports
  // production deployments where both are served from one origin.
  const base = getBase().replace(/\/+$/, '');
  if (base && await probe(`${base}/health`)) return true;
  if (await probe('/health')) return true;
  if (base && await probe(`${base}/v1/connectors`)) return true;
  return probe('/v1/connectors');
}

export async function fetchEnergy(): Promise<unknown> {
  if (isTauri()) {
    try {
      return await tauriInvoke('fetch_energy', { apiUrl: getBase() });
    } catch {}
  }
  const res = await apiFetch(`/v1/telemetry/energy`);
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
  return res.json();
}

export async function fetchTelemetry(): Promise<unknown> {
  if (isTauri()) {
    try {
      return await tauriInvoke('fetch_telemetry', { apiUrl: getBase() });
    } catch {}
  }
  const res = await apiFetch(`/v1/telemetry/stats`);
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
  return res.json();
}

export async function fetchTraces(limit: number = 50): Promise<unknown> {
  if (isTauri()) {
    try {
      return await tauriInvoke('fetch_traces', { apiUrl: getBase(), limit });
    } catch {}
  }
  const res = await apiFetch(`/v1/traces?limit=${limit}`);
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
  return res.json();
}

// ---------------------------------------------------------------------------
// Speech
// ---------------------------------------------------------------------------

export interface TranscriptionResult {
  text: string;
  language: string | null;
  confidence: number | null;
  duration_seconds: number;
}

export interface SpeechHealth {
  available: boolean;
  backend?: string;
  reason?: string;
}

export async function transcribeAudio(audioBlob: Blob, filename = 'recording.webm'): Promise<TranscriptionResult> {
  if (isTauri()) {
    try {
      const buffer = await audioBlob.arrayBuffer();
      return await tauriInvoke<TranscriptionResult>('transcribe_audio', {
        audioData: Array.from(new Uint8Array(buffer)),
        filename,
      });
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      throw new Error(msg || 'Transcription failed');
    }
  }
  const formData = new FormData();
  formData.append('file', audioBlob, filename);
  const res = await apiFetch(`/v1/speech/transcribe`, {
    method: 'POST',
    body: formData,
  });
  if (!res.ok) {
    let detail = "";
    try {
      const body = await res.json();
      detail = typeof body.detail === 'string' ? body.detail : "";
    } catch {
      // Keep the status-only message below when the body is not JSON.
    }
    throw new Error(detail || `Transcription failed: ${res.status}`);
  }
  return res.json();
}

export interface TtsHealth {
  available: boolean;
  backend?: string;
  voice_id?: string;
  speed?: number;
  reason?: string;
}

export async function synthesizeSpeech(
  text: string,
  opts: { voiceId?: string; speed?: number; signal?: AbortSignal } = {},
): Promise<Blob> {
  const res = await apiFetch(`/v1/speech/synthesize`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text, voice_id: opts.voiceId, speed: opts.speed }),
    signal: opts.signal,
  });
  if (!res.ok) {
    let detail = '';
    try {
      const body = await res.json();
      detail = typeof body.detail === 'string' ? body.detail : '';
    } catch {
      // Keep the status-only message below when the body is not JSON.
    }
    throw new Error(detail || `Speech synthesis failed: ${res.status}`);
  }
  return res.blob();
}

export async function fetchTtsHealth(): Promise<TtsHealth> {
  const res = await apiFetch(`/v1/speech/tts/health`);
  if (!res.ok) return { available: false };
  return res.json();
}

export async function fetchSpeechHealth(): Promise<SpeechHealth> {
  if (isTauri()) {
    try {
      return await tauriInvoke<SpeechHealth>('speech_health');
    } catch {
      return { available: false };
    }
  }
  const res = await apiFetch(`/v1/speech/health`);
  if (!res.ok) return { available: false };
  return res.json();
}

// ---------------------------------------------------------------------------
// Agent Manager
// ---------------------------------------------------------------------------

export interface ManagedAgentConfig extends Record<string, unknown> {
  schedule_type?: string;
  schedule_value?: string | number;
}

export interface ManagedAgent {
  id: string;
  name: string;
  agent_type: string;
  config: ManagedAgentConfig;
  status: 'idle' | 'running' | 'paused' | 'error' | 'archived' | 'needs_attention' | 'budget_exceeded' | 'stalled';
  summary_memory: string;
  created_at: number;
  updated_at: number;
  // Runtime stats
  total_runs?: number;
  total_cost?: number;
  total_tokens?: number;
  input_tokens?: number;
  output_tokens?: number;
  last_run_at?: number | null;
  // Budget
  budget?: number;
  // Learning
  learning_enabled?: boolean;
  // Live progress
  current_activity?: string;
}

export interface AgentTask {
  id: string;
  agent_id: string;
  description: string;
  status: 'pending' | 'active' | 'completed' | 'failed';
  progress: Record<string, unknown>;
  findings: unknown[];
  created_at: number;
}

export interface ChannelBinding {
  id: string;
  agent_id: string;
  channel_type: string;
  config: Record<string, unknown>;
  session_id: string;
  routing_mode: string;
}

export interface AgentTemplate {
  id: string;
  name: string;
  description: string;
  source: 'built-in' | 'user';
  agent_type: string;
  [key: string]: unknown;
}

export interface PersistedToolCall {
  tool: string;
  arguments: string;
  result?: string;
  success?: boolean;
  latency?: number;
}

export interface AgentMessage {
  id: string;
  agent_id: string;
  direction: 'user_to_agent' | 'agent_to_user';
  content: string;
  mode: 'immediate' | 'queued' | 'handoff';
  status: 'pending' | 'delivered' | 'responded';
  created_at: number;
  tool_calls?: PersistedToolCall[] | null;
}

export async function fetchManagedAgents(): Promise<ManagedAgent[]> {
  const res = await apiFetch(`/v1/managed-agents`);
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
  const data = await res.json();
  return data.agents || [];
}

export async function fetchManagedAgent(agentId: string): Promise<ManagedAgent> {
  const res = await apiFetch(`/v1/managed-agents/${agentId}`);
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
  return res.json();
}

export async function createManagedAgent(body: {
  name: string;
  agent_type?: string;
  template_id?: string;
  config?: Record<string, unknown>;
}): Promise<ManagedAgent> {
  const res = await apiFetch(`/v1/managed-agents`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const error = await res.json().catch(() => null);
    throw new Error(typeof error?.detail === 'string' ? error.detail : `Failed: ${res.status}`);
  }
  return res.json();
}

export async function updateManagedAgent(
  agentId: string,
  body: Partial<{ name: string; agent_type: string; model: string; use_shared_brain: boolean; config: Record<string, unknown> }>,
): Promise<ManagedAgent> {
  const res = await apiFetch(`/v1/managed-agents/${agentId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
  return res.json();
}

export async function deleteManagedAgent(agentId: string): Promise<void> {
  const res = await apiFetch(`/v1/managed-agents/${agentId}`, { method: 'DELETE' });
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
}

export async function pauseManagedAgent(agentId: string): Promise<void> {
  const res = await apiFetch(`/v1/managed-agents/${agentId}/pause`, { method: 'POST' });
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
}

export async function resumeManagedAgent(agentId: string): Promise<void> {
  const res = await apiFetch(`/v1/managed-agents/${agentId}/resume`, { method: 'POST' });
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
}

export async function fetchAgentTasks(agentId: string): Promise<AgentTask[]> {
  const res = await apiFetch(`/v1/managed-agents/${agentId}/tasks`);
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
  const data = await res.json();
  return data.tasks || [];
}

export async function createAgentTask(agentId: string, description: string): Promise<AgentTask> {
  const res = await apiFetch(`/v1/managed-agents/${agentId}/tasks`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ description }),
  });
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
  return res.json();
}

export async function fetchAgentChannels(agentId: string): Promise<ChannelBinding[]> {
  const res = await apiFetch(`/v1/managed-agents/${agentId}/channels`);
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
  const data = await res.json();
  return data.bindings || [];
}

export async function bindAgentChannel(
  agentId: string,
  channelType: string,
  config?: Record<string, unknown>,
): Promise<ChannelBinding> {
  const res = await apiFetch(`/v1/managed-agents/${agentId}/channels`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      channel_type: channelType,
      config: config || {},
      routing_mode: 'dedicated',
    }),
  });
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
  return res.json();
}

export async function unbindAgentChannel(
  agentId: string,
  bindingId: string,
): Promise<void> {
  const res = await apiFetch(`/v1/managed-agents/${agentId}/channels/${bindingId}`, {
    method: 'DELETE',
  });
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
}

// -- SendBlue auto-setup helpers ------------------------------------------

export async function sendblueVerify(
  apiKeyId: string,
  apiSecretKey: string,
): Promise<{ valid: boolean; numbers: string[]; raw: unknown }> {
  const res = await apiFetch(`/v1/channels/sendblue/verify`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ api_key_id: apiKeyId, api_secret_key: apiSecretKey }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || `Verification failed: ${res.status}`);
  }
  return res.json();
}

export async function sendblueRegisterWebhook(
  apiKeyId: string,
  apiSecretKey: string,
  webhookUrl: string,
): Promise<{ registered: boolean; status: number }> {
  const res = await apiFetch(`/v1/channels/sendblue/register-webhook`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      api_key_id: apiKeyId,
      api_secret_key: apiSecretKey,
      webhook_url: webhookUrl,
    }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || `Webhook registration failed: ${res.status}`);
  }
  return res.json();
}

export async function sendblueTest(
  apiKeyId: string,
  apiSecretKey: string,
  fromNumber: string,
  toNumber: string,
): Promise<{ sent: boolean; status: number }> {
  const res = await apiFetch(`/v1/channels/sendblue/test`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      api_key_id: apiKeyId,
      api_secret_key: apiSecretKey,
      from_number: fromNumber,
      to_number: toNumber,
    }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || `Test message failed: ${res.status}`);
  }
  return res.json();
}

export async function sendblueHealth(): Promise<{ channel_connected: boolean; bridge_wired: boolean; ready: boolean }> {
  const res = await apiFetch(`/v1/channels/sendblue/health`);
  if (!res.ok) return { channel_connected: false, bridge_wired: false, ready: false };
  return res.json();
}

export async function fetchTemplates(): Promise<AgentTemplate[]> {
  const res = await apiFetch(`/v1/templates`);
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
  const data = await res.json();
  return data.templates || [];
}

export async function runManagedAgent(agentId: string): Promise<void> {
  const res = await apiFetch(`/v1/managed-agents/${agentId}/run`, {
    method: 'POST',
    headers: timeZoneHeaders(),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(body.detail || `Failed: ${res.status}`);
  }
}

export async function recoverManagedAgent(agentId: string): Promise<{ recovered: boolean; checkpoint: unknown }> {
  const res = await apiFetch(`/v1/managed-agents/${agentId}/recover`, { method: 'POST' });
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(body.detail || `Failed: ${res.status}`);
  }
  return res.json();
}

export async function fetchAgentState(agentId: string): Promise<{
  agent: ManagedAgent;
  tasks: AgentTask[];
  channels: ChannelBinding[];
  messages: AgentMessage[];
  checkpoint: unknown;
}> {
  const res = await apiFetch(`/v1/managed-agents/${agentId}/state`);
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
  return res.json();
}

export interface AgentToolCallStart {
  tool: string;
  arguments: string;
}

export interface AgentToolCallEnd {
  tool: string;
  success: boolean;
  latency: number;
  result?: string;
}

export async function sendAgentMessage(
  agentId: string,
  content: string,
  mode: 'immediate' | 'queued' = 'queued',
  callbacks?: {
    onProgress?: (label: string) => void;
    onContentDelta?: (delta: string, fullContent: string) => void;
    onToolCallStart?: (info: AgentToolCallStart) => void;
    onToolCallEnd?: (info: AgentToolCallEnd) => void;
    onDone?: (fullContent: string, usage?: Record<string, number>, telemetry?: Record<string, unknown>) => void;
  },
): Promise<AgentMessage> {
  const res = await apiFetch(`/v1/managed-agents/${agentId}/messages`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...timeZoneHeaders() },
    body: JSON.stringify({ content, mode, stream: true }),
  });
  if (!res.ok) throw new Error(`Failed: ${res.status}`);

  // If streaming, consume the SSE response so the agent runs
  const contentType = res.headers.get('content-type') || '';
  if (contentType.includes('text/event-stream') && res.body) {
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let fullContent = '';
    let buffer = '';
    let lastUsage: Record<string, number> | undefined;
    let lastTelemetry: Record<string, unknown> | undefined;
    let currentEvent: string | undefined;
    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';
        for (const line of lines) {
          if (line.startsWith('event: ')) {
            currentEvent = line.slice(7).trim();
            continue;
          }
          if (!line.startsWith('data: ')) {
            if (line.trim() === '') currentEvent = undefined;
            continue;
          }
          const data = line.slice(6);
          if (data === '[DONE]') {
            currentEvent = undefined;
            continue;
          }
          const evName = currentEvent;
          currentEvent = undefined;

          if (evName === 'tool_call_start') {
            try {
              const parsed = JSON.parse(data);
              callbacks?.onToolCallStart?.({
                tool: parsed.tool,
                arguments: serializeToolCallArguments(parsed.arguments),
              });
            } catch {
              /* skip */
            }
            continue;
          }
          if (evName === 'tool_call_end') {
            try {
              const parsed = JSON.parse(data);
              callbacks?.onToolCallEnd?.({
                tool: parsed.tool,
                success: !!parsed.success,
                latency: typeof parsed.latency === 'number' ? parsed.latency : 0,
                result: parsed.result,
              });
            } catch {
              /* skip */
            }
            continue;
          }

          try {
            const chunk = JSON.parse(data);
            // Deep-research branch still uses tool_progress in a data chunk
            const toolProgress = chunk.choices?.[0]?.tool_progress;
            if (toolProgress) {
              callbacks?.onProgress?.(toolProgress);
            }
            const delta = chunk.choices?.[0]?.delta?.content || '';
            if (delta) {
              fullContent += delta;
              callbacks?.onContentDelta?.(delta, fullContent);
            }
            if (chunk.usage) lastUsage = chunk.usage;
            if (chunk.telemetry) lastTelemetry = chunk.telemetry;
          } catch {
            /* skip malformed chunks */
          }
        }
      }
    } catch { /* stream ended */ }

    callbacks?.onDone?.(fullContent, lastUsage, lastTelemetry);

    return {
      id: '',
      agent_id: agentId,
      direction: 'agent_to_user',
      content: fullContent,
      mode,
      status: 'delivered',
      created_at: Date.now() / 1000,
    };
  }

  return res.json();
}

/**
 * Ask the agent a question by triggering an ad-hoc run.
 *
 * Posts the question as an `immediate`, non-streamed message — the backend
 * stores it and spawns a real agent tick (`execute_tick`) that consumes it as
 * the run's input (tools, trace, and all), rather than a raw one-shot chat.
 * Returns immediately with the stored user message; progress is observed via
 * the `/v1/agents/events` WebSocket and the resulting trace.
 */
export async function askAgent(
  agentId: string,
  content: string,
  mode: AgentMessage['mode'] = 'immediate',
): Promise<AgentMessage> {
  const res = await apiFetch(`/v1/managed-agents/${agentId}/messages`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...timeZoneHeaders() },
    body: JSON.stringify({ content, mode, stream: false }),
  });
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
  return res.json();
}

export async function fetchAgentMessages(agentId: string): Promise<AgentMessage[]> {
  const res = await apiFetch(`/v1/managed-agents/${agentId}/messages`);
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
  const data = await res.json();
  return data.messages || [];
}

export async function fetchErrorAgents(): Promise<ManagedAgent[]> {
  const res = await apiFetch(`/v1/agents/errors`);
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
  const data = await res.json();
  return data.agents || [];
}

// ---------------------------------------------------------------------------
// Agent Learning + Traces
// ---------------------------------------------------------------------------

export interface LearningLogEntry {
  id: string;
  agent_id: string;
  event_type: string;
  description: string;
  data: Record<string, unknown>;
  created_at: number;
}

export interface AgentTrace {
  id: string;
  outcome: string;
  duration: number;
  started_at: number;
  steps: number;
  error_message?: string;
  metadata?: Record<string, unknown>;
}

export interface ToolInfo {
  name: string;
  description: string;
  category: string;
  source: 'tool' | 'channel';
  requires_credentials: boolean;
  credential_keys: string[];
  configured: boolean;
}

export async function fetchAvailableTools(): Promise<ToolInfo[]> {
  const res = await apiFetch(`/v1/tools`);
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
  const data = await res.json();
  return data.tools || [];
}

export async function saveToolCredentials(
  toolName: string,
  credentials: Record<string, string>,
): Promise<void> {
  const res = await apiFetch(`/v1/tools/${toolName}/credentials`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(credentials),
  });
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
}

export async function fetchToolCredentialStatus(
  toolName: string,
): Promise<Record<string, boolean>> {
  const res = await apiFetch(`/v1/tools/${toolName}/credentials/status`);
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
  return await res.json();
}

export async function deleteToolCredential(
  toolName: string,
  keyName: string,
): Promise<void> {
  const res = await apiFetch(
    `/v1/tools/${encodeURIComponent(toolName)}/credentials/${encodeURIComponent(keyName)}`,
    { method: 'DELETE' },
  );
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
}

export interface AgentTraceDetail {
  id: string;
  agent: string;
  outcome: string;
  duration: number;
  started_at: number;
  steps: Array<{
    step_type: string;
    input: unknown;
    output: string;
    duration: number;
    metadata: Record<string, unknown>;
  }>;
}

export async function fetchLearningLog(agentId: string): Promise<LearningLogEntry[]> {
  const res = await apiFetch(`/v1/managed-agents/${agentId}/learning`);
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
  const data = await res.json();
  return data.learning_log || [];
}

export async function triggerLearning(agentId: string): Promise<void> {
  const res = await apiFetch(`/v1/managed-agents/${agentId}/learning/run`, { method: 'POST' });
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
}

export async function fetchAgentTraces(agentId: string, limit = 20): Promise<AgentTrace[]> {
  const res = await apiFetch(`/v1/managed-agents/${agentId}/traces?limit=${limit}`);
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
  const data = await res.json();
  return data.traces || [];
}

export async function fetchAgentTrace(agentId: string, traceId: string): Promise<AgentTraceDetail> {
  const res = await apiFetch(`/v1/managed-agents/${agentId}/traces/${traceId}`);
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
  return res.json();
}

// ---------------------------------------------------------------------------
// Leaderboard savings submission (Supabase)
// ---------------------------------------------------------------------------

export interface SavingsSubmission {
  anon_id: string;
  display_name: string;
  email: string;
  total_calls: number;
  total_tokens: number;
  dollar_savings: number;
  energy_wh_saved: number;
  flops_saved: number;
  token_counting_version?: number;
}

export async function submitSavings(data: SavingsSubmission): Promise<boolean> {
  if (!SUPABASE_URL || !SUPABASE_ANON_KEY) return false;
  try {
    const res = await fetch(
      `${SUPABASE_URL}/rest/v1/savings_entries?on_conflict=anon_id`,
      {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          apikey: SUPABASE_ANON_KEY,
          Authorization: `Bearer ${SUPABASE_ANON_KEY}`,
          Prefer: 'resolution=merge-duplicates',
        },
        body: JSON.stringify(data),
      },
    );
    return res.ok || res.status === 201 || res.status === 200;
  } catch {
    return false;
  }
}

// ---------------------------------------------------------------------------
// Memory
// ---------------------------------------------------------------------------

export interface MemorySearchResult {
  content: string;
  score: number;
  metadata: Record<string, unknown>;
}

export interface MemoryStats {
  entries: number;
  backend: string;
  [key: string]: unknown;
}

export interface MemoryConfig {
  backend: string;
  // Set by the server when the native `openjarvis_rust` extension is missing,
  // so the UI can show the real cause instead of a healthy-looking config.
  available?: boolean;
  detail?: string | null;
  context_from_memory: boolean;
  context_top_k: number;
  context_min_score: number;
  context_max_tokens: number;
}

/**
 * Extract the server's `detail` message from a failed JSON response so the UI
 * surfaces the real cause (e.g. "openjarvis_rust extension is not installed")
 * instead of a blanket fallback string (#502).
 */
async function memoryErrorDetail(res: Response, fallback: string): Promise<string> {
  try {
    const data = await res.json();
    if (data && typeof data.detail === 'string' && data.detail) return data.detail;
  } catch {
    // Non-JSON body — fall through to the generic message below.
  }
  return fallback;
}

export async function getMemoryStats(): Promise<MemoryStats> {
  let res: Response;
  try {
    res = await apiFetch(`/v1/memory/stats`);
  } catch {
    throw new Error('Could not reach the OpenJarvis API. Check the server status and API URL, then retry.');
  }
  if (!res.ok) {
    const detail = await memoryErrorDetail(res, 'Memory status request failed');
    throw new Error(`${detail} (HTTP ${res.status})`);
  }
  return res.json();
}

export async function searchMemory(query: string, topK: number = 5): Promise<MemorySearchResult[]> {
  const res = await apiFetch(`/v1/memory/search`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query, top_k: topK }),
  });
  if (!res.ok) throw new Error('Failed to search memory');
  const data = await res.json();
  return data.results;
}

export async function storeMemory(content: string, metadata?: Record<string, unknown>): Promise<void> {
  const res = await apiFetch(`/v1/memory/store`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ content, metadata }),
  });
  if (!res.ok) throw new Error(await memoryErrorDetail(res, 'Failed to store memory'));
}

export async function indexMemoryPath(path: string): Promise<{ chunks_indexed: number; note?: string }> {
  const res = await apiFetch(`/v1/memory/index`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path }),
  });
  if (!res.ok) throw new Error(await memoryErrorDetail(res, 'Failed to index path'));
  return res.json();
}

export async function getMemoryConfig(): Promise<MemoryConfig> {
  const res = await apiFetch(`/v1/memory/config`);
  if (!res.ok) throw new Error('Failed to fetch memory config');
  return res.json();
}

// ---------------------------------------------------------------------------
// Approvals
// ---------------------------------------------------------------------------

export interface PendingApproval {
  id: string;
  action_type: string;
  description: string;
  payload: Record<string, unknown>;
  permission_key: string;
  tier: 'trivial' | 'low' | 'medium' | 'high';
  status: string;
  created_at: string;
  expires_at: string;
}

export async function fetchPendingApprovals(): Promise<PendingApproval[]> {
  const res = await apiFetch(`/v1/approvals/pending`);
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
  const data = await res.json();
  return data.actions || [];
}

export class ApprovalDecisionError extends Error {
  constructor(readonly status: number, message: string) {
    super(message);
  }
}

async function decideApproval(actionId: string, decision: 'approve' | 'deny'): Promise<void> {
  const res = await apiFetch(`/v1/approvals/${encodeURIComponent(actionId)}/${decision}`, { method: 'POST' });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new ApprovalDecisionError(res.status, typeof body?.detail === 'string'
      ? body.detail : `Could not record the decision (${res.status}).`);
  }
}

export async function approveAction(actionId: string): Promise<void> {
  await decideApproval(actionId, 'approve');
}

export async function denyAction(actionId: string): Promise<void> {
  await decideApproval(actionId, 'deny');
}

// ---------------------------------------------------------------------------
// Durable workflows
// ---------------------------------------------------------------------------

export type WorkflowRunStatus = 'scheduled' | 'queued' | 'running' | 'waiting_approval' | 'succeeded' | 'failed' | 'cancelled' | 'interrupted';

export interface WorkflowRunSummary {
  id: string;
  workflow_name: string;
  status: WorkflowRunStatus;
  final_output: string;
  error: string;
  parent_run_id: string | null;
  cancel_requested: boolean;
  created_at: number;
  scheduled_at?: number | null;
  started_at: number | null;
  finished_at: number | null;
}

export interface WorkflowRunInput {
  name: string;
  nodes: Array<Record<string, unknown>>;
  edges?: Array<Record<string, unknown>>;
  initial_input?: string;
  context?: Record<string, unknown>;
}

export async function fetchGmailReviewCount(signal?: AbortSignal): Promise<number | null> {
  const response = await apiFetch('/v1/dashboard/gmail-review', { signal });
  if (!response.ok) throw new Error('Gmail index unavailable.');
  const { threads_to_review } = await response.json();
  if (threads_to_review === null || Number.isInteger(threads_to_review)) return threads_to_review;
  throw new Error('Gmail index unavailable.');
}

export type GmailReviewCandidate = {
  id: string;
  message_id: string | null;
  subject: string;
  sender: string | null;
  received_at: string;
};

export async function fetchGmailReviewCandidates(signal?: AbortSignal): Promise<GmailReviewCandidate[]> {
  const response = await apiFetch('/v1/dashboard/gmail-review/candidates', { signal });
  if (!response.ok) throw new Error('Gmail index unavailable.');
  const { candidates } = await response.json();
  if (!Array.isArray(candidates)) throw new Error('Gmail index unavailable.');
  return candidates;
}

export type SavedLead = {
  id: string;
  organization: string;
  source_reference: string;
  created_at: number;
  workflow_run_id?: string | null;
};

export async function fetchSavedLeads(signal?: AbortSignal): Promise<SavedLead[]> {
  const response = await apiFetch('/v1/leads', { signal });
  if (!response.ok) throw new Error('Lead register unavailable.');
  const { leads } = await response.json();
  return leads;
}

export async function fetchLeadCount(signal?: AbortSignal): Promise<number> {
  const response = await apiFetch('/v1/leads/summary', { signal });
  if (!response.ok) throw new Error('Lead register unavailable.');
  const { count } = await response.json();
  if (!Number.isInteger(count)) throw new Error('Lead register unavailable.');
  return count;
}

export async function saveLead(
  organization: string, sourceReference: string, workflowRunId?: string,
): Promise<SavedLead> {
  const response = await apiFetch('/v1/leads', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ organization, source_reference: sourceReference, workflow_run_id: workflowRunId }),
  });
  if (!response.ok) {
    const result = await response.json().catch(() => null);
    throw new Error(typeof result?.detail === 'string' ? result.detail : 'Could not save lead.');
  }
  return response.json();
}

export type Ga4PropertySettings = {
  property_id: string;
  environment_override: boolean;
};

export async function fetchGa4Property(signal?: AbortSignal): Promise<Ga4PropertySettings> {
  const response = await apiFetch('/v1/dashboard/ga4-settings', { signal });
  if (!response.ok) throw new Error('GA4 settings unavailable.');
  return response.json();
}

export async function saveGa4Property(propertyId: string): Promise<Ga4PropertySettings> {
  const response = await apiFetch('/v1/dashboard/ga4-settings', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ property_id: propertyId }),
  });
  if (!response.ok) {
    const result = await response.json().catch(() => null);
    throw new Error(typeof result?.detail === 'string' ? result.detail : 'Could not save GA4 property.');
  }
  return response.json();
}

export async function removeGa4Authorization(): Promise<void> {
  const response = await apiFetch('/v1/dashboard/ga4-authorization', { method: 'DELETE' });
  if (!response.ok) throw new Error('Could not remove saved GA4 authorization.');
}

export type Ga4Views = {
  status: 'unconfigured' | 'invalid_property' | 'authorization_required' | 'unavailable' | 'live';
  views: number | null;
};

export async function fetchGa4Views(signal?: AbortSignal): Promise<Ga4Views> {
  const response = await apiFetch('/v1/dashboard/ga4-views', { signal });
  if (!response.ok) throw new Error('Google Analytics unavailable.');
  const result = await response.json();
  if (!result || typeof result.status !== 'string') throw new Error('Google Analytics unavailable.');
  return result;
}

export type IndexedCalendarEvent = {
  id: string;
  title: string;
  starts_at: string;
  all_day_date: string | null;
};

export async function fetchIndexedCalendarEvents(localDay: string): Promise<IndexedCalendarEvent[]> {
  const response = await apiFetch(`/v1/dashboard/calendar?local_day=${encodeURIComponent(localDay)}`);
  if (!response.ok) throw new Error(`Calendar request failed (${response.status}).`);
  const data = await response.json();
  return data.events ?? [];
}

export async function fetchWorkflowRuns(status?: WorkflowRunStatus): Promise<WorkflowRunSummary[]> {
  const query = status ? `&status=${encodeURIComponent(status)}` : '';
  const res = await apiFetch(`/v1/workflows/runs?limit=8${query}`);
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
  const data = await res.json();
  return data.runs || [];
}

export async function fetchWorkflowHistory(before: string, status: WorkflowRunStatus | ''): Promise<{
  runs: WorkflowRunSummary[];
  supportsPaging: boolean;
}> {
  const query = new URLSearchParams({ limit: '6', recent: 'true' });
  if (status) query.set('status', status);
  if (before) query.set('before', before);
  const response = await apiFetch(`/v1/workflows/runs?${query}`);
  if (!response.ok) throw new Error('Workflow history unavailable.');
  const page = await response.json();
  if (!Array.isArray(page.runs) || (before && page.before !== before)) {
    throw new Error('Workflow history paging is unavailable on this backend.');
  }
  return { runs: page.runs, supportsPaging: page.before === before && (status !== 'scheduled' || page.recent === true) };
}

export interface WorkflowRunDetail extends WorkflowRunSummary {
  initial_input: string;
  graph: SavedWorkflowDefinition['graph'];
  steps: Array<{
    node_id: string;
    attempt: number;
    success: boolean;
    output: string;
    duration_seconds?: number;
    created_at?: number;
    metadata: Record<string, unknown>;
  }>;
}

export async function fetchWorkflowRun(id: string, signal?: AbortSignal): Promise<WorkflowRunDetail> {
  const res = await apiFetch(`/v1/workflows/runs/${encodeURIComponent(id)}`, { signal });
  if (!res.ok) throw new Error(`Failed to load run details (${res.status}).`);
  return res.json();
}

export async function rescheduleWorkflowRun(
  id: string, scheduledAt: number, expectedScheduledAt: number,
): Promise<WorkflowRunDetail> {
  const response = await apiFetch(`/v1/workflows/runs/${encodeURIComponent(id)}/schedule`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ scheduled_at: scheduledAt, expected_scheduled_at: expectedScheduledAt }),
  });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(typeof body?.detail === 'string' ? body.detail : `Could not reschedule (${response.status}).`);
  }
  return response.json();
}

export type WorkflowRunAction = 'cancel' | 'retry' | 'resume';

export async function requestWorkflowRunAction(
  id: string,
  action: WorkflowRunAction,
  retryInput?: string,
  retryKey?: string,
): Promise<WorkflowRunSummary | undefined> {
  const editedRetry = action === 'retry' && retryInput !== undefined;
  const endpoint = editedRetry ? 'retry-with-input' : action;
  const res = await apiFetch(`/v1/workflows/runs/${encodeURIComponent(id)}/${endpoint}`, {
    method: 'POST',
    headers: {
      ...(editedRetry ? { 'Content-Type': 'application/json' } : {}),
      ...(retryKey ? { 'Idempotency-Key': retryKey } : {}),
    },
    ...(editedRetry ? { body: JSON.stringify({ initial_input: retryInput }) } : {}),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(typeof body?.detail === 'string'
      ? body.detail : `Workflow action failed (${res.status}).`);
  }
  if (action === 'retry') return res.json();
}

export interface SavedWorkflowDefinition {
  id: string;
  revision?: string;
  graph: Pick<WorkflowRunInput, 'name' | 'nodes' | 'edges'>;
}

export async function saveWorkflowDefinition(
  definition: Pick<WorkflowRunInput, 'name' | 'nodes' | 'edges'>,
  definitionId?: string,
  expectedRevision?: string,
): Promise<SavedWorkflowDefinition> {
  const path = '/v1/workflows/definitions';
  const res = await apiFetch(definitionId ? `${path}/${encodeURIComponent(definitionId)}` : path, {
    method: definitionId ? 'PUT' : 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ...definition, expected_revision: expectedRevision }),
  });
  if (!res.ok) {
    if (definitionId && res.status === 405) {
      throw new Error('This backend does not support saving workflow edits in place. Update the backend or use Save as copy.');
    }
    const body = await res.json().catch(() => null);
    throw new Error(typeof body?.detail === 'string'
      ? body.detail : `Failed to save workflow (${res.status}).`);
  }
  return res.json();
}

export async function fetchWorkflowDefinitions(): Promise<SavedWorkflowDefinition[]> {
  const res = await apiFetch('/v1/workflows/definitions');
  if (!res.ok) throw new Error(`Failed to load saved workflows (${res.status}).`);
  const data = await res.json();
  return data.definitions;
}

export async function fetchWorkflowDefinition(id: string): Promise<SavedWorkflowDefinition> {
  const res = await apiFetch(`/v1/workflows/definitions/${encodeURIComponent(id)}`);
  if (!res.ok) throw new Error(`Failed to load saved workflow (${res.status}).`);
  return res.json();
}

export async function runSavedWorkflow(
  id: string, initialInput: string, launchKey?: string, scheduledAt?: number,
): Promise<WorkflowRunSummary> {
  const action = scheduledAt === undefined ? 'runs' : 'schedule';
  const res = await apiFetch(`/v1/workflows/definitions/${encodeURIComponent(id)}/${action}`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(launchKey ? { 'Idempotency-Key': launchKey } : {}),
    },
    body: JSON.stringify({ initial_input: initialInput, scheduled_at: scheduledAt }),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(typeof body?.detail === 'string'
      ? body.detail : `Failed to start saved workflow (${res.status}).`);
  }
  return res.json();
}

export async function startWorkflowRun(input: WorkflowRunInput): Promise<WorkflowRunSummary> {
  const res = await apiFetch('/v1/workflows/runs', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(typeof body?.detail === 'string'
      ? body.detail : `Failed to start workflow (${res.status}).`);
  }
  return res.json();
}

// ---------------------------------------------------------------------------
// Inference source (desktop only)
// ---------------------------------------------------------------------------

export type InferenceSource = {
  kind: 'ollama' | 'custom';
  model?: string;
  host?: string;
  engine?: string;
};

export async function getInferenceSource(): Promise<InferenceSource> {
  if (isTauri()) {
    try {
      const { invoke } = await import('@tauri-apps/api/core');
      return await invoke<InferenceSource>('get_inference_source');
    } catch (e: any) {
      throw new Error(e?.message ?? e ?? 'Failed to read inference source');
    }
  }
  return { kind: 'ollama' };
}

export async function setInferenceSource(
  src: InferenceSource & { apiKey?: string },
  options: { pending?: boolean } = {},
): Promise<void> {
  if (!isTauri()) throw new Error('Inference source is configurable in the desktop app only.');
  try {
    const { invoke } = await import('@tauri-apps/api/core');
    await invoke<void>('set_inference_source', {
      kind: src.kind,
      model: src.model ?? null,
      host: src.host ?? null,
      engine: src.engine ?? null,
      apiKey: src.apiKey ?? null,
      pending: options.pending ?? null,
    });
  } catch (e: any) {
    // Surface the backend's actionable error strings (e.g. "A server URL is
    // required…", "Could not store the API key…") as proper Error instances.
    throw new Error(e?.message ?? e ?? 'Failed to save inference source');
  }
}

/** Stage a first-run choice; Rust confirms it only after backend readiness. */
export const stageInferenceSource = (
  src: InferenceSource & { apiKey?: string },
): Promise<void> => setInferenceSource(src, { pending: true });
