import { describe, expect, it } from 'vitest'

import { localeTables } from './index'

/**
 * Table-level invariants for the shipped locales.
 *
 * These are the checks that keep a translation gap from becoming a user-visible
 * bug. They run on the *resolved* tables, so they cover the inline literals in
 * `index.ts`, every `*Messages.ts` module, and the ja-JP override layer at once.
 */

const LOCALES = ['zh-CN', 'en-US', 'ja-JP'] as const

/** Han characters. A locale that is not zh-CN must not be showing any. */
const HAN = /[\u3400-\u4dbf\u4e00-\u9fff]/

/**
 * Simplified-only characters: Japanese shinjitai never uses these forms, so a
 * ja-JP value containing one is Chinese text that was never translated.
 */
const SIMPLIFIED_ONLY =
  /[这说们个时对门问题让还关闭删设证据页显视图标记录载网络误连确认启动储忆语乐频档继续暂统项务处从后边为员变单选应该读级别类层组织间无夹缓调试运弹输态权块库备归换编]/

/**
 * Endonyms are written in their own language on purpose: a language picker that
 * renders "Japanese" instead of "日本語" is worse than a mixed-script list.
 */
const ENDONYM_KEYS = new Set([
  'language.zh',
  'language.japanese',
  'language.english',
  'misc.localeChinese',
  'misc.localeJapanese',
])

const placeholders = (value: string): string[] =>
  [...value.matchAll(/\{([A-Za-z0-9_]+)\}/g)].map((match) => match[1]).sort()

const entries = (locale: (typeof LOCALES)[number]) => Object.entries(localeTables[locale])

describe('locale coverage', () => {
  it('defines the same key set in every locale', () => {
    const zh = Object.keys(localeTables['zh-CN']).sort()
    for (const locale of LOCALES) {
      expect(Object.keys(localeTables[locale]).sort(), locale).toEqual(zh)
    }
  })

  it('has no empty translation', () => {
    for (const locale of LOCALES) {
      for (const [key, value] of entries(locale)) {
        expect(value.trim(), `${locale} ${key}`).not.toBe('')
      }
    }
  })

  it('keeps the same placeholders in every locale', () => {
    for (const key of Object.keys(localeTables['zh-CN'])) {
      const expected = placeholders(localeTables['zh-CN'][key])
      for (const locale of LOCALES) {
        // Dropping `{name}` renders the sentence with the value missing, which
        // is worse for the user than an untranslated string.
        expect(placeholders(localeTables[locale][key]), `${locale} ${key}`).toEqual(expected)
      }
    }
  })

  it('keeps en-US free of Chinese', () => {
    const offenders = entries('en-US')
      .filter(([key, value]) => HAN.test(value) && !ENDONYM_KEYS.has(key))
      .map(([key]) => key)
    expect(offenders).toEqual([])
  })

  it('keeps ja-JP free of simplified Chinese characters', () => {
    const offenders = entries('ja-JP')
      .filter(([, value]) => SIMPLIFIED_ONLY.test(value))
      .map(([key]) => key)
    expect(offenders).toEqual([])
  })
})
