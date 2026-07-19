import fs from 'node:fs'
import path from 'node:path'
import { randomBytes } from 'node:crypto'

export type BackendApiTokenSource = 'environment' | 'stored' | 'generated' | 'memory'

export interface BackendApiTokenStatus {
  hasToken: boolean
  source: BackendApiTokenSource
  storagePath?: string
  tokenPreview: string
  storedTokenPreview?: string
  requiresRestart: boolean
}

export interface BackendApiTokenMutationResult {
  ok: boolean
  hasToken: boolean
  source: BackendApiTokenSource
  tokenPreview: string
  requiresRestart: boolean
}

export interface BackendApiTokenStoreLike {
  getBackendApiToken: () => string
  getBackendApiTokenStatus: () => BackendApiTokenStatus
  setBackendApiToken: (token: string) => BackendApiTokenMutationResult
  resetBackendApiToken: () => BackendApiTokenMutationResult
}

const TOKEN_FILENAME = 'backend-api-token'

const cleanToken = (token: string): string => token.trim()

const generateToken = (): string => randomBytes(32).toString('base64url')

const previewToken = (token: string): string => {
  const value = cleanToken(token)
  if (!value) return ''
  if (value.length <= 10) return `${value.slice(0, 2)}...${value.slice(-2)}`
  return `${value.slice(0, 6)}...${value.slice(-4)}`
}

const readTokenFile = (filePath: string): string => {
  try {
    return cleanToken(fs.readFileSync(filePath, 'utf8'))
  } catch {
    return ''
  }
}

const writeTokenFile = (filePath: string, token: string): void => {
  fs.mkdirSync(path.dirname(filePath), { recursive: true })
  fs.writeFileSync(filePath, `${cleanToken(token)}\n`, { encoding: 'utf8', mode: 0o600 })
}

const resolveEnvironmentToken = (): string =>
  cleanToken(process.env['YUIZAKI_CONTROL_TOKEN'] || '') ||
  cleanToken(process.env['YUIZAKI_BACKEND_API_TOKEN'] || '')

export class BackendApiTokenStore implements BackendApiTokenStoreLike {
  private readonly tokenFilePath: string
  private activeToken = ''
  private source: BackendApiTokenSource = 'generated'

  constructor(storageDir: string) {
    this.tokenFilePath = path.join(storageDir, TOKEN_FILENAME)
    this.activeToken = this.loadOrCreate()
  }

  getBackendApiToken(): string {
    return this.activeToken
  }

  getBackendApiTokenStatus(): BackendApiTokenStatus {
    const storedToken = readTokenFile(this.tokenFilePath)
    return {
      hasToken: this.activeToken.length > 0,
      source: this.source,
      storagePath: this.tokenFilePath,
      tokenPreview: previewToken(this.activeToken),
      storedTokenPreview: previewToken(storedToken),
      requiresRestart: Boolean(storedToken && storedToken !== this.activeToken),
    }
  }

  setBackendApiToken(token: string): BackendApiTokenMutationResult {
    const nextToken = cleanToken(token)
    if (!nextToken) {
      throw new Error('Backend API token cannot be empty')
    }
    writeTokenFile(this.tokenFilePath, nextToken)
    return {
      ok: true,
      hasToken: true,
      source: 'stored',
      tokenPreview: previewToken(nextToken),
      requiresRestart: nextToken !== this.activeToken,
    }
  }

  resetBackendApiToken(): BackendApiTokenMutationResult {
    const nextToken = generateToken()
    writeTokenFile(this.tokenFilePath, nextToken)
    return {
      ok: true,
      hasToken: true,
      source: 'generated',
      tokenPreview: previewToken(nextToken),
      requiresRestart: nextToken !== this.activeToken,
    }
  }

  private loadOrCreate(): string {
    const environmentToken = resolveEnvironmentToken()
    if (environmentToken) {
      writeTokenFile(this.tokenFilePath, environmentToken)
      this.source = 'environment'
      return environmentToken
    }

    const storedToken = readTokenFile(this.tokenFilePath)
    if (storedToken) {
      this.source = 'stored'
      return storedToken
    }

    const generatedToken = generateToken()
    writeTokenFile(this.tokenFilePath, generatedToken)
    this.source = 'generated'
    return generatedToken
  }
}

export const createTransientBackendApiTokenStore = (): BackendApiTokenStoreLike => {
  let activeToken = resolveEnvironmentToken() || generateToken()
  let source: BackendApiTokenSource = resolveEnvironmentToken() ? 'environment' : 'memory'
  return {
    getBackendApiToken: () => activeToken,
    getBackendApiTokenStatus: () => ({
      hasToken: activeToken.length > 0,
      source,
      tokenPreview: previewToken(activeToken),
      requiresRestart: false,
    }),
    setBackendApiToken: (token: string) => {
      const nextToken = cleanToken(token)
      if (!nextToken) {
        throw new Error('Backend API token cannot be empty')
      }
      activeToken = nextToken
      source = 'memory'
      return {
        ok: true,
        hasToken: true,
        source,
        tokenPreview: previewToken(activeToken),
        requiresRestart: false,
      }
    },
    resetBackendApiToken: () => {
      activeToken = generateToken()
      source = 'memory'
      return {
        ok: true,
        hasToken: true,
        source,
        tokenPreview: previewToken(activeToken),
        requiresRestart: false,
      }
    },
  }
}
