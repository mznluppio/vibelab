import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

vi.mock('@paper-design/shaders-react', () => ({
  PulsingBorder: ({ className, 'aria-hidden': ariaHidden }: { className?: string; 'aria-hidden'?: boolean }) => (
    <div data-testid="shader" className={className} aria-hidden={ariaHidden} />
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
    getContext.mockRestore();
  });
});
