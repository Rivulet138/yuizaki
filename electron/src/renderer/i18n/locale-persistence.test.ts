import { describe, expect, it, vi } from 'vitest'
import { settingsClient } from '@/api/clients/settings-client'
import { currentLocale, setLocale } from './index'

vi.mock('@/api/clients/settings-client', () => ({ settingsClient: { save: vi.fn() } }))

describe('locale persistence ordering', () => {
  it('finishes with the latest locale and never resends a stale theme', async () => {
    let finishFirst!: (value: { status: string }) => void
    const firstSave = new Promise<{ status: string }>((resolve) => { finishFirst = resolve })
    vi.mocked(settingsClient.save).mockReturnValueOnce(firstSave).mockResolvedValue({ status: 'ok' })
    const first = setLocale('en-US')
    await Promise.resolve()
    const second = setLocale('ja-JP')
    const last = setLocale('zh-CN')
    expect(currentLocale.value).toBe('zh-CN')
    finishFirst({ status: 'ok' })
    await Promise.all([first, second, last])
    expect(settingsClient.save).toHaveBeenCalledTimes(2)
    expect(settingsClient.save).toHaveBeenNthCalledWith(1, { system: { language: 'en-US' } })
    expect(settingsClient.save).toHaveBeenLastCalledWith({ system: { language: 'zh-CN' } })
    expect(currentLocale.value).toBe('zh-CN')
  })
})
