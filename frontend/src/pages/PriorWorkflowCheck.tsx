import { useEffect, useRef, useState } from 'react';
import { fetchSystemBuilderProposals, fetchWorkflowReviewRuns, type WorkflowRunSummary } from '../lib/api';

type CheckResult =
  | { status: 'idle' | 'loading' | 'unavailable' }
  | { status: 'checked'; runs: WorkflowRunSummary[] };

export function PriorWorkflowCheck({ query, kind, onOpenRun }: {
  query: string;
  kind: 'research' | 'project-draft';
  onOpenRun: (id: string) => void;
}) {
  const [result, setResult] = useState<CheckResult>({ status: 'idle' });
  const pending = useRef<AbortController | null>(null);
  const projectDraft = kind === 'project-draft';
  useEffect(() => () => pending.current?.abort(), []);

  const check = async () => {
    pending.current?.abort();
    const request = new AbortController();
    pending.current = request;
    setResult({ status: 'loading' });
    try {
      const runs = projectDraft
        ? await fetchWorkflowReviewRuns(request.signal, 'project_contribution_review', { projectTaskId: query })
        : await fetchSystemBuilderProposals(request.signal, query);
      if (!request.signal.aborted) setResult({ status: 'checked', runs });
    } catch {
      if (!request.signal.aborted) setResult({ status: 'unavailable' });
    }
  };

  return <fieldset>
    <legend>{projectDraft ? 'AI drafts for this task' : 'Prior System Builder research'}</legend>
    <button type="button" disabled={!query || query.length > (projectDraft ? 128 : 200) || result.status === 'loading'}
      onClick={() => void check()}>
      {result.status === 'loading' ? 'Checking prior runs…' : projectDraft ? 'Check prior AI drafts' : 'Check for prior runs'}
    </button>
    {!projectDraft && query.length > 200 && <small>Use a shorter phrase in the System Builder history search.</small>}
    {result.status === 'unavailable' && <small role="status">Prior runs are unavailable. Try again.</small>}
    {result.status === 'checked' && (result.runs.length ? (
      <>
        <small role="status">{projectDraft ? 'Review existing drafts before starting another run.'
          : 'This brief appears in prior runs. Review them before starting again.'}</small>
        <ul>
          {result.runs.map((run) => (
            <li key={run.id}>
              <button type="button" onClick={() => onOpenRun(run.id)}>
                Open {run.workflow_name} run {run.id.slice(0, 8)}
              </button>
              <small>{run.status.replace(/_/g, ' ')} · {new Date(run.created_at * 1000).toLocaleString()}</small>
            </li>
          ))}
        </ul>
      </>
    ) : <small role="status">{projectDraft ? 'No AI drafts found for this task.' : 'No prior runs contain this brief.'}</small>)}
  </fieldset>;
}
