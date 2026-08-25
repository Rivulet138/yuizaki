export type LinuxDesktopSession = 'wayland' | 'x11' | 'unknown' | 'unsupported'

export interface ElectronCommandLine {
  appendSwitch(name: string, value?: string): void
}

export interface ElectronAppCommandLine {
  commandLine: ElectronCommandLine
}

export function resolveLinuxDesktopSession(
  env: NodeJS.ProcessEnv,
  platform: NodeJS.Platform = process.platform,
): LinuxDesktopSession {
  if (platform !== 'linux') return 'unsupported'
  const sessionType = env['XDG_SESSION_TYPE']?.toLowerCase()
  if (env['WAYLAND_DISPLAY'] || sessionType === 'wayland') return 'wayland'
  if (env['DISPLAY'] || sessionType === 'x11') return 'x11'
  return 'unknown'
}

/** Configure Electron's Ozone backend before app.ready for Linux desktop sessions. */
export function configureLinuxDesktop(
  electronApp: ElectronAppCommandLine,
  env: NodeJS.ProcessEnv,
  platform: NodeJS.Platform = process.platform,
): LinuxDesktopSession {
  const session = resolveLinuxDesktopSession(env, platform)
  if (session === 'unsupported') return session

  electronApp.commandLine.appendSwitch('ozone-platform-hint', 'auto')
  if (session === 'wayland') {
    electronApp.commandLine.appendSwitch('ozone-platform', 'wayland')
    electronApp.commandLine.appendSwitch('enable-features', 'WaylandWindowDecorations')
  }
  return session
}
