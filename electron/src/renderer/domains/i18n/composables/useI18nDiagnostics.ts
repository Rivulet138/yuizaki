import { computed, onMounted, onScopeDispose, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { setLocale as setFrontendLocale, useI18n } from '@/i18n'
import { i18nClient } from '@/api/client'
import { describeFailure } from '@/shared/errors/describe-error'

export function useI18nDiagnostics() {
  const loading = ref(false)
  const locales = ref<string[]>([])
  const localeNames = ref<Record<string, string>>({})
  const currentLocale = ref('')
  const selectedLocale = ref('')
  const messages = ref<Record<string, unknown>>({})
  const messageKey = ref('')
  const lastLookup = ref('')
  const lookupFailed = ref(false)
  const loadError = ref('')
  const syncingLocale = ref(false)
  const applyingBackendLocale = ref(false)
  const { locale, localeLabel, supportedLocales, t } = useI18n()
  const selectedFrontendLocale = ref(locale.value)
  let localeSequence = 0
  let lookupSequence = 0
  const lookupKind = ref<'message' | 'error' | ''>('')
  const localeBusy = computed(() => syncingLocale.value || applyingBackendLocale.value)

  const messagesPreview = computed(() => JSON.stringify(messages.value, null, 2))
  const backendLocaleLabel = (locale: string) => localeNames.value[locale] ? `${localeNames.value[locale]} · ${locale}` : locale

  const loadAll = async () => {
    if (localeBusy.value || loading.value) return
    const requestId = ++localeSequence
    const selectedAtStart = selectedLocale.value
    loading.value = true
    loadError.value = ''
    try {
      const localeData = await i18nClient.locales()
      if (requestId !== localeSequence) return
      locales.value = localeData.available
      localeNames.value = localeData.localeNames
      const messageData = await i18nClient.messages(localeData.current)
      if (requestId !== localeSequence) return
      currentLocale.value = localeData.current
      if (selectedLocale.value === selectedAtStart) selectedLocale.value = localeData.current
      messages.value = messageData.messages
    } catch (error) {
      if (requestId !== localeSequence) return
      loadError.value = describeFailure(error, t('misc.backendDiagnosticsLoadFailed'))
      console.warn('Failed to load backend translation diagnostics', error)
    } finally {
      if (requestId === localeSequence) loading.value = false
    }
  }

  const applyAppLocale = async () => {
    if (localeBusy.value || !selectedFrontendLocale.value) return
    const requestId = ++localeSequence
    loading.value = false
    const nextLocale = selectedFrontendLocale.value
    const selectedAtStart = selectedLocale.value
    syncingLocale.value = true
    loadError.value = ''
    let backendApplied = false
    try {
      await setFrontendLocale(nextLocale)
      if (requestId !== localeSequence || locale.value !== nextLocale) return
      const backendResult = await i18nClient.setLocale(nextLocale)
      if (requestId !== localeSequence) return
      backendApplied = true
      currentLocale.value = backendResult.locale
      messages.value = {}
      const messageData = await i18nClient.messages(backendResult.locale)
      if (requestId !== localeSequence) return
      currentLocale.value = backendResult.locale
      if (selectedLocale.value === selectedAtStart) selectedLocale.value = backendResult.locale
      messages.value = messageData.messages
      ElMessage.success(t('language.changed'))
    } catch (error) {
      if (requestId !== localeSequence) return
      loadError.value = describeFailure(error, t('misc.backendLocaleSwitchFailed'))
      if (backendApplied) ElMessage.error(loadError.value)
      else ElMessage.warning(t('common.localOnly'))
    } finally {
      syncingLocale.value = false
    }
  }

  const applyBackendLocale = async () => {
    if (localeBusy.value || !selectedLocale.value) return
    const requestId = ++localeSequence
    loading.value = false
    const nextLocale = selectedLocale.value
    applyingBackendLocale.value = true
    loadError.value = ''
    try {
      const result = await i18nClient.setLocale(nextLocale)
      if (requestId !== localeSequence) return
      currentLocale.value = result.locale
      messages.value = {}
      const messageData = await i18nClient.messages(result.locale)
      if (requestId !== localeSequence) return
      currentLocale.value = result.locale
      messages.value = messageData.messages
      ElMessage.success(result.message || t('language.changed'))
    } catch (error) {
      if (requestId !== localeSequence) return
      const message = describeFailure(error, t('misc.backendLocaleSwitchFailed'))
      loadError.value = message
      ElMessage.error(message)
    } finally {
      applyingBackendLocale.value = false
    }
  }

  const lookup = async (kind: 'message' | 'error') => {
    const key = messageKey.value.trim()
    if (!key) return
    const requestedLocale = selectedLocale.value || currentLocale.value || undefined
    const requestId = ++lookupSequence
    lookupKind.value = kind
    lastLookup.value = ''
    lookupFailed.value = false
    const isCurrent = () => requestId === lookupSequence
      && key === messageKey.value.trim()
      && requestedLocale === (selectedLocale.value || currentLocale.value || undefined)
    try {
      const result = kind === 'message'
        ? await i18nClient.message(key, requestedLocale)
        : await i18nClient.errorMessage(key, requestedLocale)
      if (isCurrent()) lastLookup.value = result.message
    } catch (error) {
      if (!isCurrent()) return
      const message = describeFailure(error, t(kind === 'message' ? 'misc.translationLookupFailed' : 'misc.errorMessageLookupFailed'))
      lastLookup.value = message
      lookupFailed.value = true
      ElMessage.error(message)
    } finally {
      if (requestId === lookupSequence) lookupKind.value = ''
    }
  }

  const lookupMessage = () => lookup('message')
  const lookupError = () => lookup('error')

  watch([messageKey, selectedLocale, currentLocale], () => {
    lookupSequence += 1
    lookupKind.value = ''
    lastLookup.value = ''
    lookupFailed.value = false
  }, { flush: 'sync' })

  onMounted(() => {
    void loadAll()
  })

  watch(locale, (value, previous) => {
    if (selectedFrontendLocale.value === previous) selectedFrontendLocale.value = value
  })

  onScopeDispose(() => {
    localeSequence += 1
    lookupSequence += 1
  })
  return {
    loading, locales, currentLocale, selectedLocale, messages, messageKey, lastLookup, lookupFailed, loadError,
    syncingLocale, applyingBackendLocale, localeBusy, lookupKind, locale, localeLabel, supportedLocales,
    selectedFrontendLocale, messagesPreview, backendLocaleLabel, loadAll, applyAppLocale, applyBackendLocale,
    lookupMessage, lookupError, t,
  }
}
