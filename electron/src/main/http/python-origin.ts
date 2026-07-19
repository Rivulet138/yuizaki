export const resolvePythonApiOrigin = (): string => {
  const explicitUrl = process.env['DESKTOP_PET_BACKEND_URL']?.trim()
  if (explicitUrl) {
    const withoutTrailingSlash = explicitUrl.replace(/\/$/, '')
    return withoutTrailingSlash.endsWith('/health')
      ? withoutTrailingSlash.slice(0, -'/health'.length)
      : withoutTrailingSlash
  }

  const host = process.env['SERVER_HOST']?.trim() || 'localhost'
  const port = process.env['SERVER_PORT']?.trim() || '8001'
  return `http://${host}:${port}`
}
