import { type FormEvent, useEffect, useRef, useState } from 'react';
import { type WorkflowRecurrence, workflowRecurrences } from '../lib/api';

export function WorkflowRecurrenceEditor({ definitionId, initialInput, initiallyOpen }: {
  definitionId: string;
  initialInput: string;
  initiallyOpen?: boolean;
}) {
  const [schedules, setSchedules] = useState<WorkflowRecurrence[]>([]);
  const [firstRun, setFirstRun] = useState('');
  const [interval, setInterval] = useState('60');
  const [editing, setEditing] = useState<{ id: string; revision: number } | null>(null);
  const [editedInput, setEditedInput] = useState('');
  const [refreshVersion, setRefreshVersion] = useState(0);
  const [pending, setPending] = useState(true);
  const [message, setMessage] = useState('');
  const scheduleHeading = useRef<HTMLElement>(null);

  useEffect(() => {
    if (initiallyOpen) scheduleHeading.current?.focus();
  }, [initiallyOpen]);

  useEffect(() => {
    let active = true;
    setPending(true);
    workflowRecurrences(definitionId)
      .then((result) => { if (active) setSchedules(result); })
      .catch(() => { if (active) setMessage('Could not load recurring schedules.'); })
      .finally(() => { if (active) setPending(false); });
    return () => { active = false; };
  }, [definitionId, refreshVersion]);

  const finishEditing = () => {
    setEditing(null);
    setFirstRun('');
    setInterval('60');
    setEditedInput('');
  };

  const changeSchedule = async (
    action: NonNullable<Parameters<typeof workflowRecurrences>[1]>, success: string,
  ) => {
    setPending(true);
    setMessage('');
    try {
      setSchedules(await workflowRecurrences(definitionId, action));
      setMessage(success);
      if (typeof action === 'object' && 'expected_revision' in action) finishEditing();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Could not update schedules.');
    } finally {
      setPending(false);
    }
  };

  const saveSchedule = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const settings = {
      first_due_at: Date.parse(firstRun) / 1000,
      interval_seconds: Math.round(Number(interval) * 60),
      initial_input: editing ? editedInput : initialInput,
    };
    if (editing) {
      void changeSchedule({ ...settings, id: editing.id, expected_revision: editing.revision },
        'Schedule updated.');
    } else {
      void changeSchedule(settings, 'Schedule created.');
    }
  };

  const editSchedule = (schedule: WorkflowRecurrence) => {
    if (schedule.revision === undefined) return;
    const date = new Date(schedule.next_due_at * 1000);
    const localTime = new Date(date.getTime() - date.getTimezoneOffset() * 60000);
    setFirstRun(localTime.toISOString().slice(0, 19));
    setInterval(String(schedule.interval_seconds / 60));
    setEditedInput(schedule.initial_input ?? '');
    setEditing({ id: schedule.id, revision: schedule.revision });
    setMessage('');
  };

  return (
    <details open={initiallyOpen}>
      <summary ref={scheduleHeading}>Recurring schedules</summary>
      <form className="connector-editor" onSubmit={saveSchedule}>
        <label>{editing ? 'Next start (local time)' : 'First run (local time)'}
          <input type="datetime-local" step="1" required disabled={pending} value={firstRun}
            onChange={(event) => setFirstRun(event.target.value)} />
        </label>
        <label>Repeat every (minutes)
          <input type="number" min="1" max="525600" step="any" required disabled={pending} value={interval}
            onChange={(event) => setInterval(event.target.value)} />
        </label>
        {editing && <label>Recurring run input
          <textarea rows={3} disabled={pending} value={editedInput}
            onChange={(event) => setEditedInput(event.target.value)} />
        </label>}
        <small>{editing ? 'Existing runs keep their original input.' : 'Uses the run input above.'}{' '}
          Runs use the latest saved workflow. A scheduled start is skipped
          while the previous run is active or waiting for approval. After downtime, only the
          latest missed start is considered. Pausing leaves existing runs in place. Resuming
          starts at the next future time.</small>
        <button disabled={pending}>{editing ? 'Save schedule changes' : 'Create recurring schedule'}</button>
        {editing && <button type="button" disabled={pending} onClick={finishEditing}>Cancel edit</button>}
      </form>
      {schedules.length > 0 && (
        <ul>
          {schedules.map((schedule) => (
            <li key={schedule.id}>
              Every {schedule.interval_seconds / 60} min.{' '}
              {schedule.paused ? 'Paused' :
                `Next recorded start ${new Date(schedule.next_due_at * 1000).toLocaleString()}`}{' '}
              {!!schedule.skipped_while_active && (
                <span>Skipped while active {schedule.skipped_while_active}{' '}</span>
              )}
              {typeof schedule.paused === 'boolean' && (
                <button type="button" disabled={pending} onClick={() => void changeSchedule(
                  { id: schedule.id, paused: !schedule.paused },
                  schedule.paused ? 'Schedule resumed.' : 'Schedule paused.',
                )}>{schedule.paused ? 'Resume schedule' : 'Pause schedule'}</button>
              )}{' '}
              {typeof schedule.revision === 'number' && (
                <button type="button" disabled={pending} onClick={() => editSchedule(schedule)}>
                  Edit schedule
                </button>
              )}{' '}
              <button type="button" disabled={pending}
                onClick={() => void changeSchedule(schedule.id, 'Schedule removed.')}>Remove schedule</button>
            </li>
          ))}
        </ul>
      )}
      <button type="button" disabled={pending} onClick={() => {
        finishEditing();
        setMessage('');
        setRefreshVersion((version) => version + 1);
      }}>Refresh schedules</button>
      {message && <p role="status">{message}</p>}
    </details>
  );
}
