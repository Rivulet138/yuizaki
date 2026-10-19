/**
 * Ambient declarations for the AudioWorkletGlobalScope used by
 * `pcm-capture.worklet.ts`. The worklet bundle is evaluated inside
 * `audioWorklet.addModule`, not in the window realm, so these globals are
 * intentionally not part of the DOM lib.
 */

declare abstract class AudioWorkletProcessor {
  readonly port: MessagePort
  constructor(options?: unknown)
  abstract process(
    inputs: Float32Array[][],
    outputs: Float32Array[][],
    parameters: Record<string, Float32Array>,
  ): boolean
}

declare const sampleRate: number

declare function registerProcessor(
  name: string,
  processorCtor: new (options?: unknown) => AudioWorkletProcessor,
): void
