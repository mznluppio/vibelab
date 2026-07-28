import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

vi.mock('./MermaidDiagram', () => ({
  MermaidDiagram: ({ code }: { code: string }) => <div data-testid="mermaid-diagram">{code}</div>,
}));

import { ChatMessage } from './ChatMessage';

describe('ChatMessage Markdown', () => {
  it('uses MermaidDiagram only for fenced mermaid code', () => {
    render(<ChatMessage type="ai" content={'```mermaid\nflowchart LR\nA-->B\n```'} />);

    const diagram = screen.getByTestId('mermaid-diagram');
    expect(diagram.textContent).toContain('flowchart LR');
    expect(diagram.textContent).toContain('A-->B');
    expect(diagram.closest('pre')).toBeNull();
  });

  it('keeps JavaScript and inline mermaid text in the existing code rendering', () => {
    render(
      <ChatMessage
        type="ai"
        content={'Use `mermaid` here.\n\n```javascript\nconst answer = 42;\n```'}
      />
    );

    expect(screen.queryByTestId('mermaid-diagram')).not.toBeInTheDocument();
    expect(screen.getByText('mermaid').tagName).toBe('CODE');
    expect(screen.getByText('const answer = 42;').tagName).toBe('CODE');
    expect(screen.getByTitle('Copy')).toBeInTheDocument();
  });

  it('keeps Mermaid source as code while the message is streaming', () => {
    render(<ChatMessage type="ai" isStreaming content={'```mermaid\nflowchart LR\nA-->B\n```'} />);

    expect(screen.queryByTestId('mermaid-diagram')).not.toBeInTheDocument();
    const code = screen.getByText(
      (_content, element) =>
        element?.tagName === 'CODE' && element.textContent === 'flowchart LR\nA-->B\n'
    );
    expect(code).toBeInTheDocument();
    expect(code.closest('pre')).not.toBeNull();
  });

  it('uses the restrained user bubble style without an orange gradient', () => {
    const { container } = render(<ChatMessage type="user" content="A short message" />);

    const bubble = container.querySelector('.message-bubble');
    expect(bubble).toHaveClass('user-message-bubble');
    expect(bubble?.className).not.toContain('to-[#ff8533]');
    expect(container.querySelector('.w-fit')).toBeInTheDocument();
  });
});
