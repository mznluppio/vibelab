import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

vi.mock('@paper-design/shaders-react', () => ({
  PulsingBorder: ({ className, thickness, 'aria-hidden': ariaHidden }: { className?: string; thickness?: number; 'aria-hidden'?: boolean }) => (
    <div data-testid="shader" className={className} data-thickness={thickness} aria-hidden={ariaHidden} />
  ),
}));

import { PromptInputPulsingBorder } from './PromptInputPulsingBorder';

describe('PromptInputPulsingBorder', () => {
  it('keeps prompt content usable while placing the shader in a non-interactive layer', async () => {
    const getContext = vi
      .spyOn(HTMLCanvasElement.prototype, 'getContext')
      .mockReturnValue({} as WebGLRenderingContext);
    render(
      <PromptInputPulsingBorder active>
        <textarea aria-label="Prompt" />
      </PromptInputPulsingBorder>
    );

    expect(screen.getByRole('textbox', { name: 'Prompt' })).toBeInTheDocument();
    const shader = await screen.findByTestId('shader');
    expect(shader).toHaveAttribute('aria-hidden', 'true');
    expect(shader.className).toContain('pointer-events-none');
    expect(shader).toHaveAttribute('data-thickness', '0.05');
    const wrapper = screen.getByTestId('prompt-input-pulsing-border');
    expect(wrapper).toHaveClass('p-px');
    expect(wrapper).toHaveClass('bg-[var(--border)]');
    getContext.mockRestore();
  });

  it('keeps the static border when WebGL is unavailable', () => {
    const getContext = vi
      .spyOn(HTMLCanvasElement.prototype, 'getContext')
      .mockReturnValue(null);
    render(<PromptInputPulsingBorder active={false}><textarea aria-label="Prompt" /></PromptInputPulsingBorder>);

    expect(screen.getByTestId('prompt-input-pulsing-border')).toHaveClass(
      'bg-[var(--border)]'
    );
    expect(screen.queryByTestId('shader')).not.toBeInTheDocument();
    getContext.mockRestore();
  });
});
