import { useEffect, useState } from 'react';
import {
  createManagedAgent, fetchManagedAgents, fetchTemplates, recoverManagedAgent, refreshManagedAgentTemplatePrompt, runManagedAgent, updateManagedAgent, type ManagedAgent,
} from '../lib/api';
import { isEmbedOnlyModel } from '../lib/model-capabilities';
import { useAppStore } from '../lib/store';
import { WorkstationAgentInbox } from './WorkstationAgentInbox';

export function WorkstationAgentActivity({
  agentId,
  stationName,
  templateId,
  brainContext,
  onShare,
  onSelect,
  onOpenWorkflow,
}: {
  agentId: string;
  stationName: string;
  templateId?: string;
  brainContext: string;
  onShare: (text: string) => string;
  onSelect: (id: string) => void;
  onOpenWorkflow: (runId: string) => void;
}) {
  const [agents, setAgents] = useState<ManagedAgent[] | null>(null);
  const [unavailable, setUnavailable] = useState(false);
  const [refreshVersion, setRefreshVersion] = useState(0);
  const [starting, setStarting] = useState(false);
  const [recovering, setRecovering] = useState(false);
  const [savingOption, setSavingOption] = useState(false);
  const [optionMessage, setOptionMessage] = useState<{ id: string; text: string } | null>(null);
  const models = useAppStore((state) => state.models);
  const [creating, setCreating] = useState(false);
  const [creationError, setCreationError] = useState('');
  const [runMessage, setRunMessage] = useState<{ id: string; text: string } | null>(null);

  useEffect(() => {
    let active = true;
    let timer: number | undefined;
    const refresh = async () => {
      try {
        const items = await fetchManagedAgents();
        if (active) {
          setAgents(items.filter((item) => item.status !== 'archived'));
          setUnavailable(false);
        }
      } catch {
        if (active) setUnavailable(true);
      } finally {
        if (active) timer = window.setTimeout(() => void refresh(), 10000);
      }
    };
    void refresh();
    return () => {
      active = false;
      window.clearTimeout(timer);
    };
  }, [refreshVersion]);

  const selected = agents?.find((agent) => agent.id === agentId);
  const model = typeof selected?.config?.model === 'string' ? selected.config.model : '';
  const modelIds = [...new Set(models.map((item) => item.id).filter((id) => !isEmbedOnlyModel(id)))];
  const useSharedBrain = selected?.config?.use_shared_brain === true;
  const saveAgentOption = async (option: { model: string } | { use_shared_brain: boolean }) => {
    if (!selected || savingOption || starting || recovering) return;
    setSavingOption(true);
    setOptionMessage(null);
    try {
      const updated = await updateManagedAgent(selected.id, option);
      const saved = 'model' in option
        ? (updated.config?.model ?? '') === option.model
        : updated.config?.use_shared_brain === option.use_shared_brain;
      if (!saved) throw new Error('This backend did not save the setting. Update the backend and try again.');
      setAgents((current) => current?.map((agent) => agent.id === updated.id ? updated : agent) ?? null);
      setOptionMessage({ id: selected.id, text: 'Agent setting saved.' });
    } catch (error) {
      setOptionMessage({ id: selected.id, text: error instanceof Error ? error.message : 'Could not save the agent setting.' });
    } finally {
      setSavingOption(false);
      setRefreshVersion((version) => version + 1);
    }
  };
  const canRecover = selected && ['error', 'stalled', 'needs_attention'].includes(selected.status);
  const createRoleAgent = async () => {
    if (!templateId || agentId || creating || unavailable || agents === null) return;
    setCreating(true);
    setCreationError('');
    try {
      const templates = await fetchTemplates().catch(() => {
        throw new Error('Could not check role templates. Verify the backend connection and try again.');
      });
      if (!templates.some((template) => template.id === templateId)) {
        setCreationError('This backend does not offer this workstation’s role template. Update the backend or link an existing agent.');
        return;
      }
      const agent = await createManagedAgent({
        name: stationName,
        template_id: templateId,
        config: { schedule_type: 'manual', schedule_value: '' },
      });
      setAgents((current) => [agent, ...(current ?? []).filter((item) => item.id !== agent.id)]);
      onSelect(agent.id);
      setRefreshVersion((version) => version + 1);
    } catch (error) {
      setCreationError(error instanceof Error ? error.message : 'Could not create the role agent.');
    } finally {
      setCreating(false);
    }
  };

  const refreshRolePrompt = async () => {
    if (!selected || !templateId || unavailable || savingOption || starting || recovering ||
        selected.status === 'running') return;
    setSavingOption(true);
    setOptionMessage(null);
    try {
      const updated = await refreshManagedAgentTemplatePrompt(selected.id, templateId);
      setAgents((current) => current?.map((agent) => agent.id === updated.id ? updated : agent) ?? null);
      setOptionMessage({ id: selected.id, text: 'Role prompt refreshed.' });
    } catch (error) {
      setOptionMessage({ id: selected.id, text: error instanceof Error ? error.message : 'Could not refresh the role prompt.' });
    } finally {
      setSavingOption(false);
    }
  };

  const startRun = async () => {
    if (!selected || unavailable || starting || recovering || selected.status !== 'idle') return;
    setStarting(true);
    setRunMessage(null);
    try {
      await runManagedAgent(selected.id);
      setAgents((current) => current?.map((agent) => agent.id === selected.id
        ? { ...agent, status: 'running' }
        : agent) ?? null);
      setRunMessage({ id: selected.id, text: 'Run started.' });
    } catch (error) {
      setRunMessage({
        id: selected.id,
        text: error instanceof Error ? error.message : 'Could not start the agent.',
      });
    } finally {
      setStarting(false);
      setRefreshVersion((version) => version + 1);
    }
  };
  const recover = async () => {
    if (!selected || !canRecover || unavailable || starting || recovering) return;
    setRecovering(true);
    setRunMessage(null);
    try {
      await recoverManagedAgent(selected.id);
      setRunMessage({ id: selected.id, text: 'Agent reset. Select Run linked agent to start a new run.' });
    } catch (error) {
      setRunMessage({ id: selected.id, text: error instanceof Error ? error.message : 'Could not recover the agent.' });
    } finally {
      setRecovering(false);
      setRefreshVersion((version) => version + 1);
    }
  };
  return (
    <section className="station-details-editor" aria-label="Managed agent activity">
      <label>
        Managed agent
        <select value={agentId} disabled={creating} onChange={(event) => {
          setRunMessage(null);
          onSelect(event.target.value);
        }}>
          <option value="">No agent linked</option>
          {agentId && !selected && <option value={agentId}>Linked agent unavailable</option>}
          {agents?.map((agent) => <option key={agent.id} value={agent.id}>{agent.name}</option>)}
        </select>
      </label>
      {unavailable && <p role="status">Live agent activity unavailable.</p>}
      {!unavailable && agents === null && <p role="status">Loading agents…</p>}
      {!unavailable && agents !== null && !agentId && templateId && (
        <button type="button" disabled={creating} onClick={() => void createRoleAgent()}>
          {creating ? 'Creating agent…' : 'Create and link manual agent'}
        </button>
      )}
      {creationError && <p role="status">{creationError}</p>}
      {!unavailable && !templateId && agents?.length === 0 && <p>Create a managed agent in Agents to link it here.</p>}
      {!unavailable && selected && (
        <div>
          <label>
            Linked agent model
            <select value={model} disabled={savingOption || starting || recovering || selected.status === 'running'}
              onChange={(event) => void saveAgentOption({ model: event.target.value })}>
              <option value="">Backend default</option>
              {model && !modelIds.includes(model) && <option value={model}>{model} (configured)</option>}
              {modelIds.map((id) => <option key={id} value={id}>{id}</option>)}
            </select>
          </label>
          <label>
            <input type="checkbox" checked={useSharedBrain}
              disabled={savingOption || starting || recovering || selected.status === 'running'}
              onChange={(event) => void saveAgentOption({ use_shared_brain: event.target.checked })} />
            Include the saved Shared Brain brief in agent runs
          </label>
          {useSharedBrain && <small>The brief is sent to the model used by this agent.</small>}
          {templateId && (
            <details>
              <summary>Refresh role prompt</summary>
              <p>Replace this agent’s current prompt with the workstation template. The agent keeps its history and other settings.</p>
              <button type="button" disabled={savingOption || starting || recovering || selected.status === 'running'}
                onClick={() => void refreshRolePrompt()}>Apply latest role prompt</button>
            </details>
          )}
          {optionMessage?.id === selected.id && <p role="status">{optionMessage.text}</p>}
          <p>Status: {selected.status.replace(/_/g, ' ')}</p>
          <p>{selected.current_activity || 'No active task reported.'}</p>
          <button type="button" disabled={starting || recovering || savingOption || selected.status !== 'idle'}
            onClick={() => void startRun()}>
            {starting ? 'Starting…' : 'Run linked agent'}
          </button>
          {canRecover && (
            <button type="button" disabled={starting || recovering} onClick={() => void recover()}>
              {recovering ? 'Recovering…' : 'Recover linked agent'}
            </button>
          )}
          {runMessage?.id === selected.id && <p role="status">{runMessage.text}</p>}
          <WorkstationAgentInbox key={selected.id} agentId={selected.id}
            brainContext={brainContext} onShare={onShare} onOpenWorkflow={onOpenWorkflow} />
          {selected.summary_memory && (
            <details>
              <summary>Latest agent summary</summary>
              <p>{selected.summary_memory}</p>
            </details>
          )}
        </div>
      )}
    </section>
  );
}
