import { describe, expect, it } from 'vitest'
import type { AvatarManifest } from '../../shared/pet-control'
import { resolveLive2DMotionGroups } from './live2d-motion-groups'

const manifestWith = (motions: AvatarManifest['motions']): AvatarManifest => ({
  id: 'test',
  name: 'Test',
  summary: '',
  persona: { tone: '', traits: [], styleRules: [] },
  modelJson: '',
  modelTransform: { scale: 1, offsetX: 0, offsetY: 0 },
  transformDefaults: { scale: 1, offsetX: 0, offsetY: 0 },
  expressions: [],
  parameterControls: [],
  motions,
})

describe('resolveLive2DMotionGroups', () => {
  it('uses only groups declared by the active model', () => {
    const groups = resolveLive2DMotionGroups(manifestWith({
      'Tap@Body:0': { file: 'wave.motion3.json', group: 'Tap@Body' },
      'Flick:0': { file: 'tear.motion3.json', group: 'Flick' },
    }))

    expect(groups).toEqual(['Tap@Body', 'Flick'])
    expect(groups).not.toContain('Idle')
  })

  it('deduplicates repeated groups and skips entries without a group', () => {
    const groups = resolveLive2DMotionGroups(manifestWith({
      'Flick:0': { file: 'a.motion3.json', group: 'Flick' },
      'Flick:1': { file: 'b.motion3.json', group: 'Flick' },
      'loose': { file: 'loose.motion3.json' },
    }))

    expect(groups).toEqual(['Flick'])
  })

  it('falls back to the conservative group list when the manifest is absent', () => {
    expect(resolveLive2DMotionGroups(null)).toEqual([
      'Idle',
      'Tap',
      'Tap@Body',
      'Flick',
      'Flick@Body',
    ])
  })
})
