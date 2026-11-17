import { FormEvent, type CSSProperties, useMemo, useRef, useState } from 'react';
import { Link } from 'react-router';
import { Activity, ArrowUp, Mic, MicOff, Plus, Square, Volume2 } from 'lucide-react';

import {
  Background,
  Handle,
  MarkerType,
  Position,
  ReactFlow,
  type Edge,
  type Node,
  type NodeProps,
} from '@xyflow/react';
import WorkflowBlueprint, {
  type WorkflowApp,
  type WorkflowGraph,
} from '../components/ui/interactive-workflow-blueprint';
import { OrbLoader } from '../components/ui/orb-loader';
import { useSpeech } from '../hooks/useSpeech';
import { useTts } from '../hooks/useTts';
import { useLocalPreference } from '../hooks/useLocalPreference';
import { streamChat } from '../lib/sse';
import { useAppStore } from '../lib/store';
import { SoftwareEngineeringWorkspace, type WorkspaceEntry } from './SoftwareEngineeringWorkspace';
import { CustomDashboard, DASHBOARD_WIDGETS, DEFAULT_WIDGET_IDS } from './CustomDashboard';
import { SharedBrainPanel } from './SharedBrainPanel';
import { GmailReviewList } from './GmailReviewList';
import { LeadRegister } from './LeadRegister';
import { Ga4PropertyForm } from './Ga4PropertyForm';
import { SocialContentStudio } from './SocialContentStudio';
import { StationProjectTasks } from './StationProjectTasks';
import { SystemBuilderLab } from './SystemBuilderLab';
import { WorkstationAgentActivity } from './WorkstationAgentActivity';
import './command-center.css';
import './overview-dashboard.css';

const STATION_AGENT_TEMPLATES: Record<string, string> = {
  'general-manager': 'general_manager',
  'operations-manager': 'operations_manager',
  finance: 'cfo_finance',
  research: 'competitive_research',
  email: 'email_briefing',
  managers: 'quality_manager',
  'system-builder': 'system_builder',
};

const DEFAULT_COMMAND_ACCENT = '#d6ad52';

type Station = {
  id: string;
  code: string;
  name: string;
  purpose: string;
  current: string;
  reportsTo: string;
  status: 'working' | 'review' | 'ready';
};

type VoiceMessage = { id: string; role: 'user' | 'dot'; text: string; shareable?: boolean };
type DotTurn = { request: string; reply: string };

const INITIAL_STATIONS: Station[] = [
  { id: 'brain', code: 'BRN', name: 'Shared Brain', purpose: 'Shared communication, context, ownership, and duplicate-work prevention for every agent.', current: 'Synchronizing context across all workstations', reportsTo: 'No one — shared service', status: 'working' },
  { id: 'dot', code: 'DOT', name: 'Dot', purpose: 'Your personal agent, assistant, and executive command link.', current: 'Compiling the CEO organization status update', reportsTo: 'CEO / Director', status: 'working' },
  { id: 'marketing', code: 'MKT', name: 'Marketing', purpose: 'Plans campaigns, produces creative, and monitors channel performance.', current: 'Preparing the spring campaign launch', reportsTo: 'General Manager', status: 'working' },
  { id: 'research', code: 'RSC', name: 'Research', purpose: 'Builds source-grounded market, customer, and competitor intelligence.', current: 'Validating competitor positioning sources', reportsTo: 'Operations Manager', status: 'working' },
  { id: 'managers', code: 'MGR', name: 'Managers', purpose: 'Reviews exceptions, assigns owners, and approves high-impact decisions.', current: 'Reviewing four approval requests', reportsTo: 'Operations Manager', status: 'review' },
  { id: 'email', code: 'EML', name: 'Email Reply', purpose: 'Triages inbound mail and prepares contextual, approval-aware replies.', current: 'Drafting replies for qualified leads', reportsTo: 'Operations Manager', status: 'working' },
  { id: 'finance', code: 'FIN', name: 'Finance', purpose: 'Tracks spend, forecasts cash, and flags variance before it grows.', current: 'Refreshing the monthly forecast', reportsTo: 'General Manager', status: 'working' },
  { id: 'growth', code: 'GRW', name: 'Leads + Growth', purpose: 'Qualifies demand and coordinates the path from signal to revenue.', current: 'Qualifying the newest inbound leads', reportsTo: 'General Manager', status: 'working' },
  { id: 'general-manager', code: 'GM', name: 'General Manager', purpose: 'Turns company goals into coordinated priorities and measurable decisions.', current: 'Aligning next week’s company priorities', reportsTo: 'Dot', status: 'review' },
  { id: 'operations-manager', code: 'OPS', name: 'Operations Manager', purpose: 'Keeps delivery on track, resolves blockers, and improves operating systems.', current: 'Removing delivery blockers across teams', reportsTo: 'Dot', status: 'working' },
  { id: 'system-builder', code: 'BLD', name: 'System Builder', purpose: 'Researches improvements, proposes features, prototypes safely, and requests approval before change.', current: 'Reviewing public dashboard and agent-workspace patterns', reportsTo: 'Operations Manager', status: 'working' },
];

