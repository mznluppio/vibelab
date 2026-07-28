import {
  ArrowsOut,
  Check,
  Copy,
  Crosshair,
  MagnifyingGlassMinus,
  MagnifyingGlassPlus,
  X,
} from '@phosphor-icons/react';
import * as Dialog from '@radix-ui/react-dialog';
import {
  Background,
  BackgroundVariant,
  MiniMap,
  ReactFlow,
  useNodesInitialized,
  useReactFlow,
  type Edge,
  type NodeTypes,
  type ReactFlowInstance,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { useEffect, useMemo, useState } from 'react';
import { Button } from '../ui/button';
import { Tooltip } from '../ui/Tooltip';
import { BaseDiagramNode } from './diagram-nodes/BaseDiagramNode';
import { DecisionDiagramNode } from './diagram-nodes/DecisionDiagramNode';
import { GroupDiagramNode } from './diagram-nodes/GroupDiagramNode';
import {
  createVibeLabDiagramLayout,
  getVibeLabDiagramHeight,
  parseVibeLabDiagram,
  type DiagramFlowNode,
  type DiagramGroupFlowNode,
} from './VibeLabDiagramSchema';

interface VibeLabDiagramProps {
  code: string;
}

type DiagramFlowNodes = DiagramFlowNode | DiagramGroupFlowNode;
type DiagramFlowInstance = ReactFlowInstance<DiagramFlowNodes, Edge>;

const nodeTypes = {
  'vibelab-node': BaseDiagramNode,
  'vibelab-decision': DecisionDiagramNode,
  'vibelab-group': GroupDiagramNode,
} as unknown as NodeTypes;

function ViewportFitter({ expanded }: { expanded: boolean }) {
  const nodesInitialized = useNodesInitialized({ includeHiddenNodes: true });
  const { fitView } = useReactFlow<DiagramFlowNodes, Edge>();

  useEffect(() => {
    if (!nodesInitialized) return;

    void fitView({
      padding: expanded ? 0.14 : 0.16,
      duration: 180,
      minZoom: expanded ? 0.35 : 0.4,
      maxZoom: expanded ? 2.25 : 1.75,
    });
  }, [expanded, fitView, nodesInitialized]);

  return null;
}

function DiagramCanvas({
  nodes,
  edges,
  expanded,
  onInstance,
}: ReturnType<typeof createVibeLabDiagramLayout> & {
  expanded: boolean;
  onInstance: (instance: DiagramFlowInstance) => void;
}) {
  return (
    <ReactFlow<DiagramFlowNodes, Edge>
      nodes={nodes}
      edges={edges}
      nodeTypes={nodeTypes}
      minZoom={0.35}
      maxZoom={2.25}
      onInit={onInstance}
      panOnDrag={expanded ? true : [1]}
      panOnScroll={expanded}
      zoomOnScroll={expanded}
      zoomOnPinch
      zoomOnDoubleClick={false}
      nodesDraggable={false}
      nodesConnectable={false}
      elementsSelectable={false}
      nodesFocusable={false}
      edgesFocusable={false}
      preventScrolling={!expanded}
      proOptions={{ hideAttribution: true }}
      className="vibelab-diagram-flow"
      aria-label="Interactive VibeLab diagram"
    >
      <ViewportFitter expanded={expanded} />
      <Background variant={BackgroundVariant.Dots} gap={18} size={1} />
      {expanded && nodes.length > 14 && <MiniMap pannable zoomable aria-label="Diagram overview" />}
    </ReactFlow>
  );
}

export function VibeLabDiagram({ code }: VibeLabDiagramProps) {
  const parsed = useMemo(() => parseVibeLabDiagram(code), [code]);
  const layout = useMemo(
    () => (parsed.success ? createVibeLabDiagramLayout(parsed.data) : null),
    [parsed]
  );
  const [copied, setCopied] = useState(false);
  const [isExpanded, setIsExpanded] = useState(false);
  const [inlineFlow, setInlineFlow] = useState<DiagramFlowInstance | null>(null);
  const [dialogFlow, setDialogFlow] = useState<DiagramFlowInstance | null>(null);

  const copySource = async () => {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      if (import.meta.env.DEV) console.warn('VibeLab diagram source could not be copied');
    }
  };

  if (!parsed.success || !layout) {
    return (
      <section className="vibelab-diagram-card my-3" aria-label="VibeLab diagram fallback">
        <div className="vibelab-diagram-fallback-header">
          <div>
            <p>Structured diagram unavailable</p>
            <span>{parsed.success ? 'The diagram could not be laid out.' : parsed.error}</span>
          </div>
          <Tooltip content={copied ? 'Copied' : 'Copy diagram source'} side="top">
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="vibelab-diagram-action"
              aria-label="Copy diagram source"
              onClick={copySource}
            >
              {copied ? <Check size={15} weight="bold" /> : <Copy size={15} />}
            </Button>
          </Tooltip>
        </div>
        <pre>{code}</pre>
      </section>
    );
  }

  const { data } = parsed;
  const fitInline = () =>
    inlineFlow?.fitView({ padding: 0.16, duration: 180, minZoom: 0.4, maxZoom: 1.75 });
  const fitDialog = () =>
    dialogFlow?.fitView({ padding: 0.14, duration: 180, minZoom: 0.35, maxZoom: 2.25 });
  const resetDialog = fitDialog;

  const actionBar = (
    <div className="vibelab-diagram-actions" aria-label="Diagram controls">
      <Tooltip content="Fit diagram to view" side="top">
        <Button
          type="button"
          variant="ghost"
          size="icon"
          className="vibelab-diagram-action"
          aria-label="Fit diagram"
          onClick={fitInline}
        >
          <Crosshair size={17} />
        </Button>
      </Tooltip>
      <Tooltip content="Zoom in" side="top">
        <Button
          type="button"
          variant="ghost"
          size="icon"
          className="vibelab-diagram-action"
          aria-label="Zoom in"
          onClick={() => inlineFlow?.zoomIn({ duration: 150 })}
        >
          <MagnifyingGlassPlus size={17} />
        </Button>
      </Tooltip>
      <Tooltip content="Zoom out" side="top">
        <Button
          type="button"
          variant="ghost"
          size="icon"
          className="vibelab-diagram-action"
          aria-label="Zoom out"
          onClick={() => inlineFlow?.zoomOut({ duration: 150 })}
        >
          <MagnifyingGlassMinus size={17} />
        </Button>
      </Tooltip>
      <Tooltip content="Expand diagram" side="top">
        <Button
          type="button"
          variant="ghost"
          size="icon"
          className="vibelab-diagram-action"
          aria-label="Expand diagram"
          onClick={() => setIsExpanded(true)}
        >
          <ArrowsOut size={17} />
        </Button>
      </Tooltip>
      <Tooltip content={copied ? 'Copied' : 'Copy diagram source'} side="top">
        <Button
          type="button"
          variant="ghost"
          size="icon"
          className="vibelab-diagram-action"
          aria-label="Copy diagram source"
          onClick={copySource}
        >
          {copied ? <Check size={17} weight="bold" /> : <Copy size={17} />}
        </Button>
      </Tooltip>
    </div>
  );

  return (
    <>
      <section
        className={`vibelab-diagram-card my-3 vibelab-diagram-card--${data.preset}`}
        aria-label={data.title}
      >
        <header className="vibelab-diagram-header">
          <div>
            <h3>{data.title}</h3>
            {data.subtitle && <p>{data.subtitle}</p>}
          </div>
          {actionBar}
        </header>
        <div
          className="vibelab-diagram-canvas"
          style={{ height: getVibeLabDiagramHeight(layout.bounds, data.direction) }}
        >
          <DiagramCanvas {...layout} expanded={false} onInstance={setInlineFlow} />
        </div>
      </section>

      <Dialog.Root open={isExpanded} onOpenChange={setIsExpanded}>
        <Dialog.Portal>
          <Dialog.Overlay className="fixed inset-0 z-[400] bg-black/70 backdrop-blur-sm" />
          <Dialog.Content
            className={`vibelab-diagram-dialog fixed inset-3 z-[401] flex min-w-0 flex-col sm:inset-7 ${data.preset}`}
          >
            <div className="vibelab-diagram-dialog__header">
              <div>
                <Dialog.Title>{data.title}</Dialog.Title>
                <Dialog.Description>
                  {data.subtitle ?? 'Interactive VibeLab diagram.'}
                </Dialog.Description>
              </div>
              <div className="vibelab-diagram-actions" aria-label="Expanded diagram controls">
                <Tooltip content="Fit diagram to view" side="bottom">
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    className="vibelab-diagram-action"
                    aria-label="Fit expanded diagram"
                    onClick={fitDialog}
                  >
                    <Crosshair size={17} />
                  </Button>
                </Tooltip>
                <Tooltip content="Zoom in" side="bottom">
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    className="vibelab-diagram-action"
                    aria-label="Zoom in expanded diagram"
                    onClick={() => dialogFlow?.zoomIn({ duration: 150 })}
                  >
                    <MagnifyingGlassPlus size={17} />
                  </Button>
                </Tooltip>
                <Tooltip content="Zoom out" side="bottom">
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    className="vibelab-diagram-action"
                    aria-label="Zoom out expanded diagram"
                    onClick={() => dialogFlow?.zoomOut({ duration: 150 })}
                  >
                    <MagnifyingGlassMinus size={17} />
                  </Button>
                </Tooltip>
                <Tooltip content="Reset diagram view" side="bottom">
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    className="vibelab-diagram-action"
                    aria-label="Reset expanded diagram view"
                    onClick={resetDialog}
                  >
                    <Crosshair size={17} weight="duotone" />
                  </Button>
                </Tooltip>
                <Tooltip content="Close expanded diagram" side="bottom">
                  <Dialog.Close asChild>
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon"
                      className="vibelab-diagram-action"
                      aria-label="Close diagram"
                    >
                      <X size={17} />
                    </Button>
                  </Dialog.Close>
                </Tooltip>
              </div>
            </div>
            <div className="vibelab-diagram-dialog__canvas">
              <DiagramCanvas {...layout} expanded onInstance={setDialogFlow} />
            </div>
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>
    </>
  );
}
