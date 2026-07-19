/**
 * Socket.IO 客户端
 * 与 Python 后端 Socket.IO 服务器通信
 * 逐步替代 wsClient.ts（现阶段并行运行）
 */
import { io, type Socket } from 'socket.io-client';
import { type Ref, ref } from 'vue';
import { logger } from '../logger';
import type { ChatOptions } from '../../shared/types';
import {
  API_ORIGIN,
  getBackendAuthToken,
  refreshControlTokenFromServer,
  refreshRuntimeApiOrigin,
} from '../api/clients/http-client';

/** Socket.IO 事件名（与 backend/socket_events.py 对齐） */
export const SocketEvents = {
  // 音频
  AUDIO_CHUNK: 'audio:chunk',
  ASR_VAD_START: 'asr:vad-start',
  ASR_SPEECH_START: 'asr:speech-start',
  ASR_PARTIAL: 'asr:partial',
  ASR_FINAL: 'asr:final',
  // LLM
  LLM_REQUEST: 'llm:request',
  LLM_DELTA: 'llm:delta',
  LLM_FINAL: 'llm:final',
  // TTS
  TTS_CHUNK: 'tts:chunk',
  TTS_DONE: 'tts:done',
  // SVC
  SVC_CONVERT: 'svc:convert',
  SVC_DONE: 'svc:done',
  // 工具
  TOOL_CALL: 'tool:call',
  TOOL_RESULT: 'tool:result',
  TOOL_ERROR: 'tool:error',
  // Agent
  AGENT_CHAT: 'agent:chat',
  AGENT_UPDATE: 'agent:update',
  AGENT_RESULT: 'agent:result',
  // 记忆
  MEMORY_STATUS: 'memory:status',
  RAG_QUERY: 'rag:query',
  RAG_RESULT: 'rag:result',
  SCREENSHOT_REQUEST: 'screenshot:request',
  SCREENSHOT_RESULT: 'screenshot:result',
  // 截图
  // Pet
  PET_STATE: 'pet:state',
  PET_INTERACT: 'pet:interact',
  PET_CONTROL: 'pet:control',
  // 系统
  CONNECT: 'connect',
  DISCONNECT: 'disconnect',
  HEARTBEAT: 'heartbeat',
  INTERRUPT: 'interrupt',
  INTERRUPT_ACK: 'interrupt:ack',
  LATENCY: 'system:latency',
  CLIENT_TIMING: 'system:client-timing',
  PERMISSION_REQUEST: 'permission:request',
  PERMISSION_RESPONSE: 'permission:response',
  ERROR: 'error',
} as const;

export type SocketEventName = typeof SocketEvents[keyof typeof SocketEvents];

/** 事件处理器类型 */
type EventHandler = (data: unknown) => void;
type ScreenshotMode = 'observe' | 'frame' | 'vision' | 'ocr';
type ScreenshotOptions = {
  displayIndex?: number;
  mode?: ScreenshotMode;
  region?: { x: number; y: number; width: number; height: number };
  caption?: string;
  source?: 'desktop' | 'window' | 'region' | 'pet';
  timestamp?: number;
  frameId?: string;
  changeScore?: number;
  captureReason?: 'initial' | 'change' | 'voice_change' | 'heartbeat' | 'manual';
};

export class SocketClient {
  private socket: Socket | null = null;
  private readonly configuredUrl: string;
  private url: string;
  private handlers: Map<string, Set<EventHandler>> = new Map();
  private opening = false;
  private authRetryInFlight = false;

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
    void this.bootstrapAndOpenSocket();
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

  private async bootstrapAndOpenSocket(): Promise<void> {
    try {
      let authToken = getBackendAuthToken();
      if (!authToken) {
        try {
          authToken = await refreshControlTokenFromServer();
        } catch (error) {
          logger.warn('[SocketIO] Control token bootstrap failed before connect:', error);
        }
      }
      if (!authToken) {
        logger.warn('[SocketIO] Backend auth token missing; skip connection until the Electron control page provides authorization.');
        return;
      }
      this.url = await this.resolveSocketUrl(authToken || '');
      this.openSocket(authToken);
    } finally {
      this.opening = false;
    }
  }

