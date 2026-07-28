import { Handle, Position, type NodeProps } from '@xyflow/react';
import { GitBranch } from 'lucide-react';
import type { DiagramFlowNode } from '../VibeLabDiagramSchema';

export function DecisionDiagramNode({
  data,
  sourcePosition,
  targetPosition,
}: NodeProps<DiagramFlowNode>) {
  return (
    <div className={`vibelab-diagram-node vibelab-diagram-node--decision ${data.emphasis ? 'is-emphasized' : ''}`}>
      <Handle type="target" position={targetPosition ?? Position.Left} className="vibelab-diagram-handle" />
      <div className="vibelab-diagram-node__header">
        <GitBranch aria-hidden="true" size={15} strokeWidth={1.8} />
        <span>{data.label}</span>
      </div>
      {data.description && <p>{data.description}</p>}
      {data.annotations.length > 0 && (
        <div className="vibelab-diagram-annotations" aria-label="Diagram annotations">
          {data.annotations.map((annotation) => (
            <span key={annotation.id} data-tone={annotation.tone ?? 'info'}>
              {annotation.label}
            </span>
          ))}
        </div>
      )}
      <Handle type="source" position={sourcePosition ?? Position.Right} className="vibelab-diagram-handle" />
    </div>
  );
}
