import { describe, expect, it, afterEach } from 'vitest'

import { hasMessage, setLocale, t } from './index'

/**
 * The locales are deliberately partial: ja-JP ships far fewer strings than
 * zh-CN. A missing key must fall back to zh-CN rather than render the raw key,
 * because that is what a user sees mid-conversation.
 */
describe('message lookup with partial locales', () => {
  afterEach(async () => {
    await setLocale('zh-CN', { persistSettings: false })
  })

  it('returns the zh-CN string for a key a partial locale does not define', async () => {
    await setLocale('ja-JP', { persistSettings: false })
    // Ja-JP relies on the zh fallback for keys it has not translated yet.
    expect(hasMessage('companion.home.showPet', 'ja-JP')).toBe(false)
    expect(t('companion.home.showPet')).not.toBe('')
    expect(t('companion.home.showPet')).not.toBe('companion.home.showPet')
  })

  it('still prefers the locale string when it exists', async () => {
    await setLocale('en-US', { persistSettings: false })
    expect(t('companion.home.showPet')).toBe('Show pet')
  })

  it('interpolates params after the fallback resolves', async () => {
    await setLocale('ja-JP', { persistSettings: false })
    const text = t('settings.storage.cleaned', { files: 3, size: '2 MB' })
    expect(text).not.toContain('{files}')
    expect(text).toContain('3')
  })

  it('returns the key itself for an unknown key so failures stay visible', async () => {
    await setLocale('zh-CN', { persistSettings: false })
    expect(t('nope.not.a.key')).toBe('nope.not.a.key')
  })
})
