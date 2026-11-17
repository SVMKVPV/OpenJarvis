import type { SavedWorkflowDefinition } from './api';

type N8nNode = { id: string; type: string; usesCredentials: boolean; disabled: boolean };
type N8nConnection = { source: string; target: string; condition: string };
type DraftGraph = SavedWorkflowDefinition['graph'];
type DraftEdge = { source: string; target: string; condition?: 'true' | 'false' };

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

function stringCondition(node: Record<string, unknown>): string | undefined {
  if (node.type !== 'n8n-nodes-base.if' || typeof node.typeVersion !== 'number' ||
      ![2, 2.1, 2.2, 2.3, 2.4].includes(node.typeVersion)) return undefined;
  const parameters = object(node.parameters);
  const filter = object(parameters?.conditions);
  const options = object(filter?.options);
  if (!parameters || !filter || options?.caseSensitive !== true ||
      options.typeValidation !== 'strict' || parameters.looseTypeValidation === true ||
      object(parameters.options)?.ignoreCase === true ||
      !Array.isArray(filter.conditions) || filter.conditions.length !== 1) return undefined;
  const condition = object(filter.conditions[0]);
  const operator = object(condition?.operator);
  const left = condition?.leftValue;
  const right = condition?.rightValue;
  if (operator?.type !== 'string' || operator.operation !== 'equals' ||
      typeof left !== 'string' || typeof right !== 'string' ||
      right.startsWith('=') || right.includes('{{') || right.length > 500) return undefined;
  const match = /^=\{\{\s*\$json\.([a-zA-Z_][a-zA-Z0-9_]{0,127})\s*\}\}$/.exec(left);
  if (match) return `json_string_equals:${JSON.stringify({ key: match[1], value: right })}`;
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
  const draftNodes: DraftGraph['nodes'] = [];
  const branches = new Set<string>();
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
    const condition = stringCondition(node);
    if ((!transform && !condition) || node.disabled === true || Object.keys(object(node.credentials) ?? {}).length ||
        node.name === '_input' || node.name.length > 128 || node.continueOnFail === true ||
        (node.onError !== undefined && node.onError !== 'stopWorkflow')) {
      conversionIssue ||= `${node.name} needs manual reconstruction.`;
    } else if (condition) {
      draftNodes.push({ id: node.name, type: 'condition', condition_expr: condition });
      branches.add(node.name);
    } else {
      draftNodes.push({ id: node.name, type: 'transform', transform_expr: transform });
    }
  }

  const connections: N8nConnection[] = [];
  let skippedConnections = 0;
  const draftEdges: DraftEdge[] = [];
  let unsupportedConnection = false;
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
          const branch = branches.has(source);
          if (channel !== 'main' || index > (branch ? 1 : 0) || connection?.index !== 0 ||
              connection.type !== 'main') unsupportedConnection = true;
          draftEdges.push({ source, target, ...(branch ? { condition: index === 0 ? 'true' : 'false' } : {}) });
          connections.push({ source, target, condition: `${channel} ${index + 1}` });
        }
      });
    }
  }
  const name = typeof document.name === 'string' ? document.name.trim() : '';
  const workflowName = name || 'Unnamed n8n workflow';
  const triggers = nodes.filter((node) => node.type === 'n8n-nodes-base.manualTrigger');
  const outgoing = new Map<string, typeof draftEdges>();
  for (const edge of draftEdges) {
    const edges = outgoing.get(edge.source) ?? [];
    edges.push(edge);
    outgoing.set(edge.source, edges);
  }
  const unsupportedFanout = nodes.some(({ id }) => {
    const edges = outgoing.get(id) ?? [];
    return branches.has(id) ? edges.length !== 2 || edges[0].condition === edges[1].condition
      : edges.length > 1;
  });
  const visited = new Set<string>();
  const queue = triggers.map(({ id }) => id);
  while (queue.length) {
    const current = queue.pop()!;
    if (visited.has(current)) continue;
    visited.add(current);
    queue.push(...(outgoing.get(current) ?? []).map(({ target }) => target));
  }
  if (triggers.length !== 1 || unsupportedConnection || unsupportedFanout || skippedConnections ||
      connections.length !== nodes.length - 1 || visited.size !== nodes.length) {
    conversionIssue ||= 'Draft import needs one Manual Trigger and separate paths for each supported If branch.';
  }
  const draft: SavedWorkflowDefinition['graph'] | undefined = conversionIssue ? undefined : {
    name: workflowName,
    nodes: draftNodes,
    edges: draftEdges,
  };
  return { name: workflowName, nodes, connections, skippedConnections, draft, conversionIssue };
}
