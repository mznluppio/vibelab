import dagre from '@dagrejs/dagre';
import { MarkerType, Position, type Edge, type Node } from '@xyflow/react';

export const DIAGRAM_PRESETS = [
  'technical-dark',
  'editorial-comparison',
  'business-process',
] as const;
export const DIAGRAM_DIRECTIONS = ['LR', 'RL', 'TB', 'BT'] as const;
export const DIAGRAM_NODE_TYPES = [
  'start',
  'end',
  'step',
  'decision',
  'actor',
  'system',
  'tool',
  'action',
  'output',
  'note',
] as const;
export const DIAGRAM_ICONS = [
  'app',
  'user',
  'bot',
  'database',
  'tool',
  'message',
  'shield',
  'check',
  'sparkle',
  'globe',
] as const;

/**
 * Reusable prompt contract for any VibeLab agent that can explain a workflow.
 * The renderer remains the source of truth: an agent only describes structure.
 */
export const VIBELAB_DIAGRAM_AGENT_INSTRUCTION = `When a structured professional diagram improves understanding, output a fenced code block tagged \`vibelab-diagram\` containing valid JSON matching the platform schema.

Use Mermaid only for diagrams that cannot be represented by the structured schema. Do not output coordinates, CSS, colors, SVG, JSX, HTML, JavaScript, URLs or callbacks. Choose exactly one preset: technical-dark, editorial-comparison, or business-process. Keep labels short and descriptions only when they add useful context. Include every meaningful branch of a decision (for example Yes/No, Approved/Rejected, or Success/Failure). Use groups only when they improve comprehension; never use a decorative group or a group with one node unless there is a strong structural reason. Prefer 3 to 12 nodes in the main graph, split overly complex diagrams, and keep one coherent direction. The renderer owns all coordinates and styling.`;

export type DiagramPreset = (typeof DIAGRAM_PRESETS)[number];
export type DiagramDirection = (typeof DIAGRAM_DIRECTIONS)[number];
export type DiagramNodeKind = (typeof DIAGRAM_NODE_TYPES)[number];
export type DiagramIcon = (typeof DIAGRAM_ICONS)[number];

export interface VibeLabDiagramNode {
  id: string;
  type: DiagramNodeKind;
  label: string;
  description?: string;
  icon?: DiagramIcon;
  groupId?: string;
  emphasis?: boolean;
}

export interface VibeLabDiagramEdge {
  source: string;
  target: string;
  label?: string;
  variant?: 'solid' | 'dashed' | 'dotted';
  animated?: boolean;
}

export interface VibeLabDiagramGroup {
  id: string;
  label: string;
  description?: string;
  variant?: 'default' | 'muted' | 'highlight';
}

export interface VibeLabDiagramAnnotation {
  id: string;
  nodeId: string;
  label: string;
  tone?: 'info' | 'success' | 'warning';
}

export interface VibeLabDiagramDefinition {
  title: string;
  subtitle?: string;
  preset: DiagramPreset;
  direction: DiagramDirection;
  nodes: VibeLabDiagramNode[];
  edges: VibeLabDiagramEdge[];
  groups?: VibeLabDiagramGroup[];
  annotations?: VibeLabDiagramAnnotation[];
}

export interface DiagramNodeData extends Record<string, unknown> {
  label: string;
  description?: string;
  kind: DiagramNodeKind;
  icon?: DiagramIcon;
  emphasis?: boolean;
  annotations: VibeLabDiagramAnnotation[];
  preset: DiagramPreset;
}

export interface DiagramGroupData extends Record<string, unknown> {
  label: string;
  description?: string;
  variant: 'default' | 'muted' | 'highlight';
}

export type DiagramFlowNode = Node<DiagramNodeData, 'vibelab-node' | 'vibelab-decision'>;
export type DiagramGroupFlowNode = Node<DiagramGroupData, 'vibelab-group'>;

