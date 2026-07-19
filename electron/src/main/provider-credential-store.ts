import fs from 'node:fs'
import path from 'node:path'
import { safeStorage } from 'electron'

export const SETTINGS_SECRET_MASK = '********'
export const PROVIDER_CREDENTIALS_ENV = 'YUIZAKI_PROVIDER_CREDENTIALS_JSON'

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

  getPythonEnvironment(): Record<string, string> {
    if (!Object.keys(this.values).length) return {}
    return { [PROVIDER_CREDENTIALS_ENV]: JSON.stringify(this.values) }
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
