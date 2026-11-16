import { type FormEvent, useState } from 'react';
import { assignWorkflowFollowUp } from '../lib/api';

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
  const recipient = recipients.find((entry) => entry.stationId === stationId);

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
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Could not queue the follow-up.');
    } finally {
      setPending(false);
    }
  };

  return (
    <details>
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
    </details>
  );
}
