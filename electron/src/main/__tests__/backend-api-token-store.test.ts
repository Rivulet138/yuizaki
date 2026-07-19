import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { afterEach, describe, expect, it } from 'vitest'

import { BackendApiTokenStore } from '../backend-api-token-store'

const ORIGINAL_ENV = {
  YUIZAKI_BACKEND_API_TOKEN: process.env['YUIZAKI_BACKEND_API_TOKEN'],
  YUIZAKI_CONTROL_TOKEN: process.env['YUIZAKI_CONTROL_TOKEN'],
}

const restoreEnv = () => {
  for (const [key, value] of Object.entries(ORIGINAL_ENV)) {
    if (value === undefined) {
      delete process.env[key]
    } else {
      process.env[key] = value
    }
  }
}

const clearTokenEnv = () => {
  delete process.env['YUIZAKI_BACKEND_API_TOKEN']
  delete process.env['YUIZAKI_CONTROL_TOKEN']
}

const createStorageDir = () => fs.mkdtempSync(path.join(os.tmpdir(), 'yuizaki-backend-token-'))

const readStoredToken = (storageDir: string) =>
  fs.readFileSync(path.join(storageDir, 'backend-api-token'), 'utf8').trim()

describe('BackendApiTokenStore', () => {
  afterEach(() => {
    restoreEnv()
  })

  it('generates a token once and reloads it from storage', () => {
    clearTokenEnv()
    const storageDir = createStorageDir()

    try {
      const store = new BackendApiTokenStore(storageDir)
      const token = store.getBackendApiToken()

      expect(token).toHaveLength(43)
      expect(readStoredToken(storageDir)).toBe(token)
      expect(store.getBackendApiTokenStatus()).toEqual(expect.objectContaining({
        hasToken: true,
        source: 'generated',
        requiresRestart: false,
      }))
      expect(JSON.stringify(store.getBackendApiTokenStatus())).not.toContain(token)

      const reloaded = new BackendApiTokenStore(storageDir)
      expect(reloaded.getBackendApiToken()).toBe(token)
      expect(reloaded.getBackendApiTokenStatus().source).toBe('stored')
    } finally {
      fs.rmSync(storageDir, { recursive: true, force: true })
    }
  })

  it('uses an environment token and persists it for later launches', () => {
    clearTokenEnv()
    process.env['YUIZAKI_BACKEND_API_TOKEN'] = 'env-backend-token-123456'
    const storageDir = createStorageDir()

    try {
      const store = new BackendApiTokenStore(storageDir)

      expect(store.getBackendApiToken()).toBe('env-backend-token-123456')
      expect(readStoredToken(storageDir)).toBe('env-backend-token-123456')
      expect(store.getBackendApiTokenStatus()).toEqual(expect.objectContaining({
        hasToken: true,
        source: 'environment',
        requiresRestart: false,
      }))
      expect(JSON.stringify(store.getBackendApiTokenStatus())).not.toContain('env-backend-token-123456')
    } finally {
      fs.rmSync(storageDir, { recursive: true, force: true })
    }
  })

  it('saves a new token without replacing the active runtime token until reload', () => {
    clearTokenEnv()
    const storageDir = createStorageDir()

    try {
      const store = new BackendApiTokenStore(storageDir)
      const activeToken = store.getBackendApiToken()
      const result = store.setBackendApiToken(' manual-backend-token-123456 ')

      expect(result).toEqual(expect.objectContaining({
        ok: true,
        hasToken: true,
        source: 'stored',
        requiresRestart: true,
      }))
      expect(result.tokenPreview).not.toBe('manual-backend-token-123456')
      expect(store.getBackendApiToken()).toBe(activeToken)
      expect(readStoredToken(storageDir)).toBe('manual-backend-token-123456')
      expect(store.getBackendApiTokenStatus()).toEqual(expect.objectContaining({
        requiresRestart: true,
        storedTokenPreview: result.tokenPreview,
      }))

      const reloaded = new BackendApiTokenStore(storageDir)
      expect(reloaded.getBackendApiToken()).toBe('manual-backend-token-123456')
      expect(reloaded.getBackendApiTokenStatus().source).toBe('stored')
    } finally {
      fs.rmSync(storageDir, { recursive: true, force: true })
    }
  })

  it('resets to a generated stored token for the next launch', () => {
    clearTokenEnv()
    const storageDir = createStorageDir()

    try {
      const store = new BackendApiTokenStore(storageDir)
      const activeToken = store.getBackendApiToken()
      const result = store.resetBackendApiToken()
      const nextToken = readStoredToken(storageDir)

      expect(result).toEqual(expect.objectContaining({
        ok: true,
        hasToken: true,
        source: 'generated',
        requiresRestart: true,
      }))
      expect(nextToken).toHaveLength(43)
      expect(nextToken).not.toBe(activeToken)
      expect(store.getBackendApiToken()).toBe(activeToken)

      const reloaded = new BackendApiTokenStore(storageDir)
      expect(reloaded.getBackendApiToken()).toBe(nextToken)
      expect(reloaded.getBackendApiTokenStatus().source).toBe('stored')
    } finally {
      fs.rmSync(storageDir, { recursive: true, force: true })
    }
  })

  it('rejects empty tokens', () => {
    clearTokenEnv()
    const storageDir = createStorageDir()

    try {
      const store = new BackendApiTokenStore(storageDir)
      expect(() => store.setBackendApiToken('   ')).toThrow('Backend API token cannot be empty')
    } finally {
      fs.rmSync(storageDir, { recursive: true, force: true })
    }
  })
})
