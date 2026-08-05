export class VisualCaptureEpoch {
  private static readonly MAX_TRACKED_FRAMES = 32
  private epoch = 0
  private readonly frames = new Map<string, { epoch: number; allowWhenDisabled: boolean }>()

  current(): number {
    return this.epoch
  }

  invalidate(): void {
    this.epoch += 1
    this.frames.clear()
  }

  isCurrent(epoch: number): boolean {
    return epoch === this.epoch
  }

  trackFrame(frameId: string, epoch: number, allowWhenDisabled = false): void {
    this.frames.delete(frameId)
    this.frames.set(frameId, { epoch, allowWhenDisabled })
    while (this.frames.size > VisualCaptureEpoch.MAX_TRACKED_FRAMES) {
      const oldestFrameId = this.frames.keys().next().value
      if (typeof oldestFrameId !== 'string') break
      this.frames.delete(oldestFrameId)
    }
  }

  acceptResult(frameId: string, enabled: boolean, terminal: boolean): boolean {
    const frame = this.frames.get(frameId)
    const accepted = Boolean(
      frame
      && this.isCurrent(frame.epoch)
      && (enabled || frame.allowWhenDisabled),
    )
    if (!accepted || terminal) this.frames.delete(frameId)
    return accepted
  }

  forgetFrame(frameId: string): void {
    this.frames.delete(frameId)
  }
}

export const isVisualFrameResult = (payload: Record<string, unknown>): boolean => (
  payload.mode === 'observe' || payload.mode === 'frame' || payload.mode === 'vision'
)

export const isTerminalVisualFrameResult = (payload: Record<string, unknown>): boolean => {
  if (typeof payload.error === 'string' && payload.error) return true
  return payload.status === 'ok'
    && isVisualFrameResult(payload)
    && payload.analysis_status !== 'pending'
}
