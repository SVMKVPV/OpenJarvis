import { useEffect, useRef, useState } from 'react';
import { previewWorkflowTransform } from '../lib/api';

const MODES = [
  ['concatenate', 'Combine input'],
  ['first_line', 'Keep first line'],
  ['json_field', 'Extract JSON field'],
  ['json_select', 'Keep selected JSON fields'],
  ['json_literal', 'Output fixed JSON'],
] as const;

export function WorkflowTransformEditor({ stepId, expression, disabled, onChange }: {
  stepId: string;
  expression: string;
  disabled: boolean;
  onChange: (expression: string) => void;
}) {
  const [operation, ...fields] = expression.split(':');
  const knownMode = MODES.some(([value]) => value === expression)
    || (operation === 'json_field' || operation === 'json_select' || operation === 'json_literal') && fields.length > 0;
  const mode = !expression ? 'concatenate' : knownMode ? operation : 'custom';
  const needsFields = mode === 'json_field' || mode === 'json_select';
  const [sample, setSample] = useState('');
  const [pending, setPending] = useState(false);
  const key = JSON.stringify([expression, sample]);
  const [preview, setPreview] = useState<{ key: string; success: boolean; output: string } | null>(null);
  const result = preview?.key === key ? preview : null;
  const active = useRef<AbortController | null>(null);
  useEffect(() => () => active.current?.abort(), []);

  const test = async () => {
    if (pending) return;
    const request = new AbortController();
    active.current = request;
    setPending(true);
    setPreview(null);
    try {
      const tested = await previewWorkflowTransform(expression, sample, request.signal);
      if (!request.signal.aborted) setPreview({ key, ...tested });
    } catch {
      if (!request.signal.aborted) setPreview({ key, success: false, output: 'Transform preview is unavailable.' });
    } finally {
      if (!request.signal.aborted) setPending(false);
    }
  };

  return <>
    <label>Transform for {stepId}
      <select value={mode} disabled={disabled} onChange={(event) => {
        const next = event.target.value;
        if (next === 'json_literal') onChange('json_literal:{}');
        else onChange(next === 'json_field' || next === 'json_select' ? `${next}:` : next);
      }}>
        {mode === 'custom' && <option value="custom">{expression} (configured)</option>}
        {MODES.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
      </select>
    </label>
    {needsFields && <label>{mode === 'json_field' ? 'JSON field name' : 'JSON field names'} for {stepId}
      <input value={fields.join(':')} disabled={disabled} maxLength={980}
        onChange={(event) => onChange(`${mode}:${event.target.value}`)} />
      {mode === 'json_select' && <small>Separate field names with commas.</small>}
    </label>}
    {mode === 'json_literal' && <label>Fixed JSON for {stepId}
      <textarea value={fields.join(':')} disabled={disabled} rows={4} maxLength={987}
        onChange={(event) => onChange(`json_literal:${event.target.value}`)} />
    </label>}
    <details>
      <summary>Preview transform for {stepId}</summary>
      <label>Sample input for {stepId}
        <textarea value={sample} rows={3} maxLength={16000} onChange={(event) => setSample(event.target.value)} />
      </label>
      <button type="button" disabled={pending} onClick={() => void test()}>
        {pending ? 'Testing…' : 'Test transform'}
      </button>
      {result && <div role={result.success ? 'status' : 'alert'}>
        <pre style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>
          {result.output || 'Empty output'}
        </pre>
      </div>}
    </details>
  </>;
}
