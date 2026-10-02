import { describe, expect, it } from 'vitest'
import {
  acceleratorMatchesKeyboardEvent,
  findKeyboardBindingConflicts,
  keyboardEventToAccelerator,
  normalizeKeyboardAccelerator,
} from './input-bindings'

describe('input binding helpers', () => {
  it('formats captured keyboard events as Electron accelerators', () => {
    expect(keyboardEventToAccelerator({ key: 'p', ctrlKey: true, shiftKey: true })).toBe('Control+Shift+P')
    expect(keyboardEventToAccelerator({ key: 'Escape', ctrlKey: true })).toBe('Control+Escape')
  })

  it('matches configured accelerators in browser mode', () => {
    expect(acceleratorMatchesKeyboardEvent(
      { key: 'P', ctrlKey: true, shiftKey: true },
      'Control+Shift+P',
    )).toBe(true)
    expect(acceleratorMatchesKeyboardEvent(
      { key: 'P', ctrlKey: true },
      'Control+Shift+P',
    )).toBe(false)
  })

  it('normalizes manual aliases and rejects unknown modifiers', () => {
    expect(normalizeKeyboardAccelerator('Ctrl + Shift + p')).toBe('Control+Shift+P')
    expect(normalizeKeyboardAccelerator('Unknown+P')).toBe('')
  })

  it('reports duplicate actions before native registration', () => {
    const conflicts = findKeyboardBindingConflicts({
      interact: 'Control+Shift+P',
      lock: 'Ctrl+Shift+P',
      openPanel: '',
      toggleVision: 'Control+Alt+V',
      emergencyStop: 'Control+Shift+Escape',
    })
    expect(conflicts).toEqual([{ accelerator: 'control+shift+p', actions: ['interact', 'lock'] }])
  })
})
