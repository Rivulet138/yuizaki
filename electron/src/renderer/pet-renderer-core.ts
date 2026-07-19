import * as PIXI from 'pixi.js'
import { logger } from './logger'

export type CompatiblePixiApp = PIXI.Application & {
  init?: (options: Record<string, unknown>) => Promise<void>
  canvas?: HTMLCanvasElement
  view?: HTMLCanvasElement
}

type PetAssetWindow = Window & typeof globalThis & {
  __YUIZAKI_CONTROL_ORIGIN__?: string
}

const LOCAL_CONTROL_FALLBACK_ORIGIN = 'http://localhost:38945'

const normalizeControlAssetOrigin = (value: string | undefined): string => {
  const origin = (value || LOCAL_CONTROL_FALLBACK_ORIGIN).trim().replace(/\/$/, '')
  try {
    const parsed = new URL(origin)
    if (parsed.hostname === '127.0.0.1') {
      parsed.hostname = 'localhost'
      return parsed.toString().replace(/\/$/, '')
    }
  } catch {
    return LOCAL_CONTROL_FALLBACK_ORIGIN
  }
  return origin
}

const readControlAssetOriginHint = (): string => {
  if (typeof window === 'undefined') return ''
  const globalValue = String((window as PetAssetWindow).__YUIZAKI_CONTROL_ORIGIN__ || '').trim()
  if (globalValue) return globalValue
  const metaValue = document.querySelector<HTMLMetaElement>('meta[name="yuizaki-control-origin"]')?.content.trim() || ''
  if (metaValue) return metaValue
  try {
    const currentUrl = new URL(window.location.href)
    const queryValue = currentUrl.searchParams.get('control_origin')?.trim() || ''
    if (queryValue) return queryValue
    const { origin, protocol } = window.location
    return !import.meta.env.DEV && (protocol === 'http:' || protocol === 'https:') ? origin : ''
  } catch {
    return ''
  }
}

const CONTROL_ASSET_ORIGIN = normalizeControlAssetOrigin(
  import.meta.env.VITE_YUIZAKI_CONTROL_ORIGIN || readControlAssetOriginHint(),
)
const MANAGED_PET_ASSET_PREFIX = '/api/pet/assets/'

export const resolveRendererAsset = (relativePath: string): string => {
  if (relativePath.startsWith(MANAGED_PET_ASSET_PREFIX)) {
    return new URL(relativePath, CONTROL_ASSET_ORIGIN).toString()
  }

  return new URL(relativePath, window.location.href).toString()
}

const CUBISM_CORE_SOURCES = [
  resolveRendererAsset('./live2d/live2dcubismcore.min.js'),
  'https://cubism.live2d.com/sdk-web/cubismcore/live2dcubismcore.min.js',
]

export const createPixiApp = async (options: Record<string, unknown>): Promise<CompatiblePixiApp> => {
  const ApplicationCtor = PIXI.Application as unknown as {
    prototype: { init?: (opts: Record<string, unknown>) => Promise<void> }
    new (opts?: Record<string, unknown>): CompatiblePixiApp
  }

  if (typeof ApplicationCtor.prototype.init === 'function') {
    const app = new ApplicationCtor()
    await app.init!(options)
    return app
  }

  return new ApplicationCtor(options)
}

export const getPixiCanvas = (app: CompatiblePixiApp): HTMLCanvasElement => {
  const canvas = app.canvas ?? app.view
  if (!canvas) {
    throw new Error('PIXI application canvas is unavailable')
  }

  return canvas
}

export const getReadableError = (error: unknown): string => {
  const message = error instanceof Error ? error.message : String(error)

  if (/Failed to load Cubism Core/i.test(message)) {
    return 'Failed to load the Live2D runtime. Check network access or local Cubism Core file.'
  }

  if (/live2dcubismcore\.min\.js|Cubism 4 runtime|Cubism Core/i.test(message)) {
    return 'Live2D Cubism Core is missing. Add live2dcubismcore.min.js to the local live2d folder.'
  }

  return `Failed to load Live2D model: ${message}`
}

const loadCubismCoreScript = (src: string): Promise<void> =>
  new Promise((resolve, reject) => {
    if ((window as Window & { Live2DCubismCore?: unknown }).Live2DCubismCore) {
      resolve()
      return
    }

    const existing = document.querySelector<HTMLScriptElement>(
      `script[data-live2d-core][src="${src}"]`,
    )

    if (existing) {
      existing.addEventListener('load', () => resolve(), { once: true })
      existing.addEventListener(
        'error',
        () => reject(new Error(`Failed to load Cubism Core: ${src}`)),
        { once: true },
      )
      return
    }

    const script = document.createElement('script')
    script.src = src
    script.async = true
    script.dataset.live2dCore = 'true'
    script.onload = () => resolve()
    script.onerror = () => reject(new Error(`Failed to load Cubism Core: ${src}`))
    document.head.appendChild(script)
  })

export const ensureCubismCore = async (): Promise<void> => {
  if ((window as Window & { Live2DCubismCore?: unknown }).Live2DCubismCore) {
    return
  }

  let lastError: unknown = null

  for (const src of CUBISM_CORE_SOURCES) {
    try {
      logger.info('[PetRenderer] loading Cubism Core from:', src)
      await loadCubismCoreScript(src)
      logger.info('[PetRenderer] Cubism Core loaded from:', src)
      return
    } catch (error) {
      lastError = error
      logger.warn('[PetRenderer] Cubism Core source failed:', src, error)
    }
  }

  throw lastError instanceof Error ? lastError : new Error('Live2D Cubism Core runtime is unavailable')
}
