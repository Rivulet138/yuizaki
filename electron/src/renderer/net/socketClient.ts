/**
 * Socket.IO 客户端
 * 与 Python 后端 Socket.IO 服务器通信
 * 逐步替代 wsClient.ts（现阶段并行运行）
 */
import { io, type Socket } from 'socket.io-client';
import { type Ref, ref } from 'vue';
import { logger } from '../logger';
import type { ChatOptions } from '../../shared/types';
import { SocketEvents } from '../../shared/runtimeProtocol';
export { SocketEvents } from '../../shared/runtimeProtocol';
export type { SocketEventName } from '../../shared/runtimeProtocol';
import {
  API_ORIGIN,
  getBackendAuthToken,
  refreshControlTokenFromServer,
  refreshRuntimeApiOrigin,
} from '../api/clients/http-client';

/** Socket.IO 事件名（与 backend/socket_events.py 对齐） */

/** 事件处理器类型 */
type EventHandler = (data: unknown) => void;
type HeartbeatCorrelation = { timestamp: number; request_id: string; client_id: string };
export type HeartbeatCorrelationAudit = {
  emitted: true;
  echoed: true;
  echo_count: 1;
  correlation: { timestamp: number; request_id: '[verified]'; client_id: '[verified]' };
};
type ScreenshotMode = 'observe' | 'frame' | 'vision' | 'ocr' | 'discard';
type ScreenshotOptions = {
  displayIndex?: number;
  mode?: ScreenshotMode;
  region?: { x: number; y: number; width: number; height: number };
  caption?: string;
  source?: 'desktop' | 'window' | 'region' | 'pet';
  timestamp?: number;
  frameId?: string;
  changeScore?: number;
  captureReason?: 'initial' | 'change' | 'voice_change' | 'heartbeat' | 'manual' | 'agent_turn';
  workspaceId?: string;
  sessionId?: string;
  turnId?: string;
  jobId?: string;
  requestId?: string;
  generationId?: string;
  interruptionEpoch?: number;
};
export type ToolCallOptions = {
  requestId?: string;
  runId?: string;
  jobId?: string;
  source?: string;
  retry?: boolean;
  version?: number;
};
export type ToolRecheckOptions = Pick<ToolCallOptions, 'requestId' | 'runId' | 'jobId' | 'source'>;
export type ToolRecheckResult = {
  id: string;
  status: 'verified' | 'unverified' | 'error' | 'unavailable';
  reason?: string;
  evidence?: string[];
  durationMs?: number;
};

export class SocketClient {
  private socket: Socket | null = null;
  private readonly configuredUrl: string;
  private url: string;
  private handlers: Map<string, Set<EventHandler>> = new Map();
  private opening = false;
  private authRetryInFlight = false;
  private authRetryOperation = 0;
  private connectionEpoch = 0;

  /** 响应式连接状态 */
  public connected: Ref<boolean> = ref(false);

  /** 重连尝试次数 */
  public reconnectAttempts: Ref<number> = ref(0);

  constructor(url: string = API_ORIGIN) {
    this.configuredUrl = url;
    this.url = url;
  }

  /** 建立 Socket.IO 连接 */
  connect(): void {
    if (this.socket?.connected || this.opening) return;

    this.opening = true;
    const epoch = ++this.connectionEpoch;
    void this.bootstrapAndOpenSocket(epoch);
  }

  private shouldUseRuntimeApiOrigin(): boolean {
    try {
      const configured = new URL(this.configuredUrl);
      const api = new URL(API_ORIGIN);
      return configured.origin === api.origin;
    } catch {
      return false;
    }
  }

  private async resolveSocketUrl(authToken: string): Promise<string> {
    if (!this.shouldUseRuntimeApiOrigin()) return this.configuredUrl;
    const headers = authToken ? { Authorization: `Bearer ${authToken}` } : {};
    return refreshRuntimeApiOrigin(headers);
  }

  private async bootstrapAndOpenSocket(epoch: number): Promise<void> {
    try {
      let authToken = getBackendAuthToken();
      if (!authToken) {
        try {
          authToken = await refreshControlTokenFromServer();
          if (epoch !== this.connectionEpoch) return;
        } catch (error) {
          logger.warn('[SocketIO] Control token bootstrap failed before connect:', error);
        }
      }
      if (epoch !== this.connectionEpoch) return;
      if (!authToken) {
        logger.warn('[SocketIO] Backend auth token missing; skip connection until the Electron control page provides authorization.');
        return;
      }
      this.url = await this.resolveSocketUrl(authToken || '');
      if (epoch !== this.connectionEpoch) return;
      this.openSocket(authToken);
    } finally {
      if (epoch === this.connectionEpoch) this.opening = false;
    }
  }

