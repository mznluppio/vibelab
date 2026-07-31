import { Check, Copy, ArrowsOut, X } from '@phosphor-icons/react';
import * as Dialog from '@radix-ui/react-dialog';
import { useEffect, useId, useRef, useState } from 'react';
import { Button } from '../ui/button';
import { Tooltip } from '../ui/Tooltip';

interface MermaidDiagramProps {
  code: string;
}

let mermaidLoader: Promise<(typeof import('mermaid'))['default']> | undefined;
let mermaidThemeSignature: string | undefined;
let renderSequence = 0;

/** Removes Mermaid presentation directives while preserving the diagram structure. */
// eslint-disable-next-line react-refresh/only-export-components
export function sanitizeMermaidSourceForVibeLab(source: string): string {
  const lines = source.split('\n');
  const removedClasses = new Set(
    lines.flatMap((line) => /^\s*classDef\s+([\w-]+)/i.exec(line)?.[1] ?? [])
  );
  let skippingInitDirective = false;

  const sanitized = lines.filter((line) => {
    const trimmed = line.trim();

    if (skippingInitDirective) {
      if (trimmed.includes('}%%')) skippingInitDirective = false;
      return false;
    }

    if (/^%%\{init:/i.test(trimmed)) {
      skippingInitDirective = !trimmed.includes('}%%');
      return false;
    }

    if (/^style\s+/i.test(trimmed)) return false;

    if (/^classDef\s+/i.test(trimmed)) return false;

    const classAssignment = /^class\s+.+?\s+([\w-]+)\s*$/i.exec(trimmed);
    return !classAssignment || !removedClasses.has(classAssignment[1]);
  });

  return sanitized.join('\n');
}

function readThemeValue(name: string, fallback: string) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback;
}

function getVibeLabMermaidConfig() {
  const primary = readThemeValue('--primary', '#0055a4');
  const accent = readThemeValue('--accent', '#00a3e0');
  const surface = readThemeValue('--surface', '#161618');
  const surfaceHover = readThemeValue('--surface-hover', '#1c1e21');
  const background = readThemeValue('--bg', '#0f0f11');
  const text = readThemeValue('--text', '#ffffff');
  const border = readThemeValue('--border', '#1c1e21');
  const borderHover = readThemeValue('--border-hover', '#2a2c30');

  return {
    startOnLoad: false,
    securityLevel: 'strict' as const,
    theme: 'base' as const,
    themeVariables: {
      background: 'transparent',
      primaryColor: surfaceHover,
      primaryTextColor: text,
      primaryBorderColor: accent,
      secondaryColor: surface,
      secondaryTextColor: text,
      secondaryBorderColor: borderHover,
      tertiaryColor: background,
      tertiaryTextColor: text,
      tertiaryBorderColor: border,
      lineColor: accent,
      edgeLabelBackground: surface,
      clusterBkg: background,
      clusterBorder: borderHover,
      titleColor: text,
      nodeTextColor: text,
      mainBkg: surfaceHover,
      nodeBorder: primary,
    },
  };
}

async function loadMermaid() {
  mermaidLoader ??= import('mermaid').then(({ default: mermaid }) => mermaid);
  const mermaid = await mermaidLoader;
  const config = getVibeLabMermaidConfig();
  const signature = JSON.stringify(config);

  if (signature !== mermaidThemeSignature) {
    mermaid.initialize(config);
    mermaidThemeSignature = signature;
  }

  return mermaid;
}

