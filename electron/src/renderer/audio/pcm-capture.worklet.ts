class PcmCaptureProcessor extends AudioWorkletProcessor {
  private readonly frameSize = Math.max(128, Math.round(sampleRate * 0.032))
  private readonly frame = new Float32Array(this.frameSize)
  private offset = 0

  process(inputs: Float32Array[][]): boolean {
    const channel = inputs[0]?.[0]
    if (channel?.length) {
      let sourceOffset = 0
      while (sourceOffset < channel.length) {
        const count = Math.min(channel.length - sourceOffset, this.frameSize - this.offset)
        this.frame.set(channel.subarray(sourceOffset, sourceOffset + count), this.offset)
        this.offset += count
        sourceOffset += count
        if (this.offset === this.frameSize) {
          const samples = this.frame.slice()
          this.port.postMessage(samples.buffer, [samples.buffer])
          this.offset = 0
        }
      }
    }
    return true
  }
}

registerProcessor('yuizaki-pcm-capture', PcmCaptureProcessor)
