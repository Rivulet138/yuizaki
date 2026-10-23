import { describe, expect, it } from 'vitest'

import { hasMessage, localeTables, normalizeLocale, setLocale, t } from './index'

/**
 * Lookup behaviour, as opposed to table contents (see `coverage.test.ts`).
 *
 * The locales used to be partial: ja-JP defined far fewer strings than zh-CN and
 * a lookup fell through to Chinese, which is exactly the bug users reported.
 * Every locale is complete now, so these tests pin the behaviour that must
 * survive: a defined key never renders as itself in any locale, and an unknown
 * key stays visible instead of silently becoming an empty string.
 */
describe('message lookup', () => {
  const restoreLocale = () => setLocale('zh-CN', { persistSettings: false })

  it('resolves every zh-CN key in every locale', () => {
    for (const key of Object.keys(localeTables['zh-CN'])) {
      for (const locale of ['zh-CN', 'en-US', 'ja-JP'] as const) {
        expect(hasMessage(key, locale), `${locale} ${key}`).toBe(true)
      }
    }
  })

  it('interpolates params', () => {
    const text = t('settings.storage.cleaned', { files: 3, size: '2 MB' })
    expect(text).not.toContain('{files}')
    expect(text).toContain('3')
    expect(text).toContain('2 MB')
  })

  it('returns the key itself for an unknown key so failures stay visible', () => {
    expect(t('nope.not.a.key')).toBe('nope.not.a.key')
    expect(hasMessage('nope.not.a.key', 'en-US')).toBe(false)
  })

  it('normalizes locale tags', () => {
    expect(normalizeLocale('en-GB')).toBe('en-US')
    expect(normalizeLocale('ja')).toBe('ja-JP')
    expect(normalizeLocale('jp-JP')).toBe('ja-JP')
    expect(normalizeLocale('fr-FR')).toBe('zh-CN')
    expect(normalizeLocale(undefined)).toBe('zh-CN')
  })

  it('switches the active locale', async () => {
    await setLocale('en-US', { persistSettings: false })
    expect(t('language.english')).toBe('English')
    await restoreLocale()
  })
})