  private openSocket(authToken: string = getBackendAuthToken()): void {
    if (this.socket?.connected) return;
    if (this.socket) {
      this.socket.disconnect();
      this.socket = null;
    }
    const socket = io(this.url, {
      path: '/socket.io',
      transports: ['websocket', 'polling'],
      auth: authToken ? { token: authToken } : undefined,
      reconnection: true,
      reconnectionAttempts: 10,
      reconnectionDelay: 1000,
      reconnectionDelayMax: 5000,
      timeout: 10000,
    });
    this.socket = socket;

    // 连接生命周期
    socket.on(SocketEvents.CONNECT, () => {
      if (this.socket !== socket) return;
      logger.info('[SocketIO] Connected:', socket.id);
      this.connected.value = true;
      this.reconnectAttempts.value = 0;
    });

    socket.on(SocketEvents.DISCONNECT, (reason: string) => {
      if (this.socket !== socket) return;
      logger.info('[SocketIO] Disconnected:', reason);
      this.connected.value = false;
    });

    socket.on('connect_error', (err: Error) => {
      if (this.socket !== socket) return;
      logger.warn('[SocketIO] Connection attempt failed:', err.message);
      this.reconnectAttempts.value++;
      if (err.message.toLowerCase().includes('reject')) {
        this.retryWithFreshAuthToken(socket);
      }
    });

    socket.io.on('reconnect_failed', () => {
      if (this.socket !== socket) return;
      logger.error('[SocketIO] Reconnection failed after all attempts');
    });

    // 注册已有的事件处理器
    for (const [event, handlerSet] of this.handlers.entries()) {
      for (const handler of handlerSet) {
        socket.on(event, handler);
      }
    }

    // 心跳
    this.startHeartbeat();
  }

  private retryWithFreshAuthToken(retrySocket: Socket): void {
    if (this.socket !== retrySocket || this.authRetryInFlight) return;
    const epoch = this.connectionEpoch;
    const operation = ++this.authRetryOperation;
    const isCurrent = () => (
      operation === this.authRetryOperation
      && epoch === this.connectionEpoch
      && this.socket === retrySocket
    );
    this.authRetryInFlight = true;
    void refreshControlTokenFromServer()
      .then(async (token) => {
        if (!token || !isCurrent() || retrySocket.connected) return;
        const url = await this.resolveSocketUrl(token);
        if (!isCurrent() || retrySocket.connected) return;
        this.url = url;
        retrySocket.auth = { token };
        retrySocket.connect();
      })
      .catch((error) => {
        logger.warn('[SocketIO] Control token refresh failed after rejected connection:', error);
      })
      .finally(() => {
        if (operation === this.authRetryOperation) this.authRetryInFlight = false;
      });
  }

  /** 断开连接 */
  disconnect(): void {
    this.connectionEpoch += 1;
    this.authRetryOperation += 1;
    this.opening = false;
    this.authRetryInFlight = false;
    if (this.socket) {
      this.stopHeartbeat();
      this.socket.disconnect();
      this.socket = null;
      this.connected.value = false;
    }
  }

  /** 发送事件 */
  emit(event: string, data?: unknown): void {
    if (this.socket?.connected) {
      this.socket.emit(event, data);
    } else {
      logger.warn('[SocketIO] Not connected, event not sent:', event);
    }
  }

  /** 注册事件监听 */
  on(event: string, handler: EventHandler): void {
    let handlerSet = this.handlers.get(event);
    if (!handlerSet) {
      handlerSet = new Set();
      this.handlers.set(event, handlerSet);
    }
    handlerSet.add(handler);

    // 如果已连接，立即注册到 socket
    if (this.socket) {
      this.socket.on(event, handler);
    }
  }

  /** 注册一次性事件监听 */
  once(event: string, handler: EventHandler): void {
    if (this.socket) {
      this.socket.once(event, handler);
    }
  }

  /** 移除事件监听 */
  off(event: string, handler?: EventHandler): void {
    if (handler) {
      this.handlers.get(event)?.delete(handler);
      this.socket?.off(event, handler);
    } else {
      this.handlers.delete(event);
      this.socket?.off(event);
    }
  }

  /** 是否已连接 */
  isConnected(): boolean {
    return this.connected.value;
  }

  /** Socket ID */
  get id(): string | undefined {
    return this.socket?.id;
  }

