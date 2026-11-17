import { useEffect, useRef, useState } from 'react';
import { previewWorkflowCondition, type WorkflowConditionResult } from '../lib/api';

export function WorkflowConditionPreview({ expression, branches }: {
  expression: string;
  branches: Array<{ target: string; condition?: string }>;
}) {
  const [sample, setSample] = useState('{"_input":"yes"}');
  const [pending, setPending] = useState(false);
  const [preview, setPreview] = useState<{ key: string; result: WorkflowConditionResult } | null>(null);
  const key = JSON.stringify([expression, branches, sample]);
  const result = preview?.key === key ? preview.result : null;
  const activeRequest = useRef<AbortController | null>(null);
  useEffect(() => () => activeRequest.current?.abort(), []);

  const check = async () => {
    if (pending) return;
    let outputs: Record<string, string>;
    try {
      outputs = JSON.parse(sample);
      if (!outputs || typeof outputs !== 'object' || Array.isArray(outputs)
          || Object.values(outputs).some((value) => typeof value !== 'string')) throw new Error();
    } catch {
      setPreview({ key, result: {
        success: false, output: 'Enter a JSON object with text values.', matched_targets: [],
      } });
      return;
    }
    const request = new AbortController();
    activeRequest.current = request;
    setPreview(null);
    setPending(true);
    try {
      const tested = await previewWorkflowCondition(expression, outputs, branches, request.signal);
      if (!request.signal.aborted) setPreview({ key, result: tested });
    } catch {
      if (!request.signal.aborted) setPreview({ key, result: {
        success: false, output: 'Condition preview is unavailable.', matched_targets: [],
      } });
    } finally {
      if (!request.signal.aborted) setPending(false);
    }
  };

  return <details>
    <summary>Preview branch condition</summary>
    <label>Sample step outputs
      <textarea value={sample} rows={3} maxLength={16000} onChange={(event) => setSample(event.target.value)} />
    </label>
    <small>Use step IDs for keys. _input is the initial workflow input.</small>
    <button type="button" disabled={pending} onClick={() => void check()}>
      {pending ? 'Testing…' : 'Test condition'}
    </button>
    {result && (result.success ? <div role="status">
      <p>Condition returned <code>{result.output}</code>.</p>
      <p>{result.matched_targets.length ? `Matching branches ${result.matched_targets.join(', ')}` : 'No matching branches.'}</p>
    </div> : <p role="alert">{result.output}</p>)}
  </details>;
}
