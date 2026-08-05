import { describe, expect, it } from 'vitest'

import { isTerminalVisualFrameResult, VisualCaptureEpoch } from '@/visual-capture-epoch'

describe('VisualCaptureEpoch', () => {
  it('invalidates captures started under older visual settings', () => {
    const epoch = new VisualCaptureEpoch()
    const pendingCapture = epoch.current()

    epoch.invalidate()

    expect(epoch.isCurrent(pendingCapture)).toBe(false)
    expect(epoch.isCurrent(epoch.current())).toBe(true)
  })

  it('rejects late results after disable while allowing explicit one-shot captures', () => {
    const epoch = new VisualCaptureEpoch()
    epoch.trackFrame('scheduled', epoch.current())
    expect(epoch.acceptResult('scheduled', false, true)).toBe(false)

    epoch.trackFrame('explicit', epoch.current(), true)
    expect(epoch.acceptResult('explicit', false, true)).toBe(true)
    expect(epoch.acceptResult('explicit', true, true)).toBe(false)
  })

  it('accepts pending and terminal results for the same tracked frame', () => {
    const epoch = new VisualCaptureEpoch()
    epoch.trackFrame('frame-1', epoch.current())

    const pending = {
      status: 'ok',
      mode: 'observe',
      analysis_status: 'pending',
    }
    expect(epoch.acceptResult('frame-1', true, isTerminalVisualFrameResult(pending))).toBe(true)

    const ready = {
      status: 'ok',
      mode: 'vision',
      analysis_status: 'ready',
    }
    expect(epoch.acceptResult('frame-1', true, isTerminalVisualFrameResult(ready))).toBe(true)
    expect(epoch.acceptResult('frame-1', true, true)).toBe(false)
  })

  it('treats correlated errors as terminal results', () => {
    expect(isTerminalVisualFrameResult({
      frame_id: 'frame-1',
      error: 'IMAGE_TOO_LARGE',
    })).toBe(true)
  })

  it('forgets tracked frames when capture settings change', () => {
    const epoch = new VisualCaptureEpoch()
    epoch.trackFrame('frame-1', epoch.current())

    epoch.invalidate()

    expect(epoch.acceptResult('frame-1', true, true)).toBe(false)
  })
})
