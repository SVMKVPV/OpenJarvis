import { type FormEvent, useEffect, useState } from 'react';
import { transcribeAudio } from '../lib/api';
import { indexWorkflowEvidence } from '../lib/connectors-api';

const MAX_RECORDING_BYTES = 25 * 1024 * 1024;

export function WorkflowEvidenceUpload({ onIndexed, allowAudio = false }: {
  onIndexed: (reference: string) => void;
  allowAudio?: boolean;
}) {
  const [files, setFiles] = useState<File[]>([]);
  const [audio, setAudio] = useState<File | null>(null);
  const [audioUrl, setAudioUrl] = useState('');
  const [transcript, setTranscript] = useState('');
  const [transcribing, setTranscribing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const recording = allowAudio ? audio : null;
  const canIndex = !busy && !transcribing && (recording ? !!transcript.trim() : files.length > 0);

  useEffect(() => {
    if (!recording) {
      setAudioUrl('');
      return;
    }
    const url = URL.createObjectURL(recording);
    setAudioUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [recording]);

  const prepareTranscript = async () => {
    if (!recording || busy || transcribing) return;
    if (recording.size > MAX_RECORDING_BYTES) {
      setMessage('Choose a recording under 25 MB.');
      return;
    }
    setTranscribing(true);
    setMessage('');
    try {
      const result = await transcribeAudio(recording, recording.name);
      const text = result.text.trim();
      setTranscript(text);
      setMessage(text ? 'Transcript ready. Compare it with the recording before indexing.'
        : 'The speech backend returned no transcript.');
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Transcription failed.');
    } finally {
      setTranscribing(false);
    }
  };

  const indexEvidence = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!canIndex) return;
    const form = event.currentTarget;
    setBusy(true);
    setMessage('');
    try {
      const evidence = [...files];
      if (recording) {
        const text = `Transcript of ${recording.name}\n\n${transcript.trim()}`;
        evidence.push(new File([text], `${recording.name}.transcript.txt`, { type: 'text/plain' }));
      }
      const result = await indexWorkflowEvidence(evidence);
      if (!result.chunks_added) {
        setMessage('No readable text was found in the selected files.');
        return;
      }
      if (result.reference && result.chunks_added <= 16) {
        onIndexed(result.reference);
        setMessage('Evidence indexed and selected as the run input.');
      } else {
        setMessage(`Indexed ${result.chunks_added} excerpts. Use a keyword search for this upload.`);
      }
      form.reset();
      setFiles([]);
      setAudio(null);
      setTranscript('');
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Evidence upload failed.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <form className="connector-editor" onSubmit={indexEvidence}>
      <label>Source evidence files
        <input type="file" accept=".txt,.md,.pdf,.docx,.csv" multiple disabled={busy || transcribing}
          onChange={(event) => setFiles(Array.from(event.target.files ?? []))} />
      </label>
      {allowAudio && (
        <>
          <label>Recording (optional)
            <input type="file" accept=".wav,.mp3,.m4a,.ogg,.webm,.flac" disabled={busy || transcribing}
              onChange={(event) => {
                setAudio(event.target.files?.[0] ?? null);
                setTranscript('');
                setMessage('');
              }} />
          </label>
          {recording && (
            <>
              {audioUrl && <audio controls src={audioUrl} aria-label="Source recording" />}
              <button type="button" disabled={busy || transcribing} onClick={prepareTranscript}>
                {transcribing ? 'Transcribing…' : 'Transcribe recording'}
              </button>
              <label>Transcript to index
                <textarea rows={6} value={transcript} disabled={busy || transcribing}
                  onChange={(event) => setTranscript(event.target.value)} />
              </label>
              <small>Transcription uses the configured speech backend. Only the transcript
                is indexed with the source documents. Listen here to check pronunciation and tone.</small>
            </>
          )}
        </>
      )}
      <button disabled={!canIndex}>
        {busy ? 'Indexing…' : 'Index evidence'}
      </button>
      <small>Index the files together to review them as one batch. This supports text,
        Markdown, PDF, Word, and CSV files.</small>
      {message && <small role="status">{message}</small>}
    </form>
  );
}
