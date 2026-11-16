import { useMemo, useState } from 'react';
import { CalendarDays, ChevronLeft, ChevronRight, Grip, Plus, Settings2, X } from 'lucide-react';
import { useLocalPreference } from '../hooks/useLocalPreference';
import './custom-dashboard.css';

export type DashboardWidget = { id: string; stationId: string; station: string; name: string; value: string; detail: string; kind: 'metric' | 'calendar' | 'queue' | 'trend' | 'content' };
export const DASHBOARD_WIDGETS: DashboardWidget[] = [
  { id: 'dot-briefing', stationId: 'dot', station: 'DOT', name: 'CEO briefing', value: '7', detail: 'DECISIONS + UPDATES', kind: 'queue' },
  { id: 'brain-health', stationId: 'brain', station: 'SHARED BRAIN', name: 'Communication health', value: '98.4%', detail: '10 STATIONS SYNCHRONIZED', kind: 'metric' },
  { id: 'leads-found', stationId: 'growth', station: 'LEADS + GROWTH', name: 'Leads found', value: '148', detail: '+23 THIS WEEK', kind: 'metric' },
  { id: 'content-approval', stationId: 'marketing', station: 'MARKETING', name: 'Content to approve', value: '12', detail: '4 HIGH PRIORITY', kind: 'queue' },
  { id: 'social-pipeline', stationId: 'marketing', station: 'MARKETING', name: 'Social content pipeline', value: '4', detail: 'GENERATED → REVIEW → POSTED', kind: 'content' },
  { id: 'analytics-views', stationId: 'marketing', station: 'MARKETING', name: 'Google Analytics views', value: '24.8K', detail: '+18.6% VS PRIOR PERIOD', kind: 'trend' },
  { id: 'email-replies', stationId: 'email', station: 'EMAIL REPLY', name: 'Email replies due', value: '19', detail: '6 REQUIRE APPROVAL', kind: 'queue' },
  { id: 'comment-replies', stationId: 'email', station: 'EMAIL REPLY', name: 'Comment replies due', value: '31', detail: 'SOCIAL + COMMUNITY', kind: 'queue' },
  { id: 'revenue', stationId: 'finance', station: 'FINANCE', name: 'Revenue MTD', value: '$184K', detail: '72% OF MONTHLY TARGET', kind: 'trend' },
  { id: 'calendar', stationId: 'operations-manager', station: 'OPERATIONS MANAGER', name: 'Operating calendar', value: '8', detail: 'EVENTS THIS WEEK', kind: 'calendar' },
  { id: 'approvals', stationId: 'managers', station: 'MANAGERS', name: 'Approval queue', value: '6', detail: '2 EXECUTIVE DECISIONS', kind: 'queue' },
  { id: 'builder-proposals', stationId: 'system-builder', station: 'SYSTEM BUILDER', name: 'Improvement proposals', value: '3', detail: '1 READY FOR HUMAN REVIEW', kind: 'queue' },
];
export const DEFAULT_WIDGET_IDS = ['dot-briefing','brain-health','leads-found','content-approval','social-pipeline','analytics-views','email-replies','revenue','calendar','builder-proposals'];

