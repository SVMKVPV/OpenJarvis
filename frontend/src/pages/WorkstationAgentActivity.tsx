import { useEffect, useState } from 'react';
import { fetchManagedAgents, type ManagedAgent } from '../lib/api';

export function WorkstationAgentActivity({
  agentId,
  onSelect,
}: {
  agentId: string;
  onSelect: (id: string) => void;
}) {
  const [agents, setAgents] = useState<ManagedAgent[] | null>(null);
  const [unavailable, setUnavailable] = useState(false);

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
  }, []);

  const selected = agents?.find((agent) => agent.id === agentId);
  return (
    <section className="station-details-editor" aria-label="Managed agent activity">
      <label>
        Managed agent
        <select value={agentId} onChange={(event) => onSelect(event.target.value)}>
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
