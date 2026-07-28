import { describe, expect, it } from 'vitest';
import { createVibeLabDiagramLayout, parseVibeLabDiagram } from './VibeLabDiagramSchema';

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

  it.each([
    ['unknown field', { ...validDiagram, customTheme: 'not allowed' }],
    ['coordinates', { ...validDiagram, nodes: [{ ...validDiagram.nodes[0], x: 10 }] }],
    ['CSS', { ...validDiagram, nodes: [{ ...validDiagram.nodes[0], css: 'color:red' }] }],
    ['duplicate node id', { ...validDiagram, nodes: [validDiagram.nodes[0], validDiagram.nodes[0]] }],
    ['missing edge endpoint', { ...validDiagram, edges: [{ source: 'request', target: 'missing' }] }],
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
    expect(check?.position.x).toBeGreaterThan(request?.position.x ?? 0);
    expect(layout.edges[1]).toMatchObject({ type: 'bezier', style: { strokeDasharray: '7 5' } });
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