const STACKS: Record<string, WorkflowApp[]> = {
  brain: [
    { id: 'orchestration', name: 'Orchestration', actions: [
      { label: 'Route request', detail: 'Choose the best station for the job.', kind: 'agent', tool: 'Dynamic router' },
      { label: 'Synthesize outputs', detail: 'Combine station results into one decision brief.', kind: 'agent', tool: 'Reasoning model' },
      { label: 'Escalate risk', detail: 'Send uncertain or high-impact work to a human.', kind: 'review', tool: 'Approval gate' },
    ] },
    { id: 'memory', name: 'Memory + Audit', actions: [
      { label: 'Recall context', detail: 'Load verified organizational memory.', kind: 'integration', tool: 'OpenJarvis memory' },
      { label: 'Save decision', detail: 'Record the outcome and supporting evidence.', kind: 'delivery', tool: 'Audit ledger' },
    ] },
  ],
  dot: [
    { id: 'voice', name: 'Voice + Conversation', actions: [
      { label: 'Listen', detail: 'Capture an owner voice command.', kind: 'trigger', tool: 'OpenJarvis speech' },
      { label: 'Speak response', detail: 'Read the final response using Jarvis voice.', kind: 'delivery', tool: 'OpenJarvis TTS' },
      { label: 'Broadcast', detail: 'Open an all-stations conversation.', kind: 'delivery', tool: 'Team room' },
    ] },
    { id: 'coordination', name: 'Coordination', actions: [
      { label: 'Assign General Manager', detail: 'Route a strategic operating decision.', kind: 'agent', tool: 'GM station' },
      { label: 'Assign Operations Manager', detail: 'Route an execution or process issue.', kind: 'agent', tool: 'OPS station' },
      { label: 'Request status', detail: 'Collect current work from every station.', kind: 'integration', tool: 'Live station bus' },
    ] },
  ],
  marketing: [
    { id: 'campaign', name: 'Campaign Engine', actions: [
      { label: 'Build brief', detail: 'Turn an objective into an executable campaign brief.', kind: 'agent', tool: 'Campaign planner' },
      { label: 'Create variants', detail: 'Generate channel-specific creative variations.', kind: 'agent', tool: 'Creative studio' },
      { label: 'Brand review', detail: 'Check voice, claims, and visual consistency.', kind: 'review', tool: 'Brand gate' },
    ] },
    { id: 'channels', name: 'Channels', actions: [
      { label: 'Prepare social', detail: 'Package approved content for social channels.', kind: 'delivery', tool: 'Publisher' },
      { label: 'Measure campaign', detail: 'Attach attribution and performance signals.', kind: 'integration', tool: 'Analytics' },
    ] },
  ],
  research: [
    { id: 'research-tools', name: 'Research Tools', actions: [
      { label: 'Search sources', detail: 'Collect primary and authoritative sources.', kind: 'integration', tool: 'Web research' },
      { label: 'Run experiment', detail: 'Test a hypothesis and retain the strongest result.', kind: 'agent', tool: 'Autoresearch loop' },
      { label: 'Verify citations', detail: 'Check every material claim against its source.', kind: 'review', tool: 'Grounded citations' },
    ] },
  ],
  managers: [
    { id: 'management', name: 'Management', actions: [
      { label: 'Assign owner', detail: 'Give a decision or task one accountable owner.', kind: 'agent', tool: 'Responsibility map' },
      { label: 'Approve exception', detail: 'Review a high-impact or low-confidence action.', kind: 'review', tool: 'Human gate' },
      { label: 'Escalate blocker', detail: 'Raise unresolved work to Operations or Dot.', kind: 'delivery', tool: 'Escalation bus' },
    ] },
  ],
  email: [
    { id: 'inbox', name: 'Inbox + Reach', actions: [
      { label: 'Triage message', detail: 'Classify intent, urgency, and sensitivity.', kind: 'agent', tool: 'Inbox triage' },
      { label: 'Draft reply', detail: 'Create a contextual answer without sending it.', kind: 'agent', tool: 'Reply writer' },
      { label: 'Verify recipient', detail: 'Check channel, recipient, and approval state.', kind: 'review', tool: 'Agent Reach' },
    ] },
  ],
  finance: [
    { id: 'finance-tools', name: 'Finance Controls', actions: [
      { label: 'Refresh forecast', detail: 'Update revenue, cost, and cash assumptions.', kind: 'agent', tool: 'Forecast model' },
      { label: 'Check variance', detail: 'Compare actuals with plan and flag movement.', kind: 'integration', tool: 'Variance engine' },
      { label: 'Budget approval', detail: 'Require review before committing spend.', kind: 'review', tool: 'Finance gate' },
    ] },
  ],
  growth: [
    { id: 'growth-tools', name: 'Growth Engine', actions: [
      { label: 'Qualify lead', detail: 'Score fit, intent, evidence, and exclusions.', kind: 'agent', tool: 'Lead qualifier' },
      { label: 'Enrich account', detail: 'Add lawful business context and activity.', kind: 'integration', tool: 'Agent Reach' },
      { label: 'Measure conversion', detail: 'Connect activity to pipeline and revenue.', kind: 'delivery', tool: 'Attribution' },
    ] },
  ],
  'general-manager': [
    { id: 'gm-tools', name: 'Executive Control', actions: [
      { label: 'Set priority', detail: 'Rank work by evidence, impact, effort, and risk.', kind: 'agent', tool: 'Decision matrix' },
      { label: 'Review performance', detail: 'Read operating, growth, and financial signals.', kind: 'integration', tool: 'Executive scorecard' },
      { label: 'Approve operating plan', detail: 'Submit the plan to Dot for coordination.', kind: 'review', tool: 'Dot checkpoint' },
    ] },
  ],
  'operations-manager': [
    { id: 'ops-tools', name: 'Operations Control', actions: [
      { label: 'Map process', detail: 'Convert work into owners, stages, and controls.', kind: 'agent', tool: 'Process mapper' },
      { label: 'Resolve blocker', detail: 'Diagnose the constraint and assign a recovery path.', kind: 'agent', tool: 'Execution debugger' },
      { label: 'Report to Dot', detail: 'Return delivery status, risks, and next action.', kind: 'delivery', tool: 'Dot checkpoint' },
    ] },
  ],
};

const FALLBACK_STACK = [{ id: 'station-tools', name: 'Station Tools', actions: [
  { label: 'Accept task', detail: 'Receive a routed assignment.', kind: 'trigger' as const, tool: 'Station bus' },
  { label: 'Perform work', detail: 'Execute the station’s defined responsibility.', kind: 'agent' as const, tool: 'OpenJarvis agent' },
  { label: 'Report outcome', detail: 'Return status and evidence to the parent station.', kind: 'delivery' as const, tool: 'Status channel' },
] }];

function makeGraph(station: Station): WorkflowGraph {
  const checkpoint = station.id === 'dot' ? 'The Brain checkpoint' : station.reportsTo === 'Dot' ? 'Dot checkpoint' : `${station.reportsTo} checkpoint`;
  return {
    nodes: [
      { id: `${station.id}-intake`, type: 'blueprint', position: { x: 20, y: 90 }, data: { label: 'Receive objective', detail: `Accept work routed to ${station.name}.`, kind: 'trigger', tool: 'Station bus' } },
      { id: `${station.id}-work`, type: 'blueprint', position: { x: 280, y: 90 }, data: { label: station.name, detail: station.purpose, kind: 'agent', tool: 'OpenJarvis agent' } },
      { id: `${station.id}-review`, type: 'blueprint', position: { x: 540, y: 90 }, data: { label: checkpoint, detail: 'Verify quality, evidence, permissions, and exceptions.', kind: 'review', tool: 'Approval policy' } },
      { id: `${station.id}-deliver`, type: 'blueprint', position: { x: 800, y: 90 }, data: { label: 'Report outcome', detail: `Return current work and results to ${station.reportsTo}.`, kind: 'delivery', tool: 'Live status' } },
    ],
    edges: [
      { id: `${station.id}-e1`, source: `${station.id}-intake`, target: `${station.id}-work`, type: 'blueprint' },
      { id: `${station.id}-e2`, source: `${station.id}-work`, target: `${station.id}-review`, type: 'blueprint' },
      { id: `${station.id}-e3`, source: `${station.id}-review`, target: `${station.id}-deliver`, type: 'blueprint' },
    ],
  };
}

