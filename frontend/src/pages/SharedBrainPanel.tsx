import { useState } from 'react';
import { AlertTriangle, Network, Radio, Users } from 'lucide-react';
import './shared-brain.css';

export function SharedBrainPanel({ context, onContextChange, onShare }: {
  context: string;
  onContextChange: (value: string) => void;
  onShare: (source: string, text: string) => string;
}) {
  const [source, setSource] = useState('ChatGPT');
  const [update, setUpdate] = useState('');
  const [shareStatus, setShareStatus] = useState('');
  const [copyMessage, setCopyMessage] = useState('');
  const copyBrief = async () => {
    try {
      await navigator.clipboard.writeText(context.trim());
      setCopyMessage('Brief copied. Paste it into ChatGPT or Codex.');
    } catch {
      setCopyMessage('Clipboard unavailable. Select and copy the brief manually.');
    }
  };
  return <>
    <main className="shared-brain-panel"><header><div><span>SHARED COMMUNICATION SERVICE</span><h2>The Brain</h2><p>Common context, ownership, and coordination for every agent. The Brain is not part of the reporting hierarchy.</p></div><em>DEMO DATA · SYNCHRONIZED</em></header><section className="brain-metrics"><article><Radio/><span>COMMUNICATION HEALTH</span><strong>98.4%</strong><small>ALL STATIONS RECEIVING CONTEXT</small></article><article><Users/><span>CONNECTED STATIONS</span><strong>10</strong><small>ONE SHARED CONTEXT LAYER</small></article><article><Network/><span>ACTIVE OWNERSHIPS</span><strong>27</strong><small>ASSIGNMENTS INDEXED</small></article><article><AlertTriangle/><span>DUPLICATE WARNINGS</span><strong>0</strong><small>NO CONFLICTS DETECTED</small></article></section><section className="brain-detail-grid"><article><header><span>LIVE CONTEXT ACTIVITY</span><strong>Latest shared updates</strong></header><ul><li><b>MKT</b><div><strong>Campaign brief updated</strong><small>Shared with Growth, Finance, and General Manager</small></div><em>NOW</em></li><li><b>RSC</b><div><strong>Competitor sources verified</strong><small>Evidence added to the shared research context</small></div><em>08M</em></li><li><b>OPS</b><div><strong>Delivery blocker ownership changed</strong><small>Managers notified through the shared context layer</small></div><em>14M</em></li></ul></article><article><header><span>OWNERSHIP MAP</span><strong>Who is working on what</strong></header><ul><li><b>DOT</b><div><strong>CEO weekly briefing</strong><small>Primary owner · General Manager contributing</small></div></li><li><b>GRW</b><div><strong>Inbound lead qualification</strong><small>Primary owner · Email Reply contributing</small></div></li><li><b>FIN</b><div><strong>Monthly revenue forecast</strong><small>Primary owner · no overlap detected</small></div></li></ul></article></section></main>
    <section aria-label="Shared Brain participants" className="station-details-editor">
      <h3>Shared Brain participants</h3>
      <ul>
        <li><strong>Dot</strong> · Include the brief in a message or save a Dot reply here.</li>
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
      <p>Saved on this device. When included in a Dot message, the brief goes to the selected model.</p>
    </section>
  </>;
}
