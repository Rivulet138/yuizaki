export class VisualCaptureEpoch {
  private epoch = 0

  current(): number {
    return this.epoch
  }

  invalidate(): void {
    this.epoch += 1
  }

  isCurrent(epoch: number): boolean {
    return epoch === this.epoch
  }
}
