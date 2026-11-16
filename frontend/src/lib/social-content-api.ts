import { apiFetch } from './api';

export const SOCIAL_CHANNELS = {
  instagram: 'Instagram',
  facebook: 'Facebook',
  linkedin: 'LinkedIn',
  x: 'X',
  tiktok: 'TikTok',
  youtube: 'YouTube',
  pinterest: 'Pinterest',
  threads: 'Threads',
} as const;

export type SocialChannel = keyof typeof SOCIAL_CHANNELS;
export type SocialDraftState = 'draft' | 'review' | 'approved' | 'planned' | 'published';

export interface SocialPublication {
  channel: SocialChannel;
  url: string;
  posted_at: number;
}

export interface SocialDraftFields {
  title: string;
  caption: string;
  channels: SocialChannel[];
}

export interface SocialDraft extends SocialDraftFields {
  id: string;
  state: SocialDraftState;
  revision: number;
  scheduled_at: number | null;
  publications?: SocialPublication[];
}

export type SocialDraftAction = 'submit_review' | 'return_to_draft' | 'approve' | 'plan';

const base = '/v1/social-content/drafts';

async function readResponse(response: Response) {
  const payload = await response.json().catch(() => null);
  if (!response.ok || payload === null) {
    throw new Error(typeof payload?.detail === 'string'
      ? payload.detail : 'The Marketing draft queue is unavailable.');
  }
  return payload;
}

export interface SocialContentSummary {
  review_count: number;
  items: Pick<SocialDraft, 'id' | 'title' | 'channels' | 'state' | 'scheduled_at' | 'publications'>[];
}

export async function fetchSocialContentSummary(signal?: AbortSignal): Promise<SocialContentSummary> {
  const data = await readResponse(await apiFetch('/v1/social-content/summary', { signal }));
  if (!Number.isInteger(data.review_count) || !Array.isArray(data.items)) {
    throw new Error('The Marketing draft queue is unavailable.');
  }
  return data;
}

export async function listSocialDrafts(signal?: AbortSignal): Promise<SocialDraft[]> {
  const data = await readResponse(await apiFetch(base, { signal }));
  if (!Array.isArray(data.drafts)) throw new Error('The Marketing draft queue is unavailable.');
  return data.drafts;
}

export async function saveSocialDraft(
  fields: SocialDraftFields, current?: SocialDraft,
): Promise<SocialDraft> {
  const path = current ? `${base}/${encodeURIComponent(current.id)}` : base;
  return readResponse(await apiFetch(path, {
    method: current ? 'PUT' : 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(current ? { ...fields, revision: current.revision } : fields),
  }));
}

export async function updateSocialDraft(
  draft: SocialDraft, action: SocialDraftAction, scheduledAt?: number,
): Promise<SocialDraft> {
  return readResponse(await apiFetch(`${base}/${encodeURIComponent(draft.id)}/actions`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ action, revision: draft.revision, scheduled_at: scheduledAt }),
  }));
}

export async function recordSocialPublication(
  draft: SocialDraft, publication: SocialPublication,
): Promise<SocialDraft> {
  return readResponse(await apiFetch(`${base}/${encodeURIComponent(draft.id)}/publications`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ...publication, revision: draft.revision }),
  }));
}
