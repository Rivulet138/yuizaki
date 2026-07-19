import { describe, expect, it } from 'vitest'

import { VisualCaptureEpoch } from '@/visual-capture-epoch'

describe('VisualCaptureEpoch', () => {
  it('invalidates captures started under older visual settings', () => {
    const epoch = new VisualCaptureEpoch()
    const pendingCapture = epoch.current()

    epoch.invalidate()

    expect(epoch.isCurrent(pendingCapture)).toBe(false)
    expect(epoch.isCurrent(epoch.current())).toBe(true)
  })
})
