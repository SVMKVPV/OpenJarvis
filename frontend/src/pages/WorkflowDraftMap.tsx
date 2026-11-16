import { useMemo } from 'react';
import { Background, Handle, MarkerType, Position, ReactFlow, type Edge, type Node, type NodeProps } from '@xyflow/react';

type DraftStep = { id: string; type?: string };
type DraftConnection = { source: string; target: string; condition?: string };
type StepNode = Node<{ label: string; kind: string; onOpen: (id: string) => void }, 'draftStep'>;

function DraftStepNode({ id, data }: NodeProps<StepNode>) {
  return (
    <>
      <Handle type="target" position={Position.Top} />
      <button type="button" className="workflow-map-step" onClick={() => data.onOpen(id)}>
        <strong>{data.label}</strong>
        <small>{data.kind}</small>
      </button>
      <Handle type="source" position={Position.Bottom} />
    </>
  );
}

const nodeTypes = { draftStep: DraftStepNode };

export function WorkflowDraftMap({ steps, connections, onOpen, canConnect, onConnect }: {
  steps: DraftStep[];
  connections: DraftConnection[];
  onOpen: (id: string) => void;
  canConnect: (source: string, target: string) => boolean;
  onConnect: (source: string, target: string) => void;
}) {
  const { nodes, edges } = useMemo(() => {
    const known = new Set(steps.map((step) => step.id));
    const valid = connections.filter(({ source, target }) => known.has(source) && known.has(target));
    const incoming = new Map(steps.map((step) => [step.id, 0]));
    const outgoing = new Map<string, string[]>();
    for (const { source, target } of valid) {
      incoming.set(target, (incoming.get(target) ?? 0) + 1);
      const successors = outgoing.get(source) ?? [];
      successors.push(target);
      outgoing.set(source, successors);
    }

    let layer = steps.filter((step) => incoming.get(step.id) === 0).map((step) => step.id);
    const positions = new Map<string, { x: number; y: number }>();
    let level = 0;
    while (layer.length) {
      const next: string[] = [];
      layer.forEach((id, index) => {
        positions.set(id, { x: (index - (layer.length - 1) / 2) * 165, y: level * 90 });
        for (const target of outgoing.get(id) ?? []) {
          const remaining = (incoming.get(target) ?? 0) - 1;
          incoming.set(target, remaining);
          if (remaining === 0) next.push(target);
        }
      });
      level += 1;
      layer = next;
    }

    const nodes: StepNode[] = steps.map((step) => ({
      id: step.id,
      type: 'draftStep',
      position: positions.get(step.id) ?? { x: 0, y: level++ * 90 },
      data: { label: step.id, kind: step.type === 'agent' ? 'model' : step.type ?? 'step', onOpen },
    }));
    const edges: Edge[] = valid.map(({ source, target, condition }, index) => ({
      id: String(index),
      source,
      target,
      label: condition || undefined,
      markerEnd: { type: MarkerType.ArrowClosed, color: '#bd9549' },
      style: { stroke: '#bd9549' },
      labelStyle: { fill: '#ebd299' },
      labelBgStyle: { fill: '#171107' },
    }));
    return { nodes, edges };
  }, [steps, connections, onOpen]);

  return (
    <div className="workflow-draft-map" aria-label="Saved workflow diagram">
      <ReactFlow<StepNode> nodes={nodes} edges={edges} nodeTypes={nodeTypes} fitView
        fitViewOptions={{ padding: 0.12, maxZoom: 1 }} minZoom={0.2}
        isValidConnection={({ source, target }) => canConnect(source, target)}
        onConnect={({ source, target }) => onConnect(source, target)}
        connectionLineStyle={{ stroke: '#d6ad52', strokeWidth: 2 }}
        nodesDraggable={false} nodesFocusable={false}
        edgesFocusable={false} preventScrolling={false} zoomOnDoubleClick={false}>
        <Background color="#3b2e15" gap={18} />
      </ReactFlow>
    </div>
  );
}
