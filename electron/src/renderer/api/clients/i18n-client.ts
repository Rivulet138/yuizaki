import { CONTROL_ORIGIN, requestJson } from './http-client'

export interface I18nLocalesResponse {
  available: string[]
  current: string
  localeNames: Record<string, string>
}

export interface I18nMessagesResponse {
  locale?: string
  messages: Record<string, unknown>
}

export interface I18nLocaleMutationResponse {
  status: string
  locale: string
  message?: string
}

export const i18nClient = {
  locales: async () => requestJson<I18nLocalesResponse>(`${CONTROL_ORIGIN}/api/i18n/locales`),
  messages: async (locale?: string) => {
    const query = locale ? `?locale=${encodeURIComponent(locale)}` : ''
    return requestJson<I18nMessagesResponse>(`${CONTROL_ORIGIN}/api/i18n/messages${query}`)
  },
  setLocale: async (locale: string) =>
    requestJson<I18nLocaleMutationResponse>(`${CONTROL_ORIGIN}/api/i18n/locale?locale=${encodeURIComponent(locale)}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ locale }),
    }),
  message: async (key: string, locale?: string) => {
    const query = locale ? `?locale=${encodeURIComponent(locale)}` : ''
    return requestJson<{ message: string }>(`${CONTROL_ORIGIN}/api/i18n/message/${encodeURIComponent(key)}${query}`)
  },
  errorMessage: async (key: string, locale?: string) => {
    const query = locale ? `?locale=${encodeURIComponent(locale)}` : ''
    return requestJson<{ message: string }>(`${CONTROL_ORIGIN}/api/i18n/error/${encodeURIComponent(key)}${query}`)
  },
}
