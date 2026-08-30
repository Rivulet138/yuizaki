import fs from 'node:fs'
import path from 'node:path'
import { safeStorage } from 'electron'

export const SETTINGS_SECRET_MASK = '********'
export const PROVIDER_CREDENTIALS_ENV = 'YUIZAKI_PROVIDER_CREDENTIALS_JSON'

const CONNECTOR_CREDENTIALS: Record<string, Record<string, string>> = {
  telegram: {
    botToken: 'YUIZAKI_TELEGRAM_BOT_TOKEN',
    webhookSecret: 'YUIZAKI_TELEGRAM_WEBHOOK_SECRET',
  },
  discord: {
    botToken: 'YUIZAKI_DISCORD_BOT_TOKEN',
    publicKey: 'YUIZAKI_DISCORD_PUBLIC_KEY',
  },
  qq: { bridgeToken: 'YUIZAKI_QQ_BRIDGE_TOKEN' },
  wechat: { bridgeToken: 'YUIZAKI_WECHAT_BRIDGE_TOKEN' },
}

const TWITCH_CREDENTIALS: Record<string, string> = {
  clientId: 'YUIZAKI_TWITCH_CLIENT_ID',
  eventsubSecret: 'YUIZAKI_TWITCH_EVENTSUB_SECRET',
  eventsubToken: 'YUIZAKI_TWITCH_EVENTSUB_TOKEN',
  chatToken: 'YUIZAKI_TWITCH_CHAT_TOKEN',
  broadcasterId: 'YUIZAKI_TWITCH_BROADCASTER_ID',
  senderId: 'YUIZAKI_TWITCH_SENDER_ID',
  moderatorId: 'YUIZAKI_TWITCH_MODERATOR_ID',
  channel: 'YUIZAKI_TWITCH_CHANNEL',
  username: 'YUIZAKI_TWITCH_USERNAME',
  eventsubCallbackUrl: 'YUIZAKI_TWITCH_EVENTSUB_CALLBACK_URL',
  subscriptionProvider: 'YUIZAKI_TWITCH_SUBSCRIPTION_PROVIDER',
}

const TWITCH_CREDENTIAL_FIELDS = new Set(Object.keys(TWITCH_CREDENTIALS))

const CONNECTOR_SECRET_FIELDS = new Set(['botToken', 'webhookSecret', 'publicKey', 'bridgeToken'])
const CONNECTOR_PLAINTEXT_SECRET_FIELDS = new Set([
  'botToken',
  'webhookSecret',
  'publicKey',
  'bridgeToken',
  'appId',
  'appSecret',
  'apiKey',
])

const SECRET_FIELD_NAMES = new Set([
  'api_key',
  'vision_api_key',
  'qdrant_api_key',
])

interface CredentialFile {
  version: 1
  values: Record<string, string>
}

export interface CredentialEncryptionAdapter {
  isAvailable: () => boolean
  encrypt: (value: string) => Buffer
  decrypt: (value: Buffer) => string
}

export interface CredentialMigrationResult {
  migrated: number
  scrubbed: boolean
}

const electronEncryptionAdapter: CredentialEncryptionAdapter = {
  isAvailable: () => safeStorage.isEncryptionAvailable(),
  encrypt: (value) => safeStorage.encryptString(value),
  decrypt: (value) => safeStorage.decryptString(value),
}

const isRecord = (value: unknown): value is Record<string, unknown> =>
  Boolean(value) && typeof value === 'object' && !Array.isArray(value)

const writeJsonAtomic = (filePath: string, value: unknown): void => {
  fs.mkdirSync(path.dirname(filePath), { recursive: true })
  const tempPath = `${filePath}.${process.pid}.tmp`
  fs.writeFileSync(tempPath, `${JSON.stringify(value, null, 2)}\n`, { encoding: 'utf8', mode: 0o600 })
  fs.renameSync(tempPath, filePath)
}

const visitSecretFields = (
  value: unknown,
  visitor: (path: string, value: string, owner: Record<string, unknown>, key: string) => void,
  prefix = '',
): void => {
  if (!isRecord(value)) return
  for (const [key, child] of Object.entries(value)) {
    const fieldPath = prefix ? `${prefix}.${key}` : key
    if (SECRET_FIELD_NAMES.has(key) && typeof child === 'string') {
      visitor(fieldPath, child, value, key)
      continue
    }
    visitSecretFields(child, visitor, fieldPath)
  }
}

