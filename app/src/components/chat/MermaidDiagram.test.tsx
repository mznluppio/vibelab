import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const initialize = vi.fn();
const renderMermaid = vi.fn();

vi.mock('mermaid', () => ({
  default: { initialize, render: renderMermaid },
}));

import { MermaidDiagram, sanitizeMermaidSourceForVibeLab } from './MermaidDiagram';

describe('MermaidDiagram', () => {
  beforeEach(() => {
    renderMermaid.mockReset();
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: { writeText: vi.fn().mockResolvedValue(undefined) },
    });
  });

  it('renders the SVG returned by Mermaid', async () => {
    renderMermaid.mockResolvedValue({ svg: '<svg aria-label="process-diagram" />' });

    render(<MermaidDiagram code="flowchart LR\nA[Start] --> B[End]" />);

    await waitFor(() => expect(screen.getByLabelText('process-diagram')).toBeInTheDocument());
    expect(initialize).toHaveBeenCalledWith(
      expect.objectContaining({ startOnLoad: false, securityLevel: 'strict', theme: 'base' })
    );
    expect(initialize.mock.calls[0][0].themeVariables).toEqual(
      expect.objectContaining({
        background: 'transparent',
        primaryTextColor: expect.any(String),
        primaryBorderColor: expect.any(String),
        lineColor: expect.any(String),
      })
    );
  });

  it('removes only presentation directives from stored Mermaid source', () => {
    const source = [
      '%%{init: {"theme":"dark"} }%%',
      'flowchart LR',
      'A[Start] --> B[Decision]',
      'style A fill:#ffdddd',
      'classDef danger fill:#ff0000',
      'class B danger',
      'B --> C[End]',
    ].join('\n');

    expect(sanitizeMermaidSourceForVibeLab(source)).toBe(
      ['flowchart LR', 'A[Start] --> B[Decision]', 'B --> C[End]'].join('\n')
    );
  });

  it('shows the source fallback when Mermaid rejects the diagram', async () => {
    renderMermaid.mockRejectedValue(new Error('invalid diagram'));

    render(<MermaidDiagram code="not valid mermaid" />);

    await waitFor(() =>
      expect(screen.getByText('Diagram could not be rendered')).toBeInTheDocument()
    );
    expect(screen.getByText('not valid mermaid').tagName).toBe('PRE');
  });

  it('uses unique render IDs and renders again when the code changes', async () => {
    renderMermaid.mockResolvedValue({ svg: '<svg />' });
    const { rerender } = render(
      <>
        <MermaidDiagram code="flowchart LR\nA-->B" />
        <MermaidDiagram code="flowchart LR\nC-->D" />
      </>
    );

    await waitFor(() => expect(renderMermaid).toHaveBeenCalledTimes(2));
    const [firstId, secondId] = renderMermaid.mock.calls.map(([id]) => id);
    expect(firstId).not.toBe(secondId);

    rerender(<MermaidDiagram code="flowchart LR\nA-->C" />);

    await waitFor(() => expect(renderMermaid).toHaveBeenCalledTimes(3));
    expect(renderMermaid.mock.calls[2][0]).not.toBe(firstId);
    expect(renderMermaid.mock.calls[2][1]).toContain('A-->C');
  });

  it('does not update the DOM after unmounting', async () => {
    let resolveRender: ((value: { svg: string }) => void) | undefined;
    renderMermaid.mockReturnValue(
      new Promise<{ svg: string }>((resolve) => {
        resolveRender = resolve;
      })
    );
    const { container, unmount } = render(<MermaidDiagram code="flowchart LR\nA-->B" />);

    await waitFor(() => expect(renderMermaid).toHaveBeenCalledTimes(1));
    unmount();
    resolveRender?.({ svg: '<svg aria-label="late-diagram" />' });

    await Promise.resolve();
    expect(container.querySelector('svg')).toBeNull();
  });

  it('provides Expand and Copy actions without re-rendering Mermaid', async () => {
    renderMermaid.mockResolvedValue({ svg: '<svg viewBox="0 0 200 100" aria-label="process" />' });
    const source = ['flowchart LR', 'A-->B'].join(String.fromCharCode(10));
    render(<MermaidDiagram code={source} />);

    await waitFor(() => expect(screen.getByLabelText('process')).toBeInTheDocument());
    fireEvent.click(screen.getByRole('button', { name: 'Copy Mermaid source' }));
    await waitFor(() => expect(navigator.clipboard.writeText).toHaveBeenCalledWith(source));

    fireEvent.click(screen.getByRole('button', { name: 'Expand diagram' }));
    expect(screen.getByRole('dialog')).toBeInTheDocument();
    expect(renderMermaid).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole('button', { name: 'Close diagram' }));
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
  });

  it('pans a wide fallback diagram with a standard pointer drag', async () => {
    renderMermaid.mockResolvedValue({
      svg: '<svg viewBox="0 0 800 100" aria-label="wide-process" />',
    });
    render(<MermaidDiagram code="flowchart LR\nA-->B" />);

    await waitFor(() => expect(screen.getByLabelText('wide-process')).toBeInTheDocument());
    const canvas = screen.getByLabelText('Mermaid diagram canvas. Drag to pan.');
    Object.defineProperties(canvas, {
      scrollLeft: { configurable: true, value: 120, writable: true },
      scrollTop: { configurable: true, value: 40, writable: true },
    });

    const pointerEvent = (type: string, properties: Record<string, number>) => {
      const event = new Event(type, { bubbles: true, cancelable: true });
      Object.defineProperties(
        event,
        Object.fromEntries(
          Object.entries(properties).map(([key, value]) => [key, { configurable: true, value }])
        )
      );
      return event;
    };

    fireEvent(
      canvas,
      pointerEvent('pointerdown', { button: 0, pointerId: 4, clientX: 180, clientY: 80 })
    );
    fireEvent(canvas, pointerEvent('pointermove', { pointerId: 4, clientX: 140, clientY: 60 }));

    expect(canvas.scrollLeft).toBe(160);
    expect(canvas.scrollTop).toBe(60);
    expect(canvas).toHaveAttribute('data-panning', 'true');

    fireEvent(canvas, pointerEvent('pointerup', { pointerId: 4 }));
    expect(canvas).toHaveAttribute('data-panning', 'false');
  });
});
