import { type FormEvent, useEffect, useState } from 'react';
import { assignWorkflowFollowUp, fetchWorkflowFollowUps, type WorkflowFollowUp } from '../lib/api';

export type WorkflowRecipient = { stationId: string; name: string; agentId: string };

export function WorkflowWorkstationAssignment({ runId, recipients, onOpenStation }: {
  runId: string;
  recipients: WorkflowRecipient[];
  onOpenStation?: (stationId: string) => void;
}) {
  const [stationId, setStationId] = useState('');
  const [instruction, setInstruction] = useState('');
  const [pending, setPending] = useState(false);
  const [message, setMessage] = useState('');
  const [confirmedStation, setConfirmedStation] = useState('');
  const [open, setOpen] = useState(false);
  const [followUps, setFollowUps] = useState<WorkflowFollowUp[]>([]);
  const [followUpStatus, setFollowUpStatus] = useState('Checking follow-ups…');
  const [refreshVersion, setRefreshVersion] = useState(0);
  const recipient = recipients.find((entry) => entry.stationId === stationId);

  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    let timer: number | undefined;
    const refresh = async () => {
      try {
        const assignments = await fetchWorkflowFollowUps(runId, controller.signal);
        if (controller.signal.aborted) return;
        setFollowUps(assignments);
        setFollowUpStatus(assignments.length ? '' : 'No follow-ups assigned.');
      } catch {
        if (!controller.signal.aborted) setFollowUpStatus('Could not refresh follow-ups.');
      } finally {
        if (!controller.signal.aborted) timer = window.setTimeout(() => void refresh(), 10000);
      }
    };
    void refresh();
    return () => {
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [open, runId, refreshVersion]);

  const assign = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (pending || !recipient || !instruction.trim()) return;
    setPending(true);
    setMessage('');
    setConfirmedStation('');
    try {
      const queued = await assignWorkflowFollowUp(runId, recipient.agentId, instruction.trim());
      setMessage(queued ? `Follow-up queued for ${recipient.name}.`
        : `${recipient.name} already has a follow-up for this run.`);
      setConfirmedStation(recipient.stationId);
      setRefreshVersion((version) => version + 1);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Could not queue the follow-up.');
    } finally {
      setPending(false);
    }
  };

  return (
    <details onToggle={(event) => setOpen(event.currentTarget.open)}>
      <summary>Assign approved follow-up</summary>
      {recipients.length === 0 ? <p>Link a managed agent to a workstation to assign follow-ups.</p> : (
        <form className="connector-editor" onSubmit={assign}>
          <label>Recipient workstation
            <select value={stationId} disabled={pending} required
              onChange={(event) => setStationId(event.target.value)}>
              <option value="">Choose a workstation</option>
              {recipients.map((entry) => (
                <option key={entry.stationId} value={entry.stationId}>{entry.name}</option>
              ))}
            </select>
          </label>
          <label>Follow-up instruction
            <textarea rows={4} maxLength={2000} required value={instruction} disabled={pending}
              onChange={(event) => setInstruction(event.target.value)} />
          </label>
          <small>The recipient receives the instruction and a run reference on its next run.</small>
          <button disabled={!recipient || !instruction.trim() || pending}>Queue follow-up</button>
          {message && <small role="status">{message}</small>}
          {confirmedStation && onOpenStation && (
            <button type="button" onClick={() => onOpenStation(confirmedStation)}>Open workstation</button>
          )}
        </form>
      )}
      {followUpStatus && <p role="status">{followUpStatus}</p>}
      {followUps.length > 0 && (
        <ul aria-label="Assigned follow-ups">
          {followUps.map((followUp) => (
            <li key={followUp.id}>
              <strong>{followUp.agent_name}</strong>{' '}
              <span>{followUp.status === 'pending' ? 'Waiting for agent' : 'Picked up by agent'}</span>
            </li>
          ))}
        </ul>
      )}
    </details>
  );
}