export class ProviderCredentialStore {
  private readonly storagePath: string
  private readonly encryption: CredentialEncryptionAdapter
  private values: Record<string, string> = {}

  constructor(storageDir: string, encryption: CredentialEncryptionAdapter = electronEncryptionAdapter) {
    this.storagePath = path.join(storageDir, 'provider-credentials.json')
    this.encryption = encryption
    this.values = this.load()
  }

  getAll(): Record<string, string> {
    return { ...this.values }
  }

  isSecureStorageAvailable(): boolean {
    return this.encryption.isAvailable()
  }

  getPythonEnvironment(): Record<string, string> {
    const environment: Record<string, string> = {}
    const providerValues = Object.fromEntries(
      Object.entries(this.values).filter(([fieldPath]) => !fieldPath.startsWith('connector.')),
    )
    if (Object.keys(providerValues).length) {
      environment[PROVIDER_CREDENTIALS_ENV] = JSON.stringify(providerValues)
    }
    for (const [fieldPath, value] of Object.entries(this.values)) {
      const match = /^connector\.([a-z]+)\.([a-zA-Z]+)$/.exec(fieldPath)
      const envName = match?.[1] && match[2] ? CONNECTOR_CREDENTIALS[match[1]]?.[match[2]] : undefined
      if (envName && value) environment[envName] = value
    }
    for (const [field, envName] of Object.entries(TWITCH_CREDENTIALS)) {
      const value = this.values[`twitch.${field}`]
      if (value) environment[envName] = value
    }
    return environment
  }

  captureTwitchCredentials(payload: unknown): number {
    if (!isRecord(payload)) return 0
    let changed = 0
    for (const field of TWITCH_CREDENTIAL_FIELDS) {
      const pathKey = `twitch.${field}`
      const clearKey = `clear${field.charAt(0).toUpperCase()}${field.slice(1)}`
      if (payload[clearKey] === true) {
        if (pathKey in this.values) {
          delete this.values[pathKey]
          changed += 1
        }
        continue
      }
      const value = payload[field]
      if (typeof value !== 'string') continue
      const clean = value.trim()
      if (!clean) continue
      if (this.values[pathKey] !== clean) {
        this.values[pathKey] = clean
        changed += 1
      }
    }
    if (changed) this.save()
    return changed
  }

  getTwitchCredentials(): Record<string, string> {
    return Object.fromEntries(
      [...TWITCH_CREDENTIAL_FIELDS]
        .map((field) => [field, this.values[`twitch.${field}`]] as const)
        .filter((entry): entry is readonly [string, string] => Boolean(entry[1])),
    )
  }

  getTwitchCredentialStatus(): { secureStorageAvailable: boolean; configured: Record<string, boolean>; subscriptionProvider: string } {
    const values = this.getTwitchCredentials()
    return {
      secureStorageAvailable: this.isSecureStorageAvailable(),
      configured: Object.fromEntries([...TWITCH_CREDENTIAL_FIELDS].map((field) => [field, Boolean(values[field])])),
      subscriptionProvider: values['subscriptionProvider'] || 'none',
    }
  }

  captureConnectorCredentials(connectorId: string, payload: unknown): number {
    const fields = CONNECTOR_CREDENTIALS[connectorId]
    if (!fields || !isRecord(payload)) return 0
    let changed = 0
    for (const field of CONNECTOR_SECRET_FIELDS) {
      if (!(field in fields)) continue
      const pathKey = `connector.${connectorId}.${field}`
      const clearKey = `clear${field.charAt(0).toUpperCase()}${field.slice(1)}`
      if (payload[clearKey] === true) {
        if (pathKey in this.values) {
          delete this.values[pathKey]
          changed += 1
        }
        continue
      }
      const value = payload[field]
      if (typeof value !== 'string') continue
      const clean = value.trim()
      if (!clean) continue
      if (this.values[pathKey] !== clean) {
        this.values[pathKey] = clean
        changed += 1
      }
    }
    if (changed) this.save()
    return changed
  }

  captureSettingsPayload(payload: unknown): number {
    let changed = 0
    visitSecretFields(payload, (fieldPath, value) => {
      if (value === SETTINGS_SECRET_MASK) return
      const clean = value.trim()
      if (clean) {
        if (this.values[fieldPath] !== clean) {
          this.values[fieldPath] = clean
          changed += 1
        }
      } else if (fieldPath in this.values) {
        delete this.values[fieldPath]
        changed += 1
      }
    })
    if (changed) this.save()
    return changed
  }

