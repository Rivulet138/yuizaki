import fs from 'node:fs'
import path from 'node:path'
import { randomUUID } from 'node:crypto'
import { safeStorage } from 'electron'
import type { CredentialEncryptionAdapter } from './provider-credential-store'

const MAX_NAMESPACE = 128
const MAX_DOCUMENT = 1024 * 1024
const MAX_NAMESPACES = 64
const MAX_REFERENCES_PER_NAMESPACE = 256
const MAX_VAULT_FILE_BYTES = 16 * MAX_DOCUMENT
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i
type VaultData = { version: 1; values: Record<string, Record<string, string>> }

const defaultEncryption: CredentialEncryptionAdapter = {
  isAvailable: () => {
    if (process.platform === 'linux') {
      const backend = typeof safeStorage.getSelectedStorageBackend === 'function'
        ? safeStorage.getSelectedStorageBackend()
        : 'unknown'
      if (backend === 'basic_text' || backend === 'unknown') return false
    }
    return safeStorage.isEncryptionAvailable()
  },
  encrypt: (value) => safeStorage.encryptString(value),
  decrypt: (value) => safeStorage.decryptString(value),
}

const validUuid = (value: unknown): value is string => typeof value === 'string' && UUID.test(value)
const validNamespace = (value: unknown): value is string => typeof value === 'string' && value.length > 0 && value.length <= MAX_NAMESPACE
const atomicWrite = (file: string, data: VaultData): void => {
  const tmp = `${file}.${process.pid}.${randomUUID()}.tmp`
  fs.mkdirSync(path.dirname(file), { recursive: true })
  try {
    const serialized = `${JSON.stringify(data)}\n`
    if (Buffer.byteLength(serialized, 'utf8') > MAX_VAULT_FILE_BYTES) throw new Error('vault_too_large')
    fs.writeFileSync(tmp, serialized, { encoding: 'utf8', mode: 0o600 })
    fs.renameSync(tmp, file)
  } catch (error) {
    try { fs.unlinkSync(tmp) } catch { /* best effort */ }
    throw error
  }
}

export class McpConfigVault {
  private readonly file: string
  private readonly encryption: CredentialEncryptionAdapter
  private values: Record<string, Record<string, string>> = {}
  private usable = true

  constructor(storageDir: string, encryption: CredentialEncryptionAdapter = defaultEncryption) {
    this.file = path.join(storageDir, 'mcp-config-vault.json')
    this.encryption = encryption
    this.load()
  }

  isAvailable(): boolean { return this.usable && this.encryption.isAvailable() }

  store(namespace: string, document: string): string {
    this.ensureAvailable(); this.validate(namespace, document)
    const reference = randomUUID()
    const encrypted = this.encryption.encrypt(document).toString('base64')
    if (this.encryption.decrypt(Buffer.from(encrypted, 'base64')) !== document) throw new Error('crypto')
    const next = this.clone(); (next[namespace] ??= {})[reference] = encrypted
    atomicWrite(this.file, { version: 1, values: next }); this.values = next
    return reference
  }

  read(namespace: string, reference: string): string {
    this.ensureAvailable(); this.validateNamespaceRef(namespace, reference)
    const encrypted = this.values[namespace]?.[reference]
    if (!encrypted) throw new Error('missingref')
    return this.encryption.decrypt(Buffer.from(encrypted, 'base64'))
  }

  prune(namespace: string, reference: string): void {
    this.ensureAvailable(); this.validateNamespaceRef(namespace, reference)
    if (!this.values[namespace]?.[reference]) throw new Error('missingref')
    const next = this.clone(); const bucket = next[namespace]
    if (!bucket) throw new Error('missingref')
    delete bucket[reference]
    if (!Object.keys(bucket).length) delete next[namespace]
    atomicWrite(this.file, { version: 1, values: next }); this.values = next
  }

  private clone(): Record<string, Record<string, string>> { return JSON.parse(JSON.stringify(this.values)) as Record<string, Record<string, string>> }
  private ensureAvailable(): void { if (!this.isAvailable()) throw new Error('unavailable') }
  private validateNamespaceRef(namespace: string, reference: string): void { if (!validNamespace(namespace) || !validUuid(reference)) throw new Error('invalid') }
  private validate(namespace: string, document: string): void {
    if (!validNamespace(namespace) || typeof document !== 'string' || Buffer.byteLength(document) > MAX_DOCUMENT) throw new Error('invalid')
    if (!this.values[namespace] && Object.keys(this.values).length >= MAX_NAMESPACES) throw new Error('invalid')
    if (this.values[namespace] && Object.keys(this.values[namespace]).length >= MAX_REFERENCES_PER_NAMESPACE) throw new Error('invalid')
  }

  private load(): void {
    if (!fs.existsSync(this.file)) return
    try {
      if (!this.encryption.isAvailable()) { this.usable = false; return }
      if (fs.statSync(this.file).size > MAX_VAULT_FILE_BYTES) throw new Error('corrupt')
      const parsed = JSON.parse(fs.readFileSync(this.file, 'utf8')) as Partial<VaultData>
      if (parsed.version !== 1 || !parsed.values || typeof parsed.values !== 'object') throw new Error('corrupt')
      const values: Record<string, Record<string, string>> = {}
      if (Object.keys(parsed.values).length > MAX_NAMESPACES) throw new Error('corrupt')
      for (const [namespace, refs] of Object.entries(parsed.values)) {
        if (!validNamespace(namespace) || !refs || typeof refs !== 'object') throw new Error('corrupt')
        if (Object.keys(refs).length > MAX_REFERENCES_PER_NAMESPACE) throw new Error('corrupt')
        values[namespace] = {}
        for (const [reference, encrypted] of Object.entries(refs)) {
          if (!validUuid(reference) || typeof encrypted !== 'string' || !encrypted) throw new Error('corrupt')
          this.encryption.decrypt(Buffer.from(encrypted, 'base64'))
          values[namespace][reference] = encrypted
        }
      }
      this.values = values
    } catch { this.usable = false; this.values = {} }
  }
}

export { MAX_DOCUMENT }
