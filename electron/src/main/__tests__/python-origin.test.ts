import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

describe('resolvePythonApiOrigin', () => {
  const clearBackendEnv = () => {
    delete process.env['DESKTOP_PET_BACKEND_URL']
    delete process.env['SERVER_HOST']
    delete process.env['SERVER_PORT']
  }

  beforeEach(() => {
    clearBackendEnv()
  })

  afterEach(() => {
    clearBackendEnv()
    vi.resetModules()
  })

  it('uses the default internal backend origin', async () => {
    const { resolvePythonApiOrigin } = await import('../http/python-origin')

    expect(resolvePythonApiOrigin()).toBe('http://localhost:8001')
  })

  it('normalizes explicit backend URLs and health URLs', async () => {
    process.env['DESKTOP_PET_BACKEND_URL'] = 'http://10.0.0.2:9000/health'
    const { resolvePythonApiOrigin } = await import('../http/python-origin')

    expect(resolvePythonApiOrigin()).toBe('http://10.0.0.2:9000')
  })

  it('uses host and port overrides when no explicit backend URL is set', async () => {
    process.env['SERVER_HOST'] = '0.0.0.0'
    process.env['SERVER_PORT'] = '8123'
    const { resolvePythonApiOrigin } = await import('../http/python-origin')

    expect(resolvePythonApiOrigin()).toBe('http://0.0.0.0:8123')
  })
})
