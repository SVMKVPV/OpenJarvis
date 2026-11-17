import { useState } from 'react';

export function ApprovedGmailDraft({ draft }: { draft: string }) {
  const [message, setMessage] = useState('');

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(draft);
      setMessage('Approved reply copied.');
    } catch {
      setMessage('Clipboard unavailable. Select and copy the reply text.');
    }
  };

  return <section className="connector-editor" aria-label="Approved Gmail reply">
    <h5>Approved Gmail reply</h5>
    <label>Approved reply text
      <textarea readOnly value={draft} rows={7} spellCheck={false} />
    </label>
    <button type="button" onClick={() => void copy()}>Copy approved reply</button>
    {message && <p role="status">{message}</p>}
  </section>;
}
