export const HOST_DESKTOP_ACTION_TOKEN_ENV = 'YUIZAKI_HOST_DESKTOP_ACTION_TOKEN'

export function resolveHostDesktopActionToken(
  environment: Record<string, string | undefined>,
  generateToken: () => string,
): string {
  const configured = environment[HOST_DESKTOP_ACTION_TOKEN_ENV]?.trim()
  return configured || generateToken()
}
