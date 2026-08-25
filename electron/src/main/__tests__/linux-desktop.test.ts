import { describe, expect, it } from 'vitest'
import { configureLinuxDesktop, resolveLinuxDesktopSession } from '../linux-desktop'

describe('Linux desktop session setup', () => {
  it('detects Wayland from either standard session signal', () => {
    expect(resolveLinuxDesktopSession({ WAYLAND_DISPLAY: 'wayland-0' }, 'linux')).toBe('wayland')
    expect(resolveLinuxDesktopSession({ XDG_SESSION_TYPE: 'wayland' }, 'linux')).toBe('wayland')
  })

  it('configures Electron Ozone for Wayland before startup', () => {
    const switches: Array<[string, string | undefined]> = []
    const session = configureLinuxDesktop(
      { commandLine: { appendSwitch: (name, value) => switches.push([name, value]) } },
      { WAYLAND_DISPLAY: 'wayland-0' },
      'linux',
    )
    expect(session).toBe('wayland')
    expect(switches).toEqual([
      ['ozone-platform-hint', 'auto'],
      ['ozone-platform', 'wayland'],
      ['enable-features', 'WaylandWindowDecorations'],
    ])
  })

  it('leaves Windows and macOS command lines untouched', () => {
    const switches: string[] = []
    const session = configureLinuxDesktop(
      { commandLine: { appendSwitch: (name) => switches.push(name) } },
      { WAYLAND_DISPLAY: 'wayland-0' },
      'win32',
    )
    expect(session).toBe('unsupported')
    expect(switches).toEqual([])
  })
})
