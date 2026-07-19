import { describe, expect, it, vi } from 'vitest'
import type { ModelResourceStatusPayload } from '../../shared/resource-manager'

vi.mock('electron', () => ({ dialog: {} }))

import { missingModelResources } from '../resource-manager'

const summary = (ready: boolean) => ({
  ready,
  state: ready ? 'ready' as const : 'missing' as const,
  message: ready ? 'Ready' : 'Missing',
  details: [],
})

const status = {
  soulx: { ...summary(false) },
  sherpa: { ...summary(true) },
  sherpaOnline: { ...summary(false) },
  embedding: { ...summary(false) },
  tts: { ...summary(true) },
} as ModelResourceStatusPayload

describe('model resource selection', () => {
  it('returns each requested missing resource once and skips ready resources', () => {
    expect(missingModelResources(status, ['tts', 'embedding', 'embedding', 'sherpa_online', 'sherpa'])).toEqual([
      'embedding',
      'sherpa_online',
    ])
  })
})
