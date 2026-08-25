import { ref } from 'vue'
import type { HttpClientError } from '@/api/clients/http-client'

export interface DomainRequestState<T> {
  data: T | null
  loading: boolean
  error: string | null
  execute: (task: () => Promise<T>) => Promise<T | null>
  reset: () => void
}

/**
 * 统一管理前端异步请求状态：
 * - loading：请求进行中
 * - error：将后端异常归一化为可展示的字符串
 * - data：保存请求结果
 */
export function useDomainRequest<T>(): DomainRequestState<T> {
  const data = ref<T | null>(null)
  const loading = ref(false)
  const error = ref<string | null>(null)
  let requestSequence = 0
  const activeRequestIds = new Set<number>()

  const execute = async (task: () => Promise<T>) => {
    const requestId = ++requestSequence
    activeRequestIds.add(requestId)
    loading.value = true
    error.value = null

    try {
      const result = await task()
      if (requestId === requestSequence) {
        data.value = result
      }
      return result
    } catch (err: unknown) {
      const httpError = err as Partial<HttpClientError>
      const requestLabel = httpError.requestPath ? ` ${httpError.requestPath}` : ''
      console.error(`[DomainRequest Error]${requestLabel}:`, err)
      if (requestId === requestSequence) {
        error.value = httpError.message || '请求失败，请稍后重试'
      }
      return null
    } finally {
      activeRequestIds.delete(requestId)
      loading.value = activeRequestIds.size > 0
    }
  }

  const reset = () => {
    requestSequence += 1
    activeRequestIds.clear()
    data.value = null
    error.value = null
    loading.value = false
  }

  return {
    get data() {
      return data.value as T | null
    },
    get loading() {
      return loading.value
    },
    get error() {
      return error.value
    },
    execute,
    reset,
  }
}
