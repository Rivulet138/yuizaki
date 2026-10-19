import { readFileSync, readdirSync, statSync } from 'node:fs'
import { resolve } from 'node:path'

const rendererDir = resolve(process.cwd(), 'dist/renderer')
const panelHtml = readFileSync(resolve(rendererDir, 'index.html'), 'utf8')
const petHtml = readFileSync(resolve(rendererDir, 'pet-window.html'), 'utf8')
const assetDir = resolve(rendererDir, 'assets')
const cubismCorePath = resolve(process.cwd(), 'src/renderer/public/live2d/live2dcubismcore.min.js')
const cubismCore = readFileSync(cubismCorePath, 'utf8')

if (!/MocVersion_53/.test(cubismCore) || !/getRenderOrders/.test(cubismCore)) {
  throw new Error('Live2D Cubism Core must be Cubism 5 SDK for Web R5 (MocVersion_53/getRenderOrders)')
}

const mainEntryBytes = readdirSync(assetDir)
  .filter((name) => /^main-[^~].*\.js$/i.test(name))
  .reduce((total, name) => total + statSync(resolve(assetDir, name)).size, 0)
// Keep the control-panel entry bounded so it cannot silently absorb a large
// dependency. The current entry is ~479 KiB; 512 KiB leaves room for small UI
// changes while still failing on a meaningful dependency regression.
const mainEntryBudgetBytes = 512 * 1024
if (mainEntryBytes > mainEntryBudgetBytes) {
  throw new Error(`Control panel main entry exceeds ${mainEntryBudgetBytes} bytes: ${mainEntryBytes}`)
}

const panelHeavyRuntimePattern = /modulepreload[^>]+(?:live2d|pixi|three)-vendor/i
if (panelHeavyRuntimePattern.test(panelHtml)) {
  throw new Error('Control panel entry must not preload Live2D, Pixi, or Three runtime chunks')
}
if (!/modulepreload[^>]+live2d-vendor/i.test(petHtml)) {
  throw new Error('Desktop pet entry must preload its Live2D runtime chunk')
}

const iconChunkBytes = readdirSync(assetDir)
  .filter((name) => /^element-icons~main.*\.js$/i.test(name))
  .reduce((total, name) => total + statSync(resolve(assetDir, name)).size, 0)
if (iconChunkBytes > 80 * 1024) {
  throw new Error(`Control panel icon chunks exceed ${80 * 1024} bytes: ${iconChunkBytes}`)
}

const elementPlusChunkBytes = readdirSync(assetDir)
  .filter((name) => /^element-plus~main.*\.js$/i.test(name))
  .reduce((total, name) => total + statSync(resolve(assetDir, name)).size, 0)
if (elementPlusChunkBytes > 400 * 1024) {
  throw new Error(`Control panel Element Plus chunks exceed ${400 * 1024} bytes: ${elementPlusChunkBytes}`)
}

const elementPlusCssBytes = readdirSync(assetDir)
  .filter((name) => /^element-plus~main.*\.css$/i.test(name))
  .reduce((total, name) => total + statSync(resolve(assetDir, name)).size, 0)
if (elementPlusCssBytes > 220 * 1024) {
  throw new Error(`Control panel Element Plus CSS exceeds ${220 * 1024} bytes: ${elementPlusCssBytes}`)
}

console.log(`Renderer bundle audit passed: main ${mainEntryBytes} bytes; icon ${iconChunkBytes} bytes; Element Plus JS ${elementPlusChunkBytes} bytes; CSS ${elementPlusCssBytes} bytes`)
