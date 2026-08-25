import type {
  PackageArtifactStore,
  PackageLifecycle,
  PackageManifest,
  PackageOperationResult,
} from './package-lifecycle'
import type { PackageKeyRotationEnvelope } from './package-trust'

export interface PackageHttpResponse {
  ok: boolean
  status: number
  headers: { get(name: string): string | null }
  arrayBuffer(): Promise<ArrayBuffer>
}

export type PackageHttpRequest = (url: string, signal: AbortSignal) => Promise<PackageHttpResponse>
export type PackageArtifactUrlResolver = (manifest: PackageManifest) => string
export type PackageKeyRotationUrlResolver = () => string

export interface PackageArtifactSource {
  fetch(manifest: PackageManifest, signal: AbortSignal): Promise<Buffer>
}

export interface PackageKeyRotationSource {
  fetch(signal: AbortSignal): Promise<PackageKeyRotationEnvelope>
}

export interface PackageKeyRotationApplier {
  applyRotation(envelope: PackageKeyRotationEnvelope): void
}

const DEFAULT_MAX_ARTIFACT_BYTES = 64 * 1024 * 1024

/** HTTPS-only source with explicit origin and response-size policy. */
export class HttpPackageArtifactSource implements PackageArtifactSource {
  constructor(
    private readonly resolveUrl: PackageArtifactUrlResolver,
    private readonly allowedOrigins: ReadonlySet<string>,
    private readonly maxBytes = DEFAULT_MAX_ARTIFACT_BYTES,
    private readonly request: PackageHttpRequest = async (url, signal) => {
      const response = await fetch(url, { signal })
      return response
    },
  ) {
    if (maxBytes < 1) throw new Error('package artifact size limit must be positive')
  }

  async fetch(manifest: PackageManifest, signal: AbortSignal): Promise<Buffer> {
    signal.throwIfAborted()
    const parsed = new URL(this.resolveUrl(manifest))
    if (parsed.protocol !== 'https:' || !this.allowedOrigins.has(parsed.origin)) {
      throw new Error('package artifact origin is not allowed')
    }
    const response = await this.request(parsed.toString(), signal)
    signal.throwIfAborted()
    if (!response.ok) throw new Error(`package artifact download failed: HTTP ${response.status}`)
    const declaredLength = response.headers.get('content-length')
    if (declaredLength !== null) {
      const length = Number(declaredLength)
      if (!Number.isSafeInteger(length) || length < 0 || length > this.maxBytes) {
        throw new Error('package artifact exceeds size limit')
      }
    }
    const artifact = Buffer.from(await response.arrayBuffer())
    if (artifact.byteLength > this.maxBytes) throw new Error('package artifact exceeds size limit')
    return artifact
  }
}

const isKeyRotationEnvelope = (value: unknown): value is PackageKeyRotationEnvelope => {
  if (!value || typeof value !== 'object') return false
  const candidate = value as Record<string, unknown>
  if (!Number.isSafeInteger(candidate['version']) || (candidate['version'] as number) < 1) return false
  if (typeof candidate['signerKeyId'] !== 'string' || !candidate['signerKeyId'].trim()) return false
  if (typeof candidate['signature'] !== 'string' || !candidate['signature'].trim()) return false
  if (!Array.isArray(candidate['keys']) || candidate['keys'].length === 0) return false
  return candidate['keys'].every((key) => {
    if (!key || typeof key !== 'object') return false
    const item = key as Record<string, unknown>
    return typeof item['keyId'] === 'string' && Boolean(item['keyId'].trim())
      && typeof item['publicKeyPem'] === 'string' && Boolean(item['publicKeyPem'].trim())
  })
}

const parseKeyRotationEnvelope = (artifact: Buffer): PackageKeyRotationEnvelope => {
  let value: unknown
  try {
    value = JSON.parse(artifact.toString('utf8'))
  } catch {
    throw new Error('package key rotation metadata is not valid JSON')
  }
  if (!isKeyRotationEnvelope(value)) throw new Error('package key rotation metadata is invalid')
  return value
}

/** HTTPS-only source for root-signed key-set metadata. Signature verification stays with the authority. */
export class HttpPackageKeyRotationSource implements PackageKeyRotationSource {
  constructor(
    private readonly resolveUrl: PackageKeyRotationUrlResolver,
    private readonly allowedOrigins: ReadonlySet<string>,
    private readonly maxBytes = 1024 * 1024,
    private readonly request: PackageHttpRequest = async (url, signal) => fetch(url, { signal }),
  ) {
    if (maxBytes < 1) throw new Error('package key rotation size limit must be positive')
  }

  async fetch(signal: AbortSignal): Promise<PackageKeyRotationEnvelope> {
    signal.throwIfAborted()
    const parsed = new URL(this.resolveUrl())
    if (parsed.protocol !== 'https:' || !this.allowedOrigins.has(parsed.origin)) {
      throw new Error('package key rotation origin is not allowed')
    }
    const response = await this.request(parsed.toString(), signal)
    signal.throwIfAborted()
    if (!response.ok) throw new Error(`package key rotation download failed: HTTP ${response.status}`)
    const declaredLength = response.headers.get('content-length')
    if (declaredLength !== null) {
      const length = Number(declaredLength)
      if (!Number.isSafeInteger(length) || length < 0 || length > this.maxBytes) {
        throw new Error('package key rotation metadata exceeds size limit')
      }
    }
    const metadata = Buffer.from(await response.arrayBuffer())
    if (metadata.byteLength > this.maxBytes) throw new Error('package key rotation metadata exceeds size limit')
    return parseKeyRotationEnvelope(metadata)
  }
}

export class PackageDistributionAdapter {
  constructor(
    private readonly lifecycle: PackageLifecycle,
    private readonly source: PackageArtifactSource,
  ) {}

  async installFromSource(
    manifest: PackageManifest,
    signal: AbortSignal,
  ): Promise<PackageOperationResult> {
    signal.throwIfAborted()
    const artifact = await this.source.fetch(manifest, signal)
    signal.throwIfAborted()
    return this.lifecycle.install(manifest, artifact)
  }

  async refreshKeyRotation(
    source: PackageKeyRotationSource,
    authority: PackageKeyRotationApplier,
    signal: AbortSignal,
  ): Promise<number> {
    signal.throwIfAborted()
    const envelope = await source.fetch(signal)
    signal.throwIfAborted()
    authority.applyRotation(envelope)
    return envelope.version
  }
}

export type { PackageArtifactStore }
