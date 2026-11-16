import { type FormEvent, useEffect, useState } from 'react';
import { askAgent, fetchAgentMessages, type AgentMessage } from '../lib/api';

export function WorkstationAgentInbox({ agentId }: { agentId: string }) {
  const [draft, setDraft] = useState('');
  const [messages, setMessages] = useState<AgentMessage[]>([]);
  const [sending, setSending] = useState(false);
  const [sendStatus, setSendStatus] = useState('');
  const [inboxUnavailable, setInboxUnavailable] = useState(false);

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
  }, [agentId]);

  const send = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const content = draft.trim();
    if (!content || sending) return;
    setSending(true);
    setSendStatus('');
    try {
      await askAgent(agentId, content);
      setDraft('');
      setSendStatus('Message submitted. The reply will appear here.');
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
            <strong>{message.direction === 'user_to_agent' ? 'You' : 'Agent'}</strong>
            <p>{message.content}</p>
          </li>
        ))}
      </ol>
      <form onSubmit={send}>
        <label>Message to linked agent
          <textarea value={draft} onChange={(event) => setDraft(event.target.value)}
            maxLength={4000} disabled={sending} required />
        </label>
        <button type="submit" disabled={sending || !draft.trim()}>
          {sending ? 'Sending…' : 'Send to agent'}
        </button>
      </form>
      {sendStatus && <p role="status">{sendStatus}</p>}
    </details>
  );
}
