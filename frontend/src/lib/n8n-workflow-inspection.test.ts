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

  it('rejects connections to missing nodes', () => {
    expect(() => inspectN8nWorkflow({
      nodes: [{ name: 'Start', type: 'n8n-nodes-base.manualTrigger' }],
      connections: { Start: { main: [[{ node: 'Missing' }]] } },
    })).toThrow('A connection points to an unknown node.');
  });
});
