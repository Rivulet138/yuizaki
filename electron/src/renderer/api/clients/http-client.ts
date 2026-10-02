const env = import.meta.env
const LOCAL_API_FALLBACK_ORIGIN = 'http://localhost:8001'
const LOCAL_CONTROL_FALLBACK_ORIGIN = 'http://localhost:38945'

type YuizakiControlWindow = Window & typeof globalThis & {
  __YUIZAKI_CONTROL_TOKEN__?: string
  __YUIZAKI_CONTROL_ORIGIN__?: string
  __YUIZAKI_API_ORIGIN__?: string
}

const normalizeLocalOrigin = (value: string | undefined, fallback: string): string => {
  const origin = (value || fallback).trim().replace(/\/$/, '')
  try {
    const parsed = new URL(origin)
    if (parsed.hostname === '127.0.0.1') {
      parsed.hostname = 'localhost'
      return parsed.toString().replace(/\/$/, '')
    }
  } catch {
    return fallback
  }
  return origin
}

const readRuntimeOriginHint = (
  queryParam: string,
  metaName: string,
  globalName: keyof Pick<YuizakiControlWindow, '__YUIZAKI_CONTROL_ORIGIN__' | '__YUIZAKI_API_ORIGIN__'>,
): string => {
  if (typeof window === 'undefined') return ''
  const globalValue = String((window as YuizakiControlWindow)[globalName] || '').trim()
  if (globalValue) return globalValue
  const metaValue = document.querySelector<HTMLMetaElement>(`meta[name="${metaName}"]`)?.content.trim() || ''
  if (metaValue) return metaValue
  try {
    const currentUrl = new URL(window.location.href)
    return currentUrl.searchParams.get(queryParam)?.trim() || ''
  } catch {
    return ''
  }
}

const currentHttpPageOrigin = (): string => {
  if (typeof window === 'undefined') return ''
  try {
    const { origin, protocol } = window.location
    return protocol === 'http:' || protocol === 'https:' ? origin : ''
  } catch {
    return ''
  }
}

const resolveInitialControlOrigin = (): string => {
  const configured = env.VITE_YUIZAKI_CONTROL_ORIGIN?.trim()
  if (configured) return normalizeLocalOrigin(configured, LOCAL_CONTROL_FALLBACK_ORIGIN)
  const runtimeHint = readRuntimeOriginHint('control_origin', 'yuizaki-control-origin', '__YUIZAKI_CONTROL_ORIGIN__')
  if (runtimeHint) return normalizeLocalOrigin(runtimeHint, LOCAL_CONTROL_FALLBACK_ORIGIN)
  const pageOrigin = env.DEV ? '' : currentHttpPageOrigin()
  return normalizeLocalOrigin(pageOrigin, LOCAL_CONTROL_FALLBACK_ORIGIN)
}

const resolveInitialApiOrigin = (): string => {
  const configured = env.VITE_YUIZAKI_API_ORIGIN?.trim()
  if (configured) return normalizeLocalOrigin(configured, LOCAL_API_FALLBACK_ORIGIN)
  const runtimeHint = readRuntimeOriginHint('api_origin', 'yuizaki-api-origin', '__YUIZAKI_API_ORIGIN__')
  return normalizeLocalOrigin(runtimeHint, LOCAL_API_FALLBACK_ORIGIN)
}

export const API_ORIGIN = resolveInitialApiOrigin()
export const CONTROL_ORIGIN = resolveInitialControlOrigin()
const CONTROL_AUTH_STORAGE_KEY = 'yuizaki.control.token'
const CONTROL_TOKEN_PARAM = 'control_token'
const CONTROL_TOKEN_REFRESH_RETRY_MS = 3_000
const RUNTIME_API_ORIGIN_CACHE_MS = 10_000
const LOCAL_REQUEST_TIMEOUT_MS = 12_000
export const BACKEND_AUTH_MISSING_MESSAGE = '后端服务未授权：请刷新控制页，或从 Electron 应用入口重新打开界面。'
const LOCAL_SERVICE_UNAVAILABLE_MESSAGE = '无法连接本地服务：请确认 Yuizaki 后端和 Electron 控制服务正在运行，然后重启 Electron 窗口重试。'
const localServiceTimeoutMessage = (timeoutMs: number): string =>
  `本地服务响应超时：请求已等待 ${Math.ceil(timeoutMs / 1000)} 秒，请检查后端或控制服务是否卡住。`

