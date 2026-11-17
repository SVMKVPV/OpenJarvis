import { useId } from 'react';
import { isJsonTextCondition, jsonTextCondition, readJsonTextCondition } from '../lib/workflow-json-condition';

export function WorkflowConditionEditor({ stepId, expression, disabled, onChange }: {
  stepId?: string;
  expression: string;
  disabled?: boolean;
  onChange: (expression: string) => void;
}) {
  const fieldMode = isJsonTextCondition(expression);
  const fields = readJsonTextCondition(expression) ?? { key: '', value: '' };
  const label = stepId ? ` for ${stepId}` : '';
  const expectedTextLabel = useId();
  return <>
    <label>Condition type{label}
      <select value={fieldMode ? 'json-text' : 'expression'} disabled={disabled}
        onChange={(event) => onChange(event.target.value === 'json-text' ? jsonTextCondition('', '') : '')}>
        <option value="expression">Expression</option>
        <option value="json-text">JSON text equals</option>
      </select>
    </label>
    {fieldMode ? <>
      <label>JSON field{label}
        <input value={fields.key} disabled={disabled} maxLength={128}
          onChange={(event) => onChange(jsonTextCondition(event.target.value, fields.value))} />
      </label>
      <label>
        <span id={expectedTextLabel}>Expected text{label}</span>
        <textarea aria-labelledby={expectedTextLabel} value={fields.value} disabled={disabled} maxLength={500} rows={2}
          onChange={(event) => onChange(jsonTextCondition(fields.key, event.target.value))} />
      </label>
      <small>Matches the entire text, including case. The matching branch receives the original JSON.</small>
    </> : <label>Condition expression{label}
      <input value={expression} disabled={disabled} maxLength={4000}
        placeholder="outputs['_input'] == 'yes'" onChange={(event) => onChange(event.target.value)} />
    </label>}
  </>;
}
