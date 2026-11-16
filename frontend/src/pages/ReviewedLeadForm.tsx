import { type FormEvent, useState } from 'react';
import { saveLead } from '../lib/api';

export function ReviewedLeadForm({ runId }: { runId: string }) {
  const [pending, setPending] = useState(false);
  const [message, setMessage] = useState('');

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = event.currentTarget;
    const fields = new FormData(form);
    setPending(true);
    try {
      await saveLead(String(fields.get('organization')), String(fields.get('source')), runId);
      form.reset();
      setMessage('Reviewed lead saved to Growth.');
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Could not save reviewed lead.');
    } finally {
      setPending(false);
    }
  };

  return (
    <form className="connector-editor" onSubmit={submit}>
      <label>Reviewed organization
        <input name="organization" required maxLength={160} disabled={pending} />
      </label>
      <label>Reviewed source reference
        <input name="source" required maxLength={1000} disabled={pending} />
      </label>
      <button type="submit" disabled={pending}>Save reviewed lead</button>
      {message && <p role="status">{message}</p>}
    </form>
  );
}