export interface LocalRequestInit extends RequestInit {
  timeoutMs?: number
}

class LocalRequestTimeoutError extends Error {}

interface RuntimeEnvCheckResponse {
  pythonApiOrigin?: unknown
}

const isLocalRequestUrl = (url: string): boolean => {
  try {
    const baseUrl = typeof window === 'undefined' ? CONTROL_ORIGIN : window.location.href
    const parsed = new URL(url, baseUrl)
    return parsed.hostname === 'localhost' || parsed.hostname === '127.0.0.1'
  } catch {
    return false
  }
}

const createLocalTimeoutSignal = (
  url: string,
  inputSignal: AbortSignal | null | undefined,
  timeoutMs: number,
): { signal?: AbortSignal; timedOut: () => boolean; dispose: () => void } => {
  if (typeof AbortController === 'undefined' || !isLocalRequestUrl(url)) {
    return { signal: inputSignal ?? undefined, timedOut: () => false, dispose: () => {} }
  }

  const controller = new AbortController()
  let timeoutReached = false
  const abortFromCaller = () => {
    if (!controller.signal.aborted) {
      controller.abort()
    }
  }

  if (inputSignal?.aborted) {
    abortFromCaller()
  } else {
    inputSignal?.addEventListener('abort', abortFromCaller, { once: true })
  }

  const timeoutId = setTimeout(() => {
    timeoutReached = true
    if (!controller.signal.aborted) {
      controller.abort()
    }
  }, timeoutMs)

  return {
    signal: controller.signal,
    timedOut: () => timeoutReached,
    dispose: () => {
      clearTimeout(timeoutId)
      inputSignal?.removeEventListener('abort', abortFromCaller)
    },
  }
}

type TimedResponse = { response: Response; timedOut: () => boolean; dispose: () => void }

const fetchWithLocalTimeout = async (url: string, init: LocalRequestInit): Promise<TimedResponse> => {
  const { timeoutMs = LOCAL_REQUEST_TIMEOUT_MS, ...requestInit } = init
  const normalizedTimeoutMs = Math.max(1_000, Math.trunc(timeoutMs))
  const timeout = createLocalTimeoutSignal(url, requestInit.signal, normalizedTimeoutMs)
  try {
    const response = await fetch(url, {
      ...requestInit,
      signal: timeout.signal,
    })
    return { response, timedOut: timeout.timedOut, dispose: timeout.dispose }
  } catch (error) {
    timeout.dispose()
    // Caller cancellation stays an AbortError; our deadline becomes a visible timeout.
    if (init.signal?.aborted) throw error
    if (timeout.timedOut()) {
      const timeoutError = new LocalRequestTimeoutError(localServiceTimeoutMessage(normalizedTimeoutMs)) as Error & { cause?: unknown }
      timeoutError.cause = error
      throw timeoutError
    }
    throw error
  }
}

const writeInjectedControlToken = (token: string): void => {
  if (typeof window === 'undefined') return
  ;(window as YuizakiControlWindow).__YUIZAKI_CONTROL_TOKEN__ = token
  const existingMeta = document.querySelector<HTMLMetaElement>('meta[name="yuizaki-control-token"]')
  if (existingMeta) {
    existingMeta.content = token
    return
  }
  const meta = document.createElement('meta')
  meta.name = 'yuizaki-control-token'
  meta.content = token
  document.head.appendChild(meta)
}

