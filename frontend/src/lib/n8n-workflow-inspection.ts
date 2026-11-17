type N8nNode = { id: string; type: string; usesCredentials: boolean; disabled: boolean };
type N8nConnection = { source: string; target: string; condition: string };

function object(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown> : null;
}

export function inspectN8nWorkflow(value: unknown) {
  const document = object(value);
  if (!document || !Array.isArray(document.nodes) || !object(document.connections)) {
    throw new Error('Select a single n8n workflow JSON export.');
  }
  if (document.nodes.length === 0 || document.nodes.length > 200) {
    throw new Error('Select a workflow with 1–200 nodes.');
  }

  const nodes: N8nNode[] = [];
  const known = new Set<string>();
  for (const value of document.nodes) {
    const node = object(value);
    if (!node || typeof node.name !== 'string' || !node.name.trim() ||
        typeof node.type !== 'string' || !node.type.trim() || known.has(node.name)) {
      throw new Error('The workflow contains an invalid or duplicate node name.');
    }
    known.add(node.name);
    nodes.push({
      id: node.name, type: node.type,
      usesCredentials: Object.keys(object(node.credentials) ?? {}).length > 0,
      disabled: node.disabled === true,
    });
  }

  const connections: N8nConnection[] = [];
  let skippedConnections = 0;
  for (const [source, channels] of Object.entries(object(document.connections) ?? {})) {
    if (!object(channels)) throw new Error('The workflow contains an invalid connection source.');
    for (const [channel, outputs] of Object.entries(object(channels) ?? {})) {
      if (!Array.isArray(outputs)) throw new Error('The workflow contains invalid output connections.');
      outputs.forEach((output, index) => {
        if (output == null) return;
        if (!Array.isArray(output)) throw new Error('The workflow contains an invalid output connection.');
        for (const link of output) {
          const target = object(link)?.node;
          if (typeof target !== 'string' || !target.trim()) throw new Error('A connection has an invalid target.');
          if (connections.length + skippedConnections >= 500) {
            throw new Error('Select a workflow with up to 500 connections.');
          }
          if (!known.has(source) || !known.has(target)) {
            skippedConnections++;
            continue;
          }
          connections.push({ source, target, condition: `${channel} ${index + 1}` });
        }
      });
    }
  }
  const name = typeof document.name === 'string' ? document.name.trim() : '';
  return { name: name || 'Unnamed n8n workflow', nodes, connections, skippedConnections };
}
