export interface PointerMovePoint {
  x: number
  y: number
}

export interface PointerMoveCoalescerOptions {
  onMove: (point: PointerMovePoint) => void
  requestFrame?: (callback: () => void) => number
  cancelFrame?: (handle: number) => void
}

export class PointerMoveCoalescer {
  private readonly onMove: PointerMoveCoalescerOptions['onMove']
  private readonly requestFrame: NonNullable<PointerMoveCoalescerOptions['requestFrame']>
  private readonly cancelFrame: NonNullable<PointerMoveCoalescerOptions['cancelFrame']>
  private pending: PointerMovePoint | null = null
  private frameHandle: number | null = null

  constructor(options: PointerMoveCoalescerOptions) {
    this.onMove = options.onMove
    this.requestFrame = options.requestFrame ?? ((callback) => window.requestAnimationFrame(callback))
    this.cancelFrame = options.cancelFrame ?? ((handle) => window.cancelAnimationFrame(handle))
  }

  submit(point: PointerMovePoint): void {
    this.pending = { ...point }
    if (this.frameHandle !== null) return

    this.frameHandle = this.requestFrame(() => {
      this.frameHandle = null
      const next = this.pending
      this.pending = null
      if (next) this.onMove(next)
    })
  }

  cancel(): void {
    if (this.frameHandle !== null) {
      this.cancelFrame(this.frameHandle)
      this.frameHandle = null
    }
    this.pending = null
  }
}
