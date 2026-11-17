import { useEffect, useState, type FormEvent } from 'react';
import { apiFetch } from '../lib/api';

type RevenueRecord = {
  as_of: string;
  currency: string;
  amount: string;
  source_reference: string;
};

function localDate(): string {
  const now = new Date();
  return new Date(now.getTime() - now.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
}

export function FinanceRevenue({ editable = false }: { editable?: boolean }) {
  const [date, setDate] = useState(localDate);
  const month = (date || localDate()).slice(0, 7);
  const [currency, setCurrency] = useState('');
  const [amount, setAmount] = useState('');
  const [reference, setReference] = useState('');
  const [loaded, setLoaded] = useState<{ month: string; records: RevenueRecord[] } | null>(null);
  const [errorMonth, setErrorMonth] = useState('');
  const [saveMessage, setSaveMessage] = useState('');
  const [saving, setSaving] = useState(false);
  const records = loaded?.month === month ? loaded.records : null;

  useEffect(() => {
    const controller = new AbortController();
    const load = async () => {
      try {
        const response = await apiFetch(`/v1/finance/revenue?month=${encodeURIComponent(month)}`, {
          signal: controller.signal, cache: 'no-store',
        });
        if (!response.ok) throw new Error();
        const result = await response.json();
        if (result.month !== month || !Array.isArray(result.records)) throw new Error();
        if (!controller.signal.aborted) {
          setLoaded(result);
          setErrorMonth('');
        }
      } catch {
        if (!controller.signal.aborted) setErrorMonth(month);
      }
    };
    void load();
    return () => controller.abort();
  }, [month]);

  const save = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (saving || records === null) return;
    setSaving(true);
    setSaveMessage('');
    try {
      const response = await apiFetch('/v1/finance/revenue', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          as_of: date, amount: amount.trim(), currency: currency.trim().toUpperCase(),
          source_reference: reference.trim(),
        }),
      });
      const result = await response.json().catch(() => null);
      if (response.status === 409 && typeof result?.detail === 'string') {
        throw new Error(result.detail);
      }
      if (!response.ok || result?.month !== month) throw new Error('Revenue total could not be saved.');
      const saved = result as RevenueRecord;
      setLoaded({
        month,
        records: [...records.filter((row) => row.currency !== saved.currency), saved]
          .sort((a, b) => a.currency.localeCompare(b.currency)),
      });
      setSaveMessage('Reviewed total saved.');
    } catch (error) {
      setSaveMessage(error instanceof Error ? error.message : 'Revenue total could not be saved.');
    } finally {
      setSaving(false);
    }
  };

  return <section aria-label="Recorded revenue">
    {editable && (
      <form className="connector-editor" onSubmit={(event) => void save(event)}>
        <strong>Record reviewed month-to-date revenue</strong>
        <label>Report date
          <input type="date" value={date} onChange={(event) => setDate(event.target.value)} required disabled={saving} />
        </label>
        <label>Currency code
          <input value={currency} onChange={(event) => setCurrency(event.target.value)}
            placeholder="AUD" pattern="[A-Za-z]{3}" maxLength={3} required disabled={saving} />
        </label>
        <label>Month-to-date amount
          <input value={amount} onChange={(event) => setAmount(event.target.value)}
            inputMode="decimal" maxLength={18} required disabled={saving} />
        </label>
        <label>Source reference
          <input value={reference} onChange={(event) => setReference(event.target.value)}
            maxLength={240} required disabled={saving} />
        </label>
        <small>Saving replaces the recorded total for the same month and currency.</small>
        <button disabled={saving || records === null}>{saving ? 'Saving…' : 'Save reviewed total'}</button>
        {saveMessage && <p role="status">{saveMessage}</p>}
      </form>
    )}
    {errorMonth === month ? <p role="status">Recorded revenue is unavailable.</p>
      : records === null ? <p role="status">Checking recorded revenue…</p>
        : records.length ? <ul className="dashboard-workflow-calendar">
          {records.map((record) => <li key={record.currency}>
            <strong>{record.currency} {record.amount}</strong>{' '}
            <small>Through {record.as_of} · {record.source_reference}</small>
          </li>)}
        </ul> : <p>No reviewed revenue recorded for {month}.</p>}
  </section>;
}
