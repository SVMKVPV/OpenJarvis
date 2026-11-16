import { type FormEvent, useEffect, useState } from 'react';
import { fetchSavedLeads, saveLead, type SavedLead } from '../lib/api';

export function LeadRegister({ onOpenDiscovery }: { onOpenDiscovery: () => void }) {
  const [leads, setLeads] = useState<SavedLead[] | null>(null);
  const [organization, setOrganization] = useState('');
  const [source, setSource] = useState('');
  const [message, setMessage] = useState('Loading saved leads…');
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    fetchSavedLeads(controller.signal).then((items) => {
      if (controller.signal.aborted) return;
      setLeads(items);
      setMessage('');
    }).catch(() => {
      if (!controller.signal.aborted) setMessage('Lead register unavailable.');
    });
    return () => controller.abort();
  }, []);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!leads || !organization.trim() || !source.trim() || saving) return;
    setSaving(true);
    try {
      const lead = await saveLead(organization, source);
      setLeads((previous) => [lead, ...(previous ?? []).slice(0, 19)]);
      setOrganization('');
      setSource('');
      setMessage('Lead saved.');
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Could not save lead.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <section className="station-widget-options" aria-label="Lead register">
      <div>
        <strong>Lead register</strong>
        <button type="button" onClick={onOpenDiscovery}>Open lead discovery workflow</button>
      </div>
      <form onSubmit={submit}>
        <label>Organization
          <input value={organization} onChange={(event) => setOrganization(event.target.value)}
            required maxLength={160} disabled={!leads || saving} />
        </label>
        <label>Source reference
          <input value={source} onChange={(event) => setSource(event.target.value)}
            required maxLength={1000} disabled={!leads || saving} />
        </label>
        <button type="submit" disabled={!leads || saving}>Save lead</button>
      </form>
      {message && <p role="status">{message}</p>}
      {leads?.length === 0 && <p>No saved leads yet.</p>}
      {!!leads?.length && (
        <ul aria-label="Latest saved leads">
          {leads.map((lead) => (
            <li key={lead.id} className="py-2 break-all">
              <strong>{lead.organization}</strong>
              <div>{lead.source_reference}</div>
              {lead.workflow_run_id && <small>Reviewed workflow {lead.workflow_run_id.slice(0, 8)}</small>}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
