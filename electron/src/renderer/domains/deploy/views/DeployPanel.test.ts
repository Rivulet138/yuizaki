vi.mock('element-plus/es/components/tag/style/css', () => ({}))
vi.mock('element-plus/es/components/card/style/css', () => ({}))
vi.mock('element-plus/es/components/button/style/css', () => ({}))
vi.mock('element-plus/es/components/alert/style/css', () => ({}))
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { effectScope, type EffectScope } from 'vue'
import DeployPanel from './DeployPanel.vue'
import { systemClient, summaryClient } from '@/api/client'
import { requestJson, resolveBackendUrl } from '@/api/clients/http-client'
import { ElMessage } from 'element-plus'

vi.mock('vue', async (original) => ({ ...await original<typeof import('vue')>(), useSSRContext: () => ({ modules: new Set() }), onMounted: vi.fn() }))
vi.mock('element-plus', async (original) => ({ ...await original<typeof import('element-plus')>(),
  ElMessage: { success: vi.fn(), error: vi.fn(), info: vi.fn() }, ElMessageBox: { confirm: vi.fn().mockResolvedValue('confirm') },
}))
vi.mock('@/shared/components/panel/PanelShell.vue', () => ({ default: {} }))
vi.mock('@/i18n', () => ({ t: (key: string, params?: Record<string, unknown>) => params ? `${key}: ${Object.values(params).join(' ')}` : key }))
vi.mock('@/api/client', () => ({ systemClient: { startPython: vi.fn(), stopPython: vi.fn(), providers: vi.fn(), openExternal: vi.fn() }, summaryClient: { getReadiness: vi.fn() } }))
vi.mock('@/api/clients/http-client', () => ({ CONTROL_ORIGIN: 'http://localhost:48001', requestJson: vi.fn(), resolveBackendUrl: vi.fn() }))
let scope: EffectScope
let state: any
beforeEach(() => {
  vi.clearAllMocks()
  vi.stubGlobal('window', { petApi: { python: { start: vi.fn(), stop: vi.fn() } } })
  vi.stubGlobal('navigator', { userAgent: 'Windows' })
  vi.mocked(requestJson).mockResolvedValue({ status: 'healthy', healthy: true })
  vi.mocked(systemClient.providers).mockResolvedValue({ providers: [], summary: {} } as any)
  vi.mocked(summaryClient.getReadiness).mockResolvedValue({ ready: true } as any)
  scope = effectScope()
  state = scope.run(() => (DeployPanel as any).setup({}, { expose: vi.fn() }))
})
afterEach(() => { scope.stop(); vi.unstubAllGlobals() })

describe('deploy action feedback', () => {
  it.each(['start', 'stop'] as const)('keeps %s failure visible after automatic successful health refresh', async (action) => {
    const client = action === 'start' ? systemClient.startPython : systemClient.stopPython
    vi.mocked(client).mockResolvedValue({ success: false, error: 'process refused' })
    await (action === 'start' ? state.startPython() : state.stopPython())
    expect(state.actionError.value).toContain('process refused')
    expect(state.health.healthy).toBe(true)
    expect(state.refreshing.value).toBe(false)
  })

  it('handles backend URL resolution failure when opening docs', async () => {
    vi.mocked(resolveBackendUrl).mockRejectedValue(new Error('backend not discoverable'))
    await expect(state.openDocs()).resolves.toBeUndefined()
    expect(ElMessage.info).toHaveBeenCalled()
    expect(systemClient.openExternal).not.toHaveBeenCalled()
  })
})
