import { net, protocol } from 'electron'
import path from 'node:path'
import { pathToFileURL } from 'node:url'

export const PACKAGED_RENDERER_SCHEME = 'yuizaki-app'
export const PACKAGED_RENDERER_HOST = 'renderer'
export type PackagedRendererEntry = 'index.html' | 'pet-window.html'

export const resolvePackagedRendererRoot = (): string =>
  path.resolve(__dirname, '../../dist/renderer')

export const buildPackagedRendererUrl = (
  entry: PackagedRendererEntry,
  query?: Record<string, string>,
): string => {
  const url = new URL(`${PACKAGED_RENDERER_SCHEME}://${PACKAGED_RENDERER_HOST}/${entry}`)
  for (const [key, value] of Object.entries(query ?? {})) {
    url.searchParams.set(key, value)
  }
  return url.toString()
}

const decodeRequestPath = (rawUrl: string): string | null => {
  const authorityPrefix = `${PACKAGED_RENDERER_SCHEME}://${PACKAGED_RENDERER_HOST}`
  if (!rawUrl.startsWith(authorityPrefix)) return null
  const rawPath = rawUrl.slice(authorityPrefix.length).split(/[?#]/, 1)[0] || '/'
  try {
    const decoded = decodeURIComponent(rawPath)
    if (decoded.includes('\0')) return null
    const segments = decoded.split(/[\\/]+/)
    if (segments.some(segment => segment === '..')) return null
    return decoded
  } catch {
    return null
  }
}

export const resolveRendererRequestFile = (
  rawUrl: string,
  rendererRoot = resolvePackagedRendererRoot(),
): string | null => {
  let url: URL
  try {
    url = new URL(rawUrl)
  } catch {
    return null
  }
  if (url.protocol !== `${PACKAGED_RENDERER_SCHEME}:` || url.hostname !== PACKAGED_RENDERER_HOST) {
    return null
  }

  const decodedPath = decodeRequestPath(rawUrl)
  if (decodedPath === null) return null
  const relativeRequestPath = decodedPath.replace(/^[\\/]+/, '') || 'index.html'
  const root = path.resolve(rendererRoot)
  const target = path.resolve(root, relativeRequestPath)
  const relative = path.relative(root, target)
  if (!relative || relative.startsWith('..') || path.isAbsolute(relative)) {
    return null
  }
  return target
}

export const registerRendererProtocolPrivileges = (): void => {
  protocol.registerSchemesAsPrivileged([
    {
      scheme: PACKAGED_RENDERER_SCHEME,
      privileges: {
        standard: true,
        secure: true,
        supportFetchAPI: true,
        codeCache: true,
      },
    },
  ])
}

export const registerRendererProtocol = (): void => {
  protocol.handle(PACKAGED_RENDERER_SCHEME, (request) => {
    if (request.method !== 'GET' && request.method !== 'HEAD') {
      return new Response(null, { status: 405, headers: { allow: 'GET, HEAD' } })
    }
    const filePath = resolveRendererRequestFile(request.url)
    if (!filePath) {
      return new Response('Not found', { status: 404 })
    }
    return net.fetch(pathToFileURL(filePath).toString(), { method: request.method })
  })
}
