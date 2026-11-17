import { useEffect, useState } from 'react';
import { GitBranch, Play, ShieldCheck, Wrench } from 'lucide-react';
import { Link } from 'react-router';
import { connectSource, getSyncStatus, triggerSync } from '../lib/connectors-api';
import type { SyncStatus } from '../types/connectors';
import { WorkflowReviewHistory } from './WorkflowReviewHistory';
import './system-builder-lab.css';

export function SystemBuilderLab({ onOpenResearch, onOpenWorkflow }: {
  onOpenResearch: () => void;
  onOpenWorkflow: (runId: string) => void;
}) {
  const [feedAction, setFeedAction] = useState<'add' | 'retry' | null>(null);
  const [feedStatus, setFeedStatus] = useState('');
  const [sync, setSync] = useState<SyncStatus | 'unavailable' | null>(null);
  const [refresh, setRefresh] = useState(0);
  useEffect(() => {
    const request = new AbortController();
    let timer: number | undefined;
    const check = async () => {
      try {
        const status = await getSyncStatus('news_rss', request.signal);
        if (request.signal.aborted) return;
        setSync(status);
        if (status.state === 'syncing' || status.state === 'stopping') {
          timer = window.setTimeout(() => void check(), 2000);
        }
      } catch {
        if (!request.signal.aborted) setSync('unavailable');
      }
    };
    void check();
    return () => {
      request.abort();
      window.clearTimeout(timer);
    };
  }, [refresh]);

  const updateFeeds = async (action: 'add' | 'retry') => {
    if (feedAction) return;
    setFeedAction(action);
    setFeedStatus('');
    try {
      if (action === 'retry') {
        await triggerSync('news_rss');
      } else {
        const result = await connectSource('news_rss', { config: { preset: 'system_builder' } });
        if (!result.connected) throw new Error('The backend did not confirm the feeds.');
        setFeedStatus(result.sync_status === 'already_syncing'
          ? 'Feeds saved during an existing sync. Sync again if a source was missed.'
          : 'Research feeds saved.');
      }
      setRefresh((value) => value + 1);
    } catch (error) {
      setFeedStatus(error instanceof Error ? error.message : 'Could not update the research feeds.');
    } finally {
      setFeedAction(null);
    }
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
    <div className="research-banner">
      <button type="button" disabled={feedAction !== null} onClick={() => void updateFeeds('add')}>
        {feedAction === 'add' ? 'Adding research feeds…' : 'Add and sync public research feeds'}
      </button>
      <p>Adds OpenJarvis, n8n, Ollama, and OmniRoute releases, GitHub Changelog, and OpenAI news to your existing feeds.</p>
      {feedStatus && <p role="status">{feedStatus}</p>}
      {sync === 'unavailable' ? <p role="status">Research feed sync status is unavailable.</p> : sync && <>
        <p role="status">
          {sync.state === 'syncing' ? 'Syncing research feeds. '
            : sync.state === 'stopping' ? 'Research feed sync is stopping. ' : ''}
          {sync.items_synced} indexed entries.
          {sync.new_items_synced != null && ` ${sync.new_items_synced} in the latest sync.`}
        </p>
        {sync.error && <p role="status">{sync.error}</p>}
        {sync.state !== 'syncing' && sync.state !== 'stopping' &&
          (sync.error || sync.last_sync) && (
            <button type="button" disabled={feedAction !== null} onClick={() => void updateFeeds('retry')}>
              {feedAction === 'retry' ? 'Requesting sync…' : sync.error ? 'Retry feed sync' : 'Sync feeds again'}
            </button>
          )}
      </>}
    </div>
    <WorkflowReviewHistory kind="builder" onOpenWorkflow={onOpenWorkflow} />
  </section>;
}
