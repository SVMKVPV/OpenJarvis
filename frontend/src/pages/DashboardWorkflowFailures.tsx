import { useEffect, useState } from 'react';
import { fetchWorkflowRuns, type WorkflowRunSummary } from '../lib/api';

export function DashboardWorkflowFailures({ onOpen }: { onOpen: (runId: string) => void }) {
  const [runs, setRuns] = useState<WorkflowRunSummary[]>([]);
  const [message, setMessage] = useState('Checking workflow history…');

  useEffect(() => {
    const controller = new AbortController();
    let timer: number | undefined;

    const refresh = async () => {
      try {
        const [failed, interrupted] = await Promise.all([
          fetchWorkflowRuns('failed', controller.signal),
          fetchWorkflowRuns('interrupted', controller.signal),
        ]);
        if (controller.signal.aborted) return;
        const recent = [...failed, ...interrupted].sort((a, b) => b.created_at - a.created_at);
        setRuns(recent.slice(0, 4));
        setMessage(recent.length ? '' : 'No recent failed or interrupted runs.');
      } catch {
        if (controller.signal.aborted) return;
        setRuns([]);
        setMessage('Workflow history unavailable.');
      } finally {
        if (!controller.signal.aborted) timer = window.setTimeout(() => void refresh(), 15000);
      }
    };

    void refresh();
    return () => {
      controller.abort();
      window.clearTimeout(timer);
    };
  }, []);

  return <>
    {message && <p role="status">{message}</p>}
    {!!runs.length && <ul className="dashboard-workflow-calendar" aria-label="Recent failed or interrupted workflows">
      {runs.map((run) => (
        <li key={run.id}>
          <button type="button" onClick={() => onOpen(run.id)}>
            <strong>{run.workflow_name}</strong>
            <small>{run.status === 'interrupted' ? 'Interrupted' : 'Failed'} · {new Date(run.created_at * 1000).toLocaleString()}</small>
          </button>
        </li>
      ))}
    </ul>}
  </>;
}
