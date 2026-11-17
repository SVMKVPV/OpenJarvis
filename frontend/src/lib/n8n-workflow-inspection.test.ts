import { describe, expect, it } from 'vitest';
import { inspectN8nWorkflow } from './n8n-workflow-inspection';

describe('n8n workflow inspection', () => {
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
    expect(preview.connections).toEqual([{ source: 'Start', target: 'End', condition: 'main 1' }]);
  });
});
