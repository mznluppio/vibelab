import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

vi.mock('./chat/MermaidDiagram', () => ({
  MermaidDiagram: ({ code }: { code: string }) => <div data-testid="mermaid-diagram">{code}</div>,
}));

import AgentMessage from './AgentMessage';

describe('AgentMessage Markdown', () => {
  it('uses MermaidDiagram for a completed fenced Mermaid response', () => {
    render(
      <AgentMessage
        agentData={{ steps: [], iterations: 1, tool_calls_made: 0, completion_reason: 'complete' }}
        finalResponse={'```mermaid\nflowchart LR\nA-->B\n```'}
      />
    );

    expect(screen.getByTestId('mermaid-diagram')).toHaveTextContent('flowchart LR A-->B');
  });
});
