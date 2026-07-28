import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const flowMethods = vi.hoisted(() => ({
  fitView: vi.fn(),
  zoomIn: vi.fn(),
  zoomOut: vi.fn(),
  setViewport: vi.fn(),
}));

vi.mock('@xyflow/react', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@xyflow/react')>();
  const React = await import('react');
  return {
    ...actual,
    ReactFlow: ({ children, nodes, onInit }: { children: ReactNode; nodes: unknown[]; onInit?: (instance: unknown) => void }) => {
      React.useEffect(() => onInit?.(flowMethods), [onInit]);
      return <div data-testid="vibelab-react-flow" data-node-count={nodes.length}>{children}</div>;
    },
    Background: () => null,
    MiniMap: () => <div data-testid="diagram-minimap" />,
  };
});

import { VibeLabDiagram } from './VibeLabDiagram';

const source = JSON.stringify({
  title: 'Agentic delivery',
  preset: 'business-process',
  direction: 'LR',
  nodes: [
    { id: 'request', type: 'start', label: 'Request' },
    { id: 'result', type: 'end', label: 'Result' },
  ],
  edges: [{ source: 'request', target: 'result' }],
});

describe('VibeLabDiagram', () => {
  beforeEach(() => {
    Object.values(flowMethods).forEach((method) => method.mockReset());
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: { writeText: vi.fn().mockResolvedValue(undefined) },
    });
  });

  it('renders a structured diagram with fit, zoom, reset, expand and copy controls', async () => {
    render(<VibeLabDiagram code={source} />);

    expect(screen.getByText('Agentic delivery')).toBeInTheDocument();
    expect(screen.getByTestId('vibelab-react-flow')).toHaveAttribute('data-node-count', '2');
    fireEvent.click(screen.getByRole('button', { name: 'Fit diagram' }));
    fireEvent.click(screen.getByRole('button', { name: 'Zoom in' }));
    fireEvent.click(screen.getByRole('button', { name: 'Zoom out' }));
    fireEvent.click(screen.getByRole('button', { name: 'Reset diagram view' }));
    await waitFor(() => {
      expect(flowMethods.fitView).toHaveBeenCalled();
      expect(flowMethods.zoomIn).toHaveBeenCalled();
      expect(flowMethods.zoomOut).toHaveBeenCalled();
      expect(flowMethods.fitView).toHaveBeenCalledTimes(2);
    });

    fireEvent.click(screen.getByRole('button', { name: 'Copy diagram source' }));
    await waitFor(() => expect(navigator.clipboard.writeText).toHaveBeenCalledWith(source));

    fireEvent.click(screen.getByRole('button', { name: 'Expand diagram' }));
    expect(screen.getByRole('dialog')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Fit expanded diagram' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Close diagram' }));
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
  });

  it('keeps an invalid diagram copyable without exposing an error stack', () => {
    render(<VibeLabDiagram code='{"title":"not enough"}' />);

    expect(screen.getByText('Structured diagram unavailable')).toBeInTheDocument();
    expect(screen.getByText('{"title":"not enough"}')).toBeInTheDocument();
    expect(screen.queryByTestId('vibelab-react-flow')).not.toBeInTheDocument();
  });
});