function updateDefaultStationSteps(graph: WorkflowGraph, previous: Station, next: Station): WorkflowGraph {
  const oldNodes = makeGraph(previous).nodes;
  const newNodes = makeGraph(next).nodes;
  return {
    ...graph,
    nodes: graph.nodes.map((node) => {
      const oldStep = oldNodes.find((step) => step.id === node.id);
      const newStep = newNodes.find((step) => step.id === node.id);
      if (!oldStep || !newStep) return node;
      const label = node.data.label === oldStep.data.label ? newStep.data.label : node.data.label;
      const detail = node.data.detail === oldStep.data.detail ? newStep.data.detail : node.data.detail;
      if (label === node.data.label && detail === node.data.detail) return node;
      return { ...node, data: { ...node.data, label, detail } };
    }),
  };
}

type SpeechResultEvent = { results: { [index: number]: { [index: number]: { transcript: string } } } };
type BrowserRecognition = {
  lang: string;
  interimResults: boolean;
  continuous: boolean;
  start: () => void;
  stop: () => void;
  onresult: ((event: SpeechResultEvent) => void) | null;
  onend: (() => void) | null;
  onerror: (() => void) | null;
};
type BrowserRecognitionConstructor = new () => BrowserRecognition;

function DotVoice({ station, brainContext, onShare }: {
  station: Station;
  brainContext: string;
  onShare: (source: string, text: string) => string;
}) {
  const speech = useSpeech();
  const tts = useTts();
  const selectedModel = useAppStore((state) => state.selectedModel);
  const [includeBrainBrief, setIncludeBrainBrief] = useState(false);
  const [input, setInput] = useState('');
  const [shareStatus, setShareStatus] = useState('');
  const [browserListening, setBrowserListening] = useState(false);
  const [thinking, setThinking] = useState(false);
  const [messages, setMessages] = useState<VoiceMessage[]>([
    { id: 'welcome', role: 'dot', text: 'Dot online. Select a station, speak, or type a command.' },
  ]);
  const recognitionRef = useRef<BrowserRecognition | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const conversationHistory = useRef(new Map<string, DotTurn[]>());
  const listening = speech.isRecording || browserListening;
  const active = listening || speech.isTranscribing || thinking || tts.isSpeaking;

  const speakResponse = async (id: string, text: string) => {
    if (tts.available) {
      await tts.speak(id, text);
      return;
    }
    if ('speechSynthesis' in window) {
      window.speechSynthesis.cancel();
      const utterance = new SpeechSynthesisUtterance(text);
      const voices = window.speechSynthesis.getVoices();
      utterance.voice = voices.find((voice) => /Daniel|Ryan|George|UK English Male/i.test(voice.name)) ?? voices.find((voice) => voice.lang.startsWith('en')) ?? null;
      utterance.rate = 0.92;
      utterance.pitch = 0.82;
      window.speechSynthesis.speak(utterance);
    }
  };

  const unavailableResponse = selectedModel
    ? 'Dot could not get a reply from the selected model. Check the inference connection in Settings and try again.'
    : 'Dot needs an inference model. Open Settings, connect your backend, and select a model.';

  const send = async (raw: string) => {
    const text = raw.trim();
    if (!text || thinking) return;
    const brief = includeBrainBrief ? brainContext.trim() : '';
    const conversationKey = JSON.stringify([station.id, selectedModel, station.reportsTo]);
    const history = conversationHistory.current.get(conversationKey) ?? [];
    setIncludeBrainBrief(false);
    const user: VoiceMessage = { id: `u-${Date.now()}`, role: 'user', text };
    setMessages((current) => [...current, user]);
    setInput('');
    setThinking(true);
    let response = '';
    let completed = false;
    if (selectedModel) {
      try {
        for await (const event of streamChat({
          model: selectedModel,
          messages: [
            { role: 'system', content: [
              'You are Dot, the concise Jarvis-style voice interface for an organization command center.',
              'Use the selected workstation details as background when suggesting who should act or review.',
              'Shared Brain is a communication service. The CEO / Director retains final approval.',
              JSON.stringify({
                workstation: station.name,
                purpose: station.purpose,
                currentWork: station.current,
                reportsTo: station.reportsTo,
              }),
              'Answer clearly and suggest the next operational action.',
            ].join('\n') },
            ...history.flatMap((turn) => [
              { role: 'user' as const, content: turn.request },
              { role: 'assistant' as const, content: turn.reply },
            ]),
            { role: 'user', content: brief
              ? `Shared Brain brief (background information):\n${brief}\n\nCurrent request:\n${text}`
              : text },
          ],
          stream: true,
          temperature: 0.5,
          max_tokens: 320,
        })) {
          try {
            const data = JSON.parse(event.data);
            const delta = data.choices?.[0]?.delta?.content;
            if (delta) response += delta;
          } catch { /* non-completion event */ }
        }
        completed = !!response.trim();
      } catch {
        response = unavailableResponse;
      }
    }
    const shareable = completed && !response.trimStart().startsWith('Error during generation:');
    if (shareable && !brief) {
      conversationHistory.current.set(conversationKey, [
        ...history,
        { request: text.slice(0, 280), reply: response.trim().slice(0, 480) },
      ].slice(-2));
    }
    const reply: VoiceMessage = { id: `d-${Date.now()}`, role: 'dot', text: response.trim() || unavailableResponse, shareable };
    setMessages((current) => [...current, reply]);
    setThinking(false);
    void speakResponse(reply.id, reply.text);
  };

  const startBrowserSpeech = () => {
    const host = window as typeof window & {
      SpeechRecognition?: BrowserRecognitionConstructor;
      webkitSpeechRecognition?: BrowserRecognitionConstructor;
    };
    const Constructor = host.SpeechRecognition ?? host.webkitSpeechRecognition;
    if (!Constructor) {
      inputRef.current?.focus();
      return;
    }
    const recognition = new Constructor();
    recognition.lang = 'en-AU';
    recognition.interimResults = false;
    recognition.continuous = false;
    recognition.onresult = (event) => {
      const transcript = event.results[0]?.[0]?.transcript ?? '';
      if (transcript) void send(transcript);
    };
    recognition.onend = () => setBrowserListening(false);
    recognition.onerror = () => setBrowserListening(false);
    recognitionRef.current = recognition;
    recognition.start();
    setBrowserListening(true);
  };

  const handleOrb = async () => {
    if (tts.isSpeaking) {
      tts.stop();
      window.speechSynthesis?.cancel();
      return;
    }
    if (speech.available) {
      if (speech.isRecording) {
        try {
          const transcript = await speech.stopRecording();
          if (transcript) await send(transcript);
        } catch { /* hook exposes the error */ }
      } else if (!speech.isTranscribing) {
        await speech.startRecording();
      }
      return;
    }
    if (browserListening) {
      recognitionRef.current?.stop();
      setBrowserListening(false);
    } else {
      startBrowserSpeech();
    }
  };

  const submit = (event: FormEvent) => {
    event.preventDefault();
    void send(input);
  };

  const stateLabel = speech.isTranscribing ? 'TRANSCRIBING' : listening ? 'LISTENING' : thinking ? 'THINKING' : tts.isSpeaking ? 'SPEAKING' : 'CLICK TO SPEAK';

  return (
    <aside className="dot-console" aria-label="Dot voice console">
      <div className="console-kicker"><span>DOT // VOICE LINK</span><span className={active ? 'live' : ''}>{active ? 'ACTIVE' : 'STANDBY'}</span></div>
      <button className="orb-trigger" onClick={() => void handleOrb()} aria-label={listening ? 'Stop listening' : 'Talk to Dot'}>
        <OrbLoader size={180} speed={active ? 1.75 : 0.55} label={`Dot ${stateLabel.toLowerCase()}`} />
        <span>{listening ? <MicOff size={13} /> : <Mic size={13} />}{stateLabel}</span>
      </button>
      <div className="voice-target"><span>ROUTING TO</span><strong>{station.name}</strong><small>{station.current}</small></div>
      <div className="voice-feed" aria-live="polite">
        {messages.slice(-4).map((message) => (
          <div key={message.id} className={`voice-message ${message.role}`}>
            <span>{message.role === 'dot' ? 'DOT' : 'YOU'}</span>
            <p>{message.text}</p>
            {message.shareable && (
              <button type="button" onClick={() => setShareStatus(onShare('Dot', message.text))}>
                Add to Shared Brain
              </button>
            )}
          </div>
        ))}
        {thinking && <div className="voice-message dot"><span>DOT</span><p>Processing through OpenJarvis…</p></div>}
      </div>
      {shareStatus && <p role="status">{shareStatus}</p>}
      <form className="voice-compose" onSubmit={submit}>
        <input ref={inputRef} value={input} onChange={(event) => setInput(event.target.value)} placeholder={`Command ${station.name} through Dot…`} />
        <button type="submit" aria-label="Send to Dot" disabled={!input.trim() || thinking}><ArrowUp size={15} /></button>
      </form>
      {brainContext.trim() && (
        <label>
          <input type="checkbox" checked={includeBrainBrief} disabled={active}
            onChange={(event) => setIncludeBrainBrief(event.target.checked)} />
          Include Shared Brain brief in next message
        </label>
      )}
      <div className="voice-meta"><span><Volume2 size={11} /> JARVIS VOICE</span><span>{selectedModel || 'LOCAL PREVIEW'}</span></div>
    </aside>
  );
}

