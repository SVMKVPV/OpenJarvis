import type { WorkflowRunDetail } from './api';

export function reviewedWorkflowOutput(
  run: Pick<WorkflowRunDetail, 'status' | 'steps' | 'graph'> | null, draftId: string, approvalId: string,
): string | null {
  if (run?.status !== 'succeeded') return null;
  const attempts = new Map(run.steps.map((step) => [step.node_id, step]));
  const draft = attempts.get(draftId);
  const approval = attempts.get(approvalId);
  const actionId = approval?.metadata.approval_id;
  if (!draft?.success || !draft.output.trim() ||
      approval?.metadata.approval_status !== 'approved' || typeof actionId !== 'string') return null;
  const reviewIndex = run.steps.findIndex((step) => step.node_id === approvalId &&
    step.metadata.workflow_status === 'waiting_approval' &&
    step.metadata.approval_id === actionId,
  );
  if (reviewIndex < 0) return null;
  const reviewedInput = run.steps[reviewIndex].metadata.review_input;
  if (typeof reviewedInput !== 'string' || reviewedInput !== approval.output) return null;

  const reviewAttempts = new Map(run.steps.slice(0, reviewIndex).map((step) => [step.node_id, step]));
  const reviewedOutputs = new Map<string, string>();
  for (const edge of run.graph.edges ?? []) {
    if (edge.target !== approvalId || typeof edge.source !== 'string') continue;
    const step = reviewAttempts.get(edge.source);
    if (!step?.success || !step.output) continue;
    if (edge.condition && (typeof edge.condition !== 'string' ||
        edge.condition.trim().toLowerCase() !== step.output.trim().toLowerCase())) continue;
    reviewedOutputs.set(edge.source, step.output);
  }
  return reviewedOutputs.get(draftId) === draft.output &&
    [...reviewedOutputs.values()].join('\n\n') === reviewedInput ? draft.output : null;
}
