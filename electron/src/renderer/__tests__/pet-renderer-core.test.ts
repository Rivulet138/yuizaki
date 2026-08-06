import { describe, expect, it } from 'vitest'
import { resolveRendererAsset } from '../pet-renderer-core'

describe('resolveRendererAsset', () => {
  it('routes managed pet assets through the Electron control server origin', () => {
    expect(resolveRendererAsset('/api/pet/assets/live2d/local/model.model3.json')).toBe(
      'http://localhost:38945/api/pet/assets/live2d/local/model.model3.json',
    )
  })

  it('keeps bundled renderer assets relative to the pet window', () => {
    window.history.replaceState({}, '', '/pet-window.html')

    expect(resolveRendererAsset('./live2d/llm-live2d/yumi/yumi.model3.json')).toBe(
      `${window.location.origin}/live2d/llm-live2d/yumi/yumi.model3.json`,
    )
  })
})
