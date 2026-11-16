import { useState } from 'react';
import { Check, FlaskConical, GitBranch, Play, ShieldCheck, Wrench } from 'lucide-react';
import './system-builder-lab.css';

const IDEAS = [
  { id:'widget', title:'Adaptive dashboard layouts', source:'GitHub research', evidence:'Compared 6 open-source grid and dashboard systems', stage:'PROPOSAL', impact:'HIGH' },
  { id:'social', title:'Cross-channel content adapter', source:'YouTube + GitHub research', evidence:'Mapped public platform workflow patterns and approval gates', stage:'PROTOTYPE', impact:'HIGH' },
  { id:'memory', title:'Shared Brain ownership index', source:'GitHub research', evidence:'Reviewed agent-memory and event-ledger approaches', stage:'TESTING', impact:'MEDIUM' },
];

export function SystemBuilderLab() {
  const [researching, setResearching] = useState(false);
  const [approved, setApproved] = useState<string[]>([]);
  return <section className="builder-lab"><header><div><span>SYSTEM BUILDER WORKSTATION</span><strong>Research, propose, prototype, verify — then request approval.</strong></div><button onClick={() => setResearching(!researching)}><Play size={11}/>{researching ? 'RESEARCH QUEUED' : 'START RESEARCH CYCLE'}</button></header>
    <div className="builder-sources"><article><GitBranch/><div><strong>GitHub public research</strong><small>Repositories, releases, patterns, and implementation references</small></div><em>READ-ONLY PREVIEW</em></article><article><span className="youtube-mark">YT</span><div><strong>YouTube research</strong><small>Tutorials, transcripts, demos, and technical walkthroughs</small></div><em>PUBLIC SOURCES</em></article><article><Wrench/><div><strong>Local prototype sandbox</strong><small>Draft changes isolated from the production command center</small></div><em>NO AUTO-MERGE</em></article><article><ShieldCheck/><div><strong>Human approval gate</strong><small>Required before merge, deployment, posting, or external action</small></div><em>ENFORCED</em></article></div>
    <div className="builder-flow"><div><b>01</b><span>RESEARCH</span></div><i/><div><b>02</b><span>PROPOSE</span></div><i/><div><b>03</b><span>PROTOTYPE</span></div><i/><div><b>04</b><span>TEST</span></div><i/><div><b>05</b><span>HUMAN APPROVAL</span></div></div>
    {researching && <p className="research-banner"><FlaskConical size={12}/> Demo research cycle added to the queue. Live source access is not connected in this preview.</p>}
    <div className="builder-ideas">{IDEAS.map((idea) => <article key={idea.id}><div><span>{idea.source}</span><h3>{idea.title}</h3><p>{idea.evidence}. Shared Brain found no conflicting owner.</p></div><aside><em data-stage={idea.stage}>{idea.stage}</em><small>{idea.impact} IMPACT</small><button className={approved.includes(idea.id) ? 'approved' : ''} onClick={() => setApproved((current) => current.includes(idea.id) ? current : [...current,idea.id])}>{approved.includes(idea.id) ? <><Check size={10}/> APPROVED TO PLAN</> : 'REVIEW PROPOSAL'}</button></aside></article>)}</div>
  </section>;
}
