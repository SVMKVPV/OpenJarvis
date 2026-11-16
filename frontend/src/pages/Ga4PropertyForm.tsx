import { type FormEvent, useEffect, useState } from 'react';
import { fetchGa4Property, saveGa4Property, type Ga4PropertySettings } from '../lib/api';

export function Ga4PropertyForm() {
  const [settings, setSettings] = useState<Ga4PropertySettings | null>(null);
  const [property, setProperty] = useState('');
  const [message, setMessage] = useState('Reading GA4 settings…');
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    fetchGa4Property(controller.signal).then((result) => {
      if (controller.signal.aborted) return;
      setSettings(result);
      setProperty(result.property_id);
      setMessage(result.environment_override ? 'Property managed by the backend environment.' : '');
    }).catch(() => {
      if (!controller.signal.aborted) setMessage('GA4 settings unavailable.');
    });
    return () => controller.abort();
  }, []);

  const save = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!settings || settings.environment_override || saving) return;
    setSaving(true);
    try {
      const result = await saveGa4Property(property.trim());
      setSettings(result);
      setProperty(result.property_id);
      setMessage(result.property_id ? 'GA4 property saved.' : 'GA4 property cleared.');
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Could not save GA4 property.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <section className="station-widget-options" aria-label="Google Analytics settings">
      <div><strong>Google Analytics</strong></div>
      <form onSubmit={save}>
        <label>GA4 property ID
          <input value={property} onChange={(event) => setProperty(event.target.value)}
            inputMode="numeric" pattern="[0-9]*" maxLength={30}
            disabled={!settings || settings.environment_override || saving} />
        </label>
        <button type="submit" disabled={!settings || settings.environment_override || saving}>
          {saving ? 'Saving…' : 'Save property'}
        </button>
      </form>
      <p>The dashboard uses a read-only GA4 connection. The property ID and account authorization are configured separately.</p>
      {message && <p role="status">{message}</p>}
    </section>
  );
}
