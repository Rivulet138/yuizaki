import fs from 'node:fs'
import { createHash } from 'node:crypto'
import os from 'node:os'
import path from 'node:path'
import { describe, expect, it } from 'vitest'
import {
  LocalPackageReleaseEvidenceStore,
  PackageReleaseHealthCheckRunner,
  canonicalizePackageReleaseAttestation,
  parsePackageReleaseEvidence,
  parsePackageReleaseEvidenceEnvelope,
} from '../package-release-evidence'

const artifact = Buffer.from('avatar-package')
const digest = createHash('sha256').update(artifact).digest('hex')
const evidence = {
  schemaVersion: 1,
  packageId: 'official.avatar.feibi',
  version: '1.2.0',
  artifactSha256: digest,
  evidenceKind: 'local_contract',
  platform: 'unknown',
  runtimeVersion: '42.7.0',
  checks: [
    { name: 'artifact-present', status: 'passed' },
    { name: 'runtime-startup', status: 'passed' },
  ],
}

describe('package release evidence', () => {
  it('resolves a release-runner evidence file through a read-only bounded layout', () => {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), 'yuizaki-package-evidence-'))
    try {
      const evidencePath = path.join(root, 'official.avatar.feibi', '1.2.0', 'evidence.json')
      fs.mkdirSync(path.dirname(evidencePath), { recursive: true })
      fs.writeFileSync(evidencePath, JSON.stringify(evidence), 'utf8')

      const store = new LocalPackageReleaseEvidenceStore(root)
      expect(store.resolve('official.avatar.feibi', '1.2.0')).toEqual(evidence)
      expect(new PackageReleaseHealthCheckRunner().createHealthChecker(store.asResolver())(
        'official.avatar.feibi', '1.2.0', artifact,
      )).toBe(true)
    } finally {
      fs.rmSync(root, { recursive: true, force: true })
    }
  })

  it('fails closed for missing, corrupt, traversal, and symlinked evidence', () => {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), 'yuizaki-package-evidence-path-'))
    const outside = fs.mkdtempSync(path.join(os.tmpdir(), 'yuizaki-package-evidence-outside-'))
    try {
      const store = new LocalPackageReleaseEvidenceStore(root)
      expect(store.resolve('official.avatar.feibi', '1.2.0')).toBeNull()
      expect(store.resolve('../escape', '1.2.0')).toBeNull()
      const corruptPath = path.join(root, 'official.avatar.feibi', '1.2.0', 'evidence.json')
      fs.mkdirSync(path.dirname(corruptPath), { recursive: true })
      fs.writeFileSync(corruptPath, '{not-json', 'utf8')
      expect(store.resolve('official.avatar.feibi', '1.2.0')).toBeNull()

      fs.rmSync(path.dirname(corruptPath), { recursive: true, force: true })
      fs.symlinkSync(outside, path.join(root, 'linked-package'), 'junction')
      expect(store.resolve('linked-package', '1.2.0')).toBeNull()

      const oversizedPath = path.join(root, 'oversized.package', '1.0.0', 'evidence.json')
      fs.mkdirSync(path.dirname(oversizedPath), { recursive: true })
      fs.writeFileSync(oversizedPath, 'x'.repeat(32), 'utf8')
      expect(new LocalPackageReleaseEvidenceStore(root, 16).resolve('oversized.package', '1.0.0')).toBeNull()
      expect(() => new LocalPackageReleaseEvidenceStore(root, 0)).toThrow('size limit')
    } finally {
      fs.rmSync(root, { recursive: true, force: true })
      fs.rmSync(outside, { recursive: true, force: true })
    }
  })

  it('accepts a structurally valid manifest and passing required checks', () => {
    const parsed = parsePackageReleaseEvidence(evidence)
    const runner = new PackageReleaseHealthCheckRunner()
    expect(parsed.artifactSha256).toBe(digest)
    expect(runner.evaluate('official.avatar.feibi', '1.2.0', artifact, parsed)).toEqual({ passed: true, failures: [] })
  })

  it('fails closed for malformed, mismatched, or failed evidence', () => {
    const runner = new PackageReleaseHealthCheckRunner()
    expect(runner.evaluate('official.avatar.feibi', '1.2.0', artifact, null)).toEqual({ passed: false, failures: ['evidence-invalid'] })
    expect(runner.evaluate('other.package', '1.2.0', artifact, evidence).failures).toContain('identity-mismatch')
    expect(runner.evaluate('official.avatar.feibi', '1.2.0', Buffer.from('tampered'), evidence).failures).toContain('artifact-digest-mismatch')
    const failed = { ...evidence, checks: [{ name: 'artifact-present', status: 'failed' }, { name: 'runtime-startup', status: 'passed' }] }
    expect(runner.evaluate('official.avatar.feibi', '1.2.0', artifact, failed).failures).toContain('check:artifact-present')
  })

  it('rejects duplicate checks and unknown fields at the input boundary', () => {
    expect(() => parsePackageReleaseEvidence({ ...evidence, extra: 'secret' })).toThrow('invalid')
    expect(() => parsePackageReleaseEvidence({ ...evidence, checks: [{ name: 'artifact-present', status: 'passed' }, { name: 'artifact-present', status: 'passed' }] })).toThrow('invalid')
  })

  it('does not treat real-device labels as qualification without explicit authorization', () => {
    const runner = new PackageReleaseHealthCheckRunner()
    const realDeviceEvidence = { ...evidence, evidenceKind: 'real_device' }
    expect(runner.evaluate('official.avatar.feibi', '1.2.0', artifact, realDeviceEvidence).failures)
      .toContain('evidence-kind-not-authorized')
    const authorized = new PackageReleaseHealthCheckRunner(['artifact-present', 'runtime-startup'], ['real_device'])
    expect(authorized.evaluate('official.avatar.feibi', '1.2.0', artifact, realDeviceEvidence)).toEqual({ passed: true, failures: [] })
  })

  it('creates a lifecycle-compatible checker without accepting missing evidence', () => {
    const runner = new PackageReleaseHealthCheckRunner()
    const checker = runner.createHealthChecker(() => evidence)
    expect(checker('official.avatar.feibi', '1.2.0', artifact)).toBe(true)
    expect(runner.createHealthChecker(() => null)('official.avatar.feibi', '1.2.0', artifact)).toBe(false)
  })

  it('requires an externally verified publisher attestation for release evidence', () => {
    const runner = new PackageReleaseHealthCheckRunner()
    const attestation = {
      schemaVersion: 1 as const,
      publisherIdentity: 'github.com.yuizaki.release',
      signerKeyId: 'release-key-2026',
      signature: 'c2lnbmF0dXJl',
    }
    const envelope = { manifest: evidence, attestation }
    const parsed = parsePackageReleaseEvidenceEnvelope(envelope)
    const verifier = (canonical: Buffer, received: typeof attestation) => (
      canonical.equals(canonicalizePackageReleaseAttestation(parsed.manifest, {
        schemaVersion: received.schemaVersion,
        publisherIdentity: received.publisherIdentity,
        signerKeyId: received.signerKeyId,
      })) && received.signature === attestation.signature
    )
    expect(runner.evaluateAttested('official.avatar.feibi', '1.2.0', artifact, envelope, verifier))
      .toEqual({ passed: true, failures: [] })
    expect(runner.evaluateAttested('official.avatar.feibi', '1.2.0', artifact, envelope, () => false).failures)
      .toContain('attestation-rejected')
    expect(runner.evaluateAttested('official.avatar.feibi', '1.2.0', artifact, { ...envelope, attestation: { ...attestation, extra: true } }, verifier).failures)
      .toEqual(['attestation-invalid'])
  })
})
