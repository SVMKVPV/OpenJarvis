import { useEffect, useState } from 'react';
import { fetchManagedAgents, runManagedAgent, type ManagedAgent } from '../lib/api';

export function WorkstationAgentActivity({
  agentId,
  onSelect,
}: {
  agentId: string;
  onSelect: (id: string) => void;
}) {
  const [agents, setAgents] = useState<ManagedAgent[] | null>(null);
  const [unavailable, setUnavailable] = useState(false);
  const [refreshVersion, setRefreshVersion] = useState(0);
  const [starting, setStarting] = useState(false);
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
  const startRun = async () => {
    if (!selected || unavailable || starting || selected.status !== 'idle') return;
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
  return (
    <section className="station-details-editor" aria-label="Managed agent activity">
      <label>
        Managed agent
        <select value={agentId} onChange={(event) => {
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
      {!unavailable && agents?.length === 0 && <p>Create a managed agent in Agents to link it here.</p>}
      {!unavailable && selected && (
        <div>
          <p>Status: {selected.status.replace(/_/g, ' ')}</p>
          <p>{selected.current_activity || 'No active task reported.'}</p>
          <button type="button" disabled={starting || selected.status !== 'idle'}
            onClick={() => void startRun()}>
            {starting ? 'Starting…' : 'Run linked agent'}
          </button>
          {runMessage?.id === selected.id && <p role="status">{runMessage.text}</p>}
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
