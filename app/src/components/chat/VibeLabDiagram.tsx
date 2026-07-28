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
  type Edge,
  type NodeTypes,
  type ReactFlowInstance,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { useMemo, useState } from 'react';
import { Button } from '../ui/button';
import { Tooltip } from '../ui/Tooltip';
import { BaseDiagramNode } from './diagram-nodes/BaseDiagramNode';
import { DecisionDiagramNode } from './diagram-nodes/DecisionDiagramNode';
import { GroupDiagramNode } from './diagram-nodes/GroupDiagramNode';
import {
  createVibeLabDiagramLayout,
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

function diagramHeight(nodeCount: number, groupCount: number) {
  return Math.min(520, Math.max(320, 250 + Math.ceil(nodeCount / 4) * 62 + groupCount * 18));
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
      fitView
      fitViewOptions={{ padding: expanded ? 0.16 : 0.2, maxZoom: 1.1 }}
      minZoom={0.5}
      maxZoom={2}
      onInit={onInstance}
      panOnDrag
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
  const groupCount = data.groups?.length ?? 0;
  const fitInline = () => inlineFlow?.fitView({ padding: 0.2, maxZoom: 1.1 });
  const resetInline = fitInline;
  const fitDialog = () => dialogFlow?.fitView({ padding: 0.16, maxZoom: 1.25 });
  const resetDialog = fitDialog;

  const actionBar = (
    <div className="vibelab-diagram-actions" aria-label="Diagram controls">
      <Tooltip content="Expand diagram" side="top">
        <Button
          type="button"
          variant="ghost"
          size="icon"
          className="vibelab-diagram-action"
          aria-label="Expand diagram"
          onClick={() => setIsExpanded(true)}
        >
          <ArrowsOut size={15} />
        </Button>
      </Tooltip>
      <Tooltip content="Fit diagram" side="top">
        <Button type="button" variant="ghost" size="icon" className="vibelab-diagram-action" aria-label="Fit diagram" onClick={fitInline}>
          <Crosshair size={15} />
        </Button>
      </Tooltip>
      <Tooltip content="Zoom in" side="top">
        <Button type="button" variant="ghost" size="icon" className="vibelab-diagram-action" aria-label="Zoom in" onClick={() => inlineFlow?.zoomIn()}>
          <MagnifyingGlassPlus size={15} />
        </Button>
      </Tooltip>
      <Tooltip content="Zoom out" side="top">
        <Button type="button" variant="ghost" size="icon" className="vibelab-diagram-action" aria-label="Zoom out" onClick={() => inlineFlow?.zoomOut()}>
          <MagnifyingGlassMinus size={15} />
        </Button>
      </Tooltip>
      <Tooltip content="Reset diagram view" side="top">
        <Button type="button" variant="ghost" size="icon" className="vibelab-diagram-action" aria-label="Reset diagram view" onClick={resetInline}>
          <Crosshair size={15} weight="duotone" />
        </Button>
      </Tooltip>
      <Tooltip content={copied ? 'Copied' : 'Copy diagram source'} side="top">
        <Button type="button" variant="ghost" size="icon" className="vibelab-diagram-action" aria-label="Copy diagram source" onClick={copySource}>
          {copied ? <Check size={15} weight="bold" /> : <Copy size={15} />}
        </Button>
      </Tooltip>
    </div>
  );

  return (
    <>
      <section className={`vibelab-diagram-card my-3 vibelab-diagram-card--${data.preset}`} aria-label={data.title}>
        <header className="vibelab-diagram-header">
          <div>
            <h3>{data.title}</h3>
            {data.subtitle && <p>{data.subtitle}</p>}
          </div>
          {actionBar}
        </header>
        <div className="vibelab-diagram-canvas" style={{ height: diagramHeight(data.nodes.length, groupCount) }}>
          <DiagramCanvas {...layout} expanded={false} onInstance={setInlineFlow} />
        </div>
      </section>

      <Dialog.Root open={isExpanded} onOpenChange={setIsExpanded}>
        <Dialog.Portal>
          <Dialog.Overlay className="fixed inset-0 z-[400] bg-black/70 backdrop-blur-sm" />
          <Dialog.Content className={`vibelab-diagram-dialog fixed inset-3 z-[401] flex min-w-0 flex-col sm:inset-7 ${data.preset}`}>
            <div className="vibelab-diagram-dialog__header">
              <div>
                <Dialog.Title>{data.title}</Dialog.Title>
                <Dialog.Description>{data.subtitle ?? 'Interactive VibeLab diagram.'}</Dialog.Description>
              </div>
              <div className="vibelab-diagram-actions" aria-label="Expanded diagram controls">
                <Tooltip content="Fit diagram" side="bottom"><Button type="button" variant="ghost" size="icon" className="vibelab-diagram-action" aria-label="Fit expanded diagram" onClick={fitDialog}><Crosshair size={15} /></Button></Tooltip>
                <Tooltip content="Zoom in" side="bottom"><Button type="button" variant="ghost" size="icon" className="vibelab-diagram-action" aria-label="Zoom in expanded diagram" onClick={() => dialogFlow?.zoomIn()}><MagnifyingGlassPlus size={15} /></Button></Tooltip>
                <Tooltip content="Zoom out" side="bottom"><Button type="button" variant="ghost" size="icon" className="vibelab-diagram-action" aria-label="Zoom out expanded diagram" onClick={() => dialogFlow?.zoomOut()}><MagnifyingGlassMinus size={15} /></Button></Tooltip>
                <Tooltip content="Reset diagram view" side="bottom"><Button type="button" variant="ghost" size="icon" className="vibelab-diagram-action" aria-label="Reset expanded diagram view" onClick={resetDialog}><Crosshair size={15} weight="duotone" /></Button></Tooltip>
                <Dialog.Close asChild><Button type="button" variant="ghost" size="icon" className="vibelab-diagram-action" aria-label="Close diagram"><X size={16} /></Button></Dialog.Close>
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
