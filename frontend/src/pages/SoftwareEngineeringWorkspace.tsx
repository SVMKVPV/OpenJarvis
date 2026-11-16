import { FormEvent, useMemo, useState } from 'react';
import { Check, ChevronRight, Folder, FolderPlus, Monitor, Plus, Settings2 } from 'lucide-react';
import './software-workspace.css';

type Connector = { id: string; code: string; provider: string; product: string; role: string; model: string; status: 'setup' | 'local'; enabled: boolean; contributions: number };
type WorkItem = { id: string; folder: string; name: string; type: string; state: 'ACTIVE' | 'REVIEW' | 'BLOCKED' | 'COMPLETE'; owner: string; detail: string };
type Proposal = { id: string; connector: string; text: string; approved: boolean };

const INITIAL_CONNECTORS: Connector[] = [
  { id: 'openai', code: 'OAI', provider: 'OpenAI', product: 'ChatGPT', role: 'Implementation + code review', model: 'GPT-5', status: 'setup', enabled: true, contributions: 14 },
  { id: 'anthropic', code: 'ANT', provider: 'Anthropic', product: 'Claude', role: 'Architecture + long-context review', model: 'Claude Sonnet', status: 'setup', enabled: true, contributions: 9 },
  { id: 'google', code: 'GOO', provider: 'Google', product: 'Gemini', role: 'Research + multimodal QA', model: 'Gemini Pro', status: 'setup', enabled: true, contributions: 7 },
  { id: 'xai', code: 'XAI', provider: 'xAI', product: 'Grok', role: 'Current-context + adversarial review', model: 'Grok', status: 'setup', enabled: false, contributions: 3 },
  { id: 'meta', code: 'MET', provider: 'Meta', product: 'Llama', role: 'Open-model + batch specialist', model: 'Llama', status: 'setup', enabled: false, contributions: 5 },
  { id: 'local', code: 'LOC', provider: 'Local AI', product: 'Ollama / compatible', role: 'Private local execution', model: 'llama-local', status: 'local', enabled: true, contributions: 11 },
];

const INITIAL_FOLDERS = ['00-command', '01-product', '02-research', '03-design', '04-frontend', '05-backend', '06-tests', '07-releases'];
const ITEMS: WorkItem[] = [
  { id: 'shell', folder: '04-frontend', name: 'command-center-shell.tsx', type: 'INTERFACE', state: 'ACTIVE', owner: 'OpenAI', detail: 'Merge the workspace and configurable dashboard into the original OpenJarvis shell.' },
  { id: 'brain', folder: '05-backend', name: 'shared-brain-contract.md', type: 'ARCHITECTURE', state: 'REVIEW', owner: 'Anthropic', detail: 'Define shared context, ownership, and duplicate-work signals across all agents.' },
  { id: 'connectors', folder: '05-backend', name: 'connector-adapters.ts', type: 'CONNECTORS', state: 'BLOCKED', owner: 'Gemini', detail: 'Typed provider adapter boundary. Authentication remains disconnected in this preview.' },
  { id: 'dashboard', folder: '03-design', name: 'dashboard-widget-registry.ts', type: 'SYSTEM', state: 'ACTIVE', owner: 'OpenAI', detail: 'Station-owned widgets with independent layout state and removable calendar.' },
  { id: 'tests', folder: '06-tests', name: 'command-center.spec.ts', type: 'QUALITY', state: 'COMPLETE', owner: 'Local AI', detail: 'Keyboard, mobile, disconnected-state, and no-network verification.' },
];

