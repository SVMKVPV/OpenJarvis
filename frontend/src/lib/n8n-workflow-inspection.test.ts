import { describe, expect, it } from 'vitest';
import { inspectN8nWorkflow } from './n8n-workflow-inspection';

describe('n8n workflow inspection', () => {
  it('converts a manual linear chain with fixed JSON while preserving node names', () => {
    const preview = inspectN8nWorkflow({
      name: 'Prepare sample',
      nodes: [
        { name: 'Start here', type: 'n8n-nodes-base.manualTrigger', parameters: {} },
        { name: 'Data', type: 'n8n-nodes-base.set', typeVersion: 3.4,
          parameters: { mode: 'raw', jsonOutput: '{"status":"ready","size":2}' } },
        { name: 'Finish', type: 'n8n-nodes-base.noOp' },
      ],
      connections: {
        'Start here': { main: [[{ node: 'Data', type: 'main', index: 0 }]] },
        Data: { main: [[{ node: 'Finish', type: 'main', index: 0 }]] },
      },
    });
    expect(preview.draft).toEqual({
      name: 'Prepare sample',
      nodes: [
        { id: 'Start here', type: 'transform', transform_expr: 'json_literal:{}' },
        { id: 'Data', type: 'transform', transform_expr: 'json_literal:{"status":"ready","size":2}' },
        { id: 'Finish', type: 'transform', transform_expr: 'concatenate' },
      ],
      edges: [{ source: 'Start here', target: 'Data' }, { source: 'Data', target: 'Finish' }],
    });
  });

  it.each(['={{ $json }}', '{"nested.key":"value"}'])('leaves dynamic or path-based output inspection-only (%s)', (jsonOutput) => {
    const preview = inspectN8nWorkflow({
      nodes: [
        { name: 'Start', type: 'n8n-nodes-base.manualTrigger' },
        { name: 'Data', type: 'n8n-nodes-base.set', typeVersion: 3.4,
          parameters: { mode: 'raw', jsonOutput } },
      ],
      connections: { Start: { main: [[{ node: 'Data', type: 'main', index: 0 }]] } },
    });
    expect(preview.draft).toBeUndefined();
    expect(preview.conversionIssue).toContain('Data');
  });
  it('keeps the graph and credential presence without retaining settings or identifiers', () => {
    const preview = inspectN8nWorkflow({
      name: 'Optional template',
      nodes: [
        { name: 'Choose', type: 'n8n-nodes-base.if' },
        {
          name: 'Send',
          type: 'n8n-nodes-base.gmail',
          disabled: true,
          credentials: { gmailOAuth2: { id: 'private-id', name: 'private account' } },
          parameters: { body: 'private body' },
        },
      ],
      connections: { Choose: { main: [[], [{ node: 'Send', type: 'main', index: 0 }]] } },
    });
    expect(preview.nodes[1]).toEqual({
      id: 'Send', type: 'n8n-nodes-base.gmail', usesCredentials: true, disabled: true,
    });
    expect(preview.connections).toEqual([{ source: 'Choose', target: 'Send', condition: 'main 2' }]);
    expect(JSON.stringify(preview)).not.toContain('private');
    expect(preview.draft).toBeUndefined();
  });

  it('previews valid links and counts links with missing nodes', () => {
    const preview = inspectN8nWorkflow({
      nodes: [
        { name: 'Start', type: 'n8n-nodes-base.manualTrigger' },
        { name: 'End', type: 'n8n-nodes-base.noOp' },
      ],
      connections: {
        Start: { main: [[{ node: 'Missing' }, { node: 'End' }]] },
        Missing: { main: [[{ node: 'End' }]] },
      },
    });
    expect(preview.skippedConnections).toBe(2);
    expect(preview.draft).toBeUndefined();
    expect(preview.connections).toEqual([{ source: 'Start', target: 'End', condition: 'main 1' }]);
  });
});
