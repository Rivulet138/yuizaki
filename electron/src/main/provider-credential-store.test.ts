import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { afterEach, describe, expect, it } from 'vitest'
import { ProviderCredentialStore, type CredentialEncryptionAdapter, credentialConfigUpdates, PROVIDER_CREDENTIALS_ENV } from './provider-credential-store'

const roots: string[] = []

const adapter: CredentialEncryptionAdapter = {
  isAvailable: () => true,
  encrypt: (value) => Buffer.from(value, 'utf8').reverse(),
  decrypt: (value) => Buffer.from(value).reverse().toString('utf8'),
}

afterEach(() => {
  while (roots.length) fs.rmSync(roots.pop()!, { recursive: true, force: true })
})

describe('ProviderCredentialStore', () => {
  it('maps vault connector and Twitch values to existing config contracts', () => {
    const updates = credentialConfigUpdates({
      YUIZAKI_TELEGRAM_BOT_TOKEN: 'telegram-secret',
      YUIZAKI_TWITCH_CLIENT_ID: 'twitch-client',
    })
    const telegram = updates.find((item) => item.path.endsWith('/telegram/config'))!
    const twitch = updates.find((item) => item.path.endsWith('/twitch/config'))!
    expect(telegram.body).toMatchObject({ botToken: 'telegram-secret', clearWebhookSecret: true })
    expect(twitch.body).toMatchObject({ clientId: 'twitch-client', clearEventsubSecret: true })
  })

  it('persists LLM credentials outside settings and restores them for Python', () => {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), 'yuizaki-provider-credentials-'))
    roots.push(root)
    const store = new ProviderCredentialStore(root, adapter)

    expect(store.captureSettingsPayload({ llm: { api_key: 'sk-persisted' } })).toBe(1)
    const persisted = fs.readFileSync(path.join(root, 'provider-credentials.json'), 'utf8')

    expect(persisted).not.toContain('sk-persisted')
    expect(new ProviderCredentialStore(root, adapter).getAll()).toEqual({ 'llm.api_key': 'sk-persisted' })
    expect(JSON.parse(store.getPythonEnvironment()[PROVIDER_CREDENTIALS_ENV]!)).toEqual({ 'llm.api_key': 'sk-persisted' })
  })

  it('keeps an existing credential when the settings payload contains its mask', () => {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), 'yuizaki-provider-credentials-'))
    roots.push(root)
    const store = new ProviderCredentialStore(root, adapter)

    store.captureSettingsPayload({ llm: { api_key: 'sk-persisted' } })
    expect(store.captureSettingsPayload({ llm: { api_key: '********' } })).toBe(0)
    expect(store.getAll()['llm.api_key']).toBe('sk-persisted')
  })

  it('keeps an existing credential when a partial settings save contains an empty key', () => {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), 'yuizaki-provider-credentials-'))
    roots.push(root)
    const store = new ProviderCredentialStore(root, adapter)

    store.captureSettingsPayload({ llm: { api_key: 'sk-persisted' } })
    expect(store.captureSettingsPayload({ llm: { api_key: '' } })).toBe(0)
    expect(store.getAll()['llm.api_key']).toBe('sk-persisted')
  })

  it('does not forward arbitrary encrypted fields through the provider environment', () => {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), 'yuizaki-provider-credentials-'))
    roots.push(root)
    const store = new ProviderCredentialStore(root, adapter)

    expect(store.captureSettingValue('llm.model', 'attacker-model')).toBe(false)
    expect(store.captureSettingValue('other.api_key', 'ignored')).toBe(true)
    expect(store.captureSettingValue('llm.api_key', 'sk-valid')).toBe(true)

    expect(JSON.parse(store.getPythonEnvironment()[PROVIDER_CREDENTIALS_ENV]!)).toEqual({ 'llm.api_key': 'sk-valid' })
  })

  it('does not persist nested LLM profile credentials', () => {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), 'yuizaki-provider-credentials-'))
    roots.push(root)
    const store = new ProviderCredentialStore(root, adapter)

    expect(store.captureSettingsPayload({
      llm: {
        api_key: 'top-level-secret',
        profiles: { openai: { api_key: 'profile-secret' } },
      },
    })).toBe(1)

    expect(store.getAll()).toEqual({ 'llm.api_key': 'top-level-secret' })
    expect(store.captureSettingValue('llm.profiles.openai.api_key', 'another-secret')).toBe(false)
    expect(JSON.parse(store.getPythonEnvironment()[PROVIDER_CREDENTIALS_ENV]!)).toEqual({ 'llm.api_key': 'top-level-secret' })
  })

  it('scrubs nested LLM profile credentials during plaintext migration', () => {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), 'yuizaki-provider-credentials-'))
    roots.push(root)
    const settingsPath = path.join(root, 'settings.json')
    fs.writeFileSync(settingsPath, JSON.stringify({
      llm: { profiles: { openai: { api_key: 'profile-secret' } } },
    }))
    const store = new ProviderCredentialStore(root, adapter)

    expect(store.migratePlaintextSettings(settingsPath)).toEqual({ migrated: 0, scrubbed: true })
    expect(JSON.parse(fs.readFileSync(settingsPath, 'utf8'))).toEqual({
      llm: { profiles: { openai: { api_key: '' } } },
    })
    expect(store.getAll()).toEqual({})
  })

  it('clears legacy nested LLM profile credentials with the top-level key', () => {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), 'yuizaki-provider-credentials-'))
    roots.push(root)
    const encrypt = (value: string) => Buffer.from(value, 'utf8').reverse().toString('base64')
    fs.writeFileSync(path.join(root, 'provider-credentials.json'), JSON.stringify({
      version: 1,
      values: {
        'llm.api_key': encrypt('top-level-secret'),
        'llm.profiles.openai.api_key': encrypt('legacy-secret'),
      },
    }))

    const store = new ProviderCredentialStore(root, adapter)
    expect(store.getAll()).toEqual({
      'llm.api_key': 'top-level-secret',
      'llm.profiles.openai.api_key': 'legacy-secret',
    })
    expect(store.delete('llm.api_key')).toBe(true)
    expect(store.getAll()).toEqual({})
    expect(new ProviderCredentialStore(root, adapter).getAll()).toEqual({})
  })
})
