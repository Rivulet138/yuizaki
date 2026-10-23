import appIcon from '../assets/yuizaki/icons/yuizaki-icon.png'
import { t } from '@/i18n'

const slideModules = import.meta.glob('../assets/yuizaki/slides/*.{png,jpg,jpeg,webp}', {
  eager: true,
  import: 'default',
}) as Record<string, string>

const decorationModules = import.meta.glob('../assets/yuizaki/decor/*.{png,jpg,jpeg,webp}', {
  eager: true,
  import: 'default',
}) as Record<string, string>

const slides = Object.entries(slideModules)
  .sort(([a], [b]) => a.localeCompare(b))
  .map(([, url]) => url)

const decorations = Object.fromEntries(
  Object.entries(decorationModules).map(([assetPath, url]) => [
    assetPath.split('/').pop()?.replace(/\.(png|jpe?g|webp)$/i, '') ?? assetPath,
    url,
  ]),
) as Record<string, string>

export const yuizakiConfig = {
  // Brand title and hero copy are locale-dependent, so they are lazy getters:
  // callers spread this config inside components that re-render on locale change.
  get appName(): string { return t('nav.brandWordmark') },
  get heroTitle(): string { return t('misc.heroTitle') },
  get heroSubtitle(): string { return t('misc.heroSubtitle') },
  appIcon,
  slideshowIntervalMs: 5000,
  decorations: {
    letterDecor: decorations['yuizaki-wordmark'] || decorations['yuizaki-letter-decor'] || '',
    ribbonMoon: decorations['yuizaki-ribbon-moon'] || '',
  },
  slides,
}
