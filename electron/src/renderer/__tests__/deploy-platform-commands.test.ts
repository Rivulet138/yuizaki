import { describe, expect, it } from 'vitest'
import { buildDeployPlatformCommands, resolveDeployPlatform } from '../domains/deploy/platform-commands'

describe('deploy platform commands', () => {
  it('returns executable POSIX commands on Linux', () => {
    expect(resolveDeployPlatform('Mozilla/5.0 (X11; Linux x86_64)')).toBe('linux')
    expect(buildDeployPlatformCommands('linux')).toEqual({
      label: 'Linux',
      commands: [
        { title: '完整启动（含 MCP）', command: './YuizakiLauncher' },
        { title: '轻量启动（不含 MCP）', command: './YuizakiLauncher --no-mcp' },
        { title: '前端调试', command: './YuizakiLauncher --dev-renderer' },
      ],
    })
  })

  it('keeps the Windows command surface', () => {
    expect(resolveDeployPlatform('Mozilla/5.0 (Windows NT 10.0; Win64; x64)')).toBe('windows')
    expect(buildDeployPlatformCommands('windows').commands[0]?.command).toBe('YuizakiLauncher.exe')
  })
})
