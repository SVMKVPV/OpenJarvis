import { type FormEvent, useState } from 'react';
import { recordSocialPublication, SOCIAL_CHANNELS, type SocialChannel, type SocialDraft } from '../lib/social-content-api';

export function SocialPublicationForm({ draft, onRecorded }: {
  draft: SocialDraft;
  onRecorded: (draft: SocialDraft) => void;
}) {
  const [channel, setChannel] = useState<SocialChannel | ''>('');
  const [url, setUrl] = useState('');
  const [postedAt, setPostedAt] = useState('');
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
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
      onRecorded(await recordSocialPublication(draft, { channel, url: url.trim(), posted_at: time }));
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
    <details className="station-details-editor social-planning-form">
      <summary>Record a published post</summary>
      <form onSubmit={save}>
        <label>Published channel
          <select required value={channel} disabled={pending}
            onChange={(event) => setChannel(event.target.value as SocialChannel | '')}>
            <option value="">Choose a channel</option>
            {remaining.map((item) => <option key={item} value={item}>{SOCIAL_CHANNELS[item]}</option>)}
          </select>
        </label>
        <label>Published post link
          <input type="url" required pattern="https://.+" value={url} disabled={pending}
            onChange={(event) => setUrl(event.target.value)} />
        </label>
        <label>Published time (local time)
          <input type="datetime-local" required value={postedAt} disabled={pending}
            onChange={(event) => setPostedAt(event.target.value)} />
        </label>
        <button disabled={pending || !channel}>Save publication record</button>
      </form>
      {error && <p role="status">{error}</p>}
    </details>
  );
}
