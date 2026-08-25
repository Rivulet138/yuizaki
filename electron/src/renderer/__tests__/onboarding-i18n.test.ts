import { describe, expect, it } from 'vitest'
import { onboardingMessages } from '../i18n/onboardingMessages'

describe('onboarding locale parity', () => {
  it('keeps zh-CN, en-US, and ja-JP keys identical', () => {
    const locales = Object.values(onboardingMessages)
    const expected = Object.keys(locales[0]!).sort()
    for (const messages of locales.slice(1)) expect(Object.keys(messages).sort()).toEqual(expected)
  })
})
