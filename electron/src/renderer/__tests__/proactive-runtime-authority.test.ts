import { describe, expect, it, vi } from 'vitest'
import pythonHeartbeatProactiveEvent from './fixtures/python-heartbeat-proactive-event.json'
import { createCompanionRuntimeController } from '../app/runtime/companionRuntime'
import { parseProactiveOpportunityIdentity } from '../../shared/proactive'

const opportunity = (overrides: Record<string, unknown> = {}) => ({
  type: 'suggestion',
  message: '',
  emotion: '',
  emotion_id: '',
  motion_group: '',
  prompt: '',
  tick: 1,
  at: '2026-08-15T00:00:00Z',
  job_id: 'job-1',
  request_id: 'request-1',
  sourceKind: 'completed_turn_followup',
  sourceId: 'turn-1',
  frameId: 'frame-1',
  trigger_reason: 'completed_turn_followup',
  content_code: 'completed_turn_followup',
  expires_at: 1_800_000_000,
  proactive_state: { can_proactively_reach_out: true },
  ...overrides,
})

const snapshot = (event: Record<string, unknown>) => ({
  active_workspace_id: 'default',
  heartbeat: { behavior_events: [event] },
  jobs: { events: [], active_job_ids: typeof event['job_id'] === 'string' ? [event['job_id']] : [] },
  companion_state: { interruptibility: 1, proactive_state: { can_proactively_reach_out: true } },
})

