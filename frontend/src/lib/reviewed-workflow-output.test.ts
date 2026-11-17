import { describe, expect, it } from 'vitest';
import type { WorkflowRunDetail } from './api';
import { reviewedWorkflowOutput } from './reviewed-workflow-output';

const workpaper = '# Workpaper\n\nTotal: AUD 12';
const evidence = 'Reviewed source';
const reviewInput = [evidence, workpaper].join('\n\n');

function reviewedRun(
  edges: WorkflowRunDetail['graph']['edges'] = [
    { source: 'source', target: 'review' },
    { source: 'draft', target: 'review' },
  ],
) {
  return {
    status: 'succeeded',
    graph: { name: 'Finance', nodes: [], edges },
    steps: [
      { node_id: 'draft', attempt: 1, success: true, output: workpaper, metadata: {} },
      { node_id: 'source', attempt: 1, success: true, output: evidence, metadata: {} },
      {
        node_id: 'review', attempt: 1, success: true, output: 'Waiting for approval',
        metadata: { approval_id: 'approval-1', workflow_status: 'waiting_approval', review_input: reviewInput },
      },
      {
        node_id: 'review', attempt: 2, success: true, output: reviewInput,
        metadata: { approval_id: 'approval-1', approval_status: 'approved' },
      },
    ],
  } satisfies Pick<WorkflowRunDetail, 'status' | 'graph' | 'steps'>;
}

describe('reviewedWorkflowOutput', () => {
  it('returns the exact draft even when the approval includes multiple inputs', () => {
    expect(reviewedWorkflowOutput(reviewedRun(), 'draft', 'review')).toBe(workpaper);
  });

  it('rejects draft text present only in another connected step', () => {
    const run = reviewedRun([{ source: 'source', target: 'review' }]);
    run.steps[1].output = reviewInput;
    expect(reviewedWorkflowOutput(run, 'draft', 'review')).toBeNull();
  });

  it('rejects draft text on an inactive branch', () => {
    const run = reviewedRun([
      { source: 'source', target: 'review' },
      { source: 'draft', target: 'review', condition: 'true' },
    ]);
    run.steps[1].output = reviewInput;
    expect(reviewedWorkflowOutput(run, 'draft', 'review')).toBeNull();
  });

  it('rejects changes to the input after review', () => {
    const run = reviewedRun();
    run.steps[3].output = reviewInput + '\nChanged after review';
    expect(reviewedWorkflowOutput(run, 'draft', 'review')).toBeNull();
  });
});
