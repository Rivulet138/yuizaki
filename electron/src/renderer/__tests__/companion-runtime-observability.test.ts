import { afterEach, describe, expect, it, vi } from 'vitest'
import { logger } from '../logger'
import type { ProactiveDeliveryResult } from '../app/runtime/companionRuntime'
import {
  reportCompanionRuntimePollResult,
  reportCompanionRuntimeSinkError,
} from '../app/composables/useCompanionRuntimeBridge'

describe('companion runtime production observability', () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('records sink failures as structured production errors', () => {
    const error = vi.spyOn(logger, 'error').mockImplementation(() => undefined)

    reportCompanionRuntimeSinkError({ sink: 'motion', message: 'adapter unavailable' })

    expect(error).toHaveBeenCalledWith('[CompanionRuntime] sink delivery failed', {
      event: 'companion_runtime.sink_failure',
      sink: 'motion',
      message: 'adapter unavailable',
    })
  })

  it('treats missing browser control authorization as a degraded warning', () => {
    const warn = vi.spyOn(logger, 'warn').mockImplementation(() => undefined)
    const error = vi.spyOn(logger, 'error').mockImplementation(() => undefined)

    reportCompanionRuntimeSinkError({ sink: 'behavior', message: '控制服务未授权：请从 Electron 应用入口重新打开界面。' })

    expect(warn).toHaveBeenCalledWith('[CompanionRuntime] sink unavailable without control authorization', {
      event: 'companion_runtime.sink_failure',
      sink: 'behavior',
      message: '控制服务未授权：请从 Electron 应用入口重新打开界面。',
    })
    expect(error).not.toHaveBeenCalled()
  })

  it('records partial and failed scheduled deliveries without logging success', () => {
    const warn = vi.spyOn(logger, 'warn').mockImplementation(() => undefined)
    const error = vi.spyOn(logger, 'error').mockImplementation(() => undefined)
    const partial: ProactiveDeliveryResult = {
      status: 'partial',
      attempted: ['emotion', 'motion'],
      succeeded: ['emotion'],
      failed: [{ sink: 'motion', message: 'motion failed' }],
    }

    reportCompanionRuntimePollResult(partial)
    reportCompanionRuntimePollResult({ status: 'failed', attempted: [], succeeded: [], failed: [] })
    reportCompanionRuntimePollResult({ status: 'delivered', attempted: [], succeeded: [], failed: [] })

    expect(warn).toHaveBeenCalledOnce()
    expect(warn).toHaveBeenCalledWith('[CompanionRuntime] proactive delivery partial', expect.objectContaining({
      event: 'companion_runtime.poll_delivery',
      status: 'partial',
    }))
    expect(error).toHaveBeenCalledOnce()
    expect(error).toHaveBeenCalledWith('[CompanionRuntime] proactive delivery failed', expect.objectContaining({
      event: 'companion_runtime.poll_delivery',
      status: 'failed',
    }))
  })
})
