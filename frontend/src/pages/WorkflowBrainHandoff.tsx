import { type FormEvent, useState } from 'react';
import { shareWorkflowWithBrain } from '../lib/api';

export function WorkflowBrainHandoff({ runId }: { runId: string }) {
  const [summary, setSummary] = useState('');
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState('');

  const share = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (saving || !summary.trim()) return;
    setSaving(true);
    setMessage('');
    try {
      const added = await shareWorkflowWithBrain(runId, summary.trim());
      setMessage(added ? 'Summary saved to the backend Shared Brain brief.'
        : 'This run has already been shared.');
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'The handoff failed.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <details>
      <summary>Share approved run with Brain</summary>
      <form className="connector-editor" onSubmit={share}>
        <label>Handoff summary
          <textarea rows={4} maxLength={750} required value={summary} disabled={saving}
            onChange={(event) => setSummary(event.target.value)} />
        </label>
        <small>The shared brief receives this summary and a reference to the run.</small>
        <button disabled={saving || !summary.trim()}>Share summary</button>
        {message && <small role="status">{message}</small>}
      </form>
    </details>
  );
}
