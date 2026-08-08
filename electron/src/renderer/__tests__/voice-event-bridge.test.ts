import { describe, expect, it, vi } from 'vitest'
import { VoiceEventBridge } from '../app/runtime/voiceEventBridge'

class EventHost {
  readonly added: Array<[string, EventListener]> = []
  readonly removed: Array<[string, EventListener]> = []

  addEventListener(type: string, listener: EventListener): void {
    this.added.push([type, listener])
  }

  removeEventListener(type: string, listener: EventListener): void {
    this.removed.push([type, listener])
  }
}

class ShortcutHost {
  readonly added: Array<[string, (...args: any[]) => void]> = []
  readonly removed: Array<[string, (...args: any[]) => void]> = []

  on(event: string, handler: (...args: any[]) => void): void {
    this.added.push([event, handler])
  }

  off(event: string, handler: (...args: any[]) => void): void {
    this.removed.push([event, handler])
  }
}

const createHandlers = () => ({
  onLlmControl: vi.fn() as unknown as EventListener,
  onAudioStarted: vi.fn() as unknown as EventListener,
  onAudioEnded: vi.fn() as unknown as EventListener,
  onTtsStop: vi.fn() as unknown as EventListener,
  onRealtimeInterrupt: vi.fn() as unknown as EventListener,
  onStartMic: vi.fn(),
  onStopMic: vi.fn(),
  onToggleMic: vi.fn(),
})

describe('VoiceEventBridge', () => {
  it('binds the DOM and shortcut events once and removes exact handler identities', () => {
    const eventHost = new EventHost()
    const shortcutHost = new ShortcutHost()
    const handlers = createHandlers()
    const bridge = new VoiceEventBridge(handlers)

    bridge.attach(eventHost, shortcutHost)
    bridge.attach(eventHost, shortcutHost)
    expect(eventHost.added).toHaveLength(5)
    expect(shortcutHost.added).toHaveLength(3)

    bridge.detach()
    expect(eventHost.removed).toEqual(eventHost.added)
    expect(shortcutHost.removed).toEqual(shortcutHost.added)
  })

  it('detaches the previous hosts before reattaching to a replacement host', () => {
    const firstEventHost = new EventHost()
    const firstShortcutHost = new ShortcutHost()
    const secondEventHost = new EventHost()
    const secondShortcutHost = new ShortcutHost()
    const bridge = new VoiceEventBridge(createHandlers())

    bridge.attach(firstEventHost, firstShortcutHost)
    bridge.attach(secondEventHost, secondShortcutHost)

    expect(firstEventHost.removed).toHaveLength(5)
    expect(firstShortcutHost.removed).toHaveLength(3)
    expect(secondEventHost.added).toHaveLength(5)
    expect(secondShortcutHost.added).toHaveLength(3)
  })
})
