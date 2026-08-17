/**
 * Small, transport-agnostic helpers shared by the standalone and project chat
 * surfaces. Agent events can be replayed after a reconnect, so consumers must
 * only react to events belonging to their active chat/task.
 */
export type PreviewLifecycleStatus = 'starting' | 'ready' | 'failed' | null;

type AgentEventLike = {
  type?: string;
  task_id?: string;
  chat_id?: string;
  data?: Record<string, unknown>;
};

export function getAgentEventTaskId(event: AgentEventLike): string | null {
  const taskId = event.task_id ?? event.data?.task_id;
  return typeof taskId === 'string' && taskId.length > 0 ? taskId : null;
}

/** Events without an id are legacy stream events and belong to the stream. */
export function isEventForAgentRun(
  event: AgentEventLike,
  chatId?: string | null,
  taskId?: string | null
): boolean {
  const eventChatId = event.chat_id ?? event.data?.chat_id;
  if (chatId && typeof eventChatId === 'string' && eventChatId !== chatId) return false;

  const eventTaskId = getAgentEventTaskId(event);
  return !(taskId && eventTaskId && eventTaskId !== taskId);
}

export function getPreviewLifecycleStatus(event: AgentEventLike): PreviewLifecycleStatus {
  if (event.type === 'preview_starting') return 'starting';
  if (event.type === 'preview_ready') return 'ready';
  if (event.type === 'preview_failed') return 'failed';

  const preview = event.data?.preview as Record<string, unknown> | undefined;
  const status = preview?.status ?? event.data?.preview_status;
  if (status === 'starting' || status === 'ready' || status === 'failed') return status;

  // Legacy successful project_start continues to mean that the preview can
  // be opened. New worker events use preview_ready instead.
  return event.data?.project_started === true ? 'ready' : null;
}