  // ─── 便捷方法 ──────────────────────────────

  /** 发送 LLM 请求 */
  sendLLMRequest(messages: Array<{ role: string; content: string }>, sessionId?: string, requestId?: string, workspaceId?: string, chatOptions?: ChatOptions, generationId?: string, turnId?: string, interruptionEpoch?: number): void {
    this.emit(SocketEvents.LLM_REQUEST, {
      messages,
      session_id: sessionId || '',
      request_id: requestId || '',
      generation_id: generationId || '',
      turn_id: turnId || '',
      interruption_epoch: interruptionEpoch ?? 0,
      version: 1,
      workspace_id: workspaceId || '',
      chat_options: chatOptions,
    });
  }

  /** 发送 Agent 对话请求（规则驱动，内部可调用 RAG/工具） */
  sendAgentChat(messages: Array<{ role: string; content: string }>, sessionId?: string, petControlContext?: unknown, requestId?: string, workspaceId?: string, chatOptions?: ChatOptions, interruptionEpoch?: number, generationId?: string, turnId?: string, runtimeIdentity?: { conversationId?: string; operationId?: string; stepIndex?: number; runId?: string }): void {
    this.emit(SocketEvents.AGENT_CHAT, {
      messages,
      session_id: sessionId || '',
      workspace_id: workspaceId || '',
      pet_control_context: petControlContext,
      request_id: requestId || '',
      generation_id: generationId || '',
      turn_id: turnId || '',
      ...(runtimeIdentity?.conversationId ? { conversation_id: runtimeIdentity.conversationId } : {}),
      ...(runtimeIdentity?.operationId ? { operation_id: runtimeIdentity.operationId } : {}),
      ...(runtimeIdentity?.stepIndex !== undefined ? { step_index: runtimeIdentity.stepIndex } : {}),
      ...(runtimeIdentity?.runId ? { run_id: runtimeIdentity.runId } : {}),
      version: 1,
      chat_options: chatOptions,
      interruption_epoch: interruptionEpoch ?? 0,
    });
  }

  /** 发送音频块 */
  sendAudioChunk(chunk: string, sampleRate: number = 16000, isFinal: boolean = false, envelope?: { sessionId: string; generationId: string; turnId: string; requestId: string; interruptionEpoch: number; version: 1 }): void {
    this.emit(SocketEvents.AUDIO_CHUNK, {
      chunk,
      sample_rate: sampleRate,
      is_final: isFinal,
      session_id: envelope?.sessionId || '',
      generation_id: envelope?.generationId || '',
      turn_id: envelope?.turnId || '',
      request_id: envelope?.requestId || '',
      interruption_epoch: envelope?.interruptionEpoch ?? 0,
      version: envelope?.version ?? 1,
    });
  }

  requestScreenshot(image: string, options: ScreenshotOptions = {}): void {
    const payload: Record<string, unknown> = {
      image,
      display_index: options.displayIndex ?? 0,
      mode: options.mode ?? 'observe',
    };
    if (options.region) payload.region = options.region;
    if (options.caption) payload.caption = options.caption;
    if (options.source) payload.source = options.source;
    if (options.timestamp !== undefined) payload.timestamp = options.timestamp;
    if (options.frameId) payload.frame_id = options.frameId;
    if (options.changeScore !== undefined) payload.change_score = options.changeScore;
    if (options.captureReason) payload.capture_reason = options.captureReason;
    if (options.workspaceId) payload.workspace_id = options.workspaceId;
    if (options.sessionId) payload.session_id = options.sessionId;
    if (options.turnId) payload.turn_id = options.turnId;
    if (options.jobId) payload.job_id = options.jobId;
    if (options.requestId) payload.request_id = options.requestId;
    if (options.generationId) payload.generation_id = options.generationId;
    if (options.interruptionEpoch !== undefined) payload.interruption_epoch = options.interruptionEpoch;
    this.emit(SocketEvents.SCREENSHOT_REQUEST, payload);
  }

  clearVisualContext(): void {
    this.emit(SocketEvents.SCREENSHOT_REQUEST, { mode: 'clear' });
  }

  discardScreenshotRequest(request: Record<string, unknown>, reason: string): void {
    this.emit(SocketEvents.SCREENSHOT_REQUEST, {
      mode: 'discard',
      workspace_id: request['workspaceId'],
      session_id: request['sessionId'],
      turn_id: request['turnId'],
      job_id: request['jobId'],
      request_id: request['requestId'],
      frame_id: request['frameId'],
      interruption_epoch: request['interruptionEpoch'],
      reason,
    });
  }

