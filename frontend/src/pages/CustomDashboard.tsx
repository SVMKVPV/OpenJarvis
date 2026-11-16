import { useEffect, useMemo, useState } from 'react';
import { CalendarDays, ChevronLeft, ChevronRight, Grip, Plus, Settings2, X } from 'lucide-react';
import { useLocalPreference } from '../hooks/useLocalPreference';
import {
  fetchGmailReviewCount, fetchIndexedCalendarEvents, fetchPendingApprovals, fetchWorkflowRuns,
  type IndexedCalendarEvent, type PendingApproval, type WorkflowRunSummary,
} from '../lib/api';
import {
  fetchSocialContentSummary, SOCIAL_CHANNELS, type SocialContentSummary,
} from '../lib/social-content-api';
import './custom-dashboard.css';

export type DashboardWidget = { id: string; stationId: string; station: string; name: string; value: string; detail: string; kind: 'metric' | 'calendar' | 'queue' | 'trend' | 'content' };
export const DASHBOARD_WIDGETS: DashboardWidget[] = [
  { id: 'dot-briefing', stationId: 'dot', station: 'DOT', name: 'CEO briefing', value: '7', detail: 'DECISIONS + UPDATES', kind: 'queue' },
  { id: 'brain-health', stationId: 'brain', station: 'SHARED BRAIN', name: 'Communication health', value: '98.4%', detail: '10 STATIONS SYNCHRONIZED', kind: 'metric' },
  { id: 'leads-found', stationId: 'growth', station: 'LEADS + GROWTH', name: 'Leads found', value: '148', detail: '+23 THIS WEEK', kind: 'metric' },
  { id: 'content-approval', stationId: 'marketing', station: 'MARKETING', name: 'Content to approve', value: '', detail: 'Waiting for review', kind: 'queue' },
  { id: 'social-pipeline', stationId: 'marketing', station: 'MARKETING', name: 'Social content pipeline', value: '', detail: 'Recent drafts and planned content', kind: 'content' },
  { id: 'analytics-views', stationId: 'marketing', station: 'MARKETING', name: 'Google Analytics views', value: '24.8K', detail: '+18.6% VS PRIOR PERIOD', kind: 'trend' },
  { id: 'email-replies', stationId: 'email', station: 'EMAIL REPLY', name: 'Gmail threads to review', value: '', detail: 'Latest indexed message is inbound', kind: 'queue' },
  { id: 'comment-replies', stationId: 'email', station: 'EMAIL REPLY', name: 'Comment replies due', value: '31', detail: 'SOCIAL + COMMUNITY', kind: 'queue' },
  { id: 'revenue', stationId: 'finance', station: 'FINANCE', name: 'Revenue MTD', value: '$184K', detail: '72% OF MONTHLY TARGET', kind: 'trend' },
  { id: 'calendar', stationId: 'operations-manager', station: 'OPERATIONS MANAGER', name: 'Operating calendar', value: '', detail: 'Upcoming workflow runs', kind: 'calendar' },
  { id: 'approvals', stationId: 'managers', station: 'MANAGERS', name: 'Approval queue', value: '6', detail: '2 EXECUTIVE DECISIONS', kind: 'queue' },
  { id: 'builder-proposals', stationId: 'system-builder', station: 'SYSTEM BUILDER', name: 'Improvement proposals', value: '3', detail: '1 READY FOR HUMAN REVIEW', kind: 'queue' },
];
export const DEFAULT_WIDGET_IDS = ['dot-briefing','brain-health','leads-found','content-approval','social-pipeline','analytics-views','email-replies','revenue','calendar','builder-proposals'];

type ScheduledRun = WorkflowRunSummary & { scheduled_at: number };