export interface DiagramLayoutBounds {
  x: number;
  y: number;
  width: number;
  height: number;
}

/** Keeps inline canvases proportional to the measured Dagre content. */
export function getVibeLabDiagramHeight(bounds: DiagramLayoutBounds, direction: DiagramDirection) {
  const horizontal = direction === 'LR' || direction === 'RL';
  const viewportBreathingRoom = horizontal ? 138 : 104;
  return Math.round(Math.min(560, Math.max(280, bounds.height + viewportBreathingRoom)));
}

const MAX_NODES = 30;
const MAX_EDGES = 60;
const MAX_LABEL_LENGTH = 80;
const MAX_DESCRIPTION_LENGTH = 180;
const MAX_TITLE_LENGTH = 120;
const MAX_SUBTITLE_LENGTH = 180;
const MAX_GROUPS = 12;
const MAX_ANNOTATIONS = 30;
const SAFE_ID = /^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$/;

const ROOT_KEYS = new Set([
  'title',
  'subtitle',
  'preset',
  'direction',
  'nodes',
  'edges',
  'groups',
  'annotations',
]);
const NODE_KEYS = new Set(['id', 'type', 'label', 'description', 'icon', 'groupId', 'emphasis']);
const EDGE_KEYS = new Set(['source', 'target', 'label', 'variant', 'animated']);
const GROUP_KEYS = new Set(['id', 'label', 'description', 'variant']);
const ANNOTATION_KEYS = new Set(['id', 'nodeId', 'label', 'tone']);

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function hasOnlyKeys(value: Record<string, unknown>, keys: Set<string>) {
  return Object.keys(value).every((key) => keys.has(key));
}

