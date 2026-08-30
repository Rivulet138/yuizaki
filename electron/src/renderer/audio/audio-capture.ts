import { reactive, ref, type Ref } from 'vue';
import { SocketClient } from '../net/socketClient';
import { chatClient } from '@/api/client';
import pcmCaptureWorkletUrl from './pcm-capture.worklet.ts?worker&url';

type BrowserWindowWithAudioContext = Window & typeof globalThis & {
  webkitAudioContext?: typeof AudioContext;
};

export type AudioCapturePhase = 'idle' | 'requesting' | 'recording' | 'stopping' | 'error';
export type AudioCapturePermission = 'unknown' | 'prompt' | 'granted' | 'denied';
export type AudioInputHealth = 'unknown' | 'silent' | 'active' | 'disconnected';

export interface AudioCaptureStatus {
  phase: AudioCapturePhase;
  permission: AudioCapturePermission;
  isRecording: boolean;
  elapsedMs: number;
  sampleRate: number;
  inputSampleRate: number | null;
  audioProcessing: {
    echoCancellation: boolean | null;
    noiseSuppression: boolean | null;
    autoGainControl: boolean | null;
  };
  level: number;
  peak: number;
  speechDetected: boolean;
  inputHealth: AudioInputHealth;
  silenceMs: number;
  chunksSent: number;
  bytesSent: number;
  error: string | null;
  startedAt: number | null;
}

export interface AudioDeviceInventory {
  inputCount: number;
  outputCount: number;
  inputLabels: string[];
  outputLabels: string[];
}

interface AudioCaptureStartOptions {
  maxDurationMs?: number;
  sessionId?: string;
  interruptionEpoch?: number;
  deviceId?: string;
}

