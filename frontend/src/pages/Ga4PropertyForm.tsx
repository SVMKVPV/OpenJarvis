import { type FormEvent, useEffect, useState } from 'react';
import {
  fetchGa4Property, fetchGa4Views, removeGa4Authorization, saveGa4Property,
  type Ga4PropertySettings, type Ga4Views,
} from '../lib/api';

const CONNECTION_MESSAGES: Record<Ga4Views['status'], string> = {
  unconfigured: 'Save a GA4 property ID before testing.',
  invalid_property: 'The configured GA4 property ID must be numeric.',
  authorization_required: 'Google Analytics authorization is required.',
  unavailable: 'Google Analytics could not return a report.',
  stale: 'Google Analytics could not return a fresh report. The dashboard shows the last successful report.',
  live: 'Connection verified. The property returned a GA4 report.',
};

export function Ga4PropertyForm() {
  const [settings, setSettings] = useState<Ga4PropertySettings | null>(null);
  const [property, setProperty] = useState('');
  const [message, setMessage] = useState('Reading GA4 settings…');
  const [saving, setSaving] = useState(false);
  const [connectionAction, setConnectionAction] = useState<'test' | 'remove' | null>(null);

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

  const manageConnection = async (action: 'test' | 'remove') => {
    if (connectionAction || saving) return;
    setConnectionAction(action);
    try {
      if (action === 'remove') {
        await removeGa4Authorization();
        setMessage('Saved GA4 authorization removed from this backend.');
      } else {
        const report = await fetchGa4Views();
        setMessage(CONNECTION_MESSAGES[report.status]);
      }
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'GA4 connection action failed.');
    } finally {
      setConnectionAction(null);
    }
  };

  return (
    <section className="station-widget-options" aria-label="Google Analytics settings">
      <div><strong>Google Analytics</strong></div>
      <form onSubmit={save}>
        <label>GA4 property ID
          <input value={property} onChange={(event) => setProperty(event.target.value)}
            inputMode="numeric" pattern="[0-9]*" maxLength={30}
            disabled={!settings || settings.environment_override || saving || connectionAction !== null} />
        </label>
        <button type="submit" disabled={!settings || settings.environment_override || saving || connectionAction !== null}>
          {saving ? 'Saving…' : 'Save property'}
        </button>
      </form>
      <div>
        <button type="button" disabled={!settings || saving || connectionAction !== null}
          onClick={() => void manageConnection('test')}>
          {connectionAction === 'test' ? 'Testing…' : 'Test GA4 connection'}
        </button>
        <button type="button" disabled={!settings || saving || connectionAction !== null}
          onClick={() => void manageConnection('remove')}>
          {connectionAction === 'remove' ? 'Removing…' : 'Remove saved GA4 authorization'}
        </button>
      </div>
      <p>The dashboard uses a read-only GA4 connection. The property ID and account authorization are configured separately.</p>
      {message && <p role="status">{message}</p>}
    </section>
  );
}
