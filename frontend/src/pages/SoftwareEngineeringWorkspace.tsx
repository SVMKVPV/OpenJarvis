import { FormEvent, useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router';
import { Check, ChevronRight, Folder, FolderPlus, Monitor, Plus, Settings2 } from 'lucide-react';
import {
  approveAction,
  denyAction,
  fetchPendingApprovals,
  fetchRuntimePlugins,
  fetchWorkflowDefinitions,
  fetchWorkflowRun,
  fetchWorkflowRuns,
  requestWorkflowRunAction,
  runSavedWorkflow,
  saveWorkflowDefinition,
  startWorkflowRun,
  type PendingApproval,
  type RuntimePlugin,
  type SavedWorkflowDefinition,
  type WorkflowRunSummary,
  type WorkflowRunDetail,
  type WorkflowRunAction,
} from '../lib/api';
import { listConnectors } from '../lib/connectors-api';
import type { ConnectorInfo } from '../types/connectors';
import './software-workspace.css';

type Connector = { id: string; code: string; provider: string; product: string; role: string; model: string; status: 'setup' | 'local'; enabled: boolean; contributions: number };
type WorkItem = { id: string; folder: string; name: string; type: string; state: 'ACTIVE' | 'REVIEW' | 'BLOCKED' | 'COMPLETE'; owner: string; detail: string };
type Proposal = { id: string; connector: string; text: string; approved: boolean };

const GUARDED_DELIVERY = {
  name: 'CEO guarded delivery',
  nodes: [
    { id: 'prepare', type: 'transform', transform_expr: 'concatenate' },
    {
      id: 'approval',
      type: 'approval',
      config: {
        action_type: 'release',
        description: 'Approve the prepared delivery before release',
        tier: 'high',
        permission_key: 'workflow:release',
      },
    },
    { id: 'release', type: 'transform', transform_expr: 'concatenate' },
  ],
  edges: [{ source: 'prepare', target: 'approval' }, { source: 'approval', target: 'release' }],
};

const GUARDED_GRAPH_JSON = JSON.stringify({
  nodes: GUARDED_DELIVERY.nodes,
  edges: GUARDED_DELIVERY.edges,
}, null, 2);

type DraftEdge = { source: string; target: string; condition?: string };

type DraftGraph = { nodes: { id: string }[]; edges?: DraftEdge[] };
type NewStepType = 'transform' | 'condition' | 'approval';

function readDraftGraph(draft: string): DraftGraph | null {
  try {
    const graph = JSON.parse(draft);
    if (!graph || !Array.isArray(graph.nodes)) return null;
    if (!graph.nodes.every((node: unknown) => node && typeof node === 'object' &&
      'id' in node && typeof node.id === 'string' && node.id.trim())) return null;
    const edges: unknown = graph.edges ?? [];
    if (!Array.isArray(edges)) return null;
    if (!edges.every((edge) => edge && typeof edge.source === 'string' &&
      typeof edge.target === 'string' &&
      (edge.condition === undefined || typeof edge.condition === 'string'))) return null;
    return graph;
  } catch {
    return null;
  }
}

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
  const [runtimePlugins, setRuntimePlugins] = useState<RuntimePlugin[]>([]);
  const [liveConnectors, setLiveConnectors] = useState<ConnectorInfo[] | null>(null);
  const [pluginCatalogState, setPluginCatalogState] = useState<'loading' | 'online' | 'offline'>('loading');
  const [workflowRuns, setWorkflowRuns] = useState<WorkflowRunSummary[]>([]);
  const [inspectedRunId, setInspectedRunId] = useState('');
  const [runDetail, setRunDetail] = useState<WorkflowRunDetail | null>(null);
  const [runDetailError, setRunDetailError] = useState('');
  const [runActionPending, setRunActionPending] = useState(false);
  const [runActionMessage, setRunActionMessage] = useState<{ id: string; text: string } | null>(null);
  const inspectedRunStatus = workflowRuns.find((run) => run.id === inspectedRunId)?.status;

  const actOnRun = async (id: string, action: WorkflowRunAction) => {
    if (runActionPending) return;
    setRunActionPending(true);
    setRunActionMessage(null);
    try {
      await requestWorkflowRunAction(id, action);
      const messages = {
        cancel: 'Cancellation requested.',
        retry: 'Retry queued as a new run.',
        resume: 'Resume requested. Any pending approval still applies.',
      };
      setRunActionMessage({ id, text: messages[action] });
    } catch (error) {
      setRunActionMessage({ id, text: error instanceof Error ? error.message : 'Workflow action failed.' });
    } finally {
      setRunActionPending(false);
    }
  };
  const [definitions, setDefinitions] = useState<SavedWorkflowDefinition[]>([]);
  const [definitionId, setDefinitionId] = useState('');
  const selectedDefinition = definitions.find((item) => item.id === definitionId);
  const [workflowInput, setWorkflowInput] = useState('');
  const [definitionMessage, setDefinitionMessage] = useState('Loading saved workflows…');
  const [launchingSaved, setLaunchingSaved] = useState(false);
  const [savingDefinition, setSavingDefinition] = useState(false);
  const [workflowName, setWorkflowName] = useState(GUARDED_DELIVERY.name);
  const [workflowGraph, setWorkflowGraph] = useState(GUARDED_GRAPH_JSON);
  const draftGraph = useMemo(() => readDraftGraph(workflowGraph), [workflowGraph]);
  const [edgeSource, setEdgeSource] = useState('');
  const [edgeTarget, setEdgeTarget] = useState('');
  const [stepId, setStepId] = useState('');
  const [stepType, setStepType] = useState<NewStepType>('transform');
  const [stepSetting, setStepSetting] = useState('');
  const [workflowApprovals, setWorkflowApprovals] = useState<PendingApproval[]>([]);
  const [decidingApprovalId, setDecidingApprovalId] = useState('');
  const [approvalMessage, setApprovalMessage] = useState('');
  const [workflowState, setWorkflowState] = useState<'online' | 'offline' | 'starting'>('offline');
  const [proposals, setProposals] = useState<Proposal[]>([
    { id: 'p-1', connector: 'OpenAI / ChatGPT', text: 'Prepared the command-center component boundary and preserved existing voice routing.', approved: false },
  ]);
  const visibleItems = useMemo(() => ITEMS.filter((item) => item.folder === selectedFolder), [selectedFolder]);
  const selectedItem = ITEMS.find((item) => item.id === selectedItemId) ?? visibleItems[0] ?? ITEMS[0];

  useEffect(() => {
    if (!inspectedRunId) return;
    const controller = new AbortController();
    fetchWorkflowRun(inspectedRunId, controller.signal).then((detail) => {
      if (controller.signal.aborted) return;
      setRunDetail(detail);
      setRunDetailError('');
    }).catch((error) => {
      if (!controller.signal.aborted) setRunDetailError(error instanceof Error ? error.message : 'Could not load run details.');
    });
    return () => controller.abort();
  }, [inspectedRunId, inspectedRunStatus]);

  useEffect(() => {
    let cancelled = false;
    fetchWorkflowDefinitions().then((items) => {
      if (cancelled) return;
      setDefinitions((current) => [
        ...current,
        ...items.filter((item) => !current.some((saved) => saved.id === item.id)),
      ]);
      setDefinitionMessage(items.length ? '' : 'No saved workflows.');
    }).catch(() => {
      if (!cancelled) setDefinitionMessage('Saved workflows are unavailable. Check the backend connection.');
    });
    return () => { cancelled = true; };
  }, []);

  const saveDefinition = async (event: FormEvent) => {
    event.preventDefault();
    const name = workflowName.trim();
    if (!name || savingDefinition) return;
    setSavingDefinition(true);
    try {
      const graph = JSON.parse(workflowGraph);
      if (!graph || !Array.isArray(graph.nodes) || !graph.nodes.length ||
          (graph.edges !== undefined && !Array.isArray(graph.edges))) {
        throw new Error('Provide a nonempty nodes array and an optional edges array.');
      }
      const saved = await saveWorkflowDefinition({ name, nodes: graph.nodes, edges: graph.edges });
      setDefinitions((current) => [saved, ...current.filter((item) => item.id !== saved.id)]);
      setDefinitionId(saved.id);
      setDefinitionMessage('Workflow saved.');
    } catch (error) {
      setDefinitionMessage(error instanceof Error ? error.message : 'Could not save workflow.');
    } finally {
      setSavingDefinition(false);
    }
  };

  const replaceEdges = (edges: DraftEdge[]) => {
    if (draftGraph) setWorkflowGraph(JSON.stringify({ ...draftGraph, edges }, null, 2));
  };
  const draftEdges = draftGraph?.edges ?? [];
  const newStepId = stepId.trim();
  const canAddStep = draftGraph && newStepId && newStepId !== '_input' &&
    !draftGraph.nodes.some((node) => node.id === newStepId) &&
    (stepType === 'transform' || stepSetting.trim());
  const addStep = () => {
    if (!draftGraph || !canAddStep) return;
    const node = { id: newStepId, type: stepType };
    let definition;
    switch (stepType) {
      case 'condition':
        definition = { ...node, condition_expr: stepSetting.trim() };
        break;
      case 'approval':
        definition = { ...node, config: { description: stepSetting.trim(), tier: 'high' } };
        break;
      default:
        definition = { ...node, transform_expr: stepSetting || 'concatenate' };
    }
    setWorkflowGraph(JSON.stringify({ ...draftGraph, nodes: [...draftGraph.nodes, definition] }, null, 2));
    setStepId('');
    setStepSetting('');
  };
  const canAddEdge = draftGraph && edgeSource !== edgeTarget &&
    draftGraph.nodes.some((node) => node.id === edgeSource) &&
    draftGraph.nodes.some((node) => node.id === edgeTarget) &&
    !draftEdges.some((edge) => edge.source === edgeSource && edge.target === edgeTarget);
  const changeBranch = (index: number, condition: string) => {
    replaceEdges(draftEdges.map((edge, position) =>
      position === index ? { ...edge, condition } : edge,
    ));
  };

  const launchSaved = async (event: FormEvent) => {
    event.preventDefault();
    if (!definitionId || launchingSaved) return;
    setLaunchingSaved(true);
    setDefinitionMessage('');
    try {
      const run = await runSavedWorkflow(definitionId, workflowInput);
      setWorkflowRuns((current) => [run, ...current.filter((item) => item.id !== run.id)]);
      setDefinitionMessage('Workflow queued.');
    } catch (error) {
      setDefinitionMessage(error instanceof Error ? error.message : 'Could not start workflow.');
    } finally {
      setLaunchingSaved(false);
    }
  };

  const editSaved = () => {
    if (!selectedDefinition) return;
    const { name, nodes, edges } = selectedDefinition.graph;
    setWorkflowName(name);
    setWorkflowGraph(JSON.stringify({ nodes, edges }, null, 2));
    setEdgeSource('');
    setEdgeTarget('');
    setDefinitionMessage('Saved workflow loaded into the editor. Save workflow creates a new copy.');
  };

  const exportSaved = () => {
    if (!selectedDefinition) return;
    const { graph } = selectedDefinition;
    const file = new Blob([JSON.stringify(graph, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(file);
    const link = document.createElement('a');
    const safeName = graph.name.replace(/[^a-z0-9_-]+/gi, '-').replace(/^-+|-+$/g, '');
    link.href = url;
    link.download = `${safeName || 'workflow'}.openjarvis.json`;
    link.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  };

  const importDraft = async (file: File) => {
    if (file.size > 1024 * 1024) {
      setDefinitionMessage('Workflow JSON must be under 1 MB.');
      return;
    }
    try {
      const source = await file.text();
      const graph = readDraftGraph(source);
      if (!graph?.nodes.length) throw new Error('Choose an OpenJarvis workflow JSON export.');
      const { name, edges, nodes } = JSON.parse(source);
      if (typeof name !== 'string' || !name.trim()) {
        throw new Error('The workflow JSON needs a name.');
      }
      setWorkflowName(name);
      setWorkflowGraph(JSON.stringify({ nodes, edges }, null, 2));
      setEdgeSource('');
      setEdgeTarget('');
      setDefinitionMessage('Draft loaded. Review its steps before saving.');
    } catch (error) {
      setDefinitionMessage(error instanceof Error ? error.message : 'Could not read workflow JSON.');
    }
  };

  useEffect(() => {
    let cancelled = false;
    listConnectors()
      .then((items) => {
        if (!cancelled) setLiveConnectors(items);
      })
      .catch(() => {
        if (!cancelled) setLiveConnectors(null);
      });
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    let cancelled = false;
    fetchRuntimePlugins()
      .then((items) => {
        if (cancelled) return;
        setRuntimePlugins(items);
        setPluginCatalogState('online');
      })
      .catch(() => {
        if (!cancelled) setPluginCatalogState('offline');
      });
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    let cancelled = false;
    const refresh = async () => {
      try {
        const [runs, approvals] = await Promise.all([fetchWorkflowRuns(), fetchPendingApprovals()]);
        if (!cancelled) {
          setWorkflowRuns(runs);
          setWorkflowApprovals(approvals.filter((item) => typeof item.payload.workflow_run_id === 'string'));
          setWorkflowState('online');
        }
      } catch {
        if (!cancelled) setWorkflowState('offline');
      }
    };
    void refresh();
    const timer = window.setInterval(refresh, 2500);
    return () => { cancelled = true; window.clearInterval(timer); };
  }, []);

  const launchGuardedWorkflow = async () => {
    setWorkflowState('starting');
    try {
      await startWorkflowRun({
        ...GUARDED_DELIVERY,
        initial_input: 'Prepare a reviewed command-center delivery',
        context: { owner: 'CEO Director', station: 'System Builder' },
      });
      setWorkflowRuns(await fetchWorkflowRuns());
      setWorkflowState('online');
    } catch {
      setWorkflowState('offline');
    }
  };

  const decideWorkflow = async (approval: PendingApproval, decision: 'approve' | 'deny') => {
    if (decidingApprovalId) return;
    setDecidingApprovalId(approval.id);
    setApprovalMessage('');
    try {
      const submitDecision = decision === 'approve' ? approveAction : denyAction;
      await submitDecision(approval.id);
      setWorkflowApprovals((items) => items.filter((item) => item.id !== approval.id));
      setApprovalMessage(decision === 'approve' ? 'Approval recorded.' : 'Denial recorded.');
    } catch {
      setApprovalMessage('Could not record the decision. Check the backend and try again.');
    } finally {
      setDecidingApprovalId('');
    }
  };

  const pluginCounts = useMemo(() => runtimePlugins.reduce<Record<string, number>>((counts, plugin) => {
    counts[plugin.kind] = (counts[plugin.kind] ?? 0) + 1;
    return counts;
  }, {}), [runtimePlugins]);

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
        <section className="runtime-plugins">
          <header><div><span>BUSINESS PLUGINS</span><strong>OPENJARVIS RUNTIME</strong></div><em data-state={pluginCatalogState}>{pluginCatalogState.toUpperCase()}</em></header>
          {pluginCatalogState === 'online' ? <>
            <div className="plugin-counts">{(['connector', 'channel', 'tool', 'agent', 'engine'] as const).map((kind) => <div key={kind}><strong>{pluginCounts[kind] ?? 0}</strong><span>{kind.toUpperCase()}S</span></div>)}</div>
            <div className="plugin-sample">
              {runtimePlugins.filter((plugin) => plugin.kind === 'connector').slice(0, 8).map((plugin) => {
                const source = liveConnectors?.find((item) => item.connector_id === plugin.id);
                const status = !plugin.enabled ? 'REVIEW' : source?.connected
                  ? 'CONNECTED' : source ? 'DISCONNECTED' : 'UNVERIFIED';
                return <span key={plugin.id}>{plugin.name}<i>{status}</i></span>;
              })}
            </div>
          </> : <p>{pluginCatalogState === 'loading' ? 'READING LOCAL PLUGIN CATALOG…' : 'START LOCAL AI OR CONNECT A BACKEND TO LOAD OPERATIONAL PLUGINS.'}</p>}
          <p><Link to="/data-sources">Manage data source connections ↗</Link></p>
        </section>
        <section className="workflow-runtime">
          <header><div><span>WORKFLOW RUNTIME</span><strong>DURABLE EXECUTION LEDGER</strong></div><em data-state={workflowState}>{workflowState.toUpperCase()}</em></header>
          <button className="workflow-launch" onClick={launchGuardedWorkflow} disabled={workflowState === 'starting'}>{workflowState === 'starting' ? 'STARTING…' : '+ RUN GUARDED DELIVERY'}</button>
          <form className="connector-editor" onSubmit={saveDefinition}>
            <label>Workflow name
              <input value={workflowName} onChange={(event) => setWorkflowName(event.target.value)} />
            </label>
            <button className="workflow-launch" disabled={!workflowName.trim() || savingDefinition}>
              {savingDefinition ? 'Saving…' : 'Save workflow'}
            </button>
            <details className="workflow-graph-editor">
              <summary>Edit workflow definition</summary>
              <label>Replace draft from OpenJarvis JSON
                <input type="file" accept=".json,application/json" disabled={savingDefinition}
                  onChange={(event) => {
                    const file = event.currentTarget.files?.[0];
                    event.currentTarget.value = '';
                    if (file) void importDraft(file);
                  }} />
              </label>
              {draftGraph && (
                <fieldset>
                  <legend>Workflow steps</legend>
                  <ul>{draftGraph.nodes.map((node) => <li key={node.id}>{node.id}</li>)}</ul>
                  <label>Step ID
                    <input value={stepId} onChange={(event) => setStepId(event.target.value)} />
                  </label>
                  <label>Step type
                    <select value={stepType} onChange={(event) => {
                      setStepType(event.target.value as NewStepType);
                      setStepSetting('');
                    }}>
                      <option value="transform">Text transform</option>
                      <option value="condition">Condition</option>
                      <option value="approval">Approval</option>
                    </select>
                  </label>
                  {stepType === 'transform' ? (
                    <label>Transform
                      <select value={stepSetting || 'concatenate'} onChange={(event) => setStepSetting(event.target.value)}>
                        <option value="concatenate">Combine input</option>
                        <option value="first_line">Keep first line</option>
                      </select>
                    </label>
                  ) : (
                    <label>{stepType === 'condition' ? 'Condition expression' : 'Approval request'}
                      <input value={stepSetting} onChange={(event) => setStepSetting(event.target.value)}
                        placeholder={stepType === 'condition' ? "outputs['_input'] == 'yes'" : 'Review the prepared result'} />
                    </label>
                  )}
                  <button type="button" onClick={addStep} disabled={!canAddStep}>Add step</button>
                </fieldset>
              )}
              <fieldset>
                <legend>Branch conditions</legend>
                {draftEdges.map((edge, index) => (
                  <div key={index}>
                    <label>{edge.source} → {edge.target}
                    <select value={edge.condition?.trim().toLowerCase() ?? ''}
                      onChange={(event) => changeBranch(index, event.target.value)}>
                      <option value="">Always</option>
                      <option value="true">When true</option>
                      <option value="false">When false</option>
                    </select>
                    </label>
                    <button type="button" aria-label={`Remove connection from ${edge.source} to ${edge.target}`}
                      onClick={() => replaceEdges(draftEdges.filter((_, position) => position !== index))}>
                      Remove connection
                    </button>
                  </div>
                ))}
                {!draftGraph && <small>Fix the workflow JSON to edit its connections here.</small>}
                {draftGraph && (
                  <div>
                    <label>From <select value={edgeSource} onChange={(event) => setEdgeSource(event.target.value)}>
                      <option value="">Choose a step</option>
                      {draftGraph.nodes.map((node) => <option key={node.id} value={node.id}>{node.id}</option>)}
                    </select></label>
                    <label>To <select value={edgeTarget} onChange={(event) => setEdgeTarget(event.target.value)}>
                      <option value="">Choose a step</option>
                      {draftGraph.nodes.map((node) => <option key={node.id} value={node.id}>{node.id}</option>)}
                    </select></label>
                    <button type="button" disabled={!canAddEdge} onClick={() => {
                      if (canAddEdge) replaceEdges([...draftEdges, { source: edgeSource, target: edgeTarget }]);
                    }}>Add connection</button>
                  </div>
                )}
              </fieldset>
              <label>OpenJarvis workflow JSON
                <textarea rows={12} spellCheck={false} value={workflowGraph}
                  onChange={(event) => setWorkflowGraph(event.target.value)} />
              </label>
              <small>Conditional edges accept true or false in the condition field.</small>
              <button type="button" onClick={() => setWorkflowGraph(GUARDED_GRAPH_JSON)}>Restore guarded delivery steps</button>
            </details>
          </form>
          <p><a href="https://zie619.github.io/n8n-workflows/" target="_blank" rel="noopener noreferrer">Browse optional n8n templates ↗</a><br />Download JSON for manual import into n8n.</p>
          {definitions.length > 0 && (
            <form className="connector-editor" onSubmit={launchSaved}>
              <label>Saved workflow
                <select value={definitionId} onChange={(event) => setDefinitionId(event.target.value)}>
                  <option value="">Choose a workflow</option>
                  {definitions.map((definition) => (
                    <option key={definition.id} value={definition.id}>{definition.graph.name}</option>
                  ))}
                </select>
              </label>
              <label>Run input
                <input value={workflowInput} onChange={(event) => setWorkflowInput(event.target.value)} />
              </label>
              <button className="workflow-launch" disabled={!definitionId || launchingSaved}>
                {launchingSaved ? 'Starting…' : 'Run saved workflow'}
              </button>
              <button type="button" disabled={!selectedDefinition || savingDefinition}
                onClick={editSaved} title="Replaces the current editor draft">
                Load saved workflow into editor
              </button>
              <button type="button" disabled={!selectedDefinition} onClick={exportSaved}>
                Download saved workflow JSON
              </button>
            </form>
          )}
          {definitionMessage && <p role="status">{definitionMessage}</p>}
          {workflowApprovals.slice(0, 2).map((approval) => (
            <article className="workflow-approval" key={approval.id}>
              <div><b>CEO APPROVAL REQUIRED</b><span>{approval.description}</span></div>
              <div>
                <button type="button" disabled={!!decidingApprovalId}
                  onClick={() => void decideWorkflow(approval, 'approve')}>Approve</button>
                <button type="button" disabled={!!decidingApprovalId}
                  onClick={() => void decideWorkflow(approval, 'deny')}>Deny</button>
              </div>
            </article>
          ))}
          {approvalMessage && <p role="status">{approvalMessage}</p>}
          <div className="workflow-runs">
            {workflowRuns.slice(0, 5).map((run) => (
              <article key={run.id}>
                <div><strong>{run.workflow_name}</strong><small>{run.id.slice(0, 8)} · {new Date(run.created_at * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</small></div>
                <em data-status={run.status}>{run.status.replace('_', ' ').toUpperCase()}</em>
                <button type="button" aria-pressed={inspectedRunId === run.id} onClick={() => {
                  setRunDetail(null);
                  setRunDetailError('');
                  setInspectedRunId(inspectedRunId === run.id ? '' : run.id);
                }}>{inspectedRunId === run.id ? 'Close run details' : 'Inspect run'}</button>
              </article>
            ))}
          </div>
          {inspectedRunId && (
            <section className="workflow-run-detail" aria-label="Workflow run details">
              {runDetailError && <p role="status">{runDetailError}</p>}
              {runDetail?.id === inspectedRunId ? (
                <>
                  <h4>{runDetail.workflow_name}</h4>
                  <div>
                    {['queued', 'running', 'waiting_approval'].includes(runDetail.status) && (
                      <button type="button" disabled={runActionPending}
                        onClick={() => void actOnRun(runDetail.id, 'cancel')}>Cancel run</button>
                    )}
                    {['failed', 'cancelled', 'interrupted'].includes(runDetail.status) && (
                      <button type="button" disabled={runActionPending}
                        onClick={() => void actOnRun(runDetail.id, 'retry')}>Retry as new run</button>
                    )}
                    {runDetail.status === 'waiting_approval' && (
                      <button type="button" disabled={runActionPending}
                        onClick={() => void actOnRun(runDetail.id, 'resume')}>Request resume</button>
                    )}
                  </div>
                  {runActionMessage?.id === runDetail.id && <p role="status">{runActionMessage.text}</p>}
                  {runDetail.error && <p>{runDetail.error}</p>}
                  {runDetail.steps.length ? <ol>{runDetail.steps.map((step) => (
                    <li key={`${step.node_id}-${step.attempt}`}>
                      <strong>{step.node_id} · Attempt {step.attempt}</strong>
                      <p>{step.metadata.workflow_status === 'waiting_approval' ? 'Waiting for approval' : step.success ? 'Succeeded' : 'Failed'}</p>
                      {step.output && <pre>{step.output}</pre>}
                    </li>
                  ))}</ol> : <p>No steps recorded yet.</p>}
                  {runDetail.final_output && <><h5>Final output</h5><pre>{runDetail.final_output}</pre></>}
                </>
              ) : !runDetailError && <p role="status">Loading run details…</p>}
            </section>
          )}
          {!workflowRuns.length && <p>NO WORKFLOW RUNS RECORDED. START A GUARDED DELIVERY TO TEST THE LIVE APPROVAL PATH.</p>}
        </section>
        <section className="environment-preview"><header><div><span>ENVIRONMENT</span><strong>VIEW SURFACE</strong></div><Monitor size={13}/></header><div className="environment-tabs"><button className={environment === 'desktop' ? 'active' : ''} onClick={() => setEnvironment('desktop')}>DESKTOP</button><button className={environment === 'chrome' ? 'active' : ''} onClick={() => setEnvironment('chrome')}>CHROME</button></div>{environment === 'desktop' ? <div className="desktop-frame"><div className="desktop-top">SOFTWARE ENGINEERING DESKTOP</div><div className="desktop-windows"><span>CODE</span><span>TERMINAL</span><span>PREVIEW</span></div><p>DESKTOP CONTROL NOT CONNECTED</p></div> : <div className="chrome-frame"><div><i/><i/><i/><span>localhost / command-center</span></div><strong>OPENJARVIS PREVIEW</strong><p>BROWSER CONTROL NOT CONNECTED</p></div>}</section>
      </aside>
    </div>
  </main>;
}
