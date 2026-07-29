import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

vi.mock('./MermaidDiagram', () => ({
  MermaidDiagram: ({ code }: { code: string }) => <div data-testid="mermaid-diagram">{code}</div>,
}));

vi.mock('./VibeLabDiagram', () => ({
  VibeLabDiagram: ({ code }: { code: string }) => <div data-testid="vibelab-diagram">{code}</div>,
}));

let authUser: { name?: string; username?: string; email: string; avatar_url?: string } | null = null;
vi.mock('../../contexts/AuthContext', () => ({
  useAuth: () => ({ user: authUser }),
}));

import { ChatMessage } from './ChatMessage';

describe('ChatMessage Markdown', () => {
  it('uses the authenticated user avatar and falls back to initials after an image error', () => {
    authUser = {
      name: 'Ada Lovelace',
      email: 'ada@example.test',
      avatar_url: 'https://example.test/ada.png',
    };
    const { rerender } = render(<ChatMessage type="user" content="Hello" />);

    const avatar = screen.getByAltText("Ada Lovelace's avatar");
    expect(avatar).toHaveAttribute('src', 'https://example.test/ada.png');
    fireEvent.error(avatar);
    expect(screen.getByRole('img', { name: "Ada Lovelace's avatar" })).toHaveTextContent('AL');

    authUser = { name: 'Grace Hopper', email: 'grace@example.test' };
    rerender(<ChatMessage type="user" content="Hello" />);
    expect(screen.getByRole('img', { name: "Grace Hopper's avatar" })).toHaveTextContent('GH');
  });

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

  it('uses VibeLabDiagram only for completed vibelab-diagram fences in user or assistant messages', () => {
    const source = '{"title":"Flow","preset":"business-process","direction":"LR","nodes":[{"id":"a","type":"start","label":"Start"}],"edges":[]}';
    const { rerender } = render(<ChatMessage type="ai" content={`\`\`\`vibelab-diagram\n${source}\n\`\`\``} />);
    expect(screen.getByTestId('vibelab-diagram')).toHaveTextContent('"title":"Flow"');
    expect(screen.queryByTestId('mermaid-diagram')).not.toBeInTheDocument();

    rerender(<ChatMessage type="user" content={`\`\`\`vibelab-diagram\n${source}\n\`\`\``} />);
    expect(screen.getByTestId('vibelab-diagram')).toBeInTheDocument();
  });

  it('keeps VibeLab diagram source as code while the message is streaming', () => {
    render(<ChatMessage type="ai" isStreaming content={'```vibelab-diagram\n{"title":"Flow"}\n```'} />);
    expect(screen.queryByTestId('vibelab-diagram')).not.toBeInTheDocument();
    expect(screen.getByText('{"title":"Flow"}').tagName).toBe('CODE');
  });

  it('uses the restrained user bubble style without an orange gradient', () => {
    authUser = null;
    const { container } = render(<ChatMessage type="user" content="A short message" />);

    const bubble = container.querySelector('.message-bubble');
    expect(bubble).toHaveClass('user-message-bubble');
    expect(bubble?.className).not.toContain('to-[#ff8533]');
    expect(container.querySelector('.w-fit')).toBeInTheDocument();
  });
});
