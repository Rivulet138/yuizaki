import { readFileSync, readdirSync, statSync } from 'node:fs'
import { resolve } from 'node:path'

const rendererDir = resolve(process.cwd(), 'dist/renderer')
const panelHtml = readFileSync(resolve(rendererDir, 'index.html'), 'utf8')
const petHtml = readFileSync(resolve(rendererDir, 'pet-window.html'), 'utf8')
const assetDir = resolve(rendererDir, 'assets')

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
const iconChunkBudgetBytes = 80 * 1024
if (iconChunkBytes > iconChunkBudgetBytes) {
  throw new Error(`Control panel icon chunks exceed ${iconChunkBudgetBytes} bytes: ${iconChunkBytes}`)
}

const elementPlusChunkBytes = readdirSync(assetDir)
  .filter((name) => /^element-plus~main.*\.js$/i.test(name))
  .reduce((total, name) => total + statSync(resolve(assetDir, name)).size, 0)
const elementPlusChunkBudgetBytes = 400 * 1024
if (elementPlusChunkBytes > elementPlusChunkBudgetBytes) {
  throw new Error(`Control panel Element Plus chunks exceed ${elementPlusChunkBudgetBytes} bytes: ${elementPlusChunkBytes}`)
}

const elementPlusCssBytes = readdirSync(assetDir)
  .filter((name) => /^element-plus~main.*\.css$/i.test(name))
  .reduce((total, name) => total + statSync(resolve(assetDir, name)).size, 0)
const elementPlusCssBudgetBytes = 220 * 1024
if (elementPlusCssBytes > elementPlusCssBudgetBytes) {
  throw new Error(`Control panel Element Plus CSS exceeds ${elementPlusCssBudgetBytes} bytes: ${elementPlusCssBytes}`)
}

console.log(`Renderer bundle audit passed: icon ${iconChunkBytes} bytes; Element Plus JS ${elementPlusChunkBytes} bytes; CSS ${elementPlusCssBytes} bytes`)