const DEFAULT_MAX_RECORDING_MS = 120_000;
export const AUDIO_SILENCE_GRACE_MS = 1_800;
export const AUDIO_SPEECH_RMS_THRESHOLD = 0.015;
const SILENCE_PREROLL_CHUNKS = 6;
const createEnvelopeId = (prefix: string) => `${prefix}_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;

const normalizeMicrophoneError = (error: unknown): string => {
  if (error instanceof DOMException) {
    if (error.name === 'NotAllowedError' || error.name === 'PermissionDeniedError') {
      return '麦克风权限被拒绝';
    }
    if (error.name === 'NotFoundError' || error.name === 'DevicesNotFoundError') {
      return '没有找到可用麦克风';
    }
    if (error.name === 'NotReadableError') {
      return '麦克风正被其他程序占用';
    }
  }
  return error instanceof Error && error.message ? error.message : '麦克风启动失败';
};

const computeRms = (samples: Float32Array): number => {
  if (samples.length === 0) return 0;
  let sum = 0;
  for (let i = 0; i < samples.length; i += 1) {
    const value = samples[i] ?? 0;
    sum += value * value;
  }
  return Math.sqrt(sum / samples.length);
};

export const hasSpeechEnergy = (samples: Float32Array, threshold = AUDIO_SPEECH_RMS_THRESHOLD): boolean =>
  computeRms(samples) >= threshold;

export const classifyAudioInputHealth = (
  rms: number,
  silenceMs: number,
  trackState: MediaStreamTrackState = 'live',
): AudioInputHealth => {
  if (trackState === 'ended') return 'disconnected';
  if (Number.isFinite(rms) && rms >= AUDIO_SPEECH_RMS_THRESHOLD) return 'active';
  if (Number.isFinite(silenceMs) && silenceMs >= AUDIO_SILENCE_GRACE_MS) return 'silent';
  return 'unknown';
};

const readBooleanSetting = (value: unknown): boolean | null =>
  typeof value === 'boolean' ? value : null;

export const normalizeAudioProcessingSettings = (settings?: MediaTrackSettings) => ({
  echoCancellation: readBooleanSetting(settings?.echoCancellation),
  noiseSuppression: readBooleanSetting(settings?.noiseSuppression),
  autoGainControl: readBooleanSetting(settings?.autoGainControl),
});

/** Enumerate available endpoints without opening a device or persisting labels. */
export const enumerateAudioDevices = async (): Promise<AudioDeviceInventory> => {
  const enumerate = navigator.mediaDevices?.enumerateDevices;
  if (typeof enumerate !== 'function') {
    return { inputCount: 0, outputCount: 0, inputLabels: [], outputLabels: [] };
  }
  const devices = await enumerate.call(navigator.mediaDevices);
  const inputs = devices.filter((device) => device.kind === 'audioinput');
  const outputs = devices.filter((device) => device.kind === 'audiooutput');
  return {
    inputCount: inputs.length,
    outputCount: outputs.length,
    inputLabels: inputs.map((device) => device.label.trim()).filter(Boolean).slice(0, 8),
    outputLabels: outputs.map((device) => device.label.trim()).filter(Boolean).slice(0, 8),
  };
};

export interface AudioInputDevice {
  deviceId: string;
  label: string;
}

/** Enumerate input IDs for an explicit user-selected microphone. */
export const enumerateAudioInputDevices = async (): Promise<AudioInputDevice[]> => {
  const enumerate = navigator.mediaDevices?.enumerateDevices;
  if (typeof enumerate !== 'function') return [];
  const devices = await enumerate.call(navigator.mediaDevices);
  return devices
    .filter((device) => device.kind === 'audioinput' && device.deviceId.trim())
    .map((device) => ({ deviceId: device.deviceId, label: device.label.trim() || '未命名麦克风' }))
    .slice(0, 16);
};

export class StreamingPcmNormalizer {
  private readonly ratio: number;
  private readonly inputBuffer: number[] = [];
  private readonly outputBuffer: number[] = [];
  private position = 0;

  constructor(
    inputSampleRate: number,
    outputSampleRate: number,
    private readonly chunkSize: number,
  ) {
    if (inputSampleRate <= 0 || outputSampleRate <= 0 || chunkSize <= 0) {
      throw new Error('Audio sample rates and chunk size must be positive');
    }
    this.ratio = inputSampleRate / outputSampleRate;
  }

  push(samples: Float32Array): Float32Array[] {
    if (samples.length === 0) return [];
    if (this.ratio === 1) {
      this.outputBuffer.push(...samples);
      return this.drain(false);
    }

    this.inputBuffer.push(...samples);
    while (this.position + 1 < this.inputBuffer.length) {
      const lowerIndex = Math.floor(this.position);
      const upperIndex = lowerIndex + 1;
      const fraction = this.position - lowerIndex;
      const lower = this.inputBuffer[lowerIndex] ?? 0;
      const upper = this.inputBuffer[upperIndex] ?? lower;
      this.outputBuffer.push(lower + ((upper - lower) * fraction));
      this.position += this.ratio;
    }

    const consumed = Math.min(
      Math.floor(this.position),
      Math.max(0, this.inputBuffer.length - 1),
    );
    if (consumed > 0) {
      this.inputBuffer.splice(0, consumed);
      this.position -= consumed;
    }
    return this.drain(false);
  }

  flush(): Float32Array[] {
    if (this.ratio !== 1 && this.inputBuffer.length > 0) {
      const last = this.inputBuffer.at(-1) ?? 0;
      while (this.position < this.inputBuffer.length) {
        const lowerIndex = Math.min(Math.floor(this.position), this.inputBuffer.length - 1);
        const upperIndex = Math.min(lowerIndex + 1, this.inputBuffer.length - 1);
        const fraction = this.position - Math.floor(this.position);
        const lower = this.inputBuffer[lowerIndex] ?? last;
        const upper = this.inputBuffer[upperIndex] ?? last;
        this.outputBuffer.push(lower + ((upper - lower) * fraction));
        this.position += this.ratio;
      }
      this.inputBuffer.length = 0;
      this.position = 0;
    }
    return this.drain(true);
  }

  private drain(padFinalChunk: boolean): Float32Array[] {
    const chunks: Float32Array[] = [];
    while (this.outputBuffer.length >= this.chunkSize) {
      chunks.push(Float32Array.from(this.outputBuffer.splice(0, this.chunkSize)));
    }
    if (padFinalChunk && this.outputBuffer.length > 0) {
      const finalChunk = new Float32Array(this.chunkSize);
      finalChunk.set(this.outputBuffer.splice(0));
      chunks.push(finalChunk);
    }
    return chunks;
  }
}

export class AudioCapture {
  private mediaStream: MediaStream | null = null;
  private audioContext: AudioContext | null = null;
  private source: MediaStreamAudioSourceNode | null = null;
  private processor: ScriptProcessorNode | null = null;
  private worklet: AudioWorkletNode | null = null;
  private zeroGain: GainNode | null = null;
  private pcmNormalizer: StreamingPcmNormalizer | null = null;
  private isRecording: Ref<boolean> = ref(false);
  private elapsedTimer: ReturnType<typeof setInterval> | null = null;
  private maxDurationTimer: ReturnType<typeof setTimeout> | null = null;
  private sampleRate = 16000;
  private chunkSize = 512; // samples per chunk (32ms @ 16kHz)
  private envelope: { sessionId: string; generationId: string; turnId: string; requestId: string; interruptionEpoch: number; version: 1 } | null = null;
  private speechDetected = false;
  private silencePreroll: Float32Array[] = [];
  private inputTrack: MediaStreamTrack | null = null;
  private readonly handleInputTrackEnded = (): void => {
    this.status.inputHealth = 'disconnected';
    this.status.error = '麦克风设备已断开';
    if (!this.isRecording.value) return;
    this.stop({ sendFinal: false });
    this.status.phase = 'error';
    this.status.isRecording = false;
    this.status.inputHealth = 'disconnected';
    this.status.error = '麦克风设备已断开';
  };
  private readonly status = reactive<AudioCaptureStatus>({
    phase: 'idle',
    permission: 'unknown',
    isRecording: false,
    elapsedMs: 0,
    sampleRate: 16000,
    inputSampleRate: null,
    audioProcessing: {
      echoCancellation: null,
      noiseSuppression: null,
      autoGainControl: null,
    },
    level: 0,
    peak: 0,
    speechDetected: false,
    inputHealth: 'unknown',
    silenceMs: 0,
    chunksSent: 0,
    bytesSent: 0,
    error: null,
    startedAt: null,
  });

  constructor() {}

  async queryMicrophonePermission(): Promise<AudioCapturePermission> {
    try {
      if (!navigator.permissions?.query) {
        this.status.permission = 'unknown';
        return this.status.permission;
      }
      const permission = await navigator.permissions.query({ name: 'microphone' as PermissionName });
      this.status.permission = permission.state;
      return this.status.permission;
    } catch {
      this.status.permission = 'unknown';
      return this.status.permission;
    }
  }

  async start(options: AudioCaptureStartOptions = {}): Promise<void> {
    if (this.isRecording.value) return;

    try {
      const socketClient = chatClient.getSocketClient();
      if (!socketClient.isConnected()) {
        throw new Error('Socket.IO 未连接，无法开始语音输入');
      }

      this.resetStatusForStart();
      const generationId = createEnvelopeId('gen_voice');
      this.envelope = {
        sessionId: options.sessionId?.trim() || 'default',
        generationId,
        turnId: createEnvelopeId('turn_voice'),
        requestId: `voice_${generationId}`,
        interruptionEpoch: options.interruptionEpoch ?? 0,
        version: 1,
      };
      this.status.phase = 'requesting';
      await this.queryMicrophonePermission();

      this.mediaStream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
          sampleRate: this.sampleRate,
          ...(options.deviceId?.trim() ? { deviceId: { ideal: options.deviceId.trim() } } : {}),
        },
      });
      const track = this.mediaStream.getAudioTracks()[0];
      if (!track) throw new Error('没有找到可用麦克风');
      this.inputTrack = track;
      track.addEventListener('ended', this.handleInputTrackEnded, { once: true });
      const audioTrackSettings = track.getSettings();
      this.status.audioProcessing = normalizeAudioProcessingSettings(audioTrackSettings);

      const AudioContextConstructor = window.AudioContext || (window as BrowserWindowWithAudioContext).webkitAudioContext;
      if (!AudioContextConstructor) {
        throw new Error('AudioContext is not available in this browser');
      }
      this.audioContext = new AudioContextConstructor({
        sampleRate: this.sampleRate,
        latencyHint: 'interactive',
      });
      const inputSampleRate = this.audioContext.sampleRate || audioTrackSettings?.sampleRate || this.sampleRate;
      this.pcmNormalizer = new StreamingPcmNormalizer(inputSampleRate, this.sampleRate, this.chunkSize);

      this.source = this.audioContext.createMediaStreamSource(this.mediaStream);
      this.zeroGain = this.audioContext.createGain();
      this.zeroGain.gain.value = 0;
      if (this.audioContext.audioWorklet && typeof AudioWorkletNode !== 'undefined') {
        await this.audioContext.audioWorklet.addModule(pcmCaptureWorkletUrl);
        this.worklet = new AudioWorkletNode(this.audioContext, 'yuizaki-pcm-capture');
        this.worklet.port.onmessage = (event: MessageEvent<ArrayBuffer>) => {
          if (!this.isRecording.value || !(event.data instanceof ArrayBuffer)) return;
          this.processInputSamples(new Float32Array(event.data), socketClient);
        };
        this.source.connect(this.worklet);
        this.worklet.connect(this.zeroGain);
      } else {
        this.processor = this.audioContext.createScriptProcessor(this.chunkSize, 1, 1);
        this.processor.onaudioprocess = (event) => {
          if (!this.isRecording.value) return;
          this.processInputSamples(event.inputBuffer.getChannelData(0), socketClient);
        };
        this.source.connect(this.processor);
        this.processor.connect(this.zeroGain);
      }
      this.zeroGain.connect(this.audioContext.destination);

      this.isRecording.value = true;
      this.status.phase = 'recording';
      this.status.isRecording = true;
      this.status.permission = 'granted';
      this.status.sampleRate = this.sampleRate;
      this.status.inputSampleRate = inputSampleRate;
      this.status.startedAt = Date.now();
      this.startTimers(options.maxDurationMs ?? DEFAULT_MAX_RECORDING_MS);
      console.log('[AudioCapture] Microphone started');
    } catch (err) {
      console.error('[AudioCapture] Failed to start microphone:', err);
      this.stop({ sendFinal: false });
      this.status.phase = 'error';
      this.status.error = normalizeMicrophoneError(err);
      this.status.isRecording = false;
      throw err;
    }
  }

  stop(options: { sendFinal?: boolean } = {}): void {
    const shouldSendFinal = options.sendFinal !== false;
    const wasRecording = this.isRecording.value;
    this.isRecording.value = false;
    this.status.isRecording = false;
    this.status.phase = wasRecording ? 'stopping' : this.status.phase;
    this.clearTimers();

    const socketClient = chatClient.getSocketClient();
    if (wasRecording && shouldSendFinal && socketClient.isConnected()) {
      for (const chunk of this.pcmNormalizer?.flush() ?? []) {
        this.sendAudioChunk(chunk, socketClient);
      }
      socketClient.sendAudioChunk('', this.sampleRate, true, this.envelope ?? undefined);
    }
    this.pcmNormalizer = null;
    this.envelope = null;
    this.speechDetected = false;
    this.silencePreroll = [];

    if (this.processor) {
      this.processor.disconnect();
      this.processor = null;
    }

    if (this.worklet) {
      this.worklet.port.onmessage = null;
      this.worklet.disconnect();
      this.worklet = null;
    }

    if (this.zeroGain) {
      this.zeroGain.disconnect();
      this.zeroGain = null;
    }

    if (this.source) {
      this.source.disconnect();
      this.source = null;
    }

    if (this.audioContext) {
      void this.audioContext.close();
      this.audioContext = null;
    }

    if (this.mediaStream) {
      if (this.inputTrack) {
        this.inputTrack.removeEventListener('ended', this.handleInputTrackEnded);
        this.inputTrack = null;
      }
      this.mediaStream.getTracks().forEach((track) => {
        track.stop();
      });
      this.mediaStream = null;
    }

    if (wasRecording) {
      this.status.phase = 'idle';
      this.status.level = 0;
    }
    console.log('[AudioCapture] Microphone stopped');
  }

  private sendAudioChunk(pcmData: Float32Array, socketClient: SocketClient): void {
    this.updateLevel(pcmData);
    if (!this.speechDetected) {
      this.silencePreroll.push(pcmData.slice());
      if (this.silencePreroll.length > SILENCE_PREROLL_CHUNKS) this.silencePreroll.shift();
      if (!hasSpeechEnergy(pcmData)) return;
      this.speechDetected = true;
      this.status.speechDetected = true;
      for (const preroll of this.silencePreroll) this.sendAudioChunkNow(preroll, socketClient);
      this.silencePreroll = [];
      return;
    }
    this.sendAudioChunkNow(pcmData, socketClient);
  }

  private sendAudioChunkNow(pcmData: Float32Array, socketClient: SocketClient): void {
    if (!socketClient.isConnected()) {
      const wasRecording = this.isRecording.value;
      this.status.error = '实时通道连接已断开';
      if (wasRecording) {
        // Do not emit a final empty turn after transport loss. Releasing the
        // device immediately prevents a silent microphone from staying open.
        this.stop({ sendFinal: false });
        this.status.phase = 'error';
        this.status.error = '实时通道连接已断开';
      }
      return;
    }

    // Convert Float32 to Int16
    const int16Data = this.float32ToInt16(pcmData);
    const base64 = this.arrayBufferToBase64(int16Data);

    socketClient.sendAudioChunk(base64, this.sampleRate, false, this.envelope ?? undefined);
    this.status.chunksSent += 1;
    this.status.bytesSent += int16Data.byteLength;
  }

  private processInputSamples(inputData: Float32Array, socketClient: SocketClient): void {
    for (const chunk of this.pcmNormalizer?.push(inputData) ?? []) {
      this.sendAudioChunk(chunk, socketClient);
    }
  }

  private float32ToInt16(float32Array: Float32Array): Int16Array {
    const int16Array = new Int16Array(float32Array.length);
    for (let i = 0; i < float32Array.length; i += 1) {
      const sample = float32Array[i] ?? 0;
      const s = Math.max(-1, Math.min(1, sample));
      int16Array[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
    }
    return int16Array;
  }

  private arrayBufferToBase64(buffer: Int16Array): string {
    let binary = '';
    const bytes = new Uint8Array(buffer.buffer);
    const len = bytes.byteLength;
    // Chunk conversion to avoid max call stack size exceeded
    const chunkSize = 8192;
    for (let i = 0; i < len; i += chunkSize) {
      const chunk = bytes.subarray(i, i + chunkSize);
      binary += String.fromCharCode.apply(null, Array.from(chunk));
    }
    return btoa(binary);
  }

  private resetStatusForStart(): void {
    this.status.phase = 'idle';
    this.status.isRecording = false;
    this.status.elapsedMs = 0;
    this.status.level = 0;
    this.status.peak = 0;
    this.status.speechDetected = false;
    this.status.inputHealth = 'unknown';
    this.status.silenceMs = 0;
    this.status.chunksSent = 0;
    this.status.bytesSent = 0;
    this.status.inputSampleRate = null;
    this.status.audioProcessing = {
      echoCancellation: null,
      noiseSuppression: null,
      autoGainControl: null,
    };
    this.status.error = null;
    this.status.startedAt = null;
    this.speechDetected = false;
    this.silencePreroll = [];
  }

  private startTimers(maxDurationMs: number): void {
    this.clearTimers();
    this.elapsedTimer = setInterval(() => {
      if (!this.status.startedAt) return;
      this.status.elapsedMs = Date.now() - this.status.startedAt;
    }, 250);
    this.maxDurationTimer = setTimeout(() => {
      if (this.isRecording.value) {
        this.stop();
      }
    }, Math.max(1_000, maxDurationMs));
  }

  private clearTimers(): void {
    if (this.elapsedTimer) {
      clearInterval(this.elapsedTimer);
      this.elapsedTimer = null;
    }
    if (this.maxDurationTimer) {
      clearTimeout(this.maxDurationTimer);
      this.maxDurationTimer = null;
    }
  }

  private updateLevel(pcmData: Float32Array): void {
    const rms = computeRms(pcmData);
    const level = Math.min(1, rms * 8);
    this.status.level = this.status.level * 0.72 + level * 0.28;
    this.status.peak = Math.max(this.status.peak * 0.96, level);
    const now = Date.now();
    if (rms >= AUDIO_SPEECH_RMS_THRESHOLD) {
      this.status.silenceMs = 0;
      this.status.inputHealth = 'active';
    } else {
      const baseline = this.status.startedAt ?? now;
      this.status.silenceMs = Math.max(0, now - baseline);
      this.status.inputHealth = classifyAudioInputHealth(rms, this.status.silenceMs);
    }
  }

  getIsRecording(): Ref<boolean> {
    return this.isRecording;
  }

  getStatus(): AudioCaptureStatus {
    return this.status;
  }
}

export const audioCapture = new AudioCapture();