type OrganizationNode = Node<{ station: Station; onOpen: (id: string) => void }, 'organization'>;

function OrganizationStation({ data }: NodeProps<OrganizationNode>) {
  const station = data.station;
  const isOwner = station.id === 'ceo';
  const isBrain = station.id === 'brain';
  return (
    <button className={`org-node ${isOwner ? 'owner-node' : ''} ${isBrain ? 'brain-node' : ''}`} data-station={station.id} disabled={isOwner} onClick={(event) => { event.stopPropagation(); if (!isOwner) data.onOpen(station.id); }} aria-label={isOwner ? 'CEO and Director owner node' : `Open ${station.name} workstation`}>
      {BRAIN_COLLABORATORS.includes(station) && <Handle type="source" position={Position.Top} id="collaborator-out" />}
      {!isBrain && <Handle type="source" position={Position.Top} id="reports-out" />}
      {!isBrain && <Handle type="source" position={Position.Bottom} id="brain-out" />}
      {!isBrain && <Handle type="target" position={Position.Bottom} id="reports-in" />}
      {isBrain && <Handle type="target" position={Position.Top} id="brain-in" />}
      {isBrain && <Handle type="target" position={Position.Bottom} id="collaborator-in" />}
      <div><span>{station.code}</span><i data-status={station.status} /></div>
      <strong>{station.name}</strong>
      <small>{station.current}</small>
      <em>{BRAIN_COLLABORATORS.includes(station) ? 'SHARED BRAIN COLLABORATOR' : isOwner ? 'ORGANIZATION OWNER' : isBrain ? 'SHARED BY EVERY AGENT' : `REPORTS TO ${station.reportsTo.toUpperCase()}`}</em>
    </button>
  );
}

const BRAIN_COLLABORATORS: Station[] = [
  { id: 'brain-chatgpt', code: 'GPT', name: 'ChatGPT', purpose: 'Shared Brain collaborator', current: 'Manual brief and update sharing', reportsTo: 'No one', status: 'ready' },
  { id: 'brain-codex', code: 'CDX', name: 'Codex', purpose: 'Shared Brain collaborator', current: 'Manual brief and update sharing', reportsTo: 'No one', status: 'ready' },
];

const organizationNodeTypes = { organization: OrganizationStation };

