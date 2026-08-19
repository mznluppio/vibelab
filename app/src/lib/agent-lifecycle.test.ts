import { describe, expect, it } from 'vitest';
import {
  getAgentEventTaskId,
  getPreviewLifecycleStatus,
  isEventForAgentRun,
  shouldKeepAgentStreamOpenAfterComplete,
} from './agent-lifecycle';

describe('agent lifecycle event helpers', () => {
  it('accepts legacy events while rejecting another chat or task', () => {
    expect(isEventForAgentRun({ type: 'text_delta', data: {} }, 'chat-a', 'task-a')).toBe(true);
    expect(
      isEventForAgentRun({ type: 'text_delta', chat_id: 'chat-b', data: {} }, 'chat-a', 'task-a')
    ).toBe(false);
    expect(
      isEventForAgentRun({ type: 'text_delta', data: { task_id: 'task-b' } }, 'chat-a', 'task-a')
    ).toBe(false);
  });

  it('normalizes legacy and asynchronous preview states', () => {
    expect(getPreviewLifecycleStatus({ type: 'preview_starting', data: {} })).toBe('starting');
    expect(getPreviewLifecycleStatus({ type: 'preview_ready', data: {} })).toBe('ready');
    expect(getPreviewLifecycleStatus({ type: 'preview_failed', data: {} })).toBe('failed');
    expect(
      getPreviewLifecycleStatus({ type: 'complete', data: { preview: { status: 'starting' } } })
    ).toBe('starting');
    expect(getPreviewLifecycleStatus({ type: 'complete', data: { project_started: true } })).toBe(
      'ready'
    );
  });

  it('finds a task id in either public event location', () => {
    expect(getAgentEventTaskId({ task_id: 'task-a', data: {} })).toBe('task-a');
    expect(getAgentEventTaskId({ data: { task_id: 'task-b' } })).toBe('task-b');
  });

  it('keeps the stream open while platform preview or repair work is pending', () => {
    expect(shouldKeepAgentStreamOpenAfterComplete({ preview: { status: 'starting' } })).toBe(true);
    expect(shouldKeepAgentStreamOpenAfterComplete({ delivery_repair: { status: 'running' } })).toBe(
      true
    );
    expect(shouldKeepAgentStreamOpenAfterComplete({ preview: { status: 'ready' } })).toBe(false);
    expect(shouldKeepAgentStreamOpenAfterComplete()).toBe(false);
  });
});
