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
  const start = linux ? './start.sh' : 'start.bat'
  return {
    label: linux ? 'Linux' : 'Windows',
    commands: [
      { title: '统一启动', command: start },
      { title: '带 MCP 启动', command: `${start} --with-mcp` },
      { title: '前端调试', command: `${start} --dev-renderer` },
      { title: '后端调试', command: linux ? './scripts/run_backend_dev.sh' : 'scripts\\run_backend_dev.bat' },
    ],
  }
}
