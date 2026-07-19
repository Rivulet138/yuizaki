import fs from 'node:fs'
import path from 'node:path'
import { afterEach, describe, expect, it } from 'vitest'
import { InputBindingStore } from '../input-binding-store'
import { DEFAULT_INPUT_BINDINGS } from '../../shared/input-bindings'

const testRoot = path.join(process.cwd(), '.test-input-bindings')

describe('InputBindingStore', () => {
  afterEach(() => {
    fs.rmSync(testRoot, { recursive: true, force: true })
  })

  it('defaults to mouse side button 2 hold-to-talk', () => {
    const store = new InputBindingStore(testRoot)

    expect(store.get()).toEqual(DEFAULT_INPUT_BINDINGS)
  })

  it('persists custom mouse and keyboard bindings', () => {
    const store = new InputBindingStore(testRoot)
    store.update({
      pushToTalk: { mouseButton: 4 },
      keyboard: { openPanel: 'Control+Alt+Y' },
    })

    const restored = new InputBindingStore(testRoot).get()

    expect(restored.pushToTalk.mouseButton).toBe(4)
    expect(restored.keyboard.openPanel).toBe('Control+Alt+Y')
  })

  it('normalizes invalid side buttons and supports disabling keyboard actions', () => {
    fs.mkdirSync(testRoot, { recursive: true })
    fs.writeFileSync(path.join(testRoot, 'input-bindings.json'), JSON.stringify({
      pushToTalk: { enabled: true, mouseButton: 9 },
      keyboard: { interact: '' },
    }))

    const settings = new InputBindingStore(testRoot).get()

    expect(settings.pushToTalk.mouseButton).toBe(5)
    expect(settings.keyboard.interact).toBe('')
  })
})
