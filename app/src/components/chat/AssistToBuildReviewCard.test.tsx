import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

vi.mock('./VibeLabDiagram', () => ({
  VibeLabDiagram: ({ code }: { code: string }) => <div data-testid="vibelab-diagram">{code}</div>,
}));

import { AssistToBuildReviewCard } from './AssistToBuildReviewCard';

const summary = {
  stage: 'as_is' as const,
  title: 'Validate the current process',
  summary_markdown: 'Current **handoff** process.',
  diagram: {
    title: 'Current handoff', preset: 'business-process', direction: 'LR',
    nodes: [
      { id: 'start', type: 'start', label: 'Request' },
      { id: 'handoff', type: 'step', label: 'Manual handoff' },
      { id: 'end', type: 'end', label: 'Complete' },
    ],
    edges: [{ source: 'start', target: 'handoff' }, { source: 'handoff', target: 'end' }],
  },
  assumptions: ['One owner'],
  risks: ['Manual handoff'],
  requirements: ['Keep audit trail'],
};

describe('AssistToBuildReviewCard', () => {
  it('renders the AS-IS structured workflow and sends the semantic approval response', () => {
    const onRespond = vi.fn();
    render(<AssistToBuildReviewCard approvalId="review-1" summary={summary} onRespond={onRespond} />);

    expect(screen.getByText('AS-IS review')).toBeInTheDocument();
    expect(screen.getByText('Manual handoff')).toBeInTheDocument();
    expect(screen.getByTestId('vibelab-diagram')).toHaveTextContent('Current handoff');
    fireEvent.click(screen.getByRole('button', { name: 'Approve AS-IS' }));
    expect(onRespond).toHaveBeenCalledWith('review-1', 'approve_as_is');
  });

  it('keeps legacy artifacts without a diagram readable', () => {
    const onRespond = vi.fn();
    const legacySummary = { ...summary, diagram: undefined };
    render(<AssistToBuildReviewCard approvalId="review-2" summary={legacySummary} onRespond={onRespond} />);

    expect(screen.queryByTestId('vibelab-diagram')).not.toBeInTheDocument();
    expect(
      screen.getByText(
        (_content, element) => element?.tagName === 'P' && element.textContent === 'Current handoff process.'
      )
    ).toBeInTheDocument();
    fireEvent.change(screen.getByPlaceholderText('Describe what should change'), { target: { value: 'Clarify handoff' } });
    fireEvent.click(screen.getByRole('button', { name: 'Request changes' }));
    expect(onRespond).toHaveBeenCalledWith('review-2', 'request_changes', 'Clarify handoff');
  });
});
