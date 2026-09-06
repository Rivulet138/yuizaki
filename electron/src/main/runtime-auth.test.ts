import { describe, expect, it, vi } from 'vitest'
import { HOST_DESKTOP_ACTION_TOKEN_ENV, resolveHostDesktopActionToken } from './runtime-auth'

describe('desktop action host token resolution', () => {
  it('uses an explicitly shared token for externally managed Python', () => {
    const generated = vi.fn(() => 'generated')
    expect(resolveHostDesktopActionToken({ [HOST_DESKTOP_ACTION_TOKEN_ENV]: '  shared  ' }, generated)).toBe('shared')
    expect(generated).not.toHaveBeenCalled()
  })

  it('generates a token when no explicit token is configured', () => {
    const generated = vi.fn(() => 'generated')
    expect(resolveHostDesktopActionToken({}, generated)).toBe('generated')
    expect(generated).toHaveBeenCalledOnce()
  })
})
