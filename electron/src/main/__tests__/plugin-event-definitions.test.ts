import { describe, expect, it } from 'vitest'
import {
  DESKTOP_PET_EVENT_DEFINITIONS,
  getDesktopPetEventDefinition,
  type DesktopPetEventName,
} from '../../shared/plugin'

const desktopPetEvents: DesktopPetEventName[] = [
  'onPetClicked',
  'onPetDragged',
  'onPetIdle',
  'onEmotionChanged',
  'onSpeechStart',
  'onSpeechEnd',
  'onToolStart',
  'onToolEnd',
  'requestPetAction',
]

describe('desktop pet event definitions', () => {
  it('keeps every plugin pet event explainable in the skill market', () => {
    expect(Object.keys(DESKTOP_PET_EVENT_DEFINITIONS).sort()).toEqual([...desktopPetEvents].sort())

    for (const event of desktopPetEvents) {
      const definition = getDesktopPetEventDefinition(event)

      expect(definition.label.trim()).not.toBe('')
      expect(definition.trigger.trim()).not.toBe('')
      expect(definition.payloadHint.trim()).not.toBe('')
      expect(definition.frequencyHint.trim()).not.toBe('')
    }
  })

  it('calls out interrupted speech for speech end subscriptions', () => {
    expect(getDesktopPetEventDefinition('onSpeechEnd').payloadHint).toContain('interrupted')
  })
})
