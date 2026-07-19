import path from 'path'

const normalizeFsPath = (inputPath: string): string => path.resolve(inputPath).replace(/\\/g, '/').toLowerCase()

export const isPluginHostAllowed = (allowedHosts: string[] | undefined, targetHost: string): boolean => {
  if (!allowedHosts || allowedHosts.length === 0) {
    return false
  }

  const normalized = targetHost.trim().toLowerCase()
  return allowedHosts.some((host) => host.trim().toLowerCase() === normalized)
}

export const isPluginPathAllowed = (allowedPaths: string[] | undefined, targetPath: string): boolean => {
  if (!allowedPaths || allowedPaths.length === 0) {
    return false
  }

  const normalizedTarget = normalizeFsPath(targetPath)
  return allowedPaths.some((basePath) => {
    const normalizedBase = normalizeFsPath(basePath)
    return normalizedTarget === normalizedBase || normalizedTarget.startsWith(`${normalizedBase}/`)
  })
}

export const isPluginCommandAllowed = (allowedCommands: string[] | undefined, command: string): boolean => {
  if (!allowedCommands || allowedCommands.length === 0) {
    return false
  }

  const normalized = command.trim().toLowerCase()
  return allowedCommands.some((allowedCommand) => allowedCommand.trim().toLowerCase() === normalized)
}

export const getPluginPolicyContext = (
  allowedHosts: string[] | undefined,
  allowedPaths: string[] | undefined,
  allowedCommands: string[] | undefined,
) => ({
  allowedHosts: allowedHosts ?? [],
  allowedPaths: allowedPaths ?? [],
  allowedCommands: allowedCommands ?? [],
})
