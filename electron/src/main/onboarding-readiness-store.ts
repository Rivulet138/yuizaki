import fs from 'node:fs'
import path from 'node:path'
import {
  ONBOARDING_SCHEMA_VERSION,
  type OnboardingReadinessSnapshot,
} from '../shared/onboarding-readiness'

const createInitialSnapshot = (): OnboardingReadinessSnapshot => ({
  schemaVersion: ONBOARDING_SCHEMA_VERSION,
  runId: '',
  revision: 0,
  state: 'idle',
  operation: 'idle',
  readyForText: false,
  startedAt: null,
  completedAt: null,
  probes: [],
})

export class OnboardingReadinessStore {
  private readonly storagePath: string
  private snapshot: OnboardingReadinessSnapshot

  constructor(storageDir: string) {
    this.storagePath = path.join(storageDir, 'onboarding-readiness.json')
    this.snapshot = this.load()
    if (this.snapshot.revision > 0 && this.snapshot.state === 'blocked') this.save()
  }

  get(): OnboardingReadinessSnapshot {
    return structuredClone(this.snapshot)
  }

  set(snapshot: OnboardingReadinessSnapshot): OnboardingReadinessSnapshot {
    this.snapshot = structuredClone(snapshot)
    this.save()
    return this.get()
  }

  private load(): OnboardingReadinessSnapshot {
    if (!fs.existsSync(this.storagePath)) return createInitialSnapshot()
    try {
      const parsed = JSON.parse(fs.readFileSync(this.storagePath, 'utf8')) as Partial<OnboardingReadinessSnapshot>
      if (parsed.schemaVersion !== ONBOARDING_SCHEMA_VERSION || !Array.isArray(parsed.probes)) {
        return createInitialSnapshot()
      }
      const recovered = {
        ...parsed,
        operation: parsed.operation === 'backend_start' || parsed.operation === 'probe_scan' ? parsed.operation : 'idle',
      } as OnboardingReadinessSnapshot
      if (recovered.state === 'running') {
        return {
          ...recovered,
          revision: recovered.revision + 1,
          state: 'blocked',
          operation: 'idle',
          readyForText: false,
          completedAt: new Date().toISOString(),
          probes: recovered.probes.map((probe) => probe.status === 'running'
            ? { ...probe, status: 'failed', message: 'Previous readiness scan was interrupted', messageKey: 'onboarding.interrupted' }
            : probe),
        }
      }
      return recovered
    } catch {
      return createInitialSnapshot()
    }
  }

  private save(): void {
    fs.mkdirSync(path.dirname(this.storagePath), { recursive: true })
    const tempPath = `${this.storagePath}.${process.pid}.tmp`
    fs.writeFileSync(tempPath, `${JSON.stringify(this.snapshot, null, 2)}\n`, { encoding: 'utf8', mode: 0o600 })
    fs.chmodSync(tempPath, 0o600)
    fs.renameSync(tempPath, this.storagePath)
    fs.chmodSync(this.storagePath, 0o600)
  }
}
