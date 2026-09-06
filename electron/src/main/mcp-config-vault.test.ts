import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { afterEach, describe, expect, it } from 'vitest'
import { McpConfigVault } from './mcp-config-vault'
import type { CredentialEncryptionAdapter } from './provider-credential-store'

const roots: string[] = []
const makeRoot = () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'yuizaki-mcp-vault-'))
  roots.push(root)
  return root
}

const adapter = (): CredentialEncryptionAdapter => ({
  isAvailable: () => true,
  encrypt: (value) => Buffer.from(value, 'utf8').reverse(),
  decrypt: (value) => Buffer.from(value).reverse().toString('utf8'),
})

afterEach(() => {
  while (roots.length) fs.rmSync(roots.pop()!, { recursive: true, force: true })
})

describe('McpConfigVault', () => {
  it('round-trips encrypted documents and isolates namespaces', () => {
    const root = makeRoot()
    const vault = new McpConfigVault(root, adapter())
    const secret = '{"token":"vault-secret"}'
    const reference = vault.store('namespace-a', secret)
    const file = fs.readFileSync(path.join(root, 'mcp-config-vault.json'), 'utf8')

    expect(vault.read('namespace-a', reference)).toBe(secret)
    expect(() => vault.read('namespace-b', reference)).toThrow('missingref')
    expect(file).not.toContain('vault-secret')
    expect(new McpConfigVault(root, adapter()).read('namespace-a', reference)).toBe(secret)
  })

  it('fails closed when the vault file is corrupt', () => {
    const root = makeRoot()
    fs.writeFileSync(path.join(root, 'mcp-config-vault.json'), '{not-json')
    const vault = new McpConfigVault(root, adapter())

    expect(vault.isAvailable()).toBe(false)
    expect(() => vault.store('namespace-a', '{}')).toThrow('unavailable')
  })

  it('fails closed when the vault index exceeds bounded namespace capacity', () => {
    const root = makeRoot()
    const values = Object.fromEntries(Array.from({ length: 65 }, (_, index) => [`namespace-${index}`, {}]))
    fs.writeFileSync(path.join(root, 'mcp-config-vault.json'), JSON.stringify({ version: 1, values }))
    expect(new McpConfigVault(root, adapter()).isAvailable()).toBe(false)
  })

  it('does not replace the existing blob when encryption verification fails', () => {
    const root = makeRoot()
    const good = new McpConfigVault(root, adapter())
    const reference = good.store('namespace-a', '{"old":true}')
    const before = fs.readFileSync(path.join(root, 'mcp-config-vault.json'), 'utf8')
    const broken: CredentialEncryptionAdapter = {
      isAvailable: () => true,
      encrypt: (value) => Buffer.from(value),
      decrypt: () => 'different',
    }

    expect(() => new McpConfigVault(root, broken).store('namespace-a', '{"new":true}')).toThrow('crypto')
    expect(fs.readFileSync(path.join(root, 'mcp-config-vault.json'), 'utf8')).toBe(before)
    expect(good.read('namespace-a', reference)).toBe('{"old":true}')
  })
})
