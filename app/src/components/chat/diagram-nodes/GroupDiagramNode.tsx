import type { NodeProps } from '@xyflow/react';
import type { DiagramGroupFlowNode } from '../VibeLabDiagramSchema';

export function GroupDiagramNode({ data }: NodeProps<DiagramGroupFlowNode>) {
  return (
    <div className="vibelab-diagram-group" data-variant={data.variant}>
      <div className="vibelab-diagram-group__heading">
        <span>{data.label}</span>
        {data.description && <small>{data.description}</small>}
      </div>
    </div>
  );
}