const ORGANIZATION_POSITIONS: Record<string, { x: number; y: number }> = {
  ceo: { x: 480, y: 15 }, dot: { x: 480, y: 150 },
  'general-manager': { x: 235, y: 300 }, 'operations-manager': { x: 725, y: 300 },
  finance: { x: 20, y: 455 }, growth: { x: 205, y: 455 }, marketing: { x: 390, y: 455 },
  research: { x: 650, y: 455 }, managers: { x: 835, y: 455 }, email: { x: 1020, y: 455 },
  brain: { x: 480, y: 625 },
  'brain-chatgpt': { x: 295, y: 780 }, 'brain-codex': { x: 665, y: 780 },
  'system-builder': { x: 1205, y: 455 },
};

function reportingManager(station: Station, stations: Station[]): Station | undefined {
  if (station.id === 'brain' || station.id === 'dot') return;
  return stations.find((candidate) => candidate.id !== 'brain' &&
    candidate.id !== station.id && candidate.name === station.reportsTo);
}

function canReportTo(station: Station, candidate: Station, stations: Station[]): boolean {
  const seen = new Set([station.id]);
  let manager: Station | undefined = candidate;
  while (manager) {
    if (manager.id === 'brain' || seen.has(manager.id)) return false;
    seen.add(manager.id);
    manager = reportingManager(manager, stations);
  }
  return true;
}

function OrganizationOverview({ stations, onOpen, accent }: {
  stations: Station[];
  onOpen: (id: string) => void;
  accent: string;
}) {
  const organizationStations = useMemo(() => [{ id: 'ceo', code: 'CEO', name: 'You — CEO / Director', purpose: 'Organization owner', current: 'Direction, final approval, and accountability', reportsTo: 'No one', status: 'working' as const }, ...stations, ...BRAIN_COLLABORATORS], [stations]);
  const nodes = useMemo<OrganizationNode[]>(() => organizationStations.map((station, index) => ({
    id: station.id,
    type: 'organization',
    position: ORGANIZATION_POSITIONS[station.id] ?? { x: 25 + (index % 5) * 185, y: 520 + Math.floor(index / 5) * 150 },
    data: {
      station,
      onOpen: BRAIN_COLLABORATORS.includes(station) ? () => onOpen('brain') : onOpen,
    },
    ariaLabel: BRAIN_COLLABORATORS.includes(station)
      ? `${station.name}. Shared Brain collaborator. ${station.current}`
      : `${station.name}. Reports to ${station.reportsTo}. ${station.current}`,
  })), [organizationStations, onOpen]);
  const existing = new Set(organizationStations.map((station) => station.id));
  const links = stations.map((station) => [
    station.id, station.id === 'dot' ? 'ceo' : reportingManager(station, stations)?.id ?? '',
  ]);
  const reportingEdges: Edge[] = links
    .filter(([source, target]) => existing.has(source) && existing.has(target))
    .map(([source, target]) => ({
      id: `org-${source}-${target}`,
      source,
      target,
      sourceHandle: 'reports-out',
      targetHandle: 'reports-in',
      type: 'smoothstep',
      animated: source === 'dot',
      markerEnd: { type: MarkerType.ArrowClosed, color: accent, width: 14, height: 14 },
      style: { stroke: accent === DEFAULT_COMMAND_ACCENT ? '#a77c2e' : 'var(--gold-bright)', strokeWidth: 1.5 },
    }));
  const brainEdges: Edge[] = [...stations, ...BRAIN_COLLABORATORS].filter((station) => station.id !== 'brain').map((station) => ({ id: `brain-${station.id}`, source: station.id, target: 'brain', sourceHandle: BRAIN_COLLABORATORS.includes(station) ? 'collaborator-out' : 'brain-out', targetHandle: BRAIN_COLLABORATORS.includes(station) ? 'collaborator-in' : 'brain-in', type: 'straight', animated: false, style: { stroke: '#8a7650', strokeWidth: 1.2, strokeDasharray: '5 7', opacity: .8 } }));
  const edges = [...reportingEdges, ...brainEdges];

  return (
    <main className="overview-page">
      <div className="view-heading"><div><span>ORGANIZATION OVERVIEW</span><h2>Chain of command + shared communication</h2><p>Solid arrows report upward to you. Dashed lines connect every agent to the same Shared Brain.</p></div><div className="overview-legend"><span><i data-kind="reporting" /> REPORTING</span><span><i data-kind="brain" /> SHARED BRAIN</span><span>CLICK A STATION TO OPEN</span></div></div>
      <section className="organization-map" aria-label="Organization connection overview">
        <ReactFlow<OrganizationNode> nodes={nodes} edges={edges} nodeTypes={organizationNodeTypes} onNodeClick={(_, node) => node.data.onOpen(node.id)} fitView fitViewOptions={{ padding: 0.12, maxZoom: 1 }} minZoom={0.45} maxZoom={1.35} nodesDraggable={false} nodesConnectable={false} zoomOnDoubleClick={false}>
          <Background color="#211a0c" gap={24} size={1} />
        </ReactFlow>
      </section>
      <div className="overview-summary">
        <div><span>EXECUTIVE CHAIN</span><strong>Teams → Management → Dot → You</strong><small>Formal accountability remains separate from shared communication.</small></div>
        <div><span>YOUR ASSISTANT</span><strong>Dot → CEO / Director</strong><small>Dot is your personal agent, command link, and consolidated briefing layer.</small></div>
        <div><span>SHARED COMMUNICATION</span><strong>Every agent ↔ Shared Brain</strong><small>Common context, ownership tracking, and duplicate-work prevention.</small></div>
      </div>
    </main>
  );
}

const LOAD: Record<string, number> = { brain: 82, dot: 76, marketing: 68, research: 54, managers: 43, email: 61, finance: 72, growth: 64, 'general-manager': 58, 'operations-manager': 71 };

