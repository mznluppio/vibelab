import {
  AppWindow,
  Bot,
  CheckCircle,
  Database,
  Globe,
  MessageCircle,
  ShieldCheck,
  Sparkles,
  User,
  Wrench,
} from 'lucide-react';
import { Handle, Position, type NodeProps } from '@xyflow/react';
import type { DiagramFlowNode, DiagramIcon } from '../VibeLabDiagramSchema';

const ICONS: Record<DiagramIcon, typeof AppWindow> = {
  app: AppWindow,
  user: User,
  bot: Bot,
  database: Database,
  tool: Wrench,
  message: MessageCircle,
  shield: ShieldCheck,
  check: CheckCircle,
  sparkle: Sparkles,
  globe: Globe,
};

export function BaseDiagramNode({ data, sourcePosition, targetPosition }: NodeProps<DiagramFlowNode>) {
  const Icon = data.icon ? ICONS[data.icon] : undefined;
  return (
    <div className={`vibelab-diagram-node vibelab-diagram-node--${data.kind} ${data.emphasis ? 'is-emphasized' : ''}`}>
      <Handle type="target" position={targetPosition ?? Position.Left} className="vibelab-diagram-handle" />
      <div className="vibelab-diagram-node__header">
        {Icon && <Icon aria-hidden="true" size={15} strokeWidth={1.8} />}
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
