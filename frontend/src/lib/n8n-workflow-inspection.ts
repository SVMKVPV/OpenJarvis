import type { SavedWorkflowDefinition } from './api';

type N8nNode = { id: string; type: string; usesCredentials: boolean; disabled: boolean };
type N8nConnection = { source: string; target: string; condition: string };

function object(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown> : null;
}

function literalTransform(node: Record<string, unknown>): string | undefined {
  const parameters = object(node.parameters) ?? {};
  if (node.parameters !== undefined && !object(node.parameters)) return undefined;
  if (node.type === 'n8n-nodes-base.manualTrigger' && !Object.keys(parameters).length) return 'json_literal:{}';
  if (node.type === 'n8n-nodes-base.noOp' && !Object.keys(parameters).length) return 'concatenate';
  const options = parameters.options === undefined ? {} : object(parameters.options);
  if (node.type !== 'n8n-nodes-base.set' || typeof node.typeVersion !== 'number' ||
      ![3.3, 3.4, 3.5].includes(node.typeVersion) || parameters.mode !== 'raw' ||
      (parameters.includeOtherFields !== undefined && parameters.includeOtherFields !== false) ||
      Object.keys(parameters).some((key) => !['mode', 'jsonOutput', 'includeOtherFields', 'options'].includes(key)) ||
      !options || Object.keys(options).length) {
    return undefined;
  }
  const literal = parameters.jsonOutput;
  if (typeof literal !== 'string' || literal.length > 987 || literal.includes('{{')) return undefined;
  try {
    const data = object(JSON.parse(literal, (_key, value) => {
      if (typeof value === 'number' &&
          (!Number.isFinite(value) || Number.isInteger(value) && !Number.isSafeInteger(value))) {
        throw new Error('Number is outside the supported JSON range.');
      }
      return value;
    }));
    if (data && Object.keys(data).every((key) =>
      /^[a-zA-Z_][a-zA-Z0-9_-]*$/.test(key) && !['__proto__', 'constructor', 'prototype'].includes(key),
    )) return `json_literal:${literal}`;
  } catch {
    // An expression or malformed object needs manual reconstruction.
  }
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
  const transforms: SavedWorkflowDefinition['graph']['nodes'] = [];
  let conversionIssue = Object.keys(object(document.pinData) ?? {}).length
    ? 'Pinned data needs manual reconstruction.' : '';
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
    const transform = literalTransform(node);
    if (!transform || node.disabled === true || Object.keys(object(node.credentials) ?? {}).length ||
        node.name === '_input' || node.name.length > 128) {
      conversionIssue ||= `${node.name} needs manual reconstruction.`;
    } else {
      transforms.push({ id: node.name, type: 'transform', transform_expr: transform });
    }
  }

  const connections: N8nConnection[] = [];
  let skippedConnections = 0;
  let nonLinearConnection = false;
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
          const connection = object(link);
          if (channel !== 'main' || index !== 0 || connection?.index !== 0 ||
              connection.type !== 'main') nonLinearConnection = true;
          connections.push({ source, target, condition: `${channel} ${index + 1}` });
        }
      });
    }
  }
  const name = typeof document.name === 'string' ? document.name.trim() : '';
  const workflowName = name || 'Unnamed n8n workflow';
  const triggers = nodes.filter((node) => node.type === 'n8n-nodes-base.manualTrigger');
  const next = new Map(connections.map(({ source, target }) => [source, target]));
  const visited = new Set<string>();
  let current: string | undefined = triggers[0]?.id;
  while (current && !visited.has(current)) {
    visited.add(current);
    current = next.get(current);
  }
  if (triggers.length !== 1 || nonLinearConnection || skippedConnections ||
      connections.length !== nodes.length - 1 || visited.size !== nodes.length || current) {
    conversionIssue ||= 'Draft import requires one unbranched path from a Manual Trigger.';
  }
  const draft: SavedWorkflowDefinition['graph'] | undefined = conversionIssue ? undefined : {
    name: workflowName,
    nodes: transforms,
    edges: connections.map(({ source, target }) => ({ source, target })),
  };
  return { name: workflowName, nodes, connections, skippedConnections, draft, conversionIssue };
}
