import { type FormEvent, useEffect, useState } from 'react';
import { type WorkflowRecurrence, workflowRecurrences } from '../lib/api';

export function WorkflowRecurrenceEditor({ definitionId, initialInput }: {
  definitionId: string;
  initialInput: string;
}) {
  const [schedules, setSchedules] = useState<WorkflowRecurrence[]>([]);
  const [firstRun, setFirstRun] = useState('');
  const [interval, setInterval] = useState('60');
  const [pending, setPending] = useState(true);
  const [message, setMessage] = useState('');

  useEffect(() => {
    let active = true;
    workflowRecurrences(definitionId)
      .then((result) => { if (active) setSchedules(result); })
      .catch(() => { if (active) setMessage('Could not load recurring schedules.'); })
      .finally(() => { if (active) setPending(false); });
    return () => { active = false; };
  }, [definitionId]);

  const changeSchedule = async (action: Parameters<typeof workflowRecurrences>[1]) => {
    setPending(true);
    setMessage('');
    try {
      setSchedules(await workflowRecurrences(definitionId, action));
      setMessage(typeof action === 'string' ? 'Schedule removed.' : 'Schedule created.');
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Could not update schedules.');
    } finally {
      setPending(false);
    }
  };

  const createSchedule = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    void changeSchedule({
      first_due_at: Date.parse(firstRun) / 1000,
      interval_seconds: Number(interval) * 60,
      initial_input: initialInput,
    });
  };

  return (
    <details>
      <summary>Recurring schedules</summary>
      <form className="connector-editor" onSubmit={createSchedule}>
        <label>First run (local time)
          <input type="datetime-local" required value={firstRun}
            onChange={(event) => setFirstRun(event.target.value)} />
        </label>
        <label>Repeat every (minutes)
          <input type="number" min="1" max="525600" step="1" required value={interval}
            onChange={(event) => setInterval(event.target.value)} />
        </label>
        <small>Uses the run input above and the latest saved workflow. A scheduled start is skipped
          while the previous run is active or waiting for approval. After downtime, only the
          latest missed start is considered.</small>
        <button disabled={pending}>Create recurring schedule</button>
      </form>
      {schedules.length > 0 && (
        <ul>
          {schedules.map((schedule) => (
            <li key={schedule.id}>
              Every {schedule.interval_seconds / 60} min. Next recorded start{' '}
              {new Date(schedule.next_due_at * 1000).toLocaleString()}{' '}
              {!!schedule.skipped_while_active && (
                <span>Skipped while active {schedule.skipped_while_active}{' '}</span>
              )}
              <button type="button" disabled={pending}
                onClick={() => void changeSchedule(schedule.id)}>Remove schedule</button>
            </li>
          ))}
        </ul>
      )}
      {message && <p role="status">{message}</p>}
    </details>
  );
}
