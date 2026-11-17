import { useEffect, useRef, useState } from 'react';
import { previewWorkflowIndex } from '../lib/api';

export function WorkflowIndexPreview({ source, allowGmailReference, maxSyncAgeHours }: {
  source: string;
  allowGmailReference: boolean;
  maxSyncAgeHours?: number;
}) {
  const [query, setQuery] = useState('');
  const [pending, setPending] = useState(false);
  const [preview, setPreview] = useState<{ success: boolean; output: string } | null>(null);
  const request = useRef<AbortController | null>(null);
  useEffect(() => () => request.current?.abort(), []);

  const search = async () => {
    if (!query.trim() || pending) return;
    const controller = new AbortController();
    request.current = controller;
    setPending(true);
    setPreview(null);
    try {
      const result = await previewWorkflowIndex(source, query, allowGmailReference, controller.signal, maxSyncAgeHours);
      if (!controller.signal.aborted) setPreview(result);
    } catch {
      if (!controller.signal.aborted) setPreview({ success: false, output: 'Index preview is unavailable.' });
    } finally {
      if (!controller.signal.aborted) setPending(false);
    }
  };

  return <details>
    <summary>Preview index search</summary>
    <label>Sample query
      <input value={query} maxLength={500} disabled={pending}
        onChange={(event) => { setQuery(event.target.value); setPreview(null); }}
        onKeyDown={(event) => {
          if (event.key !== 'Enter') return;
          event.preventDefault();
          void search();
        }} />
    </label>
    <button type="button" disabled={pending || !query.trim()} onClick={() => void search()}>
      {pending ? 'Searching…' : 'Search index'}
    </button>
    {preview && <div role={preview.success ? 'status' : 'alert'}>
      <pre style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{preview.output}</pre>
    </div>}
  </details>;
}
