import { GitBranch, Play, ShieldCheck, Wrench } from 'lucide-react';
import { Link } from 'react-router';
import './system-builder-lab.css';

const IDEAS = [
  { id:'widget', title:'Adaptive dashboard layouts', source:'GitHub research', evidence:'Compared 6 open-source grid and dashboard systems', stage:'PROPOSAL', impact:'HIGH' },
  { id:'social', title:'Cross-channel content adapter', source:'YouTube + GitHub research', evidence:'Mapped public platform workflow patterns and approval gates', stage:'PROTOTYPE', impact:'HIGH' },
  { id:'memory', title:'Shared Brain ownership index', source:'GitHub research', evidence:'Reviewed agent-memory and event-ledger approaches', stage:'TESTING', impact:'MEDIUM' },
];

export function SystemBuilderLab({ onOpenResearch }: { onOpenResearch: () => void }) {
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
    <p>Example proposals</p>
    <div className="builder-ideas">
      {IDEAS.map((idea) => (
        <article key={idea.id}>
          <div><span>{idea.source}</span><h3>{idea.title}</h3><p>{idea.evidence}</p></div>
          <aside><em data-stage={idea.stage}>{idea.stage}</em><small>{idea.impact} IMPACT</small></aside>
        </article>
      ))}
    </div>
  </section>;
}
