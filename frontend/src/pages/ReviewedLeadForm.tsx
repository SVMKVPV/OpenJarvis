import { type FormEvent, useEffect, useState } from 'react';
import { fetchReviewedLeadCandidates, saveLead, type ReviewedLeadCandidate } from '../lib/api';

export function ReviewedLeadForm({ runId }: { runId: string }) {
  const [candidates, setCandidates] = useState<ReviewedLeadCandidate[] | null>();
  const [loadError, setLoadError] = useState(false);
  useEffect(() => {
    const request = new AbortController();
    fetchReviewedLeadCandidates(runId, request.signal).then(
      (result) => { if (!request.signal.aborted) setCandidates(result); },
      () => { if (!request.signal.aborted) setLoadError(true); },
    );
    return () => request.abort();
  }, [runId]);

  const [pending, setPending] = useState(false);
  const [message, setMessage] = useState('');

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = event.currentTarget;
    const fields = new FormData(form);
    const candidateIndex = fields.get('candidate');
    const selected = candidateIndex ? candidates?.[Number(candidateIndex)] : undefined;
    if (candidates && !selected) return;
    setPending(true);
    try {
      await saveLead(selected?.organization ?? String(fields.get('organization')),
        selected?.source_reference ?? String(fields.get('source')), runId);
      form.reset();
      setMessage('Reviewed lead saved to Growth.');
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Could not save reviewed lead.');
    } finally {
      setPending(false);
    }
  };

  if (loadError) return <p role="status">Could not load the reviewed lead candidates.</p>;
  if (candidates === undefined) return <p role="status">Loading reviewed leads.</p>;
  if (candidates?.length === 0) return <p>No lead candidates match the indexed evidence.</p>;

  return (
    <form className="connector-editor" onSubmit={submit}>
      {candidates ? (
        <label>Reviewed lead candidate
          <select name="candidate" defaultValue="" required disabled={pending}>
            <option value="">Choose a candidate</option>
            {candidates.map((item, index) => (
              <option key={item.organization} value={index}>{item.organization} · {item.source_reference}</option>
            ))}
          </select>
        </label>
      ) : <>
        <label>Reviewed organization
          <input name="organization" required maxLength={160} disabled={pending} />
        </label>
        <label>Reviewed source reference
          <input name="source" required maxLength={1000} disabled={pending} />
        </label>
      </>}
      <button type="submit" disabled={pending}>Save reviewed lead</button>
      {message && <p role="status">{message}</p>}
    </form>
  );
}
