import { useEffect, useState } from 'react';
import { fetchSharedBrainBrief, saveSharedBrainBrief, SharedBrainConflict, type SharedBrainBrief } from '../lib/api';
import './shared-brain.css';

export function SharedBrainPanel({ context, onContextChange, onShare, onOpenDot, onOpenWorkflow }: {
  onOpenDot: () => void;
  onOpenWorkflow: (id: string) => void;
  context: string;
  onContextChange: (value: string) => void;
  onShare: (source: string, text: string) => string;
}) {
  const [source, setSource] = useState('ChatGPT');
  const [update, setUpdate] = useState('');
  const [shareStatus, setShareStatus] = useState('');
  const [copyMessage, setCopyMessage] = useState('');
  const [backendBrief, setBackendBrief] = useState<SharedBrainBrief | null>(null);
  const [checkingBackend, setCheckingBackend] = useState(true);
  const [backendMessage, setBackendMessage] = useState('Checking backend brief…');
  const workflowHandoffs = Array.from(new Set(
    [...(backendBrief?.context ?? '').matchAll(/^\[Approved workflow ([a-f0-9]{32})\]$/gm)]
      .map((match) => match[1]),
  ));

  const backendStatus = checkingBackend
    ? 'Checking backend'
    : !backendBrief
      ? 'Backend brief unavailable'
      : backendBrief.revision > 0
        ? `Saved brief revision ${backendBrief.revision}`
        : 'No saved brief yet';

  useEffect(() => {
    const controller = new AbortController();
    fetchSharedBrainBrief(controller.signal).then((brief) => {
      if (controller.signal.aborted) return;
      setBackendBrief(brief);
      setBackendMessage('');
    }).catch(() => {
      if (!controller.signal.aborted) setBackendMessage('Backend brief unavailable. Your draft stays on this device.');
    }).finally(() => {
      if (!controller.signal.aborted) setCheckingBackend(false);
    });
    return () => controller.abort();
  }, []);

  const refreshBackend = async () => {
    setCheckingBackend(true);
    try {
      setBackendBrief(await fetchSharedBrainBrief());
      setBackendMessage('Backend brief refreshed.');
    } catch {
      setBackendBrief(null);
      setBackendMessage('Backend brief unavailable. Your draft stays on this device.');
    } finally {
      setCheckingBackend(false);
    }
  };

  const saveToBackend = async () => {
    if (!backendBrief || checkingBackend) return;
    setCheckingBackend(true);
    try {
      const saved = await saveSharedBrainBrief({ context, revision: backendBrief.revision });
      setBackendBrief(saved);
      setBackendMessage('Brief saved to the backend.');
    } catch (error) {
      setBackendBrief(null);
      setBackendMessage(error instanceof SharedBrainConflict
        ? 'Another client changed the brief. Refresh to compare it with your draft.'
        : 'The save could not be confirmed. Refresh to check the backend brief.');
    } finally {
      setCheckingBackend(false);
    }
  };
  const copyBrief = async () => {
    try {
      await navigator.clipboard.writeText(context.trim());
      setCopyMessage('Brief copied. Paste it into ChatGPT or Codex.');
    } catch {
      setCopyMessage('Clipboard unavailable. Select and copy the brief manually.');
    }
  };
  return <>
    <main className="shared-brain-panel">
      <header>
        <div>
          <h2>The Brain</h2>
          <p>Shared context for Dot, ChatGPT, Codex, and connected workstations.</p>
        </div>
        <small>{backendStatus}</small>
      </header>
      {workflowHandoffs.length > 0 && (
        <section aria-labelledby="brain-handoff-heading">
          <h3 id="brain-handoff-heading">Approved workflow handoffs</h3>
          <ul>{workflowHandoffs.map((id) => (
            <li key={id}><button type="button" onClick={() => onOpenWorkflow(id)}>
              Open workflow run {id.slice(0, 8)}
            </button></li>
          ))}</ul>
        </section>
      )}
    </main>
    <section aria-label="Shared Brain participants" className="station-details-editor">
      <h3>Shared Brain participants</h3>
      <ul>
        <li><strong>Dot</strong> · Include the brief in a message or save a Dot reply here. <button type="button" onClick={onOpenDot}>Open Dot</button></li>
        <li><strong>ChatGPT</strong> · Copy the brief into your ChatGPT conversation and paste the result below.</li>
        <li><strong>Codex</strong> · Copy the brief into your Codex task and paste the result below.</li>
      </ul>
      <label>Shared brief
        <textarea rows={5} maxLength={4000} value={context}
          onChange={(event) => {
            setCopyMessage('');
            onContextChange(event.target.value);
          }} />
      </label>
      <button type="button" disabled={!context.trim()} onClick={() => void copyBrief()}>
        Copy brief
      </button>
      <div className="brain-brief-backend">
        <button type="button" disabled={checkingBackend} onClick={() => void refreshBackend()}>
          Refresh backend brief
        </button>
        {backendBrief && backendBrief.context !== context && (
          <>
            <details>
              <summary>Compare backend brief</summary>
              <pre>{backendBrief.context || 'The backend brief is empty.'}</pre>
            </details>
            {backendBrief.revision > 0 && (
              <button type="button" disabled={checkingBackend} onClick={() => {
                onContextChange(backendBrief.context);
                setBackendMessage('Backend brief loaded into your local draft.');
              }}>Use backend brief</button>
            )}
            <button type="button" disabled={checkingBackend} onClick={() => void saveToBackend()}>
              Save brief to backend
            </button>
          </>
        )}
        {backendBrief && backendBrief.context === context && backendBrief.revision > 0 && <small>Draft matches the backend brief.</small>}
        {backendMessage && <p role="status">{backendMessage}</p>}
      </div>
      {copyMessage && <p role="status">{copyMessage}</p>}
      <form onSubmit={(event) => {
        event.preventDefault();
        if (!update.trim()) return;
        const status = onShare(source, update);
        setShareStatus(status);
        if (status === 'Added to Shared Brain.') setUpdate('');
      }}>
        <label>Update source
          <select value={source} onChange={(event) => setSource(event.target.value)}>
            <option>ChatGPT</option>
            <option>Dot</option>
            <option>Codex</option>
          </select>
        </label>
        <label>Paste an update
          <textarea rows={3} maxLength={4000} value={update}
            onChange={(event) => setUpdate(event.target.value)} />
        </label>
        <button type="submit" disabled={!update.trim()}>Add to shared brief</button>
        {shareStatus && <p role="status">{shareStatus}</p>}
      </form>
      <p>Edits stay in your local draft until you save to the backend. Another client on the same backend can load that brief. If you include the draft in a message to Dot or a linked agent, it goes to that message’s model.</p>
    </section>
  </>;
}
