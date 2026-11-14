import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createSSRApp, h, ref, type Ref } from 'vue'
import { renderToString } from '@vue/server-renderer'
import type { CompanionEventEnvelope } from '../../../../shared/companion-event'
import AgentTracePanel from './AgentTracePanel.vue'
import { ElMessage } from 'element-plus'

vi.mock('element-plus/es/components/alert/style/css', () => ({}))
vi.mock('element-plus/es/components/empty/style/css', () => ({}))
vi.mock('element-plus/es/components/button/style/css', () => ({}))
vi.mock('element-plus/es/components/switch/style/css', () => ({}))
vi.mock('element-plus/es/components/input/style/css', () => ({}))
vi.mock('element-plus/es/components/select/style/css', () => ({}))
vi.mock('element-plus/es/components/option/style/css', () => ({}))
vi.mock('element-plus/es/components/input-number/style/css', () => ({}))
vi.mock('element-plus/es/components/tag/style/css', () => ({}))
vi.mock('element-plus/es/components/progress/style/css', () => ({}))
vi.mock('element-plus/es/components/form/style/css', () => ({}))
vi.mock('element-plus/es/components/form-item/style/css', () => ({}))

const mocks = vi.hoisted(() => ({ sendInterrupt: vi.fn(), load: vi.fn(async () => undefined), removeSchedule: vi.fn() }))
vi.mock('@/net/socketClient', async () => ({
  ...await import('../../../../shared/runtimeProtocol'),
  getSocketClient: () => ({ sendInterrupt: mocks.sendInterrupt }),
}))
vi.mock('../composables/useSystemDomain', () => ({ useSystemDomain: () => ({
  companionRuntime: ref({ jobs: { events: [] } }), loadCompanionRuntime: mocks.load,
  schedules: ref([]), removeSchedule: mocks.removeSchedule,
}) }))
vi.mock('@/shared/components/feedback/AsyncState.vue', () => ({ default: {} }))
vi.mock('@/shared/components/panel/PanelShell.vue', () => ({ default: {} }))
vi.mock('@/api/client', () => ({ systemClient: {} }))
vi.mock('@/i18n', () => ({ t: (key: string) => key }))
vi.mock('element-plus', () => ({ ElMessage: { warning: vi.fn(), success: vi.fn() }, ElMessageBox: { confirm: vi.fn().mockResolvedValue('confirm') } }))

interface TraceState {
  removeScheduleItem: (id: string) => Promise<void>
  removingScheduleIds: Ref<Set<string>>
  cancelCompanionJob: (job: CompanionEventEnvelope) => Promise<void>
  handleCancellationAck: (data: unknown) => void
  observeCancellationTerminal: (job: CompanionEventEnvelope) => void
  toolCancellations: Ref<Record<string, { phase: string }>>
}
const job: CompanionEventEnvelope = {
  version: 1, type: 'AgentJobRunning', status: 'running', source: 'builtin',
  jobId: 'job', requestId: 'request', sessionId: 'session', workspaceId: 'workspace',
  turnId: 'turn', runId: 'run', revision: 1, interruptionEpoch: 0, timestamp: 1,
  data: { tool: 'shell' },
}

describe('trace tool cancellation acknowledgement', () => {
  let state: TraceState
  beforeEach(async () => {
    vi.useFakeTimers()
    vi.clearAllMocks()
    mocks.sendInterrupt.mockReturnValue({ status: 'accepted' })
    vi.stubGlobal('window', { setTimeout, clearTimeout })
    // Execute the real SFC setup in an SSR scope; render output is irrelevant to this state contract.
    const app = createSSRApp({ setup(props, context) {
      state = Reflect.apply(Reflect.get(AgentTracePanel, 'setup'), null, [props, context]) as TraceState
      return () => h('div')
    } })
    await renderToString(app)
  })
  afterEach(() => {
    vi.clearAllTimers()
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })
  it.each([null, { ok: false }, { ok: true }])('only acknowledges confirmed schedule deletion: %j', async (result) => {
    mocks.removeSchedule.mockResolvedValue(result)
    await state.removeScheduleItem('task')
    expect(ElMessage.success).toHaveBeenCalledTimes(result?.ok ? 1 : 0)
    expect(state.removingScheduleIds.value.size).toBe(0)
  })

  const phase = () => state.toolCancellations.value[job.jobId]?.phase

  it.each(['offline', 'rejected'])('does not claim a cancellation was sent when %s', async (status) => {
    mocks.sendInterrupt.mockReturnValue({ status })
    await state.cancelCompanionJob(job)
    expect(phase()).toBe(status)
  })

  it('requires the matching ACK and a newer terminal event for the exact job identity', async () => {
    await state.cancelCompanionJob(job)
    expect(phase()).toBe('waitingAck')
    state.handleCancellationAck({ request_id: job.requestId, session_id: 'other', hit_active_tool: true })
    expect(phase()).toBe('waitingAck')
    state.handleCancellationAck({ request_id: job.requestId, session_id: job.sessionId, hit_active_tool: true })
    expect(phase()).toBe('waitingTerminal')
    state.observeCancellationTerminal({ ...job, revision: 2, status: 'cancelled', workspaceId: 'other' })
    expect(phase()).toBe('waitingTerminal')
    state.observeCancellationTerminal({ ...job, revision: 2, status: 'completed' })
    expect(phase()).toBe('completed')
  })

  it('reports an unknown outcome when no ACK or terminal event arrives', async () => {
    await state.cancelCompanionJob(job)
    await vi.advanceTimersByTimeAsync(15000)
    expect(phase()).toBe('unknown')
  })
})
