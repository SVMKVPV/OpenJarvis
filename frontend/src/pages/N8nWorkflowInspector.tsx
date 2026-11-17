import { useRef, useState } from 'react';
import { inspectN8nWorkflow } from '../lib/n8n-workflow-inspection';
import type { SavedWorkflowDefinition } from '../lib/api';
import { WorkflowDraftMap } from './WorkflowDraftMap';

export function N8nWorkflowInspector({ onLoadDraft }: {
  onLoadDraft: (graph: SavedWorkflowDefinition['graph']) => void;
}) {
  const [workflow, setWorkflow] = useState<ReturnType<typeof inspectN8nWorkflow> | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const nodes = useRef(new Map<string, HTMLTableRowElement>());

  const inspect = async (file: File) => {
    setWorkflow(null);
    setError('');
    if (file.size > 2 * 1024 * 1024) {
      setError('Select an n8n workflow export under 2 MB.');
      return;
    }
    setLoading(true);
    try {
      setWorkflow(inspectN8nWorkflow(JSON.parse(await file.text())));
    } catch (failure) {
      setError(failure instanceof SyntaxError ? 'The file is invalid JSON.'
        : failure instanceof Error ? failure.message : 'The workflow could not be opened.');
    } finally {
      setLoading(false);
    }
  };

  return <details className="connector-editor">
    <summary>Inspect an n8n workflow export</summary>
    <label>n8n workflow JSON
      <input type="file" accept=".json,application/json" disabled={loading}
        onChange={(event) => {
          const file = event.currentTarget.files?.[0];
          event.currentTarget.value = '';
          if (file) void inspect(file);
        }} />
    </label>
    <small>Supported manual workflows can use No Operation, fixed JSON output, and strict text equality branches.</small>
    {loading && <p role="status">Reading workflow…</p>}
    {error && <p role="alert">{error}</p>}
    {workflow && <>
      <h4>{workflow.name}</h4>
      {workflow.draft ? <>
        <button type="button" onClick={() => workflow.draft && onLoadDraft(workflow.draft)}>
          Load as OpenJarvis draft
        </button>
        <small>Replaces the editor draft. Review literal values before saving or running.</small>
      </> : <p>{workflow.conversionIssue}</p>}
      {workflow.skippedConnections > 0 && <p role="status">
        Skipped {workflow.skippedConnections} {workflow.skippedConnections === 1 ? 'connection' : 'connections'} with missing nodes.
      </p>}
      <WorkflowDraftMap label="n8n workflow preview" steps={workflow.nodes}
        connections={workflow.connections} onOpen={(id) => nodes.current.get(id)?.focus()} />
      <table aria-label="Imported node requirements">
        <thead><tr><th scope="col">Node</th><th scope="col">Type</th><th scope="col">Setup</th></tr></thead>
        <tbody>{workflow.nodes.map((node) => (
          <tr key={node.id} tabIndex={-1} ref={(element) => {
            if (element) nodes.current.set(node.id, element);
            else nodes.current.delete(node.id);
          }}>
            <th scope="row">{node.id}</th><td>{node.type}</td>
            <td>{node.usesCredentials ? 'Credential reference' : 'No credential reference'}
              {node.disabled && ' · Disabled in export'}</td>
          </tr>
        ))}</tbody>
      </table>
    </>}
  </details>;
}
