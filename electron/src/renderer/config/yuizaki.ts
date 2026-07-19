import appIcon from '../assets/yuizaki/icons/yuizaki-icon.png'

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
  appName: '結崎',
  heroTitle: '結崎 · 本地桌宠 Agent',
  heroSubtitle: '桌宠对话、Live2D/VRM 模型、长期记忆与本地工具的本地角色入口',
  appIcon,
  slideshowIntervalMs: 5000,
  decorations: {
    letterDecor: decorations['yuizaki-wordmark'] || decorations['yuizaki-letter-decor'] || '',
    ribbonMoon: decorations['yuizaki-ribbon-moon'] || '',
  },
  slides,
}
