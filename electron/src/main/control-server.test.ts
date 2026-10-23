import { describe, expect, it } from 'vitest'

import {
  isControlRequestAuthorized,
  isPublicControlPath,
} from './control-server'

type RequestOverrides = {
  method?: string
  origin?: string
  authorization?: string
  controlHeader?: string
  remoteAddress?: string
}

const makeRequest = (overrides: RequestOverrides = {}): Parameters<typeof isControlRequestAuthorized>[0] => ({
  method: overrides.method ?? 'GET',
  headers: {
    ...(overrides.origin ? { origin: overrides.origin } : {}),
    ...(overrides.authorization ? { authorization: overrides.authorization } : {}),
    ...(overrides.controlHeader ? { 'x-yuizaki-backend-token': overrides.controlHeader } : {}),
  },
  socket: { remoteAddress: overrides.remoteAddress ?? '127.0.0.1' },
}) as Parameters<typeof isControlRequestAuthorized>[0]

describe('control-server token helper', () => {
  // The control server no longer enforces this check: it binds to loopback and the
  // Origin allow-list rejects foreign pages, which is the boundary this local app
  // needs. The helper stays exported (and tested) so a caller that still wants to
  // prove token possession can, and so a stricter mode could be restored in one line.
  const token = 'control-secret'

  it('rejects a no-Origin request without a token', () => {
    expect(isControlRequestAuthorized(makeRequest(), new URL('http://localhost/api/ping'), token)).toBe(false)
  })

  it('rejects a wrong bearer token', () => {
    expect(isControlRequestAuthorized(
      makeRequest({ authorization: 'Bearer wrong-token' }),
      new URL('http://localhost/api/ping'),
      token,
    )).toBe(false)
  })

  it('accepts the expected bearer token without an Origin header', () => {
    expect(isControlRequestAuthorized(
      makeRequest({ authorization: `Bearer ${token}` }),
      new URL('http://localhost/api/ping'),
      token,
    )).toBe(true)
  })

  it('accepts the legacy query bootstrap token only for local no-Origin GETs', () => {
    expect(isControlRequestAuthorized(
      makeRequest(),
      new URL(`http://localhost/api/ping?control_token=${token}`),
      token,
    )).toBe(true)
    expect(isControlRequestAuthorized(
      makeRequest({ origin: 'http://localhost:38945' }),
      new URL(`http://localhost/api/ping?control_token=${token}`),
      token,
    )).toBe(false)
    expect(isControlRequestAuthorized(
      makeRequest({ method: 'POST' }),
      new URL(`http://localhost/api/ping?control_token=${token}`),
      token,
    )).toBe(false)
  })

  it('accepts the existing backend token header', () => {
    expect(isControlRequestAuthorized(
      makeRequest({ controlHeader: token }),
      new URL('http://localhost/api/ping'),
      token,
    )).toBe(true)
  })
})

describe('control-server public routes', () => {
  it('keeps health and pet assets public while protecting other API paths', () => {
    expect(isPublicControlPath('GET', '/health', false)).toBe(true)
    expect(isPublicControlPath('GET', '/api/health', false)).toBe(true)
    expect(isPublicControlPath('GET', '/api/pet/assets/live2d/model.json', true)).toBe(true)
    expect(isPublicControlPath('POST', '/api/health', false)).toBe(false)
    expect(isPublicControlPath('GET', '/api/ping', false)).toBe(false)
  })
})
