export type DeployCommandCard = {
  title: string
  command: string
}

export type DeployPlatformCommands = {
  label: string
  commands: DeployCommandCard[]
}

export const resolveDeployPlatform = (userAgent: string): 'linux' | 'windows' =>
  /Linux|X11/i.test(userAgent) ? 'linux' : 'windows'

export const buildDeployPlatformCommands = (platform: 'linux' | 'windows'): DeployPlatformCommands => {
  const linux = platform === 'linux'
  const launcher = linux ? './YuizakiLauncher' : 'YuizakiLauncher.exe'
  return {
    label: linux ? 'Linux' : 'Windows',
    commands: [
      { title: '完整启动（含 MCP）', command: launcher },
      { title: '轻量启动（不含 MCP）', command: `${launcher} --no-mcp` },
      { title: '前端调试', command: `${launcher} --dev-renderer` },
    ],
  }
}