function safeText(value: unknown, maxLength: number): value is string {
  return (
    typeof value === 'string' &&
    value.trim().length > 0 &&
    value.length <= maxLength &&
    !/[<>`]/.test(value)
  );
}

function safeOptionalText(value: unknown, maxLength: number): value is string | undefined {
  return value === undefined || safeText(value, maxLength);
}

function unique(values: string[]) {
  return new Set(values).size === values.length;
}

function hasBannedContent(value: unknown): boolean {
  if (typeof value === 'string') return /javascript:|<\/?[a-z]|<svg|<script/i.test(value);
  if (Array.isArray(value)) return value.some(hasBannedContent);
  if (!isRecord(value)) return false;

  const bannedKeys = new Set([
    'style',
    'className',
    'css',
    'color',
    'background',
    'position',
    'x',
    'y',
    'width',
    'height',
    'html',
    'svg',
    'javascript',
    'url',
    'callback',
  ]);
  return Object.entries(value).some(
    ([key, nestedValue]) => bannedKeys.has(key) || hasBannedContent(nestedValue)
  );
}

/** Parses the intentionally small, presentation-safe diagram contract. */
export function parseVibeLabDiagram(
  source: string
): { success: true; data: VibeLabDiagramDefinition } | { success: false; error: string } {
  let parsed: unknown;
  try {
    parsed = JSON.parse(source);
  } catch {
    return { success: false, error: 'The diagram JSON is invalid.' };
  }

  if (!isRecord(parsed) || !hasOnlyKeys(parsed, ROOT_KEYS) || hasBannedContent(parsed)) {
    return { success: false, error: 'The diagram contains unsupported fields or content.' };
  }

  const {
    title,
    subtitle,
    preset,
    direction,
    nodes,
    edges,
    groups = [],
    annotations = [],
  } = parsed;
  if (
    !safeText(title, MAX_TITLE_LENGTH) ||
    !safeOptionalText(subtitle, MAX_SUBTITLE_LENGTH) ||
    !DIAGRAM_PRESETS.includes(preset as DiagramPreset) ||
    !DIAGRAM_DIRECTIONS.includes(direction as DiagramDirection) ||
    !Array.isArray(nodes) ||
    !Array.isArray(edges) ||
    !Array.isArray(groups) ||
    !Array.isArray(annotations) ||
    nodes.length < 1 ||
    nodes.length > MAX_NODES ||
    edges.length > MAX_EDGES ||
    groups.length > MAX_GROUPS ||
    annotations.length > MAX_ANNOTATIONS
  ) {
    return { success: false, error: 'The diagram does not match the supported VibeLab schema.' };
  }

  if (
    !nodes.every(
      (node) =>
        isRecord(node) &&
        hasOnlyKeys(node, NODE_KEYS) &&
        typeof node.id === 'string' &&
        SAFE_ID.test(node.id) &&
        DIAGRAM_NODE_TYPES.includes(node.type as DiagramNodeKind) &&
        safeText(node.label, MAX_LABEL_LENGTH) &&
        safeOptionalText(node.description, MAX_DESCRIPTION_LENGTH) &&
        (node.icon === undefined || DIAGRAM_ICONS.includes(node.icon as DiagramIcon)) &&
        (node.groupId === undefined ||
          (typeof node.groupId === 'string' && SAFE_ID.test(node.groupId))) &&
        (node.emphasis === undefined || typeof node.emphasis === 'boolean')
    )
  ) {
    return { success: false, error: 'One or more diagram nodes are invalid.' };
  }

  if (
    !groups.every(
      (group) =>
        isRecord(group) &&
        hasOnlyKeys(group, GROUP_KEYS) &&
        typeof group.id === 'string' &&
        SAFE_ID.test(group.id) &&
        safeText(group.label, MAX_LABEL_LENGTH) &&
        safeOptionalText(group.description, MAX_DESCRIPTION_LENGTH) &&
        (group.variant === undefined ||
          ['default', 'muted', 'highlight'].includes(group.variant as string))
    )
  ) {
    return { success: false, error: 'One or more diagram groups are invalid.' };
  }

  const typedNodes = nodes as VibeLabDiagramNode[];
  const typedGroups = groups as VibeLabDiagramGroup[];
  const nodeIds = typedNodes.map((node) => node.id);
  const groupIds = typedGroups.map((group) => group.id);
  if (!unique(nodeIds) || !unique(groupIds) || nodeIds.some((id) => groupIds.includes(id))) {
    return { success: false, error: 'Diagram and group identifiers must be unique.' };
  }
  if (typedNodes.some((node) => node.groupId && !groupIds.includes(node.groupId))) {
    return { success: false, error: 'A node references a group that does not exist.' };
  }

  if (
    !edges.every(
      (edge) =>
        isRecord(edge) &&
        hasOnlyKeys(edge, EDGE_KEYS) &&
        typeof edge.source === 'string' &&
        typeof edge.target === 'string' &&
        nodeIds.includes(edge.source) &&
        nodeIds.includes(edge.target) &&
        edge.source !== edge.target &&
        safeOptionalText(edge.label, MAX_LABEL_LENGTH) &&
        (edge.variant === undefined ||
          ['solid', 'dashed', 'dotted'].includes(edge.variant as string)) &&
        (edge.animated === undefined || typeof edge.animated === 'boolean')
    )
  ) {
    return { success: false, error: 'One or more diagram edges are invalid.' };
  }

  if (
    !annotations.every(
      (annotation) =>
        isRecord(annotation) &&
        hasOnlyKeys(annotation, ANNOTATION_KEYS) &&
        typeof annotation.id === 'string' &&
        SAFE_ID.test(annotation.id) &&
        typeof annotation.nodeId === 'string' &&
        nodeIds.includes(annotation.nodeId) &&
        safeText(annotation.label, MAX_LABEL_LENGTH) &&
        (annotation.tone === undefined ||
          ['info', 'success', 'warning'].includes(annotation.tone as string))
    )
  ) {
    return { success: false, error: 'One or more diagram annotations are invalid.' };
  }

  if (!unique((annotations as VibeLabDiagramAnnotation[]).map((annotation) => annotation.id))) {
    return { success: false, error: 'Diagram annotation identifiers must be unique.' };
  }

  return {
    success: true,
    data: {
      title: title.trim(),
      ...(subtitle ? { subtitle: (subtitle as string).trim() } : {}),
      preset: preset as DiagramPreset,
      direction: direction as DiagramDirection,
      nodes: typedNodes.map((node) => ({ ...node, label: node.label.trim() })),
      edges: edges as VibeLabDiagramEdge[],
      ...(typedGroups.length ? { groups: typedGroups } : {}),
      ...(annotations.length ? { annotations: annotations as VibeLabDiagramAnnotation[] } : {}),
    },
  };
}

function nodeSize(node: VibeLabDiagramNode, annotationCount = 0) {
  const width = node.type === 'note' ? 240 : node.type === 'decision' ? 210 : 220;
  const labelLines = Math.max(1, Math.ceil(node.label.length / (node.type === 'note' ? 31 : 27)));
  const descriptionLines = node.description
    ? Math.min(3, Math.ceil(node.description.length / 37))
    : 0;
  const annotationLines = annotationCount ? Math.ceil(annotationCount / 2) : 0;
  const minHeight = node.type === 'decision' ? 82 : node.type === 'note' ? 78 : 74;
  return {
    width,
    height: Math.max(
      minHeight,
      34 + labelLines * 18 + descriptionLines * 15 + annotationLines * 22
    ),
  };
}

function directionPositions(direction: DiagramDirection) {
  const horizontal = direction === 'LR' || direction === 'RL';
  return {
    sourcePosition: horizontal
      ? direction === 'LR'
        ? Position.Right
        : Position.Left
      : direction === 'TB'
        ? Position.Bottom
        : Position.Top,
    targetPosition: horizontal
      ? direction === 'LR'
        ? Position.Left
        : Position.Right
      : direction === 'TB'
        ? Position.Top
        : Position.Bottom,
  };
}

export function createVibeLabDiagramLayout(definition: VibeLabDiagramDefinition): {
  nodes: Array<DiagramFlowNode | DiagramGroupFlowNode>;
  edges: Edge[];
  bounds: DiagramLayoutBounds;
} {
  const graph = new dagre.graphlib.Graph();
  const horizontal = definition.direction === 'LR' || definition.direction === 'RL';
  graph.setDefaultEdgeLabel(() => ({}));
  graph.setGraph({
    rankdir: definition.direction,
    nodesep: horizontal ? 42 : 54,
    ranksep: horizontal ? 86 : 72,
    marginx: 32,
    marginy: 32,
  });

  const annotationsByNode = new Map<string, VibeLabDiagramAnnotation[]>();
  definition.annotations?.forEach((annotation) => {
    annotationsByNode.set(annotation.nodeId, [
      ...(annotationsByNode.get(annotation.nodeId) ?? []),
      annotation,
    ]);
  });

  definition.nodes.forEach((node) => {
    graph.setNode(node.id, nodeSize(node, annotationsByNode.get(node.id)?.length));
  });
  definition.edges.forEach((edge) => graph.setEdge(edge.source, edge.target));
  dagre.layout(graph);

  const flowPositions = directionPositions(definition.direction);
  const calculated = definition.nodes.map((node) => {
    const position = graph.node(node.id);
    const dimensions = nodeSize(node, annotationsByNode.get(node.id)?.length);
    return {
      node,
      dimensions,
      position: { x: position.x - dimensions.width / 2, y: position.y - dimensions.height / 2 },
    };
  });
  const groupPadding = { horizontal: 28, top: 62, bottom: 26 };
  const groupNodes = new Map<string, DiagramGroupFlowNode>();
  const groupBounds = new Map<string, DiagramLayoutBounds>();
  const groupOffsets = new Map<string, { x: number; y: number }>();

  definition.groups?.forEach((group) => {
    const children = calculated.filter(({ node }) => node.groupId === group.id);
    if (!children.length) return;
    const minX = Math.min(...children.map(({ position }) => position.x));
    const minY = Math.min(...children.map(({ position }) => position.y));
    const maxX = Math.max(
      ...children.map(({ position, dimensions }) => position.x + dimensions.width)
    );
    const maxY = Math.max(
      ...children.map(({ position, dimensions }) => position.y + dimensions.height)
    );
    const position = { x: minX - groupPadding.horizontal, y: minY - groupPadding.top };
    const bounds = {
      x: position.x,
      y: position.y,
      width: maxX - minX + groupPadding.horizontal * 2,
      height: maxY - minY + groupPadding.top + groupPadding.bottom,
    };
    groupOffsets.set(group.id, position);
    groupBounds.set(group.id, bounds);
    groupNodes.set(group.id, {
      id: `group-${group.id}`,
      type: 'vibelab-group',
      position,
      selectable: false,
      draggable: false,
      zIndex: 0,
      data: {
        label: group.label,
        description: group.description,
        variant: group.variant ?? 'default',
      },
      style: {
        width: bounds.width,
        height: bounds.height,
      },
    });
  });

  const nodes: Array<DiagramFlowNode | DiagramGroupFlowNode> = [
    ...groupNodes.values(),
    ...calculated.map(({ node, dimensions, position }) => {
      const groupPosition = node.groupId ? groupOffsets.get(node.groupId) : undefined;
      return {
        id: node.id,
        type: node.type === 'decision' ? 'vibelab-decision' : 'vibelab-node',
        position: groupPosition
          ? { x: position.x - groupPosition.x, y: position.y - groupPosition.y }
          : position,
        ...(node.groupId ? { parentId: `group-${node.groupId}`, extent: 'parent' as const } : {}),
        sourcePosition: flowPositions.sourcePosition,
        targetPosition: flowPositions.targetPosition,
        selectable: false,
        draggable: false,
        zIndex: 2,
        data: {
          label: node.label,
          description: node.description,
          kind: node.type,
          icon: node.icon,
          emphasis: node.emphasis,
          annotations: annotationsByNode.get(node.id) ?? [],
          preset: definition.preset,
        },
        style: { width: dimensions.width, height: dimensions.height },
      } satisfies DiagramFlowNode;
    }),
  ];

  const edgeType = definition.preset === 'technical-dark' ? 'bezier' : 'smoothstep';
  const edges: Edge[] = definition.edges.map((edge, index) => ({
    id: `${edge.source}-${edge.target}-${index}`,
    source: edge.source,
    target: edge.target,
    label: edge.label,
    type: edgeType,
    animated: edge.animated,
    markerEnd: { type: MarkerType.ArrowClosed },
    style:
      edge.variant === 'dashed'
        ? { strokeDasharray: '7 5' }
        : edge.variant === 'dotted'
          ? { strokeDasharray: '2 5' }
          : undefined,
    zIndex: 1,
    ...(edge.label
      ? {
          labelShowBg: true,
          labelBgPadding: [7, 4] as [number, number],
          labelBgBorderRadius: 7,
          labelStyle: { fontSize: 11, fontWeight: 650 },
          labelBgStyle: { fillOpacity: 1 },
        }
      : {}),
  }));

  const contentRects = [
    ...calculated
      .filter(({ node }) => !node.groupId)
      .map(({ position, dimensions }) => ({ ...position, ...dimensions })),
    ...groupBounds.values(),
  ];
  const minX = Math.min(...contentRects.map((rect) => rect.x));
  const minY = Math.min(...contentRects.map((rect) => rect.y));
  const maxX = Math.max(...contentRects.map((rect) => rect.x + rect.width));
  const maxY = Math.max(...contentRects.map((rect) => rect.y + rect.height));

  return {
    nodes,
    edges,
    bounds: { x: minX, y: minY, width: maxX - minX, height: maxY - minY },
  };
}