  /** 发送工具调用 */
  sendToolCall(id: string, name: string, args: Record<string, unknown>, options: ToolCallOptions = {}): void {
    const payload: Record<string, unknown> = { id, name, args, version: options.version ?? 1 };
    if (options.requestId) payload.request_id = options.requestId;
    if (options.runId) payload.run_id = options.runId;
    if (options.jobId) payload.job_id = options.jobId;
    if (options.source) payload.source = options.source;
    if (options.retry !== undefined) payload.retry = options.retry;
    this.emit(SocketEvents.TOOL_CALL, payload);
  }

  /** Probe a tool's current effect without repeating the original action. */
  sendToolRecheck(id: string, name: string, args: Record<string, unknown>, options: ToolRecheckOptions = {}): void {
    const payload: Record<string, unknown> = { id, name, args, version: 1 };
    if (options.requestId) payload.request_id = options.requestId;
    if (options.runId) payload.run_id = options.runId;
    if (options.jobId) payload.job_id = options.jobId;
    if (options.source) payload.source = options.source;
    this.emit(SocketEvents.TOOL_RECHECK, payload);
  }

  requestToolRecheck(
    id: string,
    name: string,
    args: Record<string, unknown>,
    options: ToolRecheckOptions & { timeoutMs?: number } = {},
  ): Promise<ToolRecheckResult> {
    const timeoutMs = Math.max(250, Math.min(30_000, options.timeoutMs ?? 5_000));
    return new Promise((resolve, reject) => {
      const timer = window.setTimeout(() => {
        this.off(SocketEvents.TOOL_RECHECK_RESULT, handler);
        reject(new Error('Tool status check timed out'));
      }, timeoutMs);
      const handler: EventHandler = (value) => {
        if (!value || typeof value !== 'object' || Array.isArray(value)) return;
        const result = value as Record<string, unknown>;
        if (result.id !== id) return;
        window.clearTimeout(timer);
        this.off(SocketEvents.TOOL_RECHECK_RESULT, handler);
        const status = typeof result.status === 'string' ? result.status : 'error';
        if (!['verified', 'unverified', 'error', 'unavailable'].includes(status)) {
          reject(new Error('Invalid tool status check response'));
          return;
        }
        resolve({
          id,
          status: status as ToolRecheckResult['status'],
          ...(typeof result.reason === 'string' ? { reason: result.reason } : {}),
          ...(Array.isArray(result.evidence) ? { evidence: result.evidence.filter((item): item is string => typeof item === 'string').slice(0, 6) } : {}),
          ...(typeof result.durationMs === 'number' && Number.isFinite(result.durationMs) ? { durationMs: result.durationMs } : {}),
        });
      };
      this.on(SocketEvents.TOOL_RECHECK_RESULT, handler);
      this.sendToolRecheck(id, name, args, options);
    });
  }

  /** 发送 RAG 查询 */
  sendRAGQuery(query: string, options?: { topK?: number; sessionId?: string; workspaceId?: string; scope?: string; layers?: string[] }): void {
    this.emit(SocketEvents.RAG_QUERY, {
      query,
      top_k: options?.topK ?? 5,
      session_id: options?.sessionId,
      workspace_id: options?.workspaceId,
      scope: options?.scope,
      layers: options?.layers,
    });
  }

  sendInterrupt(sessionId?: string, requestId?: string, source: 'manual' | 'voice' = 'manual'): void {
    this.emit(SocketEvents.INTERRUPT, {
      session_id: sessionId || '',
      request_id: requestId || '',
      source,
    });
  }

  sendClientTiming(stage:
    | 'playback_start'
    | 'interrupt_ack'
    | 'realtime_connect'
    | 'realtime_transcript_stable'
    | 'realtime_speech_to_response'
    | 'realtime_speech_to_playback'
    | 'realtime_turn_complete'
    | 'realtime_interrupt_ack'
    | 'realtime_playback_stop'
    | 'realtime_playback_recovery'
    | 'realtime_provider_cancel',
  options: {
    sessionId?: string;
    generationId?: string;
    elapsedMs?: number;
    ok?: boolean;
    recovered?: boolean;
    recoveryLatencyMs?: number;
    playbackUnderruns?: number;
  } = {}): void {
    this.emit(SocketEvents.CLIENT_TIMING, {
      stage,
      session_id: options.sessionId || '',
      generation_id: options.generationId || '',
      ...(Number.isFinite(options.elapsedMs) ? { elapsed_ms: options.elapsedMs } : {}),
      ...(typeof options.ok === 'boolean' ? { ok: options.ok } : {}),
      ...(typeof options.recovered === 'boolean' ? { recovered: options.recovered } : {}),
      ...(Number.isFinite(options.recoveryLatencyMs) ? { recovery_latency_ms: options.recoveryLatencyMs } : {}),
      ...(Number.isFinite(options.playbackUnderruns) ? { playback_underruns: options.playbackUnderruns } : {}),
    });
  }

