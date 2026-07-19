import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { describe, expect, it } from 'vitest'

import {
  PROVIDER_CREDENTIALS_ENV,
  ProviderCredentialStore,
  type CredentialEncryptionAdapter,
} from '../provider-credential-store'

const testEncryption: CredentialEncryptionAdapter = {
  isAvailable: () => true,
  encrypt: (value) => Buffer.from(`encrypted:${value}`, 'utf8'),
  decrypt: (value) => value.toString('utf8').replace(/^encrypted:/, ''),
}

const createStorageDir = () => fs.mkdtempSync(path.join(os.tmpdir(), 'yuizaki-provider-credentials-'))

describe('ProviderCredentialStore', () => {
  it('encrypts captured credentials and rehydrates the Python environment', () => {
    const storageDir = createStorageDir()
    try {
      const store = new ProviderCredentialStore(storageDir, testEncryption)
      expect(store.captureSettingsPayload({
        llm: {
          api_key: 'deepseek-secret',
          profiles: { claude: { api_key: 'claude-secret' } },
        },
      })).toBe(2)

      const persisted = fs.readFileSync(path.join(storageDir, 'provider-credentials.json'), 'utf8')
      expect(persisted).not.toContain('deepseek-secret')
      expect(persisted).not.toContain('claude-secret')

      const reloaded = new ProviderCredentialStore(storageDir, testEncryption)
      const environment = reloaded.getPythonEnvironment()
      expect(JSON.parse(environment[PROVIDER_CREDENTIALS_ENV] ?? '{}')).toEqual({
        'llm.api_key': 'deepseek-secret',
        'llm.profiles.claude.api_key': 'claude-secret',
      })
    } finally {
      fs.rmSync(storageDir, { recursive: true, force: true })
    }
  })

  it('migrates plaintext settings and scrubs the original file', () => {
    const storageDir = createStorageDir()
    const settingsPath = path.join(storageDir, 'settings.json')
    fs.writeFileSync(settingsPath, JSON.stringify({
      llm: { api_key: 'legacy-secret', vision_api_key: 'vision-secret' },
      memory: { qdrant_api_key: 'qdrant-secret' },
    }))

    try {
      const store = new ProviderCredentialStore(path.join(storageDir, 'credentials'), testEncryption)
      expect(store.migratePlaintextSettings(settingsPath)).toEqual({ migrated: 3, scrubbed: true })

      const scrubbed = fs.readFileSync(settingsPath, 'utf8')
      expect(scrubbed).not.toContain('legacy-secret')
      expect(scrubbed).not.toContain('vision-secret')
      expect(scrubbed).not.toContain('qdrant-secret')
      expect(JSON.parse(scrubbed)).toEqual({
        llm: { api_key: '', vision_api_key: '' },
        memory: { qdrant_api_key: '' },
      })
      expect(store.getAll()).toEqual({
        'llm.api_key': 'legacy-secret',
        'llm.vision_api_key': 'vision-secret',
        'memory.qdrant_api_key': 'qdrant-secret',
      })
    } finally {
      fs.rmSync(storageDir, { recursive: true, force: true })
    }
  })

  it('only captures direct values for recognized credential fields', () => {
    const storageDir = createStorageDir()
    try {
      const store = new ProviderCredentialStore(storageDir, testEncryption)
      expect(store.captureSettingValue('llm.api_key', 'direct-secret')).toBe(true)
      expect(store.captureSettingValue('api_key', 'temporary-model-list-key')).toBe(true)
      expect(store.captureSettingValue('llm.model', 'not-a-secret')).toBe(false)
      expect(store.captureSettingValue('llm.api_key', '********')).toBe(false)
      expect(store.getAll()).toEqual({
        'llm.api_key': 'direct-secret',
        api_key: 'temporary-model-list-key',
      })
    } finally {
      fs.rmSync(storageDir, { recursive: true, force: true })
    }
  })
})