export function CustomDashboard({ widgetIds, setWidgetIds, onOpenStation }: { widgetIds: string[]; setWidgetIds: (ids: string[]) => void; onOpenStation: (id: string) => void }) {
  const [editing, setEditing] = useState(false);
  const [sizes, setSizes] = useLocalPreference<Record<string, 'small' | 'medium' | 'large'>>(
    'openjarvis.command-center.widget-sizes.v1',
    () => ({ calendar: 'large', 'analytics-views': 'medium', 'social-pipeline': 'large' }),
    (value) => !!value && typeof value === 'object' && !Array.isArray(value) &&
      Object.values(value).every((size) => ['small', 'medium', 'large'].includes(size)),
  );
  const widgets = useMemo(() => widgetIds.map((id) => DASHBOARD_WIDGETS.find((widget) => widget.id === id)).filter(Boolean) as DashboardWidget[], [widgetIds]);
  const available = DASHBOARD_WIDGETS.filter((widget) => !widgetIds.includes(widget.id));
  const move = (index: number, delta: number) => { const next = [...widgetIds]; const target = index + delta; if (target < 0 || target >= next.length) return; [next[index], next[target]] = [next[target], next[index]]; setWidgetIds(next); };
  return <main className="custom-dashboard"><div className="dashboard-title"><div><span>CUSTOM DASHBOARD</span><h2>CEO operating picture</h2><p>Station-owned widgets. Add what matters, remove what does not.</p></div><button className={editing ? 'active' : ''} onClick={() => setEditing(!editing)}><Settings2 size={13}/>{editing ? 'DONE EDITING' : 'EDIT DASHBOARD'}</button></div>
    {editing && <section className="widget-catalog"><header><div><span>ADD WIDGET</span><strong>AVAILABLE FROM WORKSTATIONS</strong></div><em>{available.length} AVAILABLE</em></header><div>{available.length ? available.map((widget) => <button key={widget.id} onClick={() => setWidgetIds([...widgetIds, widget.id])}><Plus size={11}/><span><b>{widget.name}</b><small>{widget.station}</small></span></button>) : <p>All available widgets are already on the dashboard.</p>}</div></section>}
    {widgets.length ? <section className="widget-grid">{widgets.map((widget,index) => <article key={widget.id} className={`dashboard-widget ${sizes[widget.id] ?? (widget.kind === 'calendar' ? 'large' : 'small')}`}><header><button onClick={() => onOpenStation(widget.stationId)}>{widget.station}</button><span>DEMO DATA</span></header><div className="widget-content"><span>{widget.name}</span>{widget.kind !== 'content' && <><strong>{widget.value}</strong><small>{widget.detail}</small></>}{widget.kind === 'trend' && <div className="mini-trend"><i/><i/><i/><i/><i/><i/></div>}{widget.kind === 'calendar' && <div className="calendar-list"><p><b>09:00</b><span>Executive stand-up</span><em>DOT</em></p><p><b>11:30</b><span>Campaign approval</span><em>MKT</em></p><p><b>14:00</b><span>Engineering review</span><em>OPS</em></p></div>}{widget.kind === 'content' && <div className="content-pipeline"><article><div className="content-thumb">IG</div><div><b>Spring launch carousel</b><small>ChatGPT + Marketing · Instagram</small></div><em data-content-state="review">REVIEW</em></article><article><div className="content-thumb">TT</div><div><b>Behind-the-scenes reel</b><small>Gemini + Marketing · TikTok</small></div><em data-content-state="scheduled">SCHEDULED</em></article><article><div className="content-thumb">LI</div><div><b>Customer result story</b><small>Claude + Marketing · LinkedIn</small></div><em data-content-state="approved">APPROVED</em></article><article><div className="content-thumb posted">ALL</div><div><b>Weekly founder update</b><small>Dot + Marketing · multi-channel</small></div><em data-content-state="posted">POSTED · 2.8K</em></article></div>}</div>{editing && <footer><button aria-label={`Move ${widget.name} left`} onClick={() => move(index,-1)}><ChevronLeft size={11}/></button><button aria-label={`Move ${widget.name} right`} onClick={() => move(index,1)}><ChevronRight size={11}/></button><button aria-label={`Resize ${widget.name}`} onClick={() => setSizes((current) => ({...current,[widget.id]: current[widget.id] === 'large' ? 'small' : current[widget.id] === 'medium' ? 'large' : 'medium'}))}><Grip size={11}/>{(sizes[widget.id] ?? 'SMALL').toUpperCase()}</button><button aria-label={`Remove ${widget.name}`} onClick={() => setWidgetIds(widgetIds.filter((id) => id !== widget.id))}><X size={11}/></button></footer>}</article>)}</section> : <section className="dashboard-empty"><CalendarDays size={25}/><h3>Your dashboard is empty</h3><p>Add any widget from a workstation without changing that workstation's capability.</p><button onClick={() => setEditing(true)}><Plus size={12}/> ADD WIDGET</button></section>}
  </main>;
}
