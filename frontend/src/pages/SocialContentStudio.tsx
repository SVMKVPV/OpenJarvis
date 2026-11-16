import { useEffect, useState, type FormEvent } from 'react';
import { Plus } from 'lucide-react';
import {
  listSocialDrafts, saveSocialDraft, SOCIAL_CHANNELS, updateSocialDraft,
  type SocialChannel, type SocialDraft, type SocialDraftAction,
  type SocialDraftFields, type SocialDraftState,
} from '../lib/social-content-api';
import './social-content-studio.css';

const STATE_LABELS: Record<SocialDraftState, string> = {
  draft: 'Draft', review: 'In review', approved: 'Approved', planned: 'Planned',
};
const EMPTY_DRAFT: SocialDraftFields = { title: '', caption: '', channels: [] };

export function SocialContentStudio() {
  const [drafts, setDrafts] = useState<SocialDraft[]>([]);
  const [available, setAvailable] = useState(false);
  const [filter, setFilter] = useState<SocialDraftState | 'all'>('all');
  const [editor, setEditor] = useState<{ fields: SocialDraftFields; draft?: SocialDraft } | null>(null);
  const [planningId, setPlanningId] = useState('');
  const [planningTime, setPlanningTime] = useState('');
  const [busy, setBusy] = useState(true);
  const [message, setMessage] = useState('Loading content drafts…');

  useEffect(() => {
    const controller = new AbortController();
    listSocialDrafts(controller.signal).then((items) => {
      if (controller.signal.aborted) return;
      setDrafts(items);
      setAvailable(true);
      setMessage('');
    }).catch((error) => {
      if (!controller.signal.aborted) setMessage(error.message);
    }).finally(() => {
      if (!controller.signal.aborted) setBusy(false);
    });
    return () => controller.abort();
  }, []);

  const saveResult = (draft: SocialDraft) => {
    setDrafts((current) => [draft, ...current.filter((item) => item.id !== draft.id)]);
  };
  const refresh = async () => {
    setBusy(true);
    try {
      setDrafts(await listSocialDrafts());
      setAvailable(true);
      setMessage('Content queue refreshed.');
    } catch (error) {
      setAvailable(false);
      setMessage(error instanceof Error ? error.message : 'Could not refresh drafts.');
    } finally {
      setBusy(false);
    }
  };
  const save = async (event: FormEvent) => {
    event.preventDefault();
    if (!editor || busy || !available) return;
    setBusy(true);
    try {
      saveResult(await saveSocialDraft(editor.fields, editor.draft));
      setEditor(null);
      setFilter('draft');
      setMessage('Draft saved.');
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Could not save the draft.');
    } finally {
      setBusy(false);
    }
  };
  const transition = async (draft: SocialDraft, action: SocialDraftAction) => {
    if (busy || !available) return;
    const scheduledAt = action === 'plan' ? Date.parse(planningTime) / 1000 : undefined;
    if (scheduledAt !== undefined && (!Number.isFinite(scheduledAt) || scheduledAt <= Date.now() / 1000)) {
      setMessage('Choose a future planning time.');
      return;
    }
    setBusy(true);
    try {
      const updated = await updateSocialDraft(draft, action, scheduledAt);
      saveResult(updated);
      setFilter(updated.state);
      setPlanningId('');
      setMessage(action === 'plan' ? 'Publish time planned.' : `Content moved to ${STATE_LABELS[updated.state].toLowerCase()}.`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Could not update the draft.');
    } finally {
      setBusy(false);
    }
  };

  const visible = drafts.filter((draft) => filter === 'all' || draft.state === filter);
  return (
    <section className="social-studio" aria-label="Social Content Studio">
      <header>
        <div><span>SOCIAL CONTENT STUDIO</span><strong>Draft, review, and plan channel content.</strong></div>
        <button type="button" disabled={!available || busy}
          onClick={() => setEditor({ fields: EMPTY_DRAFT })}><Plus size={12} /> New draft</button>
      </header>
      <p className="social-studio-note">Planning saves a time in this workspace. Channel publishing requires a separate connection.</p>
      {editor && (
        <form className="station-details-editor social-draft-editor" onSubmit={save}>
          <label>Draft title
            <input required maxLength={160} value={editor.fields.title}
              onChange={(event) => setEditor({ ...editor, fields: { ...editor.fields, title: event.target.value } })} />
          </label>
          <label>Caption
            <textarea required rows={4} maxLength={8000} value={editor.fields.caption}
              onChange={(event) => setEditor({ ...editor, fields: { ...editor.fields, caption: event.target.value } })} />
          </label>
          <fieldset>
            <legend>Target channels</legend>
            {Object.entries(SOCIAL_CHANNELS).map(([key, name]) => {
              const channel = key as SocialChannel;
              return <label key={channel}>
                <input type="checkbox" checked={editor.fields.channels.includes(channel)}
                  onChange={(event) => {
                    const channels = event.target.checked ? [...editor.fields.channels, channel]
                      : editor.fields.channels.filter((item) => item !== channel);
                    setEditor({ ...editor, fields: { ...editor.fields, channels } });
                  }} />
                {name}
              </label>;
            })}
          </fieldset>
          <button type="submit" disabled={busy || !available || !editor.fields.channels.length}>Save draft</button>
          <button type="button" disabled={busy} onClick={() => setEditor(null)}>Close editor</button>
        </form>
      )}
      <nav className="content-filters" aria-label="Content states">
        <button type="button" aria-pressed={filter === 'all'} onClick={() => setFilter('all')}>All</button>
        {(Object.keys(STATE_LABELS) as SocialDraftState[]).map((state) => (
          <button key={state} type="button" aria-pressed={filter === state}
            onClick={() => setFilter(state)}>{STATE_LABELS[state]}</button>
        ))}
        <button type="button" disabled={busy} onClick={() => void refresh()}>Refresh drafts</button>
      </nav>
      {message && <p className="social-studio-note" role="status">{message}</p>}
      {available && !visible.length && <p className="social-studio-note">No drafts in this view.</p>}
      <div className="content-board">
        {visible.map((draft) => (
          <article key={draft.id}>
            <div className="content-description">
              <h3>{draft.title}</h3>
              <p className="social-caption-preview">{draft.caption}</p>
              <div>{draft.channels.map((channel) => <b key={channel}>{SOCIAL_CHANNELS[channel]}</b>)}</div>
            </div>
            <aside>
              <em data-state={draft.state.toUpperCase()}>{STATE_LABELS[draft.state]}</em>
              {draft.scheduled_at && <small>Planned for {new Date(draft.scheduled_at * 1000).toLocaleString()}</small>}
              {draft.state === 'draft' ? (
                <>
                  <button type="button" disabled={busy || !available}
                    onClick={() => setEditor({ fields: draft, draft })}>Edit draft</button>
                  <button type="button" disabled={busy || !available}
                    onClick={() => void transition(draft, 'submit_review')}>Submit for review</button>
                </>
              ) : (
                <button type="button" disabled={busy || !available}
                  onClick={() => void transition(draft, 'return_to_draft')}>Return to draft</button>
              )}
              {draft.state === 'review' && <button type="button" disabled={busy || !available}
                onClick={() => void transition(draft, 'approve')}>Approve content</button>}
              {(draft.state === 'approved' || draft.state === 'planned') && (
                <button type="button" disabled={busy || !available} onClick={() => {
                  setPlanningId(draft.id);
                  setPlanningTime('');
                }}>{draft.state === 'planned' ? 'Change planned time' : 'Plan publish time'}</button>
              )}
            </aside>
            {planningId === draft.id && (
              <form className="station-details-editor social-planning-form" onSubmit={(event) => {
                event.preventDefault();
                void transition(draft, 'plan');
              }}>
                <label>Planned publish time (local time)
                  <input type="datetime-local" required value={planningTime}
                    onChange={(event) => setPlanningTime(event.target.value)} />
                </label>
                <button type="submit" disabled={busy || !available}>Save planned time</button>
              </form>
            )}
          </article>
        ))}
      </div>
    </section>
  );
}