  private openSocket(authToken: string = getBackendAuthToken()): void {
    if (this.socket?.connected) return;
    if (this.socket) {
      this.socket.disconnect();
      this.socket = null;
    }
    this.socket = io(this.url, {
      path: '/socket.io',
      transports: ['websocket', 'polling'],
      auth: authToken ? { token: authToken } : undefined,
      reconnection: true,
      reconnectionAttempts: 10,
      reconnectionDelay: 1000,
      reconnectionDelayMax: 5000,
      timeout: 10000,
    });

    // 连接生命周期
    this.socket.on(SocketEvents.CONNECT, () => {
      logger.info('[SocketIO] Connected:', this.socket?.id);
      this.connected.value = true;
      this.reconnectAttempts.value = 0;
    });

    this.socket.on(SocketEvents.DISCONNECT, (reason: string) => {
      logger.info('[SocketIO] Disconnected:', reason);
      this.connected.value = false;
    });

    this.socket.on('connect_error', (err: Error) => {
      logger.error('[SocketIO] Connection error:', err.message);
      this.reconnectAttempts.value++;
      if (err.message.toLowerCase().includes('reject')) {
        this.retryWithFreshAuthToken();
      }
    });

    // 注册已有的事件处理器
    for (const [event, handlerSet] of this.handlers.entries()) {
      for (const handler of handlerSet) {
        this.socket.on(event, handler);
      }
    }

    // 心跳
    this.startHeartbeat();
  }

  private retryWithFreshAuthToken(): void {
    if (!this.socket || this.authRetryInFlight) return;
    this.authRetryInFlight = true;
    void refreshControlTokenFromServer()
      .then(async (token) => {
        if (!token || !this.socket || this.socket.connected) return;
        this.url = await this.resolveSocketUrl(token);
        this.socket.auth = { token };
        this.socket.connect();
      })
      .catch((error) => {
        logger.warn('[SocketIO] Control token refresh failed after rejected connection:', error);
      })
      .finally(() => {
        this.authRetryInFlight = false;
      });
  }

  /** 断开连接 */
  disconnect(): void {
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
  sendLLMRequest(messages: Array<{ role: string; content: string }>, sessionId?: string, requestId?: string, workspaceId?: string, chatOptions?: ChatOptions): void {
    this.emit(SocketEvents.LLM_REQUEST, {
      messages,
      session_id: sessionId || '',
      request_id: requestId || '',
      workspace_id: workspaceId || '',
      chat_options: chatOptions,
    });
  }

  /** 发送 Agent 对话请求（规则驱动，内部可调用 RAG/工具） */
  sendAgentChat(messages: Array<{ role: string; content: string }>, sessionId?: string, petControlContext?: unknown, requestId?: string, workspaceId?: string, chatOptions?: ChatOptions): void {
    this.emit(SocketEvents.AGENT_CHAT, {
      messages,
      session_id: sessionId || '',
      workspace_id: workspaceId || '',
      pet_control_context: petControlContext,
      request_id: requestId || '',
      chat_options: chatOptions,
    });
  }

  /** 发送音频块 */
  sendAudioChunk(chunk: string, sampleRate: number = 16000, isFinal: boolean = false): void {
    this.emit(SocketEvents.AUDIO_CHUNK, {
      chunk,
      sample_rate: sampleRate,
      is_final: isFinal,
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
    this.emit(SocketEvents.SCREENSHOT_REQUEST, payload);
  }

  clearVisualContext(): void {
    this.emit(SocketEvents.SCREENSHOT_REQUEST, { mode: 'clear' });
  }

  /** 发送工具调用 */
  sendToolCall(id: string, name: string, args: Record<string, unknown>): void {
    this.emit(SocketEvents.TOOL_CALL, { id, name, args });
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
    | 'realtime_speech_to_response'
    | 'realtime_speech_to_playback'
    | 'realtime_interrupt_ack',
  options: {
    sessionId?: string;
    generationId?: string;
    elapsedMs?: number;
  } = {}): void {
    this.emit(SocketEvents.CLIENT_TIMING, {
      stage,
      session_id: options.sessionId || '',
      generation_id: options.generationId || '',
      ...(Number.isFinite(options.elapsedMs) ? { elapsed_ms: options.elapsedMs } : {}),
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

  private startHeartbeat(): void {
    this.stopHeartbeat();
    this.heartbeatInterval = setInterval(() => {
      if (this.socket?.connected) {
        this.emit(SocketEvents.HEARTBEAT, {
          timestamp: Date.now(),
        });
      }
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