const readStoredControlToken = (): string => {
  if (typeof window === 'undefined') return ''
  try {
    return window.sessionStorage.getItem(CONTROL_AUTH_STORAGE_KEY) || ''
  } catch {
    return ''
  }
}

const storeControlToken = (token: string): void => {
  if (typeof window === 'undefined') return
  try {
    window.sessionStorage.setItem(CONTROL_AUTH_STORAGE_KEY, token)
  } catch {
    // keep token in memory only when storage is unavailable
  }
}

const rememberControlToken = (token: string, updateInjectedToken = false): string => {
  const cleanToken = token.trim()
  if (!cleanToken) return ''
  inMemoryControlToken = cleanToken
  storeControlToken(cleanToken)
  if (updateInjectedToken) {
    writeInjectedControlToken(cleanToken)
  }
  return cleanToken
}

const readInjectedControlToken = (): string => {
  if (typeof window === 'undefined') return ''
  const globalToken = ((window as YuizakiControlWindow).__YUIZAKI_CONTROL_TOKEN__ || '').trim()
  const metaToken = document
    .querySelector<HTMLMetaElement>('meta[name="yuizaki-control-token"]')
    ?.content
    .trim() || ''
  const token = globalToken || metaToken
  if (!token) return ''
  return rememberControlToken(token)
}

let inMemoryControlToken = ''
let controlTokenRefreshRequest: Promise<string> | null = null
let controlTokenRefreshFailedAt = 0

const hasStaticControlToken = (): boolean => {
  if (inMemoryControlToken) return true
  if (typeof window === 'undefined') return false
  const globalToken = ((window as YuizakiControlWindow).__YUIZAKI_CONTROL_TOKEN__ || '').trim()
  const metaToken = document
    .querySelector<HTMLMetaElement>('meta[name="yuizaki-control-token"]')
    ?.content
    .trim() || ''
  return Boolean(globalToken || metaToken || readStoredControlToken())
}

const hasRuntimeControlOriginHint = (): boolean =>
  Boolean(readRuntimeOriginHint('control_origin', 'yuizaki-control-origin', '__YUIZAKI_CONTROL_ORIGIN__'))

const canBootstrapControlTokenFromServer = (): boolean => {
  if (typeof window === 'undefined') return true
  if (hasStaticControlToken() || hasRuntimeControlOriginHint()) return true
  return currentHttpPageOrigin() === CONTROL_ORIGIN
}

export const clearControlAuthToken = (): void => {
  inMemoryControlToken = ''
  controlTokenRefreshRequest = null
  controlTokenRefreshFailedAt = 0
  clearRuntimeApiOriginCache()
  if (typeof window === 'undefined') return
  try {
    window.sessionStorage.removeItem(CONTROL_AUTH_STORAGE_KEY)
  } catch {
    // storage cleanup is best-effort only
  }
}

const consumeControlTokenFromUrl = (): string => {
  if (typeof window === 'undefined') return ''
  const currentUrl = new URL(window.location.href)
  let token = currentUrl.searchParams.get(CONTROL_TOKEN_PARAM)?.trim() || ''
  let hashUrl: URL | null = null
  if (!token && currentUrl.hash.includes('?')) {
    hashUrl = new URL(currentUrl.hash.slice(1), currentUrl.origin)
    token = hashUrl.searchParams.get(CONTROL_TOKEN_PARAM)?.trim() || ''
  }
  if (!token) return ''
  rememberControlToken(token, true)
  if (hashUrl) {
    hashUrl.searchParams.delete(CONTROL_TOKEN_PARAM)
    currentUrl.hash = `${hashUrl.pathname}${hashUrl.search}${hashUrl.hash}`
  } else {
    currentUrl.searchParams.delete(CONTROL_TOKEN_PARAM)
  }
  window.history.replaceState(window.history.state, '', currentUrl.toString())
  return token
}

