import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const readRendererSource = (path: string) => readFileSync(
  resolve(process.cwd(), 'src/renderer', path),
  'utf8',
)

const extractMediaBlock = (source: string, maxWidth: number) => {
  const marker = new RegExp(`@media\\s*\\(max-width:\\s*${maxWidth}px\\)\\s*\\{`, 'g')
  const blocks: string[] = []
  let match: RegExpExecArray | null

  while ((match = marker.exec(source))) {
    const bodyStart = match.index + match[0].length
    let depth = 1
    let cursor = bodyStart
    while (cursor < source.length && depth > 0) {
      if (source[cursor] === '{') depth += 1
      if (source[cursor] === '}') depth -= 1
      cursor += 1
    }
    blocks.push(source.slice(bodyStart, cursor - 1))
  }

  return blocks.join('\n')
}

const ruleBodiesFor = (css: string, selector: string) => {
  const bodies: string[] = []
  const rule = /([^{}]+)\{([^{}]*)\}/g
  let match: RegExpExecArray | null
  while ((match = rule.exec(css))) {
    const selectors = match[1].split(',').map((value) => value.trim())
    if (selectors.includes(selector)) bodies.push(match[2])
  }
  return bodies.join('\n')
}

const targetSize = (declarations: string, axis: 'width' | 'height') => {
  const minimum = declarations.match(new RegExp(`min-${axis}\\s*:\\s*(\\d+)px`))
  const fixed = declarations.match(new RegExp(`(?:^|[;\\s])${axis}\\s*:\\s*(\\d+)px`))
  return Number(minimum?.[1] ?? fixed?.[1] ?? 0)
}

describe('responsive shell and chat contracts', () => {
  it('keeps the compact composer on one row with horizontal overflow for both tool groups', () => {
    const source = readRendererSource('domains/chat/views/ChatPanel.vue')
    const compactCss = extractMediaBlock(source, 900)
    const toolbar = ruleBodiesFor(compactCss, '.composer-toolbar')
    const leftTools = ruleBodiesFor(compactCss, '.composer-tools-left')
    const rightTools = ruleBodiesFor(compactCss, '.composer-tools-right')

    expect(toolbar).not.toMatch(/flex-direction\s*:\s*column/)
    expect(`${leftTools}\n${rightTools}`.match(/overflow-x\s*:\s*auto/g)).toHaveLength(2)
    expect(`${leftTools}\n${rightTools}`.match(/flex-wrap\s*:\s*nowrap/g)).toHaveLength(2)
  })

  it('provides at least 44px topbar icon targets at 720px and below', () => {
    const source = readRendererSource('app/AppTopbar.vue')
    const compactCss = extractMediaBlock(source, 720)
    const iconActions = ruleBodiesFor(compactCss, '.icon-action')
    const windowButtons = ruleBodiesFor(compactCss, '.win-btn')

    expect(targetSize(iconActions, 'width')).toBeGreaterThanOrEqual(44)
    expect(targetSize(iconActions, 'height')).toBeGreaterThanOrEqual(44)
    expect(targetSize(windowButtons, 'width')).toBeGreaterThanOrEqual(44)
    expect(targetSize(windowButtons, 'height')).toBeGreaterThanOrEqual(44)
  })
})
