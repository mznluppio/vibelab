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
    ReactFlow: ({
      children,
      nodes,
      onInit,
      panOnDrag,
      panOnScroll,
      zoomOnScroll,
      zoomOnPinch,
    }: {
      children: ReactNode;
      nodes: unknown[];
      onInit?: (instance: unknown) => void;
      panOnDrag?: boolean | number[];
      panOnScroll?: boolean;
      zoomOnScroll?: boolean;
      zoomOnPinch?: boolean;
    }) => {
      React.useEffect(() => onInit?.(flowMethods), [onInit]);
      return (
        <div
          data-testid="vibelab-react-flow"
          data-node-count={nodes.length}
          data-pan-on-drag={JSON.stringify(panOnDrag)}
          data-pan-on-scroll={panOnScroll}
          data-zoom-on-scroll={zoomOnScroll}
          data-zoom-on-pinch={zoomOnPinch}
        >
          {children}
        </div>
      );
    },
    useNodesInitialized: () => true,
    useReactFlow: () => flowMethods,
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

  it('fits after node initialization and renders the compact inline controls', async () => {
    render(<VibeLabDiagram code={source} />);

    expect(screen.getByText('Agentic delivery')).toBeInTheDocument();
    expect(screen.getByTestId('vibelab-react-flow')).toHaveAttribute('data-node-count', '2');
    expect(screen.getByTestId('vibelab-react-flow')).toHaveAttribute('data-pan-on-drag', '[1]');
    expect(screen.getByTestId('vibelab-react-flow')).toHaveAttribute(
      'data-zoom-on-scroll',
      'false'
    );
    await waitFor(() => expect(flowMethods.fitView).toHaveBeenCalled());
    fireEvent.click(screen.getByRole('button', { name: 'Fit diagram' }));
    fireEvent.click(screen.getByRole('button', { name: 'Zoom in' }));
    fireEvent.click(screen.getByRole('button', { name: 'Zoom out' }));
    await waitFor(() => {
      expect(flowMethods.fitView).toHaveBeenLastCalledWith(
        expect.objectContaining({
          minZoom: 0.4,
          maxZoom: 1.75,
        })
      );
      expect(flowMethods.zoomIn).toHaveBeenCalled();
      expect(flowMethods.zoomOut).toHaveBeenCalled();
    });

    expect(screen.queryByRole('button', { name: 'Reset diagram view' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Export diagram' })).toBeInTheDocument();
    expect(screen.getAllByRole('button', { name: 'Copy diagram source' })).toHaveLength(1);
    fireEvent.click(screen.getByRole('button', { name: 'Copy diagram source' }));
    await waitFor(() => expect(navigator.clipboard.writeText).toHaveBeenCalledWith(source));

    fireEvent.click(screen.getByRole('button', { name: 'Expand diagram' }));
    expect(screen.getByRole('dialog')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Fit expanded diagram' })).toBeInTheDocument();
    expect(screen.getAllByRole('button', { name: 'Export diagram' })).toHaveLength(1);
    expect(screen.getAllByTestId('vibelab-react-flow')[1]).toHaveAttribute(
      'data-pan-on-drag',
      'true'
    );
    expect(screen.getAllByTestId('vibelab-react-flow')[1]).toHaveAttribute(
      'data-zoom-on-scroll',
      'true'
    );
    fireEvent.click(screen.getByRole('button', { name: 'Reset expanded diagram view' }));
    await waitFor(() =>
      expect(flowMethods.fitView).toHaveBeenLastCalledWith(
        expect.objectContaining({
          minZoom: 0.35,
          maxZoom: 2.25,
        })
      )
    );
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
