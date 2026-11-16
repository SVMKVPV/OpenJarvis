import { type FormEvent, useState } from 'react';
import { recordSocialPublication, SOCIAL_CHANNELS, type SocialChannel, type SocialDraft, type SocialPublication } from '../lib/social-content-api';

export function SocialPublicationForm({ draft, existing, onRecorded, onCancel }: {
  draft: SocialDraft;
  existing?: SocialPublication;
  onRecorded: (draft: SocialDraft) => void;
  onCancel?: () => void;
}) {
  const [channel, setChannel] = useState<SocialChannel | ''>(existing?.channel ?? '');
  const [url, setUrl] = useState(existing?.url ?? '');
  const [postedAt, setPostedAt] = useState(() => {
    if (!existing) return '';
    const date = new Date(existing.posted_at * 1000);
    return new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 19);
  });
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  const [editRevision] = useState(draft.revision);
  const remaining = draft.channels.filter((item) =>
    !draft.publications?.some((record) => record.channel === item));

  const save = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (pending || !channel) return;
    const time = Date.parse(postedAt) / 1000;
    if (!Number.isFinite(time) || time > Date.now() / 1000) {
      setError('Choose a published time in the past.');
      return;
    }
    setPending(true);
    setError('');
    try {
      onRecorded(await recordSocialPublication(
        existing ? { ...draft, revision: editRevision } : draft,
        { channel, url: url.trim(), posted_at: time }, !!existing,
      ));
      setChannel('');
      setUrl('');
      setPostedAt('');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not record the post.');
    } finally {
      setPending(false);
    }
  };

  return (
    <details className="station-details-editor social-planning-form" open={existing ? true : undefined}>
      <summary>{existing ? `Correct ${SOCIAL_CHANNELS[existing.channel]} record` : 'Record a published post'}</summary>
      <form onSubmit={save}>
        {!existing && <label>Published channel
          <select required value={channel} disabled={pending}
            onChange={(event) => setChannel(event.target.value as SocialChannel | '')}>
            <option value="">Choose a channel</option>
            {remaining.map((item) => <option key={item} value={item}>{SOCIAL_CHANNELS[item]}</option>)}
          </select>
        </label>}
        <label>Published post link
          <input type="url" required pattern="https://.+" value={url} disabled={pending}
            onChange={(event) => setUrl(event.target.value)} />
        </label>
        <label>Published time (local time)
          <input type="datetime-local" step="1" required value={postedAt} disabled={pending}
            onChange={(event) => setPostedAt(event.target.value)} />
        </label>
        <button disabled={pending || !channel}>{existing ? 'Save publication correction' : 'Save publication record'}</button>
        {onCancel && <button type="button" disabled={pending} onClick={onCancel}>Cancel correction</button>}
      </form>
      {error && <p role="status">{error}</p>}
    </details>
  );
}
