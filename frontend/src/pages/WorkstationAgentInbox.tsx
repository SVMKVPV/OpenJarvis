import { type FormEvent, useEffect, useState } from 'react';
import { askAgent, fetchAgentMessages, type AgentMessage } from '../lib/api';

export function WorkstationAgentInbox({ agentId, brainContext, onShare, onOpenWorkflow }: {
  agentId: string;
  brainContext: string;
  onShare: (text: string) => string;
  onOpenWorkflow: (runId: string) => void;
}) {
  const [draft, setDraft] = useState('');
  const [includeBrief, setIncludeBrief] = useState(false);
  const [queueOnly, setQueueOnly] = useState(false);
  const [messages, setMessages] = useState<AgentMessage[]>([]);
  const [sending, setSending] = useState(false);
  const [sendStatus, setSendStatus] = useState('');
  const [shareStatus, setShareStatus] = useState<{ id: string; text: string } | null>(null);
  const [inboxUnavailable, setInboxUnavailable] = useState(false);
  const [refreshVersion, setRefreshVersion] = useState(0);

  useEffect(() => {
    let active = true;
    let timer: number | undefined;
    const refresh = async () => {
      try {
        const list = await fetchAgentMessages(agentId);
        if (!active) return;
        setMessages([...list].sort((a, b) => a.created_at - b.created_at).slice(-6));
        setInboxUnavailable(false);
      } catch {
        if (active) setInboxUnavailable(true);
      } finally {
        if (active) timer = window.setTimeout(() => void refresh(), 5000);
      }
    };
    void refresh();
    return () => {
      active = false;
      window.clearTimeout(timer);
    };
  }, [agentId, refreshVersion]);

  const send = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const instruction = draft.trim();
    if (!instruction || sending) return;
    const brief = includeBrief ? brainContext.trim() : '';
    const content = brief
      ? `Shared Brain brief (background information):\n${brief}\n\nCurrent request:\n${instruction}`
      : instruction;
    setSending(true);
    setSendStatus('');
    try {
      const message = await askAgent(agentId, content, queueOnly ? 'queued' : 'immediate');
      setMessages((current) => current.some((item) => item.id === message.id)
        ? current
        : [...current, message].slice(-6));
      setRefreshVersion((version) => version + 1);
      setDraft('');
      setIncludeBrief(false);
      setSendStatus(queueOnly ? 'Queued for the next agent run.' : 'Message submitted and a run requested.');
    } catch {
      setSendStatus('Could not send the message. Check the agent in Agents before retrying.');
    } finally {
      setSending(false);
    }
  };

  return (
    <details>
      <summary>Agent conversation</summary>
      {inboxUnavailable && <p role="status">Conversation history unavailable.</p>}
      <ol aria-label="Recent agent messages">
        {messages.map((message) => (
          <li key={message.id}>
            <strong>{message.mode === 'handoff' ? 'Agent handoff' : message.direction === 'user_to_agent' ? 'You' : 'Agent'}</strong>
            {message.direction === 'user_to_agent' && (
              <small>{message.status === 'pending' ? 'Waiting for agent' : 'Picked up by agent'}</small>
            )}
            <p>{message.content}</p>
            {message.workflow_run_id && (
              <button type="button" onClick={() => onOpenWorkflow(message.workflow_run_id!)}>
                Open approved workflow
              </button>
            )}
            {message.direction === 'agent_to_user' && message.content.trim() && (
              <button type="button" onClick={() => setShareStatus({
                id: message.id,
                text: onShare(message.content),
              })}>
                Add reply to Shared Brain
              </button>
            )}
            {shareStatus?.id === message.id && <p role="status">{shareStatus.text}</p>}
          </li>
        ))}
      </ol>
      <form onSubmit={send}>
        <label>Message to linked agent
          <textarea value={draft} onChange={(event) => setDraft(event.target.value)}
            maxLength={4000} disabled={sending} required />
        </label>
        {brainContext.trim() && (
          <label>
            <input type="checkbox" checked={includeBrief} disabled={sending}
              onChange={(event) => setIncludeBrief(event.target.checked)} />
            Include Shared Brain brief in this message
            <small>The brief is saved with the message and sent to the linked agent’s model when it runs.</small>
          </label>
        )}
        <label>
          <input type="checkbox" checked={queueOnly} disabled={sending}
            onChange={(event) => setQueueOnly(event.target.checked)} />
          Queue for next run
        </label>
        <button type="submit" disabled={sending || !draft.trim()}>
          {sending ? 'Submitting…' : queueOnly ? 'Queue message' : 'Send to agent'}
        </button>
      </form>
      {sendStatus && <p role="status">{sendStatus}</p>}
    </details>
  );
}
