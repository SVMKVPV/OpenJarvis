import { useEffect, useState } from 'react';
import { fetchGmailReviewCandidates, type GmailReviewCandidate } from '../lib/api';

export function GmailReviewList() {
  const [candidates, setCandidates] = useState<GmailReviewCandidate[] | null>(null);
  const [message, setMessage] = useState('Checking the Gmail index…');
  const [revision, setRevision] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    fetchGmailReviewCandidates(controller.signal).then((items) => {
      if (controller.signal.aborted) return;
      setCandidates(items);
      setMessage(items.length ? '' : 'No review candidates in the Gmail index.');
    }).catch(() => {
      if (controller.signal.aborted) return;
      setCandidates(null);
      setMessage('Gmail index unavailable.');
    });
    return () => controller.abort();
  }, [revision]);

  return (
    <section className="station-widget-options" aria-label="Gmail review candidates">
      <div>
        <strong>Gmail review candidates</strong>
        <button type="button" onClick={() => setRevision((previous) => previous + 1)}>Refresh</button>
      </div>
      <p>Up to 10 threads whose latest indexed inbox or sent message is inbound.</p>
      {message && <p role="status">{message}</p>}
      {!!candidates?.length && (
        <ul>
          {candidates.map(({ id, message_id, sender, subject, received_at }) => (
            <li key={id} className="py-2">
              {message_id && /^[a-f0-9]+$/i.test(message_id) ? (
                <a href={`https://mail.google.com/mail/u/0/#all/${message_id}`} target="_blank" rel="noopener noreferrer">
                  {subject}
                </a>
              ) : <strong>{subject}</strong>}
              <div>{sender || 'Unknown sender'} · <time dateTime={received_at}>{new Date(received_at).toLocaleString()}</time></div>
              {message_id && id === 'gmail:' + message_id && (
                <div>Workflow reference <code>{id}</code></div>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
