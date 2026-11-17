import { useEffect, useState } from 'react';
import { GitBranch, Play, ShieldCheck, Wrench } from 'lucide-react';
import { Link } from 'react-router';
import { fetchSystemBuilderProposals, type WorkflowRunSummary } from '../lib/api';
import './system-builder-lab.css';

type ProposalHistory =
  | { status: 'loading' | 'unavailable' }
  | { status: 'loaded'; runs: Array<WorkflowRunSummary & { initial_input?: string }> };

export function SystemBuilderLab({ onOpenResearch, onOpenWorkflow }: {
  onOpenResearch: () => void;
  onOpenWorkflow: (runId: string) => void;
}) {
  const [history, setHistory] = useState<ProposalHistory>({ status: 'loading' });
  const [searchInput, setSearchInput] = useState('');
  const [search, setSearch] = useState('');
  const [refresh, setRefresh] = useState(0);

  useEffect(() => {
    const request = new AbortController();
    fetchSystemBuilderProposals(request.signal, search).then(
      (runs) => {
        if (!request.signal.aborted) setHistory({ status: 'loaded', runs });
      },
      () => {
        if (!request.signal.aborted) setHistory({ status: 'unavailable' });
      },
    );
    return () => request.abort();
  }, [refresh, search]);

  const reload = () => {
    setHistory({ status: 'loading' });
    setRefresh((value) => value + 1);
  };

  return <section className="builder-lab"><header><div><span>SYSTEM BUILDER WORKSTATION</span><strong>Research and review improvement proposals</strong></div><button type="button" onClick={onOpenResearch}><Play size={11}/>Open research workflow</button></header>
    <div className="builder-sources">
      <article><GitBranch/><div><strong>GitHub release research</strong><small>Search indexed entries from configured public release feeds</small></div><em>RSS / ATOM</em></article>
      <article><span className="youtube-mark">YT</span><div><strong>YouTube research</strong><small>Search indexed titles and descriptions from configured public feeds</small></div><em>RSS / ATOM</em></article>
      <article><Wrench/><div><strong>Prototype planning</strong><small>Propose an isolated test, success metric, and integration dependencies</small></div><em>PROPOSAL</em></article>
      <article><ShieldCheck/><div><strong>Human approval</strong><small>Review source evidence and decide whether to assign a prototype</small></div><em>REVIEW QUEUE</em></article>
    </div>
    <div className="builder-flow"><div><b>01</b><span>RESEARCH</span></div><i/><div><b>02</b><span>PROPOSE</span></div><i/><div><b>03</b><span>PROTOTYPE</span></div><i/><div><b>04</b><span>TEST</span></div><i/><div><b>05</b><span>HUMAN APPROVAL</span></div></div>
    <p className="research-banner">The research workflow searches synced public feeds and sends citations
      and a proposal to the approval queue. <Link to="/data-sources">Configure News / RSS feeds</Link></p>
    <header>
      <strong>Recent proposal runs</strong>
      <button type="button" onClick={reload} disabled={history.status === 'loading'}>Refresh</button>
    </header>
    <form className="builder-search" onSubmit={(event) => {
      event.preventDefault();
      setSearch(searchInput.trim());
      reload();
    }}>
      <label htmlFor="builder-brief-search">Search research briefs</label>
      <input id="builder-brief-search" type="search" maxLength={200}
        value={searchInput} onChange={(event) => setSearchInput(event.target.value)} />
      <button type="submit">Search</button>
      {search && <button type="button" onClick={() => {
        setSearchInput('');
        setSearch('');
        reload();
      }}>Clear search</button>}
    </form>
    {history.status === 'loading' && <p role="status">Loading proposal history.</p>}
    {history.status === 'unavailable' && <p role="status">Proposal history is unavailable. Check the backend and refresh.</p>}
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
      ) : <p role="status">{search ? 'No proposal runs match that brief.' : 'No System Builder proposal runs yet.'}</p>
    )}
  </section>;
}
