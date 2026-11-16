import { type FormEvent, useState } from 'react';
import { indexWorkflowEvidence } from '../lib/connectors-api';

export function WorkflowEvidenceUpload({ onIndexed }: { onIndexed: (reference: string) => void }) {
  const [files, setFiles] = useState<File[]>([]);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');

  const indexEvidence = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (busy || !files.length) return;
    const form = event.currentTarget;
    setBusy(true);
    setMessage('');
    try {
      const result = await indexWorkflowEvidence(files);
      if (!result.chunks_added) {
        setMessage('No readable text was found in the selected files.');
        return;
      }
      if (result.reference && result.chunks_added <= 16) {
        onIndexed(result.reference);
        setMessage('Evidence indexed and selected as the run input.');
      } else {
        setMessage(`Indexed ${result.chunks_added} excerpts. Use a keyword search for this upload.`);
      }
      form.reset();
      setFiles([]);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Evidence upload failed.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <form className="connector-editor" onSubmit={indexEvidence}>
      <label>Source evidence files
        <input type="file" accept=".txt,.md,.pdf,.docx,.csv" multiple disabled={busy}
          onChange={(event) => setFiles(Array.from(event.target.files ?? []))} />
      </label>
      <button disabled={busy || !files.length}>{busy ? 'Indexing…' : 'Index evidence'}</button>
      <small>Index the files together to review them as one batch. This supports text,
        Markdown, PDF, Word, and CSV files.</small>
      {message && <small role="status">{message}</small>}
    </form>
  );
}