const extractControlTokenFromHtml = (html: string): string => {
  const nameFirst = html.match(/<meta[^>]+name=["']yuizaki-control-token["'][^>]+content=["']([^"']+)["'][^>]*>/i)
  if (nameFirst?.[1]) return nameFirst[1].trim()
  const contentFirst = html.match(/<meta[^>]+content=["']([^"']+)["'][^>]+name=["']yuizaki-control-token["'][^>]*>/i)
  return contentFirst?.[1]?.trim() || ''
}

export const refreshControlTokenFromServer = async (): Promise<string> => {
  if (typeof fetch === 'undefined') return ''
  if (!canBootstrapControlTokenFromServer()) {
    controlTokenRefreshFailedAt = Date.now()
    return ''
  }
  const now = Date.now()
  if (!controlTokenRefreshRequest && now - controlTokenRefreshFailedAt < CONTROL_TOKEN_REFRESH_RETRY_MS) {
    return ''
  }
  if (!controlTokenRefreshRequest) {
    controlTokenRefreshRequest = fetchWithLocalTimeout(`${CONTROL_ORIGIN}/`, { cache: 'no-store' })
      .then(async (timed) => {
        try {
          const response = timed.response
          if (!response.ok) return ''
          const token = extractControlTokenFromHtml(await response.text())
          return token ? rememberControlToken(token, true) : ''
        } finally {
          timed.dispose()
        }
      })
      .catch(() => '')
      .then((token) => {
        controlTokenRefreshFailedAt = token ? 0 : Date.now()
        return token
      })
      .finally(() => {
        controlTokenRefreshRequest = null
      })
  }
  return controlTokenRefreshRequest
}

const getControlToken = (): string => {
  const urlToken = consumeControlTokenFromUrl()
  if (urlToken) return urlToken
  const injectedToken = readInjectedControlToken()
  if (injectedToken) return injectedToken
  const storedToken = readStoredControlToken()
  if (storedToken) {
    inMemoryControlToken = storedToken
    return storedToken
  }
  return inMemoryControlToken
}

const isBackendRequest = (url: string): boolean => {
  if (typeof window === 'undefined') return url.startsWith(API_ORIGIN)
  return new URL(url, window.location.href).origin === API_ORIGIN
}

let runtimeApiOrigin = API_ORIGIN
let runtimeApiOriginFetchedAt = 0
let runtimeApiOriginRequest: Promise<string> | null = null

const isLocalBackendOrigin = (origin: string): boolean => {
  try {
    const parsed = new URL(origin)
    return parsed.hostname === 'localhost' || parsed.hostname === '127.0.0.1'
  } catch {
    return false
  }
}

const normalizeRuntimeApiOrigin = (value: unknown): string => {
  if (typeof value !== 'string' || !value.trim()) return runtimeApiOrigin
  return normalizeLocalOrigin(value, runtimeApiOrigin)
}

export const clearRuntimeApiOriginCache = (): void => {
  runtimeApiOrigin = API_ORIGIN
  runtimeApiOriginFetchedAt = 0
  runtimeApiOriginRequest = null
}

export const refreshRuntimeApiOrigin = async (
  authHeaders: Record<string, string> = getControlAuthHeaders(),
): Promise<string> => {
  if (typeof fetch === 'undefined' || !authHeaders.Authorization || !isLocalBackendOrigin(API_ORIGIN)) {
    return runtimeApiOrigin
  }

  const now = Date.now()
  if (now - runtimeApiOriginFetchedAt < RUNTIME_API_ORIGIN_CACHE_MS) {
    return runtimeApiOrigin
  }

  if (!runtimeApiOriginRequest) {
    runtimeApiOriginRequest = fetchWithLocalTimeout(`${CONTROL_ORIGIN}/api/system/env-check`, {
      cache: 'no-store',
      headers: authHeaders,
    })
      .then(async (timed) => {
        try {
          const response = timed.response
          if (!response.ok) return runtimeApiOrigin
          const payload = await response.json() as RuntimeEnvCheckResponse
          runtimeApiOrigin = normalizeRuntimeApiOrigin(payload.pythonApiOrigin)
          runtimeApiOriginFetchedAt = Date.now()
          return runtimeApiOrigin
        } finally {
          timed.dispose()
        }
      })
      .catch(() => runtimeApiOrigin)
      .finally(() => {
        runtimeApiOriginRequest = null
      })
  }

  return runtimeApiOriginRequest
}

const rewriteBackendRequestUrl = async (
  url: string,
  authHeaders: Record<string, string>,
): Promise<string> => {
  if (!isBackendRequest(url)) return url

  const nextOrigin = await refreshRuntimeApiOrigin(authHeaders)
  if (nextOrigin === API_ORIGIN) return url

  const parsedUrl = typeof window === 'undefined'
    ? new URL(url)
    : new URL(url, window.location.href)
  const parsedOrigin = new URL(nextOrigin)
  parsedUrl.protocol = parsedOrigin.protocol
  parsedUrl.host = parsedOrigin.host
  return parsedUrl.toString()
}

export const getControlAuthHeaders = (): Record<string, string> => {
  const token = getControlToken()
  return token ? { Authorization: `Bearer ${token}` } : {}
}

export const hasControlAuthToken = (): boolean => Boolean(getControlToken())
export const getBackendAuthToken = getControlToken
export const getBackendAuthHeaders = getControlAuthHeaders

export const resolveBackendUrl = async (
  pathOrUrl: string,
  authHeaders: Record<string, string> = getControlAuthHeaders(),
): Promise<string> => {
  const rawValue = pathOrUrl.trim()
  if (!rawValue) return rawValue
  if (/^https?:\/\//i.test(rawValue)) return rawValue
  const origin = await refreshRuntimeApiOrigin(authHeaders)
  return `${origin}${rawValue.startsWith('/') ? rawValue : `/${rawValue}`}`
}

const createTraceId = (): string => `trace_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`

export interface HttpClientError extends Error {
  status?: number
  payload?: unknown
  code?: string
  details?: unknown
  retryable?: boolean
  requestId?: string
  requestPath?: string
}

type NormalizedErrorPayload = {
  code?: string
  message?: string
  details?: unknown
  retryable?: boolean
  requestId?: string
}

const normalizeErrorPayload = (payload: unknown): NormalizedErrorPayload => {
  if (!payload || typeof payload !== 'object' || Array.isArray(payload)) return {}
  const value = payload as Record<string, unknown>
  const detail = value.detail
  const structuredDetail = detail && typeof detail === 'object' && !Array.isArray(detail)
    ? detail as Record<string, unknown>
    : {}
  const firstString = (...candidates: unknown[]): string | undefined =>
    candidates.find((candidate): candidate is string => typeof candidate === 'string' && candidate.length > 0)
  const detailMessage = typeof detail === 'string'
    ? detail
    : Array.isArray(detail)
      ? detail.map((item) => item && typeof item === 'object' && 'msg' in item ? String(item.msg) : String(item))
        .join('; ')
      : undefined
  // Prefer canonical fields while accepting older FastAPI HTTPException detail payloads.
  return {
    code: firstString(value.code, structuredDetail.code, structuredDetail.error, value.error),
    message: firstString(value.message, structuredDetail.message, structuredDetail.error, detailMessage, value.error),
    details: value.details !== undefined ? value.details : structuredDetail.details,
    retryable: typeof value.retryable === 'boolean'
      ? value.retryable
      : typeof structuredDetail.retryable === 'boolean' ? structuredDetail.retryable : false,
    requestId: firstString(value.request_id, value.requestId, structuredDetail.request_id, structuredDetail.requestId),
  }
}

const applyErrorPayload = (error: HttpClientError, payload: unknown): void => {
  error.payload = payload
  const normalized = normalizeErrorPayload(payload)
  if (normalized.message) error.message = normalized.message
  if (normalized.code) error.code = normalized.code
  if (normalized.details !== undefined) error.details = normalized.details
  error.retryable = normalized.retryable ?? false
  if (normalized.requestId) error.requestId = normalized.requestId
}

const createClientError = (
  message: string,
  patch: Partial<Pick<HttpClientError, 'status' | 'payload' | 'code' | 'requestPath'>> = {},
): HttpClientError => Object.assign(new Error(message) as HttpClientError, patch)

const throwResponseError = async (response: Response, requestUrl: string, needsLocalAuth: boolean, hasAuthHeader: boolean): Promise<never> => {
  const error = createClientError(`HTTP ${response.status}`, {
    status: response.status,
    requestPath: requestPath(requestUrl),
  })
  try {
    const contentType = response.headers.get('Content-Type') || ''
    if (contentType.includes('application/json')) {
      applyErrorPayload(error, await response.json())
    } else {
      const text = await response.text()
      if (text) {
        error.payload = text
        error.message = text
        error.retryable = false
      }
    }
  } catch (parseError) {
    if (parseError instanceof DOMException && parseError.name === 'AbortError') throw parseError
    error.retryable = false
  }
  if (needsLocalAuth && response.status === 401 && !hasAuthHeader) {
    error.message = BACKEND_AUTH_MISSING_MESSAGE
    error.code = 'auth_missing'
  }
  throw error
}

const requestPath = (url: string): string => {
  try {
    const parsed = new URL(url, CONTROL_ORIGIN)
    return parsed.pathname
  } catch {
    return ''
  }
}

const sendAuthedRequest = async (
  url: string,
  init: LocalRequestInit | undefined,
  traceId: string,
  authHeaders: Record<string, string>,
): Promise<TimedResponse> => fetchWithLocalTimeout(url, {
  cache: 'no-store',
  ...init,
  headers: {
    'x-trace-id': traceId,
    ...authHeaders,
    ...(init?.headers ?? {}),
  },
})

export const isAuthMissingError = (error: unknown): boolean => {
  if (!(error instanceof Error)) return false
  const clientError = error as HttpClientError
  return clientError.code === 'auth_missing' ||
    clientError.status === 401 ||
    error.message.includes('control_token') ||
    error.message.includes('未授权')
}

// Bootstrap requests are shared: cancel the caller's wait without cancelling other callers.
const awaitWithCallerSignal = <T>(pending: Promise<T>, signal?: AbortSignal | null): Promise<T> => {
  if (!signal) return pending
  return new Promise<T>((resolve, reject) => {
    const abort = () => reject(new DOMException('Request aborted', 'AbortError'))
    if (signal.aborted) abort()
    else signal.addEventListener('abort', abort, { once: true })
    pending.then(resolve, reject).finally(() => signal.removeEventListener('abort', abort))
  })
}

// JSON and downloads share authentication, cancellation, retry, and error semantics.
const requestResponse = async <T>(
  url: string,
  init: LocalRequestInit | undefined,
  decode: (response: Response) => Promise<T>,
): Promise<T> => {
  consumeControlTokenFromUrl()
  const ensureRequestActive = () => {
    if (init?.signal?.aborted) {
      throw new DOMException('Request aborted', 'AbortError')
    }
  }
  ensureRequestActive()
  const traceId = createTraceId()
  const needsLocalAuth = isBackendRequest(url)
  let authHeaders = needsLocalAuth ? getControlAuthHeaders() : {}
  let hasAuthHeader = Boolean(authHeaders['Authorization'])
  if (needsLocalAuth && !hasAuthHeader) {
    const refreshedToken = await awaitWithCallerSignal(refreshControlTokenFromServer(), init?.signal)
    ensureRequestActive()
    if (refreshedToken) {
      authHeaders = { Authorization: `Bearer ${refreshedToken}` }
      hasAuthHeader = true
    }
  }
  if (needsLocalAuth && !hasAuthHeader) {
    throw createClientError(BACKEND_AUTH_MISSING_MESSAGE, { code: 'auth_missing' })
  }
  let requestUrl = await awaitWithCallerSignal(rewriteBackendRequestUrl(url, authHeaders), init?.signal)
  ensureRequestActive()
  let response: Response
  let timeoutLease: TimedResponse | undefined
  try {
    const timed = await sendAuthedRequest(requestUrl, init, traceId, authHeaders)
    response = timed.response
    timeoutLease = timed
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error
    if (init?.signal?.aborted) throw error
    if (needsLocalAuth && !hasAuthHeader) {
      throw createClientError(BACKEND_AUTH_MISSING_MESSAGE, { code: 'auth_missing' })
    }
    if (error instanceof LocalRequestTimeoutError) {
      throw createClientError(error.message, { code: 'request_timeout' })
    }
    const detail = error instanceof Error && error.message ? `（${error.message}）` : ''
    throw createClientError(`${LOCAL_SERVICE_UNAVAILABLE_MESSAGE}${detail}`, { code: 'service_unavailable' })
  }
  if (needsLocalAuth && response.status === 401) {
    timeoutLease?.dispose()
    timeoutLease = undefined
    const refreshedToken = await awaitWithCallerSignal(refreshControlTokenFromServer(), init?.signal)
    ensureRequestActive()
    const previousAuthHeader = authHeaders['Authorization'] || ''
    if (refreshedToken && `Bearer ${refreshedToken}` !== previousAuthHeader) {
      try {
        const refreshedAuthHeaders = { Authorization: `Bearer ${refreshedToken}` }
        requestUrl = await awaitWithCallerSignal(rewriteBackendRequestUrl(url, refreshedAuthHeaders), init?.signal)
        ensureRequestActive()
        const timed = await sendAuthedRequest(requestUrl, init, traceId, refreshedAuthHeaders)
        response = timed.response
        timeoutLease = timed
        hasAuthHeader = true
      } catch (error) {
        if (error instanceof DOMException && error.name === 'AbortError') throw error
        if (init?.signal?.aborted) throw error
        if (error instanceof LocalRequestTimeoutError) {
          throw createClientError(error.message, { code: 'request_timeout' })
        }
        const detail = error instanceof Error && error.message ? `（${error.message}）` : ''
        throw createClientError(`${LOCAL_SERVICE_UNAVAILABLE_MESSAGE}${detail}`, { code: 'service_unavailable' })
      }
    }
  }
  if (!response.ok) {
    try {
      return await throwResponseError(response, requestUrl, needsLocalAuth, hasAuthHeader)
    } catch (error) {
      if (timeoutLease?.timedOut() && !(init?.signal?.aborted)) {
        throw createClientError(localServiceTimeoutMessage(Math.max(1_000, Math.trunc(init?.timeoutMs ?? LOCAL_REQUEST_TIMEOUT_MS))), { code: 'request_timeout' })
      }
      throw error
    } finally {
      timeoutLease?.dispose()
    }
  }
  try {
    return await decode(response)
  } catch (error) {
    if (timeoutLease?.timedOut() && !(init?.signal?.aborted)) {
      throw createClientError(localServiceTimeoutMessage(Math.max(1_000, Math.trunc(init?.timeoutMs ?? LOCAL_REQUEST_TIMEOUT_MS))), { code: 'request_timeout' })
    }
    throw error
  } finally {
    timeoutLease?.dispose()
  }
}

export const requestJson = async <T>(url: string, init?: LocalRequestInit): Promise<T> =>
  requestResponse(url, init, (response) => response.json() as Promise<T>)

export const requestBlob = async (url: string, init?: LocalRequestInit): Promise<Blob> =>
  requestResponse(url, init, (response) => response.blob())
