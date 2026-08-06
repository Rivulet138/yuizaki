export type PetFpsTier = 'active' | 'idle'

interface PetTickerControl {
  start: () => void
  stop: () => void
}

interface PetPerformanceControllerOptions {
  ticker: PetTickerControl
  isHidden: () => boolean
  onTierChange: (tier: PetFpsTier, reason: string) => void
  idleThresholdMs: number
  now?: () => number
}

export class PetPerformanceController {
  private readonly ticker: PetTickerControl
  private readonly isHidden: () => boolean
  private readonly onTierChange: (tier: PetFpsTier, reason: string) => void
  private readonly idleThresholdMs: number
  private readonly now: () => number
  private timer: number | null = null
  private tier: PetFpsTier = 'active'
  private lastActivityAt: number
  private stopped = true

  constructor(options: PetPerformanceControllerOptions) {
    this.ticker = options.ticker
    this.isHidden = options.isHidden
    this.onTierChange = options.onTierChange
    this.idleThresholdMs = options.idleThresholdMs
    this.now = options.now ?? Date.now
    this.lastActivityAt = this.now()
  }

  start(): void {
    this.stopped = false
    this.setTier('active', 'startup', true)
    this.syncVisibility()
  }

  stop(): void {
    this.stopped = true
    this.clearTimer()
  }

  markActivity(reason: string): void {
    if (this.stopped) return
    this.lastActivityAt = this.now()
    if (this.tier !== 'active') this.setTier('active', reason)
    if (this.timer === null && !this.isHidden()) this.schedule()
  }

  syncVisibility(): void {
    if (this.stopped) return
    this.clearTimer()
    if (this.isHidden()) {
      this.ticker.stop()
      return
    }
    this.ticker.start()
    this.schedule()
  }

  private schedule(): void {
    const idleTime = this.now() - this.lastActivityAt
    if (idleTime >= this.idleThresholdMs) {
      if (this.tier !== 'idle') this.setTier('idle', `idle-${Math.round(idleTime / 1000)}s`)
      return
    }
    this.timer = window.setTimeout(() => {
      this.timer = null
      if (this.stopped) return
      if (this.isHidden()) {
        this.ticker.stop()
        return
      }
      this.schedule()
    }, this.idleThresholdMs - idleTime)
  }

  private clearTimer(): void {
    if (this.timer === null) return
    window.clearTimeout(this.timer)
    this.timer = null
  }

  private setTier(tier: PetFpsTier, reason: string, force = false): void {
    if (!force && this.tier === tier) return
    this.tier = tier
    this.onTierChange(tier, reason)
  }
}
