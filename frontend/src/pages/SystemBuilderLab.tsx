import { useState } from 'react';
import { GitBranch, Play, ShieldCheck, Wrench } from 'lucide-react';
import { Link } from 'react-router';
import { connectSource } from '../lib/connectors-api';
import { WorkflowReviewHistory } from './WorkflowReviewHistory';
import './system-builder-lab.css';

export function SystemBuilderLab({ onOpenResearch, onOpenWorkflow }: {
  onOpenResearch: () => void;
  onOpenWorkflow: (runId: string) => void;
}) {
  const [addingFeeds, setAddingFeeds] = useState(false);
  const [feedStatus, setFeedStatus] = useState('');
  const addFeeds = async () => {
    if (addingFeeds) return;
    setAddingFeeds(true);
    setFeedStatus('');
    try {
      const result = await connectSource('news_rss', { config: { preset: 'system_builder' } });
      if (!result.connected) throw new Error('The backend did not confirm the feeds.');
      setFeedStatus(result.sync_status === 'started'
        ? 'Research feeds saved. Sync started.'
        : result.sync_status === 'already_syncing'
          ? 'Research feeds saved. If they are missing from the current sync, run Sync now in Data Sources.'
          : 'Research feeds saved. Sync them from Data Sources.');
    } catch (error) {
      setFeedStatus(error instanceof Error ? error.message : 'Could not add the research feeds.');
    } finally {
      setAddingFeeds(false);
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
      <button type="button" disabled={addingFeeds} onClick={() => void addFeeds()}>
        {addingFeeds ? 'Adding research feeds…' : 'Add and sync public research feeds'}
      </button>
      <p>Adds OpenJarvis, n8n, Ollama, and OmniRoute releases, GitHub Changelog, and OpenAI news to your existing feeds.</p>
      {feedStatus && <p role="status">{feedStatus}</p>}
    </div>
    <WorkflowReviewHistory kind="builder" onOpenWorkflow={onOpenWorkflow} />
  </section>;
}