export function CustomDashboard({ widgetIds, setWidgetIds, onOpenStation, onOpenWorkflow }: {
  widgetIds: string[];
  setWidgetIds: (ids: string[]) => void;
  onOpenStation: (id: string) => void;
  onOpenWorkflow: (id: string) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [pendingApprovals, setPendingApprovals] = useState<PendingApproval[] | null>(null);
  const approvalCount = pendingApprovals?.length ?? null;
  const workflowApprovals = (pendingApprovals ?? []).flatMap((approval) => {
    const runId = approval.payload.workflow_run_id;
    return typeof runId === 'string' && runId ? [{ approval, runId }] : [];
  });
  const [approvalDetail, setApprovalDetail] = useState('Checking approval queue…');
  const showApprovals = widgetIds.includes('approvals');

  useEffect(() => {
    if (!showApprovals) return;
    let active = true;
    let timer: number | undefined;
    const refresh = async () => {
      try {
        const approvals = await fetchPendingApprovals();
        if (!active) return;
        setPendingApprovals(approvals);
        setApprovalDetail('Pending decisions');
      } catch {
        if (!active) return;
        setPendingApprovals(null);
        setApprovalDetail('Approval queue unavailable');
      } finally {
        if (active) timer = window.setTimeout(() => void refresh(), 15000);
      }
    };
    void refresh();
    return () => {
      active = false;
      window.clearTimeout(timer);
    };
  }, [showApprovals]);
  const [scheduledRuns, setScheduledRuns] = useState<ScheduledRun[] | null>(null);
  const [calendarMessage, setCalendarMessage] = useState('Checking scheduled workflows…');
  const [calendarEvents, setCalendarEvents] = useState<IndexedCalendarEvent[] | null>(null);
  const [eventMessage, setEventMessage] = useState('Checking indexed events…');
  const showCalendar = widgetIds.includes('calendar');

  useEffect(() => {
    if (!showCalendar) return;
    let active = true;
    let timer: number | undefined;
    const refresh = async () => {
      const now = new Date();
      const localDay = new Date(now.getTime() - now.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
      const [runs, events] = await Promise.allSettled([
        fetchWorkflowRuns('scheduled'), fetchIndexedCalendarEvents(localDay),
      ]);
      if (!active) return;
      if (runs.status === 'fulfilled') {
        const scheduled = runs.value.filter((run): run is ScheduledRun =>
          typeof run.scheduled_at === 'number' &&
          Number.isFinite(new Date(run.scheduled_at * 1000).getTime()));
        setScheduledRuns(scheduled);
        setCalendarMessage(scheduled.length ? '' : 'No scheduled workflows.');
      } else {
        setScheduledRuns(null);
        setCalendarMessage('Workflow calendar unavailable.');
      }
      if (events.status === 'fulfilled') {
        setCalendarEvents(events.value);
        setEventMessage(events.value.length ? '' : 'No upcoming events in the index.');
      } else {
        setCalendarEvents(null);
        setEventMessage('Indexed Google Calendar events unavailable.');
      }
      timer = window.setTimeout(() => void refresh(), 15000);
    };
    void refresh();
    return () => {
      active = false;
      window.clearTimeout(timer);
    };
  }, [showCalendar]);

  const [socialQueue, setSocialQueue] = useState<SocialContentSummary | null>(null);
  const [socialUnavailable, setSocialUnavailable] = useState(false);
  const showSocialQueue = widgetIds.includes('content-approval') || widgetIds.includes('social-pipeline');

  useEffect(() => {
    if (!showSocialQueue) return;
    const controller = new AbortController();
    let timer: number | undefined;
    const refresh = async () => {
      try {
        const summary = await fetchSocialContentSummary(controller.signal);
        if (controller.signal.aborted) return;
        setSocialQueue(summary);
        setSocialUnavailable(false);
      } catch {
        if (controller.signal.aborted) return;
        setSocialQueue(null);
        setSocialUnavailable(true);
      } finally {
        if (!controller.signal.aborted) timer = window.setTimeout(() => void refresh(), 15000);
      }
    };
    void refresh();
    return () => {
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [showSocialQueue]);

  const socialMessage = socialUnavailable ? 'Marketing queue unavailable.' : 'Checking Marketing queue…';
  const showGmail = widgetIds.includes('email-replies');
  const [gmail, setGmail] = useState<{ count: number | null; detail: string }>({
    count: null, detail: 'Checking Gmail index…',
  });

  useEffect(() => {
    if (!showGmail) return;
    const controller = new AbortController();
    let timer: number | undefined;
    const refresh = async () => {
      try {
        const count = await fetchGmailReviewCount(controller.signal);
        if (!controller.signal.aborted) setGmail({
          count,
          detail: count === null ? 'No indexed inbox or sent threads' : 'Latest indexed inbox or sent message is inbound',
        });
      } catch {
        if (!controller.signal.aborted) setGmail({ count: null, detail: 'Gmail index unavailable' });
      } finally {
        if (!controller.signal.aborted) timer = window.setTimeout(() => void refresh(), 15000);
      }
    };
    void refresh();
    return () => {
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [showGmail]);

  const queueMetrics: Record<string, { value: string | number; detail: string }> = {
    'email-replies': { value: gmail.count ?? '—', detail: gmail.detail },
    approvals: { value: approvalCount ?? '—', detail: approvalDetail },
    'content-approval': {
      value: socialQueue?.review_count ?? '—',
      detail: socialQueue ? 'Waiting for review' : socialMessage,
    },
  };

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
    {widgets.length ? <section className="widget-grid">{widgets.map((widget,index) => <article key={widget.id} className={`dashboard-widget ${sizes[widget.id] ?? (widget.kind === 'calendar' ? 'large' : 'small')}`}><header><button onClick={() => onOpenStation(widget.stationId)}>{widget.station}</button><span>{widget.id === 'approvals' ? (approvalCount !== null ? 'LIVE DATA' : 'BACKEND') : widget.kind === 'calendar' ? (scheduledRuns !== null ? 'LIVE WORKFLOWS' : 'BACKEND') : widget.id === 'content-approval' || widget.id === 'social-pipeline' ? (socialQueue ? 'LIVE QUEUE' : 'BACKEND') : widget.id === 'email-replies' ? 'GMAIL INDEX' : 'DEMO DATA'}</span></header><div className="widget-content"><span>{widget.name}</span>{widget.kind !== 'content' && widget.kind !== 'calendar' && <><strong>{queueMetrics[widget.id]?.value ?? widget.value}</strong><small>{queueMetrics[widget.id]?.detail ?? widget.detail}</small></>}{widget.id === 'approvals' && workflowApprovals.length > 0 && (
      <ul className="dashboard-workflow-approvals" aria-label="Workflow approvals">
        {workflowApprovals.slice(0, 3).map(({ approval, runId }) => (
          <li key={approval.id}>
            <button type="button" onClick={() => onOpenWorkflow(runId)}>{approval.description || 'Review workflow run'}</button>
          </li>
        ))}
      </ul>
    )}{widget.kind === 'trend' && <div className="mini-trend"><i/><i/><i/><i/><i/><i/></div>}{widget.kind === 'calendar' && (
      <>
        <small>{widget.detail}</small>
        {calendarMessage && <p role="status">{calendarMessage}</p>}
        {!!scheduledRuns?.length && (
          <ul className="dashboard-workflow-calendar" aria-label="Upcoming workflow runs">
            {scheduledRuns.map((run) => (
              <li key={run.id}>
                <button type="button" onClick={() => onOpenWorkflow(run.id)}>
                  <time dateTime={new Date(run.scheduled_at * 1000).toISOString()}>
                    {new Date(run.scheduled_at * 1000).toLocaleString([], {
                      month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit',
                    })}
                  </time>
                  <span>{run.workflow_name}</span>
                </button>
              </li>
            ))}
          </ul>
        )}
        <small>Indexed Google Calendar events</small>
        {eventMessage && <p role="status">{eventMessage}</p>}
        {!!calendarEvents?.length && (
          <ul className="dashboard-indexed-calendar" aria-label="Indexed Google Calendar events">
            {calendarEvents.map((event) => {
              const allDay = event.all_day_date;
              const date = new Date(allDay ? `${allDay}T00:00:00` : event.starts_at);
              return <li key={event.id}>
                <time dateTime={allDay ?? event.starts_at}>
                  {date.toLocaleDateString([], { month: 'short', day: 'numeric' })}{' '}
                  {allDay ? 'All day' : date.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}
                </time>
                <span>{event.title}</span>
              </li>;
            })}
          </ul>
        )}
      </>
    )}{widget.kind === 'content' && (
      <div className="content-pipeline">
        {!socialQueue && <p role="status">{socialMessage}</p>}
        {socialQueue?.items.length === 0 && <p>No saved social content yet.</p>}
        {socialQueue?.items.map((item) => (
          <article key={item.id}>
            <div>
              <b>{item.title}</b>
              <small>{item.channels.map((channel) => SOCIAL_CHANNELS[channel]).join(' · ')}</small>
              {item.state === 'planned' && item.scheduled_at !== null && (
                <small>{new Date(item.scheduled_at * 1000).toLocaleString()}</small>
              )}
            </div>
            <em data-content-state={item.state}>{item.state === 'review' ? 'IN REVIEW' : item.state.toUpperCase()}</em>
          </article>
        ))}
      </div>
    )}</div>{editing && <footer><button aria-label={`Move ${widget.name} left`} onClick={() => move(index,-1)}><ChevronLeft size={11}/></button><button aria-label={`Move ${widget.name} right`} onClick={() => move(index,1)}><ChevronRight size={11}/></button><button aria-label={`Resize ${widget.name}`} onClick={() => setSizes((current) => ({...current,[widget.id]: current[widget.id] === 'large' ? 'small' : current[widget.id] === 'medium' ? 'large' : 'medium'}))}><Grip size={11}/>{(sizes[widget.id] ?? 'SMALL').toUpperCase()}</button><button aria-label={`Remove ${widget.name}`} onClick={() => setWidgetIds(widgetIds.filter((id) => id !== widget.id))}><X size={11}/></button></footer>}</article>)}</section> : <section className="dashboard-empty"><CalendarDays size={25}/><h3>Your dashboard is empty</h3><p>Add any widget from a workstation without changing that workstation's capability.</p><button onClick={() => setEditing(true)}><Plus size={12}/> ADD WIDGET</button></section>}
  </main>;
}
