import { describe, expect, it } from 'vitest';
import {
  createVibeLabDiagramLayout,
  getVibeLabDiagramHeight,
  parseVibeLabDiagram,
} from './VibeLabDiagramSchema';

const validDiagram = {
  title: 'Incident response',
  subtitle: 'A deliberate, observable workflow',
  preset: 'technical-dark',
  direction: 'LR',
  nodes: [
    { id: 'request', type: 'actor', label: 'Incoming request', icon: 'user' },
    { id: 'check', type: 'decision', label: 'Needs escalation?' },
    { id: 'result', type: 'output', label: 'Result published', groupId: 'delivery' },
  ],
  edges: [
    { source: 'request', target: 'check' },
    { source: 'check', target: 'result', label: 'Yes', variant: 'dashed' },
  ],
  groups: [{ id: 'delivery', label: 'Delivery', variant: 'highlight' }],
  annotations: [{ id: 'reviewed', nodeId: 'result', label: 'Reviewed', tone: 'success' }],
};

function parse(value: unknown) {
  return parseVibeLabDiagram(JSON.stringify(value));
}

describe('VibeLab diagram schema', () => {
  it('accepts a valid closed schema', () => {
    const result = parse(validDiagram);

    expect(result.success).toBe(true);
    if (result.success) expect(result.data.preset).toBe('technical-dark');
  });

  it('normalizes legacy workflow aliases from existing Assist to Build chats', () => {
    const result = parse({
      title: 'Incident workflow',
      preset: 'business-process',
      direction: 'TB',
      nodes: [
        { id: 'monitor', label: 'Monitor services' },
        { id: 'incident', label: 'Create incident' },
      ],
      edges: [
        { from: 'monitor', to: 'incident' },
        { from: 'incident', to: 'incident', label: 'Progress update' },
      ],
    });

    expect(result.success).toBe(true);
    if (result.success) {
      expect(result.data.nodes.every((node) => node.type === 'step')).toBe(true);
      expect(result.data.edges).toEqual([{ source: 'monitor', target: 'incident' }]);
    }
  });

  it.each([
    ['unknown field', { ...validDiagram, customTheme: 'not allowed' }],
    ['coordinates', { ...validDiagram, nodes: [{ ...validDiagram.nodes[0], x: 10 }] }],
    ['CSS', { ...validDiagram, nodes: [{ ...validDiagram.nodes[0], css: 'color:red' }] }],
    [
      'duplicate node id',
      { ...validDiagram, nodes: [validDiagram.nodes[0], validDiagram.nodes[0]] },
    ],
    [
      'missing edge endpoint',
      { ...validDiagram, edges: [{ source: 'request', target: 'missing' }] },
    ],
  ])('rejects %s', (_label, diagram) => {
    expect(parse(diagram).success).toBe(false);
  });

  it('creates left-to-right layout with a decision, group and dashed edge', () => {
    const result = parse(validDiagram);
    if (!result.success) throw new Error(result.error);

    const layout = createVibeLabDiagramLayout(result.data);
    const request = layout.nodes.find((node) => node.id === 'request');
    const check = layout.nodes.find((node) => node.id === 'check');
    const group = layout.nodes.find((node) => node.id === 'group-delivery');
    const delivery = layout.nodes.find((node) => node.id === 'result');

    expect(check?.type).toBe('vibelab-decision');
    expect(group?.type).toBe('vibelab-group');
    expect(delivery?.parentId).toBe('group-delivery');
    expect(group?.zIndex).toBeLessThan(delivery?.zIndex ?? 0);
    expect(check?.position.x).toBeGreaterThan(request?.position.x ?? 0);
    expect(layout.edges[1]).toMatchObject({
      type: 'bezier',
      source: 'check',
      target: 'result',
      style: { strokeDasharray: '7 5' },
      labelShowBg: true,
      zIndex: 1,
    });
    expect(layout.edges[1].target).not.toBe(group?.id);
  });

  it('derives group bounds from child bounds, including title space', () => {
    const result = parse({
      ...validDiagram,
      nodes: [
        validDiagram.nodes[0],
        { id: 'first', type: 'step', label: 'First grouped step', groupId: 'delivery' },
        { id: 'second', type: 'output', label: 'Second grouped step', groupId: 'delivery' },
      ],
      edges: [
        { source: 'request', target: 'first' },
        { source: 'first', target: 'second', label: 'Yes' },
      ],
      annotations: [],
    });
    if (!result.success) throw new Error(result.error);

    const layout = createVibeLabDiagramLayout(result.data);
    const group = layout.nodes.find((node) => node.id === 'group-delivery');
    const children = layout.nodes.filter((node) => node.parentId === 'group-delivery');
    const groupWidth = Number(group?.style?.width);
    const groupHeight = Number(group?.style?.height);

    expect(children).toHaveLength(2);
    expect(groupWidth).toBeGreaterThan(
      Math.max(...children.map((node) => Number(node.style?.width)))
    );
    expect(groupHeight).toBeGreaterThan(
      Math.max(...children.map((node) => Number(node.style?.height)))
    );
    expect(children.every((node) => node.position.x >= 28 && node.position.y >= 62)).toBe(true);
  });

  it('keeps node sizes readable and clamps inline canvas height from content bounds', () => {
    const result = parse({
      title: 'Short process',
      preset: 'technical-dark',
      direction: 'LR',
      nodes: [
        { id: 'one', type: 'start', label: 'Incoming request' },
        { id: 'two', type: 'decision', label: 'Needs escalation?' },
        { id: 'three', type: 'tool', label: 'Run trusted tools' },
        { id: 'four', type: 'end', label: 'Verified result' },
      ],
      edges: [
        { source: 'one', target: 'two' },
        { source: 'two', target: 'three', label: 'Yes' },
        { source: 'two', target: 'four', label: 'No' },
      ],
    });
    if (!result.success) throw new Error(result.error);

    const layout = createVibeLabDiagramLayout(result.data);
    const decision = layout.nodes.find((node) => node.id === 'two');
    expect(Number(decision?.style?.width)).toBeGreaterThanOrEqual(190);
    expect(Number(decision?.style?.width)).toBeLessThanOrEqual(230);
    expect(Number(decision?.style?.height)).toBeGreaterThanOrEqual(82);
    expect(layout.edges.filter((edge) => edge.source === 'two').map((edge) => edge.label)).toEqual([
      'Yes',
      'No',
    ]);
    expect(getVibeLabDiagramHeight(layout.bounds, result.data.direction)).toBeGreaterThanOrEqual(
      280
    );
    expect(getVibeLabDiagramHeight(layout.bounds, result.data.direction)).toBeLessThanOrEqual(360);
  });

  it('caps a large vertical diagram at the inline maximum', () => {
    const nodes = Array.from({ length: 15 }, (_, index) => ({
      id: `step-${index}`,
      type: 'step' as const,
      label: `Process step ${index + 1}`,
    }));
    const result = parse({
      title: 'Long process',
      preset: 'business-process',
      direction: 'TB',
      nodes,
      edges: nodes.slice(1).map((node, index) => ({ source: nodes[index].id, target: node.id })),
    });
    if (!result.success) throw new Error(result.error);

    const layout = createVibeLabDiagramLayout(result.data);
    expect(getVibeLabDiagramHeight(layout.bounds, result.data.direction)).toBe(560);
  });

  it.each(['editorial-comparison', 'business-process'] as const)(
    'creates the %s preset with process-friendly smoothstep edges',
    (preset) => {
      const result = parse({ ...validDiagram, preset, direction: 'TB' });
      if (!result.success) throw new Error(result.error);

      const layout = createVibeLabDiagramLayout(result.data);
      const request = layout.nodes.find((node) => node.id === 'request');
      const check = layout.nodes.find((node) => node.id === 'check');
      expect(check?.position.y).toBeGreaterThan(request?.position.y ?? 0);
      expect(layout.edges[0].type).toBe('smoothstep');
    }
  );
});
