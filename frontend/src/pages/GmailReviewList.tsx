import { useEffect, useState } from 'react';
import { fetchGmailReviewCandidates, type GmailReviewCandidate } from '../lib/api';
import { indexGmailEvidence } from '../lib/connectors-api';

export function GmailReviewList({ onOpenWorkflow, onOpenFinance }: {
  onOpenWorkflow?: (reference: string) => void;
  onOpenFinance?: (reference: string) => void;
}) {
  const [candidates, setCandidates] = useState<GmailReviewCandidate[] | null>(null);
  const [message, setMessage] = useState('Checking the Gmail index…');
  const [revision, setRevision] = useState(0);
  const [importing, setImporting] = useState(false);
  const [importMessage, setImportMessage] = useState('');

  const openFinance = async (messageId: string) => {
    if (!onOpenFinance || importing) return;
    setImporting(true);
    setImportMessage('Importing attachments…');
    try {
      const result = await indexGmailEvidence(messageId);
      if (!result.reference || result.chunks_added > 16) {
        setImportMessage('Use an indexed keyword search or upload a smaller set of files.');
        return;
      }
      onOpenFinance(result.reference);
    } catch (error) {
      setImportMessage(error instanceof Error ? error.message : 'Could not import attachments.');
    } finally {
      setImporting(false);
    }
  };

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
      {importMessage && <p role="status">{importMessage}</p>}
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
                <>
                  {onOpenWorkflow && <button type="button" onClick={() => onOpenWorkflow(id)}>Open reply workflow</button>}
                  {onOpenFinance && <button type="button" disabled={importing}
                    onClick={() => void openFinance(message_id)}>Import attachments for workpaper</button>}
                </>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