export function SoftwareEngineeringWorkspace() {
  const [folders, setFolders] = useState(INITIAL_FOLDERS);
  const [selectedFolder, setSelectedFolder] = useState('04-frontend');
  const [selectedItemId, setSelectedItemId] = useState('shell');
  const [connectors, setConnectors] = useState(INITIAL_CONNECTORS);
  const [assigned, setAssigned] = useState<string[]>(['openai']);
  const [configuring, setConfiguring] = useState<string | null>(null);
  const [environment, setEnvironment] = useState<'chrome' | 'desktop'>('desktop');
  const [folderName, setFolderName] = useState('');
  const [showAddFolder, setShowAddFolder] = useState(false);
  const [warning, setWarning] = useState('');
  const [proposals, setProposals] = useState<Proposal[]>([
    { id: 'p-1', connector: 'OpenAI / ChatGPT', text: 'Prepared the command-center component boundary and preserved existing voice routing.', approved: false },
  ]);
  const visibleItems = useMemo(() => ITEMS.filter((item) => item.folder === selectedFolder), [selectedFolder]);
  const selectedItem = ITEMS.find((item) => item.id === selectedItemId) ?? visibleItems[0] ?? ITEMS[0];

  const addFolder = (event: FormEvent) => {
    event.preventDefault();
    const next = folderName.trim().toLowerCase().replace(/\s+/g, '-');
    if (!next || folders.includes(next)) return;
    setFolders((current) => [...current, next]); setSelectedFolder(next); setFolderName(''); setShowAddFolder(false);
  };

  const contribute = () => {
    if (!assigned.length) return;
    if (assigned.length > 1) { setWarning(`Shared Brain warning: ${selectedItem.name} already has an owner. Confirmed collaborators will contribute without replacing ownership.`); }
    const additions = assigned.map((id) => {
      const connector = connectors.find((item) => item.id === id)!;
      return { id: `${id}-${Date.now()}`, connector: `${connector.provider} / ${connector.product}`, text: `Simulated ${connector.role.toLowerCase()} proposal for ${selectedItem.name}.`, approved: false };
    });
    setProposals((current) => [...additions, ...current]);
  };

  return <main className="se-workspace">
    <div className="se-heading"><div><span>SHARED PROJECT WORKSPACE</span><h2>Software Engineering</h2><p>One project surface for internal stations, cloud AI collaborators, and private local models.</p></div><div className="demo-flag">FUNCTIONAL PREVIEW · NO LIVE PROVIDER REQUESTS</div></div>
    <div className="se-layout">
      <aside className="folder-rail">
        <header><div><span>PROJECT FOLDERS</span><strong>{folders.length} DIRECTORIES</strong></div><button onClick={() => setShowAddFolder((value) => !value)} aria-label="Add project folder"><FolderPlus size={14}/></button></header>
        {showAddFolder && <form onSubmit={addFolder}><input autoFocus value={folderName} onChange={(event) => setFolderName(event.target.value)} placeholder="folder-name"/><button>ADD</button></form>}
        <nav>{folders.map((folder) => <button key={folder} className={folder === selectedFolder ? 'active' : ''} onClick={() => setSelectedFolder(folder)}><Folder size={13}/><span>{folder}</span><ChevronRight size={11}/></button>)}</nav>
        <div className="folder-status"><span>SHARED BRAIN</span><strong>CONTEXT SYNCHRONIZED</strong><small>10 stations · 0 duplicate conflicts</small></div>
      </aside>

      <section className="project-surface">
        <header><div><span>ACTIVE FOLDER</span><strong>/{selectedFolder}</strong></div><em>{visibleItems.length} ITEMS</em></header>
        <div className="project-body">
          <div className="work-items">{visibleItems.length ? visibleItems.map((item) => <button key={item.id} className={item.id === selectedItem.id ? 'active' : ''} onClick={() => setSelectedItemId(item.id)}><span>{item.type}</span><strong>{item.name}</strong><small>{item.owner}</small><em data-state={item.state}>{item.state}</em></button>) : <div className="workspace-empty"><Folder size={20}/><strong>Empty folder</strong><small>Add project files when the live adapter is connected.</small></div>}</div>
          <article className="item-preview"><div className="preview-meta"><span>{selectedItem.type}</span><em data-state={selectedItem.state}>{selectedItem.state}</em></div><h3>{selectedItem.name}</h3><p>{selectedItem.detail}</p><dl><div><dt>OWNER</dt><dd>{selectedItem.owner}</dd></div><div><dt>SHARED CONTEXT</dt><dd>AVAILABLE TO ALL ASSIGNED AGENTS</dd></div></dl>
            <div className="assignment"><span>ASSIGN COLLABORATORS</span><div>{connectors.filter((connector) => connector.enabled).map((connector) => <label key={connector.id}><input type="checkbox" checked={assigned.includes(connector.id)} onChange={() => setAssigned((current) => current.includes(connector.id) ? current.filter((id) => id !== connector.id) : [...current, connector.id])}/><b>{connector.code}</b></label>)}</div><button onClick={contribute} disabled={!assigned.length}><Plus size={12}/> CREATE SIMULATED CONTRIBUTION</button>{warning && <p className="brain-warning">{warning}</p>}</div>
          </article>
        </div>
        <section className="proposal-feed"><header><span>PROPOSED CONTRIBUTIONS</span><strong>{proposals.filter((proposal) => !proposal.approved).length} AWAITING APPROVAL</strong></header>{proposals.slice(0,4).map((proposal) => <article key={proposal.id}><div><strong>{proposal.connector}</strong><p>{proposal.text}</p></div><button className={proposal.approved ? 'approved' : ''} onClick={() => setProposals((current) => current.map((item) => item.id === proposal.id ? {...item, approved: true} : item))}>{proposal.approved ? <><Check size={11}/> APPROVED</> : 'APPROVE'}</button></article>)}</section>
      </section>

      <aside className="connector-column">
        <header><div><span>AI CONNECTORS</span><strong>CONTRIBUTOR ROSTER</strong></div><em>{connectors.filter((item) => item.enabled).length} ENABLED</em></header>
        <div className="connector-list">{connectors.map((connector) => <article key={connector.id} className={connector.enabled ? 'enabled' : ''}><button className="connector-toggle" aria-label={`${connector.enabled ? 'Disable' : 'Enable'} ${connector.product}`} onClick={() => setConnectors((current) => current.map((item) => item.id === connector.id ? {...item, enabled: !item.enabled} : item))}><i/></button><div className="connector-code">{connector.code}</div><div><strong>{connector.product}</strong><small>{connector.provider} · {connector.model}</small><p>{connector.role}</p></div><button className="connector-config" onClick={() => setConfiguring(configuring === connector.id ? null : connector.id)} aria-label={`Configure ${connector.product}`}><Settings2 size={12}/></button>{configuring === connector.id && <div className="connector-editor"><label>ROLE<input value={connector.role} onChange={(event) => setConnectors((current) => current.map((item) => item.id === connector.id ? {...item, role: event.target.value} : item))}/></label><label>MODEL<input value={connector.model} onChange={(event) => setConnectors((current) => current.map((item) => item.id === connector.id ? {...item, model: event.target.value} : item))}/></label>{connector.id === 'local' && <label>LOCAL ENDPOINT<input value="http://localhost:11434" readOnly/></label>}<small>{connector.status === 'local' ? 'LOCAL CONFIGURATION · NOT PROBED' : 'NEEDS SETUP · NO CREDENTIALS STORED'}</small></div>}</article>)}</div>
        <section className="environment-preview"><header><div><span>ENVIRONMENT</span><strong>VIEW SURFACE</strong></div><Monitor size={13}/></header><div className="environment-tabs"><button className={environment === 'desktop' ? 'active' : ''} onClick={() => setEnvironment('desktop')}>DESKTOP</button><button className={environment === 'chrome' ? 'active' : ''} onClick={() => setEnvironment('chrome')}>CHROME</button></div>{environment === 'desktop' ? <div className="desktop-frame"><div className="desktop-top">SOFTWARE ENGINEERING DESKTOP</div><div className="desktop-windows"><span>CODE</span><span>TERMINAL</span><span>PREVIEW</span></div><p>DESKTOP CONTROL NOT CONNECTED</p></div> : <div className="chrome-frame"><div><i/><i/><i/><span>localhost / command-center</span></div><strong>OPENJARVIS PREVIEW</strong><p>BROWSER CONTROL NOT CONNECTED</p></div>}</section>
      </aside>
    </div>
  </main>;
}
