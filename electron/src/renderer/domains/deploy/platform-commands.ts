import { t } from '@/i18n'

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
      { title: t('misc.deployFullLaunch'), command: launcher },
      { title: t('misc.deployLiteLaunch'), command: `${launcher} --no-mcp` },
      { title: t('misc.deployFrontendDebug'), command: `${launcher} --dev-renderer` },
    ],
  }
}
