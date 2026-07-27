import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const renderMermaid = vi.fn();

vi.mock('mermaid', () => ({
  default: { initialize: vi.fn(), render: renderMermaid },
}));

import { AssistToBuildReviewCard } from './AssistToBuildReviewCard';

const summary = {
  stage: 'as_is' as const,
  title: 'Validate the current process',
  summary_markdown: 'Current **handoff** process.',
  mermaid: 'flowchart LR\nA-->B',
  assumptions: ['One owner'],
  risks: ['Manual handoff'],
  requirements: ['Keep audit trail'],
};

describe('AssistToBuildReviewCard', () => {
  beforeEach(() => {
    renderMermaid.mockReset();
  });

  it('renders the AS-IS checkpoint and sends the semantic approval response', async () => {
    renderMermaid.mockResolvedValue({ svg: '<svg aria-label="process" />' });
    const onRespond = vi.fn();
    render(<AssistToBuildReviewCard approvalId="review-1" summary={summary} onRespond={onRespond} />);

    expect(screen.getByText('AS-IS review')).toBeInTheDocument();
    expect(screen.getByText('Manual handoff')).toBeInTheDocument();
    await waitFor(() => expect(screen.getByLabelText('process')).toBeInTheDocument());
    fireEvent.click(screen.getByRole('button', { name: 'Approve AS-IS' }));
    expect(onRespond).toHaveBeenCalledWith('review-1', 'approve_as_is');
  });

  it('falls back to Mermaid source when rendering fails', async () => {
    renderMermaid.mockRejectedValue(new Error('invalid diagram'));
    const onRespond = vi.fn();
    render(<AssistToBuildReviewCard approvalId="review-2" summary={summary} onRespond={onRespond} />);

    await waitFor(() => expect(screen.getByText((_content, element) => (
      element?.tagName === 'PRE' && element.textContent === 'flowchart LR\nA-->B'
    ))).toBeInTheDocument());
    fireEvent.change(screen.getByPlaceholderText('Describe what should change'), { target: { value: 'Clarify handoff' } });
    fireEvent.click(screen.getByRole('button', { name: 'Request changes' }));
    expect(onRespond).toHaveBeenCalledWith('review-2', 'request_changes', 'Clarify handoff');
  });
});