describe('proactive runtime backend authority', () => {
  it('consumes the unmodified Python heartbeat event contract through identity authorization and a visible sink', async () => {
    const event = structuredClone(pythonHeartbeatProactiveEvent)
    const advice = vi.fn()
    const authorizeOpportunity = vi.fn((candidate) => parseProactiveOpportunityIdentity(candidate) !== null)
    const controller = createCompanionRuntimeController({
      pollSnapshot: async () => snapshot(event) as never,
      isAvailable: () => true,
      readDoNotDisturb: async () => false,
      authorizeOpportunity,
      getWorkspaceId: () => 'default',
      getLocale: () => 'en-US',
      sinks: { advice },
    })

    expect(event).toMatchObject({
      tick: expect.any(Number),
      at: expect.stringMatching(/(?:Z|[+-]\d{2}:\d{2})$/),
      job_id: expect.any(String),
      request_id: expect.any(String),
      frame_id: expect.any(String),
      source_kind: 'completed_turn_followup',
      source_id: expect.any(String),
      content_code: 'completed_turn_followup',
    })
    expect(await controller.pollOnce()).toMatchObject({ status: 'delivered', succeeded: ['advice'] })
    expect(authorizeOpportunity).toHaveBeenCalledTimes(2)
    expect(advice).toHaveBeenCalledWith('Your previous task is complete. You can review the result now.')
  })

  it('revalidates authorization immediately before effects when quiet hours begin during delivery', async () => {
    const advice = vi.fn()
    const authorizeOpportunity = vi.fn()
      .mockResolvedValueOnce(true)
      .mockResolvedValueOnce(false)
    const controller = createCompanionRuntimeController({
      pollSnapshot: async () => snapshot(opportunity()) as never,
      isAvailable: () => true,
      readDoNotDisturb: async () => false,
      authorizeOpportunity,
      getWorkspaceId: () => 'default',
      sinks: { advice },
    })

    expect(await controller.pollOnce()).toBe('ineligible')
    expect(authorizeOpportunity).toHaveBeenCalledTimes(2)
    expect(advice).not.toHaveBeenCalled()
  })

  it('selects an active authorized opportunity when a newer jobless legacy event would otherwise starve it', async () => {
    const authorized = opportunity()
    const legacy = {
      type: 'idle_prompt',
      tick: 2,
      at: '2026-08-15T00:00:01Z',
      message: 'legacy presentation must not shadow authority',
      proactive_state: { can_proactively_reach_out: true },
    }
    const advice = vi.fn()
    const authorizeOpportunity = vi.fn(async () => true)
    const controller = createCompanionRuntimeController({
      pollSnapshot: async () => ({
        ...snapshot(authorized),
        heartbeat: { behavior_events: [authorized, legacy] },
      }) as never,
      isAvailable: () => true,
      readDoNotDisturb: async () => false,
      authorizeOpportunity,
      getWorkspaceId: () => 'default',
      getLocale: () => 'en-US',
      sinks: { advice },
    })

    expect(await controller.pollOnce()).toMatchObject({ status: 'delivered', succeeded: ['advice'] })
    expect(authorizeOpportunity).toHaveBeenCalledTimes(2)
    expect(advice).toHaveBeenCalledWith('Your previous task is complete. You can review the result now.')
    expect(advice).not.toHaveBeenCalledWith(legacy.message)
  })

  it.each([
    ['zh-CN', '之前的任务已经完成，我来提醒你查看结果。'],
    ['en-US', 'Your previous task is complete. You can review the result now.'],
    ['ja-JP', '先ほどのタスクが完了しました。結果を確認できます。'],
  ])('delivers the closed content code through a localized visible sink for %s', async (locale, expectedMessage) => {
    const advice = vi.fn()
    const reportOpportunityOutcome = vi.fn()
    const controller = createCompanionRuntimeController({
      pollSnapshot: async () => snapshot(opportunity()) as never,
      isAvailable: () => true,
      readDoNotDisturb: async () => false,
      authorizeOpportunity: async () => true,
      getWorkspaceId: () => 'default',
      getLocale: () => locale,
      sinks: { advice },
      reportOpportunityOutcome,
    })

    expect(await controller.pollOnce()).toEqual({
      status: 'delivered',
      attempted: ['advice'],
      succeeded: ['advice'],
      failed: [],
    })
    expect(advice).toHaveBeenCalledWith(expectedMessage)
    expect(reportOpportunityOutcome).toHaveBeenCalledWith('job-1', 'request-1', 'delivered', 'delivered')
  })

  it.each([
    opportunity({ content_code: 'unknown_code' }),
    opportunity({ content_code: undefined }),
    opportunity({ sourceKind: 'unknown_source' }),
  ])('fails closed without sinks or a delivered acknowledgement for unknown source/content', async (event) => {
    const advice = vi.fn()
    const reportOpportunityOutcome = vi.fn()
    const controller = createCompanionRuntimeController({
      pollSnapshot: async () => snapshot(event) as never,
      isAvailable: () => true,
      readDoNotDisturb: async () => false,
      authorizeOpportunity: async () => true,
      getWorkspaceId: () => 'default',
      getLocale: () => 'en-US',
      sinks: { advice },
      reportOpportunityOutcome,
    })

    const result = await controller.pollOnce()
    expect(result === 'empty' || result === 'duplicate_or_invalid' || (typeof result === 'object' && result.status === 'failed')).toBe(true)
    expect(advice).not.toHaveBeenCalled()
    expect(reportOpportunityOutcome).not.toHaveBeenCalledWith('job-1', 'request-1', 'delivered', expect.anything())
  })

  it('reports failed when an authorized candidate has no available visible sink', async () => {
    const reportOpportunityOutcome = vi.fn()
    const controller = createCompanionRuntimeController({
      pollSnapshot: async () => snapshot(opportunity()) as never,
      isAvailable: () => true,
      readDoNotDisturb: async () => false,
      authorizeOpportunity: async () => true,
      getWorkspaceId: () => 'default',
      getLocale: () => 'en-US',
      sinks: {},
      reportOpportunityOutcome,
    })

    expect(await controller.pollOnce()).toEqual({ status: 'failed', attempted: [], succeeded: [], failed: [] })
    expect(reportOpportunityOutcome).toHaveBeenCalledWith('job-1', 'request-1', 'failed', 'no_visible_sink')
  })

  it.each([
    opportunity({ job_id: undefined }),
    opportunity({ request_id: undefined }),
    opportunity({ frameId: undefined }),
    opportunity({ sourceKind: undefined }),
    opportunity({ sourceId: undefined }),
  ])('fails closed before every sink when identity is incomplete', async (event) => {
    const advice = vi.fn()
    const authorizeOpportunity = vi.fn(async () => true)
    const controller = createCompanionRuntimeController({
      pollSnapshot: async () => snapshot(event) as never,
      isAvailable: () => true,
      readDoNotDisturb: async () => false,
      authorizeOpportunity,
      getWorkspaceId: () => 'default',
      sinks: { advice },
    })
    expect(await controller.pollOnce()).toBe('empty')
    expect(authorizeOpportunity).not.toHaveBeenCalled()
    expect(advice).not.toHaveBeenCalled()
  })

  it('does not deliver or report a second outcome after backend denial', async () => {
    const advice = vi.fn()
    const reportOpportunityOutcome = vi.fn()
    const controller = createCompanionRuntimeController({
      pollSnapshot: async () => snapshot(opportunity()) as never,
      isAvailable: () => true,
      readDoNotDisturb: async () => false,
      authorizeOpportunity: async () => false,
      getWorkspaceId: () => 'default',
      sinks: { advice },
      reportOpportunityOutcome,
    })
    expect(await controller.pollOnce()).toBe('ineligible')
    expect(advice).not.toHaveBeenCalled()
    expect(reportOpportunityOutcome).not.toHaveBeenCalled()
  })

  it('drops a late authorization after the active workspace changes', async () => {
    let workspaceId = 'default'
    let resolve!: (value: boolean) => void
    const authorization = new Promise<boolean>((done) => { resolve = done })
    const advice = vi.fn()
    const controller = createCompanionRuntimeController({
      pollSnapshot: async () => snapshot(opportunity()) as never,
      isAvailable: () => true,
      readDoNotDisturb: async () => false,
      authorizeOpportunity: () => authorization,
      getWorkspaceId: () => workspaceId,
      sinks: { advice },
    })
    const pending = controller.pollOnce()
    await vi.waitFor(() => expect(controller.lastSnapshot.value).not.toBeNull())
    workspaceId = 'other'
    resolve(true)
    expect(await pending).toBe('stopped')
    expect(advice).not.toHaveBeenCalled()
  })
})
