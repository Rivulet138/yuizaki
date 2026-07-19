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
export const CONTROL_AUTH_MISSING_MESSAGE = '控制服务未授权：请刷新控制页，或从 Electron 应用入口重新打开界面。'
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

const fetchWithLocalTimeout = async (url: string, init: LocalRequestInit): Promise<Response> => {
  const { timeoutMs = LOCAL_REQUEST_TIMEOUT_MS, ...requestInit } = init
  const normalizedTimeoutMs = Math.max(1_000, Math.trunc(timeoutMs))
  const timeout = createLocalTimeoutSignal(url, requestInit.signal, normalizedTimeoutMs)
  try {
    return await fetch(url, {
      ...requestInit,
      signal: timeout.signal,
    })
  } catch (error) {
    if (timeout.timedOut()) {
      const timeoutError = new LocalRequestTimeoutError(localServiceTimeoutMessage(normalizedTimeoutMs)) as Error & { cause?: unknown }
      timeoutError.cause = error
      throw timeoutError
    }
    throw error
  } finally {
    timeout.dispose()
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

const hasExplicitControlOriginHint = (): boolean =>
  Boolean(env.VITE_YUIZAKI_CONTROL_ORIGIN?.trim()) ||
  Boolean(readRuntimeOriginHint('control_origin', 'yuizaki-control-origin', '__YUIZAKI_CONTROL_ORIGIN__'))

const canBootstrapControlTokenFromServer = (): boolean => {
  if (typeof window === 'undefined') return true
  if (hasStaticControlToken() || hasExplicitControlOriginHint()) return true
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
      .then(async (response) => {
        if (!response.ok) return ''
        const token = extractControlTokenFromHtml(await response.text())
        return token ? rememberControlToken(token, true) : ''
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

const isControlRequest = (url: string): boolean => {
  if (typeof window === 'undefined') return url.startsWith(CONTROL_ORIGIN)
  return new URL(url, window.location.href).origin === CONTROL_ORIGIN
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
      .then(async (response) => {
        if (!response.ok) return runtimeApiOrigin
        const payload = await response.json() as RuntimeEnvCheckResponse
        runtimeApiOrigin = normalizeRuntimeApiOrigin(payload.pythonApiOrigin)
        runtimeApiOriginFetchedAt = Date.now()
        return runtimeApiOrigin
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
  code?: 'auth_missing' | 'service_unavailable' | 'request_timeout'
}

const payloadMessage = (payload: unknown): string | null => {
  if (!payload || typeof payload !== 'object') return null
  if ('message' in payload && typeof payload.message === 'string') return payload.message
  if ('error' in payload && typeof payload.error === 'string') return payload.error
  if ('detail' in payload) {
    const detail = payload.detail
    if (typeof detail === 'string') return detail
    if (Array.isArray(detail)) {
      return detail
        .map((item) => {
          if (typeof item === 'string') return item
          if (item && typeof item === 'object' && 'msg' in item && typeof item.msg === 'string') return item.msg
          return null
        })
        .filter((item): item is string => Boolean(item))
        .join('; ') || null
    }
  }
  return null
}

const getAuthMissingMessage = (url: string): string =>
  isControlRequest(url) ? CONTROL_AUTH_MISSING_MESSAGE : BACKEND_AUTH_MISSING_MESSAGE

const createClientError = (
  message: string,
  patch: Partial<Pick<HttpClientError, 'status' | 'payload' | 'code'>> = {},
): HttpClientError => Object.assign(new Error(message) as HttpClientError, patch)

const sendJsonRequest = async (
  url: string,
  init: LocalRequestInit | undefined,
  traceId: string,
  authHeaders: Record<string, string>,
): Promise<Response> => fetchWithLocalTimeout(url, {
  cache: 'no-store',
  ...init,
  headers: {
    'x-trace-id': traceId,
    ...authHeaders,
    ...(init?.headers ?? {}),
  },
})

const sendAuthedRequest = async (
  url: string,
  init: LocalRequestInit | undefined,
  traceId: string,
  authHeaders: Record<string, string>,
): Promise<Response> => fetchWithLocalTimeout(url, {
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

export const requestJson = async <T>(url: string, init?: LocalRequestInit): Promise<T> => {
  const traceId = createTraceId()
  const needsLocalAuth = isControlRequest(url) || isBackendRequest(url)
  let authHeaders = needsLocalAuth ? getControlAuthHeaders() : {}
  let hasAuthHeader = Boolean(authHeaders['Authorization'])
  if (needsLocalAuth && !hasAuthHeader) {
    const refreshedToken = await refreshControlTokenFromServer()
    if (refreshedToken) {
      authHeaders = { Authorization: `Bearer ${refreshedToken}` }
      hasAuthHeader = true
    }
  }
  if (needsLocalAuth && !hasAuthHeader) {
    throw createClientError(getAuthMissingMessage(url), { code: 'auth_missing' })
  }
  let requestUrl = await rewriteBackendRequestUrl(url, authHeaders)
  let response: Response
  try {
    response = await sendJsonRequest(requestUrl, init, traceId, authHeaders)
  } catch (error) {
    if (needsLocalAuth && !hasAuthHeader) {
      throw createClientError(getAuthMissingMessage(url), { code: 'auth_missing' })
    }
    if (error instanceof LocalRequestTimeoutError) {
      throw createClientError(error.message, { code: 'request_timeout' })
    }
    const detail = error instanceof Error && error.message ? `（${error.message}）` : ''
    throw createClientError(`${LOCAL_SERVICE_UNAVAILABLE_MESSAGE}${detail}`, { code: 'service_unavailable' })
  }
  if (needsLocalAuth && response.status === 401) {
    const refreshedToken = await refreshControlTokenFromServer()
    const previousAuthHeader = authHeaders['Authorization'] || ''
    if (refreshedToken && `Bearer ${refreshedToken}` !== previousAuthHeader) {
      try {
        const refreshedAuthHeaders = { Authorization: `Bearer ${refreshedToken}` }
        requestUrl = await rewriteBackendRequestUrl(url, refreshedAuthHeaders)
        response = await sendJsonRequest(requestUrl, init, traceId, refreshedAuthHeaders)
      } catch (error) {
        if (error instanceof LocalRequestTimeoutError) {
          throw createClientError(error.message, { code: 'request_timeout' })
        }
        const detail = error instanceof Error && error.message ? `（${error.message}）` : ''
        throw createClientError(`${LOCAL_SERVICE_UNAVAILABLE_MESSAGE}${detail}`, { code: 'service_unavailable' })
      }
    }
  }
  if (!response.ok) {
    const error = createClientError(`HTTP ${response.status}`, { status: response.status })
    try {
      error.payload = await response.json()
      const message = payloadMessage(error.payload)
      if (message) {
        error.message = message
      }
    } catch {
      // ignore non-json payloads
    }
    if (needsLocalAuth && response.status === 401 && !hasAuthHeader) {
      error.message = getAuthMissingMessage(url)
      error.code = 'auth_missing'
    }
    throw error
  }
  return response.json() as Promise<T>
}

export const requestBlob = async (url: string, init?: LocalRequestInit): Promise<Blob> => {
  const traceId = createTraceId()
  const needsLocalAuth = isControlRequest(url) || isBackendRequest(url)
  let authHeaders = needsLocalAuth ? getControlAuthHeaders() : {}
  let hasAuthHeader = Boolean(authHeaders['Authorization'])
  if (needsLocalAuth && !hasAuthHeader) {
    const refreshedToken = await refreshControlTokenFromServer()
    if (refreshedToken) {
      authHeaders = { Authorization: `Bearer ${refreshedToken}` }
      hasAuthHeader = true
    }
  }
  if (needsLocalAuth && !hasAuthHeader) {
    throw createClientError(getAuthMissingMessage(url), { code: 'auth_missing' })
  }
  let requestUrl = await rewriteBackendRequestUrl(url, authHeaders)
  let response: Response
  try {
    response = await sendAuthedRequest(requestUrl, init, traceId, authHeaders)
  } catch (error) {
    if (needsLocalAuth && !hasAuthHeader) {
      throw createClientError(getAuthMissingMessage(url), { code: 'auth_missing' })
    }
    if (error instanceof LocalRequestTimeoutError) {
      throw createClientError(error.message, { code: 'request_timeout' })
    }
    const detail = error instanceof Error && error.message ? `: ${error.message}` : ''
    throw createClientError(`${LOCAL_SERVICE_UNAVAILABLE_MESSAGE}${detail}`, { code: 'service_unavailable' })
  }
  if (needsLocalAuth && response.status === 401) {
    const refreshedToken = await refreshControlTokenFromServer()
    const previousAuthHeader = authHeaders['Authorization'] || ''
    if (refreshedToken && `Bearer ${refreshedToken}` !== previousAuthHeader) {
      try {
        const refreshedAuthHeaders = { Authorization: `Bearer ${refreshedToken}` }
        requestUrl = await rewriteBackendRequestUrl(url, refreshedAuthHeaders)
        response = await sendAuthedRequest(requestUrl, init, traceId, refreshedAuthHeaders)
      } catch (error) {
        if (error instanceof LocalRequestTimeoutError) {
          throw createClientError(error.message, { code: 'request_timeout' })
        }
        const detail = error instanceof Error && error.message ? `: ${error.message}` : ''
        throw createClientError(`${LOCAL_SERVICE_UNAVAILABLE_MESSAGE}${detail}`, { code: 'service_unavailable' })
      }
    }
  }
  if (!response.ok) {
    const error = createClientError(`HTTP ${response.status}`, { status: response.status })
    try {
      const contentType = response.headers.get('Content-Type') || ''
      if (contentType.includes('application/json')) {
        error.payload = await response.json()
        const message = payloadMessage(error.payload)
        if (message) {
          error.message = message
        }
      } else {
        const text = await response.text()
        if (text) {
          error.payload = text
          error.message = text
        }
      }
    } catch {
      // ignore unreadable error payloads
    }
    if (needsLocalAuth && response.status === 401 && !hasAuthHeader) {
      error.message = getAuthMissingMessage(url)
      error.code = 'auth_missing'
    }
    throw error
  }
  return response.blob()
}