function BasicDashboard({ stations, onOpen }: { stations: Station[]; onOpen: (id: string) => void }) {
  const working = stations.filter((station) => station.status === 'working').length;
  const review = stations.filter((station) => station.status === 'review');
  const averageLoad = Math.round(stations.reduce((total, station) => total + (LOAD[station.id] ?? 20), 0) / stations.length);
  return (
    <main className="dashboard-page">
      <div className="view-heading"><div><span>BASIC DASHBOARD</span><h2>Organization operating picture</h2><p>A concise view of current work, exceptions, capacity, and reporting health.</p></div><button onClick={() => onOpen('dot')}>OPEN DOT COMMAND LINK</button></div>
      <section className="metric-grid">
        <div><span>SYSTEM HEALTH</span><strong>98.4<small>%</small></strong><em>ALL CORE SERVICES NOMINAL</em></div>
        <div><span>ACTIVE STATIONS</span><strong>{working}<small>/{stations.length}</small></strong><em>{review.length} WAITING FOR REVIEW</em></div>
        <div><span>TASKS COMPLETED</span><strong>284</strong><em>+18 SINCE 09:00</em></div>
        <div><span>AVERAGE LOAD</span><strong>{averageLoad}<small>%</small></strong><em>WITHIN OPERATING RANGE</em></div>
      </section>
      <section className="dashboard-grid">
        <div className="dashboard-panel workload-panel">
          <header><div><span>LIVE WORKLOAD</span><strong>Stations by active capacity</strong></div><em>UPDATED NOW</em></header>
          <div className="workload-list">{stations.map((station) => {
            const load = LOAD[station.id] ?? 20;
            return <button key={station.id} onClick={() => onOpen(station.id)}><span>{station.code}</span><div><strong>{station.name}</strong><small>{station.current}</small><i><b style={{ width: `${load}%` }} /></i></div><em>{load}%</em></button>;
          })}</div>
        </div>
        <div className="dashboard-side">
          <section className="dashboard-panel approval-panel">
            <header><div><span>NEEDS ATTENTION</span><strong>Approval queue</strong></div><em>{review.length + 1} ITEMS</em></header>
            <button onClick={() => onOpen('managers')}><span>MGR</span><div><strong>Campaign approval</strong><small>Managers · confidence below 85%</small></div><em>HIGH</em></button>
            <button onClick={() => onOpen('general-manager')}><span>GM</span><div><strong>Growth investment decision</strong><small>General Manager · financial impact</small></div><em>REVIEW</em></button>
            <button onClick={() => onOpen('finance')}><span>FIN</span><div><strong>Budget variance</strong><small>Finance · software spend +6%</small></div><em>MED</em></button>
          </section>
          <section className="dashboard-panel priority-panel">
            <header><div><span>TOP PRIORITIES</span><strong>Current operating focus</strong></div><em>THIS WEEK</em></header>
            <ol><li><b>01</b><span>Complete growth brief and campaign review</span></li><li><b>02</b><span>Resolve delivery blockers across teams</span></li><li><b>03</b><span>Qualify and route the newest inbound leads</span></li></ol>
          </section>
        </div>
      </section>
    </main>
  );
}

