import { AlertTriangle, Network, Radio, Users } from 'lucide-react';
import './shared-brain.css';

export function SharedBrainPanel({ context, onContextChange }: {
  context: string;
  onContextChange: (value: string) => void;
}) {
  return <>
    <main className="shared-brain-panel"><header><div><span>SHARED COMMUNICATION SERVICE</span><h2>The Brain</h2><p>Common context, ownership, and coordination for every agent. The Brain is not part of the reporting hierarchy.</p></div><em>DEMO DATA · SYNCHRONIZED</em></header><section className="brain-metrics"><article><Radio/><span>COMMUNICATION HEALTH</span><strong>98.4%</strong><small>ALL STATIONS RECEIVING CONTEXT</small></article><article><Users/><span>CONNECTED STATIONS</span><strong>10</strong><small>ONE SHARED CONTEXT LAYER</small></article><article><Network/><span>ACTIVE OWNERSHIPS</span><strong>27</strong><small>ASSIGNMENTS INDEXED</small></article><article><AlertTriangle/><span>DUPLICATE WARNINGS</span><strong>0</strong><small>NO CONFLICTS DETECTED</small></article></section><section className="brain-detail-grid"><article><header><span>LIVE CONTEXT ACTIVITY</span><strong>Latest shared updates</strong></header><ul><li><b>MKT</b><div><strong>Campaign brief updated</strong><small>Shared with Growth, Finance, and General Manager</small></div><em>NOW</em></li><li><b>RSC</b><div><strong>Competitor sources verified</strong><small>Evidence added to the shared research context</small></div><em>08M</em></li><li><b>OPS</b><div><strong>Delivery blocker ownership changed</strong><small>Managers notified through the shared context layer</small></div><em>14M</em></li></ul></article><article><header><span>OWNERSHIP MAP</span><strong>Who is working on what</strong></header><ul><li><b>DOT</b><div><strong>CEO weekly briefing</strong><small>Primary owner · General Manager contributing</small></div></li><li><b>GRW</b><div><strong>Inbound lead qualification</strong><small>Primary owner · Email Reply contributing</small></div></li><li><b>FIN</b><div><strong>Monthly revenue forecast</strong><small>Primary owner · no overlap detected</small></div></li></ul></article></section></main>
    <section aria-label="Shared Brain participants" className="station-details-editor">
      <h3>Shared Brain participants</h3>
      <ul>
        <li><strong>Dot</strong> · Uses this shared brief when you send a message.</li>
        <li><strong>ChatGPT</strong> · Copy the brief into your ChatGPT conversation.</li>
        <li><strong>Codex</strong> · Copy the brief into your Codex task.</li>
      </ul>
      <label>Shared brief
        <textarea rows={5} maxLength={4000} value={context}
          onChange={(event) => onContextChange(event.target.value)} />
      </label>
      <p>Saved on this device. Dot sends the brief to the selected model with your message.</p>
    </section>
  </>;
}
