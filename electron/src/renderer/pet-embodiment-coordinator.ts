export type PetEmbodimentBehavior =
  | 'idle'
  | 'thinking'
  | 'speaking'
  | 'reacting'
  | 'sleepy'
  | 'waiting'
  | 'curious'
  | 'focused'
  | 'interrupted'

export type PetEmbodimentTransientChannel = 'expression' | 'gaze' | 'viseme'
export type PetEmbodimentChannel = 'behavior' | PetEmbodimentTransientChannel
type Timer = ReturnType<typeof setTimeout>

interface BehaviorRequest {
  behavior: PetEmbodimentBehavior
  epoch: number
  expiresAt: number | null
  owner: string | null
}

interface TransientRequest {
  epoch: number
  owner: string | null
}

interface PetEmbodimentCoordinatorDependencies {
  applyBehavior: (behavior: PetEmbodimentBehavior) => void
  resetTransient?: (channel: PetEmbodimentTransientChannel) => void
  now?: () => number
  setTimeout?: (handler: () => void, timeoutMs: number) => Timer
  clearTimeout?: (timer: Timer) => void
}

const BEHAVIOR_PRIORITY: Record<PetEmbodimentBehavior, number> = {
  idle: 0,
  sleepy: 5,
  waiting: 8,
  curious: 10,
  focused: 12,
  thinking: 20,
  reacting: 20,
  interrupted: 25,
  speaking: 30,
}

/** Coordinates local avatar state only; it never performs inference or network work. */
export class PetEmbodimentCoordinator {
  private readonly applyBehavior: (behavior: PetEmbodimentBehavior) => void
  private readonly resetTransient: (channel: PetEmbodimentTransientChannel) => void
  private readonly now: () => number
  private readonly scheduleTimeout: (handler: () => void, timeoutMs: number) => Timer
  private readonly cancelTimeout: (timer: Timer) => void
  private readonly requests = new Map<string, BehaviorRequest>()
  private readonly timers = new Map<string, Timer>()
  private readonly transients = new Map<PetEmbodimentTransientChannel, TransientRequest>()
  private epoch = 0
  private resolved: PetEmbodimentBehavior = 'idle'

  constructor(dependencies: PetEmbodimentCoordinatorDependencies) {
    this.applyBehavior = dependencies.applyBehavior
    this.resetTransient = dependencies.resetTransient ?? (() => undefined)
    this.now = dependencies.now ?? Date.now
    this.scheduleTimeout = dependencies.setTimeout ?? ((handler, timeoutMs) => setTimeout(handler, timeoutMs))
    this.cancelTimeout = dependencies.clearTimeout ?? ((timer) => clearTimeout(timer))
  }

  requestBehavior(behavior: PetEmbodimentBehavior, durationMs = 0, owner: string | null = null): number {
    const epoch = ++this.epoch
    if (behavior === 'idle') {
      if (owner) {
        const wasIdle = this.resolved === 'idle'
        this.cancelOwner(owner)
        if (wasIdle && this.resolved === 'idle') this.applyBehavior('idle')
        return epoch
      }
      this.requests.clear()
      this.clearBehaviorTimers()
      if (this.resolved === 'idle') this.applyBehavior('idle')
      else this.resolve()
      return epoch
    }

    const key = this.behaviorKey(behavior, owner)
    const expiresAt = durationMs > 0 ? this.now() + durationMs : null
    this.requests.set(key, { behavior, epoch, expiresAt, owner })
    this.replaceTimer(key, durationMs, () => {
      const current = this.requests.get(key)
      if (!current || current.epoch !== epoch) return
      this.requests.delete(key)
      this.resolve()
    })
    this.resolve()
    return epoch
  }

  clearBehavior(behavior: PetEmbodimentBehavior, owner: string | null = null): void {
    const key = this.behaviorKey(behavior, owner)
    this.requests.delete(key)
    this.clearTimer(key)
    this.resolve()
  }

  beginTransient(channel: PetEmbodimentTransientChannel, durationMs = 0, owner: string | null = null): number {
    const epoch = ++this.epoch
    this.transients.set(channel, { epoch, owner })
    this.replaceTimer(`transient:${channel}`, durationMs, () => {
      if (this.transients.get(channel)?.epoch !== epoch) return
      this.transients.delete(channel)
      this.resetTransient(channel)
    })
    return epoch
  }

  endTransient(channel: PetEmbodimentTransientChannel, epoch?: number): void {
    if (epoch !== undefined && this.transients.get(channel)?.epoch !== epoch) return
    this.transients.delete(channel)
    this.clearTimer(`transient:${channel}`)
    this.resetTransient(channel)
  }

  cancelOwner(owner: string, channel?: PetEmbodimentChannel): void {
    if (!channel || channel === 'behavior') {
      for (const [key, request] of this.requests) {
        if (request.owner !== owner) continue
        this.requests.delete(key)
        this.clearTimer(key)
      }
    }
    if (channel !== 'behavior') {
      for (const [transientChannel, request] of this.transients) {
        if (request.owner !== owner || (channel && channel !== transientChannel)) continue
        this.transients.delete(transientChannel)
        this.clearTimer(`transient:${transientChannel}`)
        this.resetTransient(transientChannel)
      }
    }
    this.resolve()
  }

  cancelCommandClaims(channel?: PetEmbodimentChannel): void {
    const owners = new Set<string>()
    for (const request of this.requests.values()) if (request.owner) owners.add(request.owner)
    for (const request of this.transients.values()) if (request.owner) owners.add(request.owner)
    for (const owner of owners) this.cancelOwner(owner, channel)
  }

  refresh(): void {
    if (this.resolved !== 'idle') this.applyBehavior(this.resolved)
  }

  destroy(): void {
    for (const timer of this.timers.values()) this.cancelTimeout(timer)
    this.timers.clear()
    this.requests.clear()
    this.transients.clear()
  }

  private resolve(): void {
    const now = this.now()
    let next: PetEmbodimentBehavior = 'idle'
    let winner: BehaviorRequest | null = null
    for (const request of this.requests.values()) {
      if (request.expiresAt !== null && request.expiresAt <= now) continue
      const behavior = request.behavior
      if (!winner || BEHAVIOR_PRIORITY[behavior] > BEHAVIOR_PRIORITY[next]
        || (BEHAVIOR_PRIORITY[behavior] === BEHAVIOR_PRIORITY[next] && request.epoch > winner.epoch)) {
        next = behavior
        winner = request
      }
    }
    if (next === this.resolved) return
    this.resolved = next
    this.applyBehavior(next)
  }

  private replaceTimer(key: string, durationMs: number, handler: () => void): void {
    this.clearTimer(key)
    if (durationMs <= 0) return
    this.timers.set(key, this.scheduleTimeout(() => {
      this.timers.delete(key)
      handler()
    }, durationMs))
  }

  private clearTimer(key: string): void {
    const timer = this.timers.get(key)
    if (timer === undefined) return
    this.cancelTimeout(timer)
    this.timers.delete(key)
  }

  private clearBehaviorTimers(): void {
    for (const key of [...this.timers.keys()]) {
      if (key.startsWith('behavior')) this.clearTimer(key)
    }
  }

  private behaviorKey(behavior: PetEmbodimentBehavior, owner: string | null): string {
    return owner ? `behavior-owner:${owner}` : `behavior:${behavior}`
  }
}
