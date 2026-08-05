import { describe, expect, it, vi } from 'vitest'

import {
  assertE2ERequest,
  buildE2EActivation,
  E2E_IPC_CHANNELS,
  registerE2EActivationHandshake,
  type E2ERequestEvent,
} from '../e2e-test-mode'

describe('E2E test mode security isolation', () => {
  it.each([
    [{ YUIZAKI_E2E: '0', YUIZAKI_E2E_TOKEN: 'token' }, false, false],
    [{ YUIZAKI_E2E: '1', YUIZAKI_E2E_TOKEN: '' }, false, false],
    [{ YUIZAKI_E2E: '1', YUIZAKI_E2E_TOKEN: 'token' }, true, false],
  ])('requires exact flag, unpackaged app, and non-empty token', (env, packaged, expected) => {
    expect(buildE2EActivation(env, packaged).active).toBe(expected)
  })

  it('keeps all E2E controls bounded and excludes arbitrary shell/file/eval channels', () => {
    expect(E2E_IPC_CHANNELS).toContain('e2e:voice-sequence')
    expect(E2E_IPC_CHANNELS.some((channel) => /shell|file|eval|execute/i.test(channel))).toBe(false)
  })

  it('rejects wrong token, sender, origin, inactive, and packaged requests', () => {
    const expectedSender = { getURL: () => 'yuizaki://renderer/index.html' }
    const otherSender = { getURL: () => 'yuizaki://renderer/index.html' }
    const event = (sender = expectedSender, url = 'yuizaki://renderer/index.html'): E2ERequestEvent => ({
      sender,
      senderFrame: { url },
    })
    const trusted = vi.fn((url: string) => url === 'yuizaki://renderer/index.html')
    const active = buildE2EActivation({ YUIZAKI_E2E: '1', YUIZAKI_E2E_TOKEN: 'secret' }, false)

    expect(() => assertE2ERequest(active, event(), 'secret', 'proof', 'proof', expectedSender, trusted)).not.toThrow()
    expect(() => assertE2ERequest(active, event(), 'wrong', 'proof', 'proof', expectedSender, trusted)).toThrow(/token/i)
    expect(() => assertE2ERequest(active, event(), 'secret', 'wrong', 'proof', expectedSender, trusted)).toThrow(/proof/i)
    expect(() => assertE2ERequest(active, event(otherSender), 'secret', 'proof', 'proof', expectedSender, trusted)).toThrow(/sender/i)
    expect(() => assertE2ERequest(active, event(expectedSender, 'https://evil.test'), 'secret', 'proof', 'proof', expectedSender, trusted)).toThrow(/origin/i)
    expect(() => assertE2ERequest(buildE2EActivation({}, false), event(), '', '', null, expectedSender, trusted)).toThrow(/inactive/i)
    expect(() => assertE2ERequest(buildE2EActivation({ YUIZAKI_E2E: '1', YUIZAKI_E2E_TOKEN: 'secret' }, true), event(), 'secret', 'proof', 'proof', expectedSender, trusted)).toThrow(/inactive/i)
  })

  it('issues one proof only to the exact panel sender and removes the handler on cleanup', () => {
    const listeners = new Map<string, (...args: any[]) => void>()
    const ipcMain = {
      on: vi.fn((channel: string, listener: (...args: any[]) => void) => listeners.set(channel, listener)),
      removeListener: vi.fn((channel: string, listener: (...args: any[]) => void) => {
        if (listeners.get(channel) === listener) listeners.delete(channel)
      }),
    }
    const expectedSender = {}
    const proofState = { value: null as string | null }
    const dispose = registerE2EActivationHandshake({
      ipcMain: ipcMain as never,
      activation: buildE2EActivation({ YUIZAKI_E2E: '1', YUIZAKI_E2E_TOKEN: 'secret' }, false),
      expectedSender: expectedSender as never,
      apiOrigin: 'http://127.0.0.1:1',
      activationProof: proofState,
    })
    const activate = listeners.get('e2e:activate')!
    const request = (sender: unknown, token: string) => {
      let value: unknown
      let writes = 0
      const event = { sender } as { sender: unknown; returnValue: unknown }
      Object.defineProperty(event, 'returnValue', {
        get: () => value,
        set: (next: unknown) => {
          writes += 1
          value = next
        },
      })
      activate(event, token)
      return { value, writes }
    }

    expect(request(expectedSender, 'wrong')).toEqual({ value: null, writes: 1 })
    expect(request({}, 'secret')).toEqual({ value: null, writes: 1 })
    const activation = request(expectedSender, 'secret')
    expect(activation.writes).toBe(1)
    const proof = activation.value as { proof: string }
    expect(proof.proof).toMatch(/^[0-9a-f-]{36}$/)
    expect(proofState.value).toBe(proof.proof)
    expect(request(expectedSender, 'secret')).toEqual({ value: null, writes: 1 })
    dispose()
    expect(listeners.has('e2e:activate')).toBe(false)
    expect(proofState.value).toBeNull()
  })
})
