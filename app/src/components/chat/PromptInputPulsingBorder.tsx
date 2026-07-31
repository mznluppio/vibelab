import {
  Component,
  lazy,
  Suspense,
  useEffect,
  useRef,
  useState,
  type ErrorInfo,
  type ReactNode,
} from 'react';
import { useTheme } from '../../theme/ThemeContext';

const LazyPulsingBorder = lazy(async () => {
  const module = await import('@paper-design/shaders-react');
  return { default: module.PulsingBorder };
});

/** Width of the visible ring (the wrapper padding the shader shows through). */
const BORDER_WIDTH = 2;
/** Lets the glow spill outside the input without moving its actual contour. */
const GLOW_BLEED = 20;
/** ``thickness`` is relative to the canvas short side. */
const BORDER_THICKNESS = 0.05;
const FALLBACK_GEOMETRY = { roundness: 0.3, marginX: 0.02, marginY: 0.1 };

class ShaderFallbackBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  componentDidCatch(_error: Error, _info: ErrorInfo) {
    if (import.meta.env.DEV)
      console.warn('Prompt border shader is unavailable; using the static border.');
  }

  render() {
    return this.state.failed ? null : this.props.children;
  }
}

function supportsWebGL() {
  try {
    const canvas = document.createElement('canvas');
    return Boolean(canvas.getContext('webgl2'));
  } catch {
    return false;
  }
}

function usePulsingBorderGeometry() {
  const wrapperRef = useRef<HTMLDivElement>(null);
  const [geometry, setGeometry] = useState(FALLBACK_GEOMETRY);

  useEffect(() => {
    const wrapper = wrapperRef.current;
    if (!wrapper) return;

    const measure = () => {
      const { width, height } = wrapper.getBoundingClientRect();
      if (width <= 0 || height <= 0) return;

      const radius = Number.parseFloat(getComputedStyle(wrapper).borderTopLeftRadius) || 0;
      const next = {
        roundness: Math.min(1, Math.max(0, (2 * radius) / Math.min(width, height))),
        marginX: GLOW_BLEED / (width + 2 * GLOW_BLEED),
        marginY: GLOW_BLEED / (height + 2 * GLOW_BLEED),
      };

      setGeometry((current) =>
        current.roundness === next.roundness &&
        current.marginX === next.marginX &&
        current.marginY === next.marginY
          ? current
          : next
      );
    };

    measure();
    if (typeof ResizeObserver === 'undefined') return;

    const observer = new ResizeObserver(measure);
    observer.observe(wrapper);
    return () => observer.disconnect();
  }, []);

  return { wrapperRef, geometry };
}

export function PromptInputPulsingBorder({
  active,
  children,
}: {
  active: boolean;
  children: ReactNode;
}) {
  const { themePreset } = useTheme();
  const [canAnimate, setCanAnimate] = useState(false);
  const [reducedMotion, setReducedMotion] = useState(false);
  const { wrapperRef, geometry } = usePulsingBorderGeometry();
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
      ref={wrapperRef}
      className="relative rounded-[var(--radius)] bg-transparent p-[2px]"
      data-testid="prompt-input-pulsing-border"
    >
      {canAnimate && (
        <ShaderFallbackBoundary>
          <Suspense fallback={null}>
            <LazyPulsingBorder
              aria-hidden="true"
              className="pointer-events-none absolute z-0 transition-opacity duration-500"
              style={{
                top: -GLOW_BLEED,
                right: -GLOW_BLEED,
                bottom: -GLOW_BLEED,
                left: -GLOW_BLEED,
                opacity: active ? 1 : 0.7,
              }}
              // These colors come from the active theme instead of the former
              // VibeLab blue constants, so the animated border belongs to the
              // current Team's appearance as well.
              colors={[themePreset.colors.primary, themePreset.colors.accent]}
              colorBack="rgba(0, 0, 0, 0)"
              roundness={geometry.roundness}
              thickness={BORDER_THICKNESS}
              softness={1}
              aspectRatio="auto"
              // Kept low on purpose — high intensity saturates every spot and
              // flattens the bright/dark contrast that makes the ring move.
              intensity={active ? 0.05 : 0.2}
              bloom={active ? 0.35 : 0.25}
              spots={2}
              // Spots are placed by *angle*, and on a bar this wide equal angles
              // map to very unequal perimeter: small spots pile up on the short
              // left/right edges and leave the long top/bottom edges dark. Wide,
              // overlapping sectors turn that into one continuous contour with
              // travelling bright zones.
              spotSize={0.5}
              pulse={animate ? (active ? 0.35 : 0.2) : 0}
              smoke={animate ? (active ? 0.3 : 0.2) : 0}
              smokeSize={0.6}
              speed={animate ? (active ? 1 : 0.5) : 0}
              // scale must stay at 1: anything lower shrinks the contour inside
              // the canvas and it stops hugging the input's edges.
              scale={1}
              marginLeft={geometry.marginX}
              marginRight={geometry.marginX}
              marginTop={geometry.marginY}
              marginBottom={geometry.marginY}
              minPixelRatio={1}
              maxPixelCount={900_000}
            />
          </Suspense>
        </ShaderFallbackBoundary>
      )}

      <div
        aria-hidden="true"
        className="pointer-events-none absolute z-0 rounded-[calc(var(--radius)-2px)] bg-[var(--surface)]"
        style={{ inset: BORDER_WIDTH }}
      />
      <div className="relative z-[1] rounded-[calc(var(--radius)-2px)]">{children}</div>
    </div>
  );
}