  sendPermissionResponse(requestId: string, allowed: boolean, remember: boolean = false): void {
    this.emit(SocketEvents.PERMISSION_RESPONSE, {
      request_id: requestId,
      allowed,
      remember,
    });
  }

  sendSVCConvert(audio: string, speakerId: number = 0, transpose: number = 0): void {
    this.emit(SocketEvents.SVC_CONVERT, {
      audio,
      speaker_id: speakerId,
      transpose,
    });
  }

  // ─── 心跳 ──────────────────────────────────

  private heartbeatInterval: ReturnType<typeof setInterval> | null = null;
  private heartbeatPaused = false;

  private emitHeartbeat(): void {
    if (this.socket?.connected) {
      this.emit(SocketEvents.HEARTBEAT, { timestamp: Date.now() });
    }
  }

  pauseHeartbeat(): void {
    this.heartbeatPaused = true;
    this.stopHeartbeat();
  }

  async emitHeartbeatOnceAndWaitForEcho(options: {
    timeoutMs?: number;
    duplicateWindowMs?: number;
    correlation?: HeartbeatCorrelation;
  } = {}): Promise<HeartbeatCorrelationAudit> {
    const clientId = this.socket?.id || '';
    if (!this.socket?.connected || !clientId) throw new Error('Socket did not connect for isolated heartbeat');
    const correlation = options.correlation ?? {
      timestamp: Date.now(),
      request_id: `heartbeat-${crypto.randomUUID()}`,
      client_id: clientId,
    };
    const timeoutMs = options.timeoutMs ?? 2_000;
    const duplicateWindowMs = options.duplicateWindowMs ?? 100;
    let handler: EventHandler | undefined;
    try {
      return await new Promise<HeartbeatCorrelationAudit>((resolve, reject) => {
        let echoCount = 0;
        let settleTimer: ReturnType<typeof setTimeout> | undefined;
        const timeout = setTimeout(() => reject(new Error('Heartbeat echo timed out')), timeoutMs);
        const fail = (message: string) => {
          clearTimeout(timeout);
          if (settleTimer) clearTimeout(settleTimer);
          reject(new Error(message));
        };
        handler = (value) => {
          if (!value || typeof value !== 'object') return fail('Heartbeat echo correlation did not match');
          const payload = value as Record<string, unknown>;
          const keys = Object.keys(payload).sort();
          if (
            keys.join(',') !== 'client_id,request_id,timestamp'
            || payload['timestamp'] !== correlation.timestamp
            || payload['request_id'] !== correlation.request_id
            || payload['client_id'] !== correlation.client_id
          ) {
            return fail('Heartbeat echo correlation did not match');
          }
          echoCount += 1;
          if (echoCount > 1) return fail('Heartbeat echo was duplicated');
          clearTimeout(timeout);
          settleTimer = setTimeout(() => resolve({
            emitted: true,
            echoed: true,
            echo_count: 1,
            correlation: {
              timestamp: correlation.timestamp,
              request_id: '[verified]',
              client_id: '[verified]',
            },
          }), duplicateWindowMs);
        };
        this.on(SocketEvents.HEARTBEAT, handler);
        this.emit(SocketEvents.HEARTBEAT, correlation);
      });
    } finally {
      if (handler) this.off(SocketEvents.HEARTBEAT, handler);
    }
  }

  private startHeartbeat(): void {
    this.stopHeartbeat();
    if (this.heartbeatPaused) return;
    this.heartbeatInterval = setInterval(() => {
      this.emitHeartbeat();
    }, 30000); // 30秒心跳
  }

  private stopHeartbeat(): void {
    if (this.heartbeatInterval) {
      clearInterval(this.heartbeatInterval);
      this.heartbeatInterval = null;
    }
  }
}

/** 全局单例 */
let _instance: SocketClient | null = null;

export function getSocketClient(url?: string): SocketClient {
  if (!_instance) {
    _instance = new SocketClient(url);
  }
  return _instance;
}