export function MermaidDiagram({ code }: MermaidDiagramProps) {
  const [svg, setSvg] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  const [copied, setCopied] = useState(false);
  const [isExpanded, setIsExpanded] = useState(false);
  const [isWide, setIsWide] = useState(false);
  const componentId = useId().replace(/:/g, '-');
  const scrollRef = useRef<HTMLDivElement>(null);
  const panRef = useRef<{
    pointerId: number;
    startX: number;
    startY: number;
    scrollLeft: number;
    scrollTop: number;
  } | null>(null);
  const [isPanning, setIsPanning] = useState(false);
  const sanitizedCode = sanitizeMermaidSourceForVibeLab(code);
  const [themeRevision, setThemeRevision] = useState(0);

  useEffect(() => {
    const root = document.documentElement;
    let frame: number | undefined;
    const observer = new MutationObserver(() => {
      if (frame !== undefined) cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => setThemeRevision((revision) => revision + 1));
    });

    observer.observe(root, { attributes: true, attributeFilter: ['style', 'class'] });
    return () => {
      observer.disconnect();
      if (frame !== undefined) cancelAnimationFrame(frame);
    };
  }, []);

  useEffect(() => {
    let mounted = true;

    setSvg(null);
    setFailed(false);

    if (!sanitizedCode.trim()) {
      setFailed(true);
      return () => {
        mounted = false;
      };
    }

    const renderId = `mermaid-${componentId}-${++renderSequence}`;

    void loadMermaid()
      .then((mermaid) => mermaid.render(renderId, sanitizedCode))
      .then((rendered) => {
        if (mounted) setSvg(rendered.svg);
      })
      .catch(() => {
        if (import.meta.env.DEV) {
          console.warn('Mermaid diagram could not be rendered');
        }
        if (mounted) setFailed(true);
      });

    return () => {
      mounted = false;
    };
  }, [componentId, sanitizedCode, themeRevision]);

  useEffect(() => {
    if (!svg || !scrollRef.current) return;

    const container = scrollRef.current;
    const measure = () => {
      const renderedSvg = container.querySelector('svg');
      const viewBoxWidth =
        Number(renderedSvg?.getAttribute('viewBox')?.trim().split(/\s+/)[2]) || 0;
      setIsWide(viewBoxWidth > container.clientWidth);
    };

    const frame = requestAnimationFrame(measure);
    window.addEventListener('resize', measure);
    return () => {
      cancelAnimationFrame(frame);
      window.removeEventListener('resize', measure);
    };
  }, [svg]);

  const copySource = async () => {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      if (import.meta.env.DEV) console.warn('Mermaid source could not be copied');
    }
  };

  const beginPan = (event: React.PointerEvent<HTMLDivElement>) => {
    if (event.button !== 0) return;

    const container = event.currentTarget;
    panRef.current = {
      pointerId: event.pointerId,
      startX: event.clientX,
      startY: event.clientY,
      scrollLeft: container.scrollLeft,
      scrollTop: container.scrollTop,
    };
    container.setPointerCapture?.(event.pointerId);
    setIsPanning(true);
    event.preventDefault();
  };

  const pan = (event: React.PointerEvent<HTMLDivElement>) => {
    const activePan = panRef.current;
    if (!activePan || activePan.pointerId !== event.pointerId) return;

    event.currentTarget.scrollLeft = activePan.scrollLeft - (event.clientX - activePan.startX);
    event.currentTarget.scrollTop = activePan.scrollTop - (event.clientY - activePan.startY);
  };

  const endPan = (event: React.PointerEvent<HTMLDivElement>) => {
    if (panRef.current?.pointerId !== event.pointerId) return;

    if (event.currentTarget.hasPointerCapture?.(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
    panRef.current = null;
    setIsPanning(false);
  };

  const actionBar = (
    <div className="mermaid-diagram-actions">
      {svg && (
        <Tooltip content="Expand diagram" side="top">
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="mermaid-diagram-action"
            aria-label="Expand diagram"
            onClick={() => setIsExpanded(true)}
          >
            <ArrowsOut size={15} />
          </Button>
        </Tooltip>
      )}
      <Tooltip content={copied ? 'Copied' : 'Copy Mermaid source'} side="top">
        <Button
          type="button"
          variant="ghost"
          size="icon"
          className="mermaid-diagram-action"
          aria-label="Copy Mermaid source"
          onClick={copySource}
        >
          {copied ? <Check size={15} weight="bold" /> : <Copy size={15} />}
        </Button>
      </Tooltip>
    </div>
  );

  if (failed) {
    return (
      <section className="mermaid-diagram-card my-2" aria-label="Mermaid diagram">
        {actionBar}
        <p className="mb-1 text-xs text-[var(--text-muted)]">Diagram could not be rendered</p>
        <pre className="overflow-x-auto rounded border border-[var(--code-block-border)] bg-[var(--code-block-bg)] px-3 py-2 text-xs font-mono text-[var(--code-block-text)]">
          {code}
        </pre>
      </section>
    );
  }

  if (!svg) {
    return <div className="my-2 text-xs text-[var(--text-muted)]">Rendering diagram…</div>;
  }

  return (
    <>
      <section className="mermaid-diagram-card my-2" aria-label="Mermaid diagram">
        {actionBar}
        <div
          ref={scrollRef}
          className="mermaid-diagram-scroll"
          data-wide={isWide}
          data-panning={isPanning}
          onPointerDown={beginPan}
          onPointerMove={pan}
          onPointerUp={endPan}
          onPointerCancel={endPan}
          aria-label="Mermaid diagram canvas. Drag to pan."
        >
          <div
            className="mermaid-diagram-canvas"
            // Mermaid strict mode sanitizes its generated SVG; the source text is never injected as HTML.
            dangerouslySetInnerHTML={{ __html: svg }}
          />
        </div>
      </section>

      <Dialog.Root open={isExpanded} onOpenChange={setIsExpanded}>
        <Dialog.Portal>
          <Dialog.Overlay className="fixed inset-0 z-[400] bg-black/70 backdrop-blur-sm" />
          <Dialog.Content className="mermaid-diagram-dialog fixed inset-4 z-[401] flex min-w-0 flex-col rounded-[var(--radius)] border border-[var(--border-hover)] bg-[var(--bg)] p-4 shadow-[var(--shadow-large)] focus:outline-none sm:inset-8">
            <div className="mb-3 flex items-center justify-between gap-3">
              <Dialog.Title className="text-sm font-medium text-[var(--text)]">
                Mermaid diagram
              </Dialog.Title>
              <Dialog.Description className="sr-only">
                Expanded Mermaid diagram with horizontal and vertical scrolling.
              </Dialog.Description>
              <Dialog.Close asChild>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  className="mermaid-diagram-action"
                  aria-label="Close diagram"
                >
                  <X size={16} />
                </Button>
              </Dialog.Close>
            </div>
            <div className="mermaid-diagram-dialog-scroll">
              <div
                className="mermaid-diagram-dialog-canvas"
                dangerouslySetInnerHTML={{ __html: svg }}
              />
            </div>
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>
    </>
  );
}