export function CommandCenterPage() {
  const [view, setView] = useState<'overview' | 'workstations' | 'workspace' | 'dashboard'>('overview');
  const [workspaceEntry, setWorkspaceEntry] = useState<WorkspaceEntry>({});
  const openWorkspace = (entry: WorkspaceEntry) => {
    setWorkspaceEntry(entry);
    setView('workspace');
  };
  const openWorkflowReview = (id: string) => openWorkspace({ initialRunId: id });
  const openGmailReplyWorkflow = (reference: string) =>
    openWorkspace({ initialGmailReference: reference });
  const [stations, setStations] = useLocalPreference(
    'openjarvis.command-center.stations.v1',
    () => INITIAL_STATIONS,
    (value) => Array.isArray(value) && value.length > 0 &&
      value.every((station) => station && ['id', 'code', 'name', 'purpose', 'current', 'reportsTo', 'status']
        .every((field) => typeof station[field] === 'string')),
  );
  const [selectedId, setSelectedId] = useState('brain');
  const [graphs, setGraphs] = useLocalPreference<Record<string, WorkflowGraph>>(
    'openjarvis.command-center.graphs.v1',
    () => Object.fromEntries(INITIAL_STATIONS.map((station) => [station.id, makeGraph(station)])),
    (value) => !!value && typeof value === 'object' && !Array.isArray(value) &&
      Object.values(value).every((graph) => graph && Array.isArray(graph.nodes) && Array.isArray(graph.edges)),
  );
  const [adding, setAdding] = useState(false);
  const [newName, setNewName] = useState('');
  const [addStationError, setAddStationError] = useState('');
  const [brainContext, setBrainContext] = useLocalPreference(
    'openjarvis.command-center.brain-brief.v1',
    () => '',
    (value) => typeof value === 'string' && value.length <= 4000,
  );
  const addBrainUpdate = (source: string, text: string) => {
    const entry = `[${source}]\n${text.trim()}`;
    const current = brainContext.trim();
    const separator = '\n\n';
    if (`${separator}${current}${separator}`.includes(`${separator}${entry}${separator}`)) {
      return 'This update is already in the brief.';
    }
    const next = [current, entry].filter(Boolean).join(separator);
    if (next.length > 4000) return 'The brief is full. Shorten it before adding this update.';
    setBrainContext(next);
    return 'Added to Shared Brain.';
  };
  const [stationEditMessage, setStationEditMessage] = useState<{ id: string; text: string } | null>(null);
  const [stationAgentIds, setStationAgentIds] = useLocalPreference<Record<string, string>>(
    'openjarvis.command-center.station-agents.v1',
    () => ({}),
    (value) => !!value && typeof value === 'object' && !Array.isArray(value) &&
      Object.values(value).every((id) => typeof id === 'string'),
  );
  const workflowRecipients = stations.flatMap((station) => {
    const agentId = stationAgentIds[station.id];
    return agentId ? [{ stationId: station.id, name: station.name, agentId }] : [];
  });
  const workflowReportingRoutes = stations.flatMap((station) => {
    const manager = reportingManager(station, stations);
    return manager ? [{
      stationId: station.id, stationName: station.name,
      managerId: manager.id, managerName: manager.name,
    }] : [];
  });
  const [dashboardWidgetIds, setDashboardWidgetIds] = useLocalPreference(
    'openjarvis.command-center.widget-order.v1',
    () => DEFAULT_WIDGET_IDS,
    (value) => Array.isArray(value) && value.every((id) => typeof id === 'string'),
  );
  const [accent, setAccent] = useLocalPreference(
    'openjarvis.command-center.accent.v1',
    () => DEFAULT_COMMAND_ACCENT,
    (value) => typeof value === 'string' && /^#[0-9a-f]{6}$/i.test(value),
  );
  const accentStyle = accent === DEFAULT_COMMAND_ACCENT ? undefined : {
    '--gold': accent,
    '--gold-bright': 'color-mix(in srgb, var(--gold), white 28%)',
    '--gold-dim': 'color-mix(in srgb, var(--gold), black 45%)',
  } as CSSProperties;
  const selected = stations.find((station) => station.id === selectedId) ?? stations[0];
  const managerOptions = selected.id === 'dot' || selected.id === 'brain' ? []
    : stations.filter((station) => canReportTo(selected, station, stations));
  const apps = useMemo(() => STACKS[selected.id] ?? FALLBACK_STACK, [selected.id]);
  const stationWidgets = DASHBOARD_WIDGETS.filter((widget) => widget.stationId === selected.id);

  const openStation = (id: string) => {
    setSelectedId(id);
    setView('workstations');
  };

  const addStation = (event: FormEvent) => {
    event.preventDefault();
    const name = newName.trim();
    if (!name) return;
    if (stations.some((station) => station.name.toLowerCase() === name.toLowerCase())) {
      setAddStationError('A workstation with this name already exists.');
      return;
    }
    const id = `${name.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '')}-${Date.now()}`;
    const managerName = stations.find((station) => station.id === 'operations-manager')?.name;
    const station: Station = { id, code: name.slice(0, 3).toUpperCase(), name, purpose: 'A configurable specialist workstation connected to Shared Brain.', current: 'Waiting for its first objective', reportsTo: managerName ?? 'Operations Manager', status: 'ready' };
    setStations((current) => [...current, station]);
    setGraphs((current) => ({ ...current, [id]: makeGraph(station) }));
    setSelectedId(id);
    setNewName('');
    setAddStationError('');
    setAdding(false);
  };

  const editStation = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const fields = new FormData(event.currentTarget);
    const name = String(fields.get('station-name') ?? '').trim();
    const purpose = String(fields.get('station-purpose') ?? '').trim();
    const current = String(fields.get('station-current') ?? '').trim();
    const managerId = fields.get('station-manager');
    const manager = managerOptions.find((option) => option.id === managerId);
    if (managerId !== null && !manager) {
      setStationEditMessage({ id: selected.id, text: 'Choose a valid reporting manager.' });
      return;
    }
    if (!name || !purpose || !current) {
      setStationEditMessage({ id: selected.id, text: 'Fill in all workstation fields.' });
      return;
    }
    if (name !== selected.name && stations.some((station) =>
      station.id !== selected.id && station.name.toLowerCase() === name.toLowerCase()
    )) {
      setStationEditMessage({ id: selected.id, text: 'A workstation with this name already exists.' });
      return;
    }
    const nextStations = stations.map((station) => {
      if (station.id === selected.id) return { ...station, name, purpose, current, reportsTo: manager?.name ?? station.reportsTo };
      return name !== selected.name && reportingManager(station, stations)?.id === selected.id
        ? { ...station, reportsTo: name } : station;
    });
    setStations(nextStations);
    setGraphs((previous) => {
      const nextGraphs = { ...previous };
      nextStations.forEach((station, index) => {
        const oldStation = stations[index];
        if (station !== oldStation && previous[station.id]) {
          nextGraphs[station.id] = updateDefaultStationSteps(previous[station.id], oldStation, station);
        }
      });
      return nextGraphs;
    });
    setStationEditMessage({ id: selected.id, text: 'Workstation details saved.' });
  };

  return (
    <div className="jarvis-command" style={accentStyle} data-custom-accent={accentStyle ? 'true' : undefined}>
      <header className="command-header">
        <div><span className="command-eyebrow">OPENJARVIS // ORGANIZATION CONTROL</span><h1>COMMAND CENTER</h1></div>
        <nav className="command-view-nav" aria-label="Command center views">
          <button className={view === 'overview' ? 'active' : ''} onClick={() => setView('overview')}>OVERVIEW</button>
          <button className={view === 'workstations' ? 'active' : ''} onClick={() => setView('workstations')}>WORKSTATIONS</button>
          <button className={view === 'workspace' ? 'active' : ''} onClick={() => { if (view !== 'workspace') openWorkflowReview(''); }}>WORKSPACE</button>
          <button className={view === 'dashboard' ? 'active' : ''} onClick={() => setView('dashboard')}>DASHBOARD</button>
        </nav>
        <div className="header-telemetry"><span><i /> SYSTEM ONLINE</span><span>{stations.length} STATIONS</span><span>LOCAL FIRST</span></div>
      </header>
      {view === 'overview' ? <OrganizationOverview stations={stations} onOpen={openStation} accent={accent} /> : view === 'workspace' ? <SoftwareEngineeringWorkspace {...workspaceEntry} recipients={workflowRecipients} projectStations={stations} reportingRoutes={workflowReportingRoutes} onOpenStation={openStation} /> : view === 'dashboard' ? <CustomDashboard widgetIds={dashboardWidgetIds} setWidgetIds={setDashboardWidgetIds} onOpenStation={openStation} onOpenWorkflow={openWorkflowReview}
        onOpenRecurringWorkflow={(initialDefinitionId, initialRecurrenceId) =>
          openWorkspace({ initialDefinitionId, initialRecurrenceId })} /> : <div className="command-grid">
        <aside className="station-rail">
          <div className="rail-head"><div><span>WORKSTATIONS</span><strong>{stations.length} ACTIVE</strong></div><button onClick={() => setAdding((value) => !value)} aria-label="Add workstation"><Plus size={15} /></button></div>
          {adding && <>
            <form className="station-add" onSubmit={addStation}><input autoFocus value={newName} onChange={(event) => {
              setNewName(event.target.value);
              setAddStationError('');
            }} placeholder="Station name" /><button type="submit">ADD</button></form>
            {addStationError && <p role="status">{addStationError}</p>}
          </>}
          <div className="station-list">
            {stations.map((station) => (
              <button key={station.id} className={station.id === selected.id ? 'selected' : ''} onClick={() => setSelectedId(station.id)}>
                <span className="station-code">{station.code}</span>
                <span className="station-copy"><strong>{station.name}</strong><small>{station.current}</small></span>
                <i data-status={station.status} />
              </button>
            ))}
          </div>
          <div className="rail-foot"><Activity size={13} /><span>LIVE WORK FEED</span><b>284</b></div>
        </aside>

        {selected.id === 'brain' ? <section className="workflow-stage brain-stage"><SharedBrainPanel context={brainContext} onContextChange={setBrainContext} onShare={addBrainUpdate} onOpenDot={() => openStation('dot')} onOpenWorkflow={openWorkflowReview} /></section> : <main className="workflow-stage">
          <div className="station-header">
            <div><span>{selected.code} // SELECTED STATION</span><h2>{selected.name}</h2><p>{selected.purpose}</p></div>
            <div className="station-now"><span>CURRENT WORK</span><strong>{selected.current}</strong><small>Reports to {selected.reportsTo}</small></div>
          </div>
          <details className="station-details-editor" key={`station-details-${selected.id}`}>
            <summary>Edit workstation details</summary>
            <form onSubmit={editStation}>
              <label>Name <input name="station-name" defaultValue={selected.name} maxLength={80} required /></label>
              <label>Purpose <textarea name="station-purpose" defaultValue={selected.purpose} maxLength={400} required /></label>
              <label>Current-work note <textarea name="station-current" defaultValue={selected.current} maxLength={400} required /></label>
              {managerOptions.length > 0 && (
                <label><span id="station-manager-label">Reports to</span>
                  <select name="station-manager" aria-labelledby="station-manager-label"
                    defaultValue={reportingManager(selected, stations)?.id ?? ''} required>
                    <option value="">Choose a workstation</option>
                    {managerOptions.map((manager) => <option key={manager.id} value={manager.id}>{manager.name}</option>)}
                  </select>
                </label>
              )}
              <button type="submit">Save workstation</button>
            </form>
            {stationEditMessage?.id === selected.id && <p role="status">{stationEditMessage.text}</p>}
          </details>
          <section className="station-widget-options">
            <div><span>DASHBOARD WIDGETS</span><strong>{stationWidgets.length ? `${stationWidgets.length} AVAILABLE FROM ${selected.name.toUpperCase()}` : 'NO WIDGETS REGISTERED'}</strong></div>
            <div>{stationWidgets.map((widget) => {
              const added = dashboardWidgetIds.includes(widget.id);
              return <button key={widget.id} className={added ? 'added' : ''} onClick={() => setDashboardWidgetIds(added ? dashboardWidgetIds.filter((id) => id !== widget.id) : [...dashboardWidgetIds, widget.id])}>{added ? 'REMOVE' : '+ ADD'} {widget.name.toUpperCase()}</button>;
            })}</div>
          </section>
          {selected.id === 'finance' && (
            <>
            <section className="station-widget-options" aria-label="Finance workpapers">
              <div>
                <strong>Finance workpapers</strong>
                <button type="button" onClick={() => openWorkspace({ initialStarter: 'finance' })}>
                  Open workpaper workflow
                </button>
              </div>
              <p>Search indexed invoices and receipts, then review the draft against its sources.</p>
            </section>
            <GmailReviewList onOpenFinance={(initialUploadReference) =>
              openWorkspace({ initialStarter: 'finance', initialUploadReference })} />
            </>
          )}
          {selected.id === 'growth' && (
            <LeadRegister onOpenDiscovery={() => openWorkspace({ initialStarter: 'leads' })} />
          )}
          {selected.id === 'research' && (
            <section className="station-widget-options" aria-label="Competitor advertising">
              <div>
                <strong>Competitor ad review</strong>
                <button type="button" onClick={() => openWorkspace({ initialStarter: 'competitor-ads' })}>
                  Open competitor ad workflow
                </button>
              </div>
              <p>Compare indexed ads by offer and observed dates, then review an experiment grounded in the evidence.</p>
            </section>
          )}
          {selected.id === 'managers' && (
            <section className="station-widget-options" aria-label="Delivery quality">
              <div>
                <strong>Delivery quality review</strong>
                <button type="button" onClick={() => openWorkspace({ initialStarter: 'delivery-quality' })}>
                  Open delivery quality workflow
                </button>
              </div>
              <p>Check indexed copy or transcripts against the brief and review the findings before handoff.</p>
            </section>
          )}
          {selected.id === 'email' && <GmailReviewList onOpenWorkflow={openGmailReplyWorkflow} />}
          {selected.id === 'marketing' && <><Ga4PropertyForm /><SocialContentStudio /></>}
          {selected.id === 'system-builder' && (
            <SystemBuilderLab onOpenResearch={() => openWorkspace({ initialStarter: 'builder-research' })} onOpenWorkflow={openWorkflowReview} />
          )}
          <StationProjectTasks key={`station-tasks-${selected.id}`} stationId={selected.id}
            onOpenTask={(initialProjectFolder, initialProjectTaskId) =>
              openWorkspace({ initialProjectFolder, initialProjectTaskId })} />
          {STATION_AGENT_TEMPLATES[selected.id] && (
            <Link to={`/agents?template=${STATION_AGENT_TEMPLATES[selected.id]}`}>
              Configure {selected.name} agent ↗
            </Link>
          )}
          <WorkstationAgentActivity
            key={`station-agent-${selected.id}`}
            agentId={stationAgentIds[selected.id] ?? ''}
            stationName={selected.name}
            templateId={STATION_AGENT_TEMPLATES[selected.id]}
            brainContext={brainContext}
            onShare={(text) => addBrainUpdate(selected.name, text)}
            onSelect={(id) => setStationAgentIds((previous) => ({ ...previous, [selected.id]: id }))}
            onOpenWorkflow={openWorkflowReview}
          />
          <WorkflowBlueprint
            key={JSON.stringify([selected.id, selected.name, selected.purpose, selected.reportsTo])}
            className="gold-blueprint"
            title={`${selected.name} connection map`}
            initialGraph={graphs[selected.id] ?? makeGraph(selected)}
            apps={apps}
            agentTemplate={{ label: `New ${selected.name} agent`, detail: `Add a specialist inside ${selected.name}.`, kind: 'agent', tool: 'OpenJarvis agent' }}
            onChange={(graph) => setGraphs((current) => ({ ...current, [selected.id]: graph }))}
          />
        </main>}

        <DotVoice station={selected} brainContext={brainContext} onShare={addBrainUpdate} />
      </div>}
      <footer className="command-footer">
        <span><Square size={7} fill="currentColor" /> BLACK OAK OPERATING SYSTEM</span>
        <span>DOT VOICE ROUTER // OPENJARVIS RUNTIME</span>
        <label className="command-accent-control">
          Accent color
          <input type="color" value={accent} onChange={(event) => setAccent(event.target.value)} />
        </label>
        <button type="button" onClick={() => setAccent(DEFAULT_COMMAND_ACCENT)} disabled={accent === DEFAULT_COMMAND_ACCENT}>
          Reset gold
        </button>
      </footer>
    </div>
  );
}
