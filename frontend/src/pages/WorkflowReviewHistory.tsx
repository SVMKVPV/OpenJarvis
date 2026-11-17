import { useEffect, useState } from 'react';
import { fetchWorkflowReviewRuns, type WorkflowRunSummary } from '../lib/api';
import './system-builder-lab.css';

const COPY = {
  builder: {
    approvalType: 'system_builder_proposal',
    legacyNode: '',
    title: 'Recent proposal runs',
    search: 'Search research briefs',
    loading: 'Loading proposal history.',
    noMatches: 'No proposal runs match that brief.',
    empty: 'No System Builder proposal runs yet.',
  },
  finance: {
    approvalType: 'finance_workpaper_review',
    legacyNode: 'finance-review',
    title: 'Recent workpaper runs',
    search: 'Search workpaper inputs',
    loading: 'Loading workpaper history.',
    noMatches: 'No workpaper runs match that search.',
    empty: 'No Finance workpaper runs yet.',
  },
  email: {
    approvalType: 'gmail_reply_review',
    legacyNode: 'review-reply',
    title: 'Recent reply reviews',
    search: 'Search reply inputs',
    loading: 'Loading reply review history.',
    noMatches: 'No reply reviews match that search.',
    empty: 'No Gmail reply reviews yet.',
  },
  delivery: {
    approvalType: 'delivery_quality_review',
    legacyNode: 'handoff-review',
    title: 'Recent delivery reviews',
    search: 'Search delivery inputs',
    loading: 'Loading delivery review history.',
    noMatches: 'No delivery reviews match that search.',
    empty: 'No delivery quality reviews yet.',
  },
  growth: {
    approvalType: 'lead_discovery_review',
    legacyNode: 'lead-review',
    title: 'Recent lead reviews',
    search: 'Search lead inputs',
    loading: 'Loading lead review history.',
    noMatches: 'No lead reviews match that search.',
    empty: 'No lead discovery reviews yet.',
  },
  research: {
    approvalType: 'competitor_ad_review',
    legacyNode: 'ad-review',
    title: 'Recent competitor ad reviews',
    search: 'Search competitor ad inputs',
    loading: 'Loading competitor ad review history.',
    noMatches: 'No competitor ad reviews match that search.',
    empty: 'No competitor ad reviews yet.',
  },
};

type ReviewHistory =
  | { status: 'loading' | 'unavailable' }
  | { status: 'loaded'; runs: Array<WorkflowRunSummary & { initial_input?: string }> };

export function WorkflowReviewHistory({ kind, onOpenWorkflow }: {
  kind: keyof typeof COPY;
  onOpenWorkflow: (runId: string) => void;
}) {
  const copy = COPY[kind];
  const [history, setHistory] = useState<ReviewHistory>({ status: 'loading' });
  const [searchInput, setSearchInput] = useState('');
  const [search, setSearch] = useState('');
  const [refresh, setRefresh] = useState(0);

  useEffect(() => {
    const request = new AbortController();
    fetchWorkflowReviewRuns(request.signal, copy.approvalType, {
      inputContains: search, legacyApprovalNode: copy.legacyNode,
    }).then(
      (runs) => {
        if (!request.signal.aborted) setHistory({ status: 'loaded', runs });
      },
      () => {
        if (!request.signal.aborted) setHistory({ status: 'unavailable' });
      },
    );
    return () => request.abort();
  }, [copy, refresh, search]);

  const reload = () => {
    setHistory({ status: 'loading' });
    setRefresh((value) => value + 1);
  };

  return <section className="builder-lab" aria-label={copy.title}>
    <header>
      <strong>{copy.title}</strong>
      <button type="button" onClick={reload} disabled={history.status === 'loading'}>Refresh</button>
    </header>
    <form className="builder-search" onSubmit={(event) => {
      event.preventDefault();
      setSearch(searchInput.trim());
      reload();
    }}>
      <label>{copy.search}
        <input type="search" maxLength={200}
          value={searchInput} onChange={(event) => setSearchInput(event.target.value)} />
      </label>
      <button type="submit">Search</button>
      {search && <button type="button" onClick={() => {
        setSearchInput('');
        setSearch('');
        reload();
      }}>Clear search</button>}
    </form>
    {history.status === 'loading' && <p role="status">{copy.loading}</p>}
    {history.status === 'unavailable' && <p role="status">Review history is unavailable. Check the backend and refresh.</p>}
    {history.status === 'loaded' && (
      history.runs.length ? (
        <div className="builder-ideas">
          {history.runs.map((run) => (
            <article key={run.id}>
              <div>
                <span>{new Date(run.created_at * 1000).toLocaleString()}</span>
                <h3>{run.workflow_name}</h3>
                {run.initial_input?.trim() && <p className="builder-run-brief">{run.initial_input.trim()}</p>}
                <p>Run {run.id.slice(0, 8)} · {run.status.replace(/_/g, ' ')}</p>
              </div>
              <button type="button" onClick={() => onOpenWorkflow(run.id)}
                aria-label={`Open ${run.workflow_name} run ${run.id.slice(0, 8)}`}>Open run</button>
            </article>
          ))}
        </div>
      ) : <p role="status">{search ? copy.noMatches : copy.empty}</p>
    )}
  </section>;
}