  captureSettingValue(fieldPath: string, value: unknown): boolean {
    const fieldParts = fieldPath.split('.')
    const fieldName = fieldParts[fieldParts.length - 1] ?? ''
    if (!SECRET_FIELD_NAMES.has(fieldName) || typeof value !== 'string' || value === SETTINGS_SECRET_MASK) {
      return false
    }
    const clean = value.trim()
    if (clean) {
      if (this.values[fieldPath] === clean) return false
      this.values[fieldPath] = clean
    } else {
      if (!(fieldPath in this.values)) return false
      delete this.values[fieldPath]
    }
    this.save()
    return true
  }

  delete(fieldPath: string): boolean {
    if (!(fieldPath in this.values)) return false
    delete this.values[fieldPath]
    this.save()
    return true
  }

  migratePlaintextSettings(settingsPath: string): CredentialMigrationResult {
    if (!fs.existsSync(settingsPath)) return { migrated: 0, scrubbed: false }
    const payload = JSON.parse(fs.readFileSync(settingsPath, 'utf8')) as unknown
    let migrated = 0
    let scrubbed = false
    visitSecretFields(payload, (fieldPath, value, owner, key) => {
      const clean = value.trim()
      if (clean && clean !== SETTINGS_SECRET_MASK) {
        if (this.values[fieldPath] !== clean) {
          this.values[fieldPath] = clean
          migrated += 1
        }
        owner[key] = ''
        scrubbed = true
      } else if (value === SETTINGS_SECRET_MASK) {
        owner[key] = ''
        scrubbed = true
      }
    })
    if (migrated) this.save()
    if (scrubbed) writeJsonAtomic(settingsPath, payload)
    return { migrated, scrubbed }
  }

  migratePlaintextConnectorState(statePath: string): CredentialMigrationResult {
    if (!fs.existsSync(statePath)) return { migrated: 0, scrubbed: false }
    const payload = JSON.parse(fs.readFileSync(statePath, 'utf8')) as unknown
    const connectors = isRecord(payload) && isRecord(payload['connectors']) ? payload['connectors'] : null
    if (!connectors) return { migrated: 0, scrubbed: false }
    let migrated = 0
    let scrubbed = false
    for (const [connectorId, rawConnector] of Object.entries(connectors)) {
      if (!isRecord(rawConnector) || !CONNECTOR_CREDENTIALS[connectorId]) continue
      for (const [field, rawValue] of Object.entries(rawConnector)) {
        if (!CONNECTOR_PLAINTEXT_SECRET_FIELDS.has(field) || typeof rawValue !== 'string') continue
        const value = rawValue
        const pathKey = `connector.${connectorId}.${field}`
        const clean = value.trim()
        const mappedField = CONNECTOR_CREDENTIALS[connectorId][field]
        if (mappedField && clean && clean !== SETTINGS_SECRET_MASK) {
          if (this.values[pathKey] !== clean) {
            this.values[pathKey] = clean
            migrated += 1
          }
        }
        rawConnector[field] = ''
        scrubbed = true
      }
    }
    if (migrated) this.save()
    if (scrubbed) writeJsonAtomic(statePath, payload)
    return { migrated, scrubbed }
  }

  private load(): Record<string, string> {
    if (!fs.existsSync(this.storagePath)) return {}
    if (!this.encryption.isAvailable()) {
      throw new Error('Operating-system credential encryption is unavailable')
    }
    const payload = JSON.parse(fs.readFileSync(this.storagePath, 'utf8')) as CredentialFile
    const result: Record<string, string> = {}
    for (const [fieldPath, encrypted] of Object.entries(payload.values || {})) {
      try {
        result[fieldPath] = this.encryption.decrypt(Buffer.from(encrypted, 'base64'))
      } catch {
        // Ignore a single damaged credential without exposing or discarding the rest.
      }
    }
    return result
  }

  private save(): void {
    if (!this.encryption.isAvailable()) {
      throw new Error('Operating-system credential encryption is unavailable')
    }
    const values = Object.fromEntries(
      Object.entries(this.values).map(([fieldPath, value]) => [
        fieldPath,
        this.encryption.encrypt(value).toString('base64'),
      ]),
    )
    writeJsonAtomic(this.storagePath, { version: 1, values } satisfies CredentialFile)
  }
}
