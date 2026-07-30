import {
  Component,
  lazy,
  Suspense,
  useEffect,
  useState,
  type ErrorInfo,
  type ReactNode,
} from 'react';

const LazyPulsingBorder = lazy(async () => {
  const module = await import('@paper-design/shaders-react');
  return { default: module.PulsingBorder };
});

class ShaderFallbackBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  componentDidCatch(_error: Error, _info: ErrorInfo) {
    if (import.meta.env.DEV) console.warn('Prompt border shader is unavailable; using the static border.');
  }

  render() {
    return this.state.failed ? null : this.props.children;
  }
}

function supportsWebGL() {
  try {
    const canvas = document.createElement('canvas');
    return Boolean(canvas.getContext('webgl2') || canvas.getContext('webgl'));
  } catch {
    return false;
  }
}

export function PromptInputPulsingBorder({
  active,
  children,
}: {
  active: boolean;
  children: ReactNode;
}) {
  const [canAnimate, setCanAnimate] = useState(false);
  const [reducedMotion, setReducedMotion] = useState(false);

  useEffect(() => {
    setCanAnimate(supportsWebGL());
    const mediaQuery = window.matchMedia('(prefers-reduced-motion: reduce)');
    const syncReducedMotion = () => setReducedMotion(mediaQuery.matches);
    syncReducedMotion();
    mediaQuery.addEventListener('change', syncReducedMotion);
    return () => mediaQuery.removeEventListener('change', syncReducedMotion);
  }, []);

  const animate = canAnimate && !reducedMotion;

  return (
    <div
      // This static frame guarantees one clean, continuous contour. The shader
      // travels inside it as an enhancement instead of becoming the border.
      className="relative rounded-[var(--radius)] bg-[var(--border)] p-px"
      data-testid="prompt-input-pulsing-border"
    >
      {canAnimate && (
        <ShaderFallbackBoundary>
          <Suspense fallback={null}>
            <LazyPulsingBorder
              aria-hidden="true"
              className="pointer-events-none absolute inset-0 z-0 rounded-[var(--radius)] opacity-80"
              colors={['#0dc1fd']}
              colorBack="rgba(0, 0, 0, 0)"
              roundness={0.3}
              thickness={0.05}
              softness={0.75}
              aspectRatio="auto"
              intensity={active ? 0.2 : 0.06}
              bloom={active ? 0.25 : 0.08}
              spots={4}
              spotSize={0.5}
              pulse={animate && active ? 0.25 : 0}
              smoke={animate && active ? 0.3 : 0}
              smokeSize={0.6}
              speed={animate ? (active ? 1 : 0.25) : 0}
              scale={0.6}
              marginLeft={0}
              marginRight={0}
              marginTop={0}
              marginBottom={0}
              minPixelRatio={1}
              maxPixelCount={220000}
            />
          </Suspense>
        </ShaderFallbackBoundary>
      )}

      <div className="relative z-[1] rounded-[calc(var(--radius)-1px)]">{children}</div>
    </div>
  );
}
