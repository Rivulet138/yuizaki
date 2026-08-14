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
    const source = readRendererSource('domains/chat/views/ChatPanel.css')
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

  it('caches model discovery per provider while keeping the selected model visible', () => {
    const source = readRendererSource('domains/chat/views/ChatPanel.vue')
    expect(source).toContain('const modelOptionsProviderKey = ref(\'\')')
    expect(source).toContain('if (!force && modelOptionsProviderKey.value === providerKey && modelOptions.value.length)')
    expect(source).toContain('settingsStore.state.llm.model,')
    expect(source).toContain('chatOptions.model,')
  })

  it('keeps desktop pet controls reachable from the conversation surface', () => {
    const source = readRendererSource('domains/chat/views/ChatPanel.vue')

    expect(source).toContain('data-testid="chat-pet-settings"')
    expect(source).toContain('openPetSettings')
    expect(source).toContain('/pet`')
  })

  it('keeps playback controls in the composer and removes the redundant advice strip', () => {
    const source = readRendererSource('domains/chat/views/ChatPanel.vue')
    expect(source).toContain('<ChatPlaybackBar')
    expect(source).toContain('@toggle-pet-link="togglePetLink"')
    expect(source).not.toContain('advice-strip')
  })

  it('uses a stable chat surface and disables the unused wallpaper blur layer', () => {
    const source = readRendererSource('app/AppShell.vue')

    expect(source).toMatch(/\.app-main\.chat-mode\s*\{[\s\S]*background:\s*var\(--yui-chat-page-bg\)/)
    expect(source).toMatch(/\.wallpaper-blur\s*\{[\s\S]*display:\s*none/)
  })

  it('keeps wallpaper subordinate to functional panel content', () => {
    const source = readRendererSource('app/AppShell.vue')

    expect(source).toMatch(/\.wallpaper-mask\s*\{[\s\S]*background:\s*var\(--yui-panel-wallpaper-mask\)/)
    expect(source).toMatch(/\.wallpaper-on\s+\.wallpaper-layer\s*\{[\s\S]*opacity:\s*var\(--yui-panel-wallpaper-opacity\)/)
    expect(source).toContain('--yui-panel-wallpaper-opacity: 1')
    expect(source).toContain('--yui-chat-wallpaper-opacity: 1')
    expect(source).toContain('--yui-chat-page-bg: transparent')
    expect(source).toContain('--yui-chat-wallpaper-mask: transparent')
  })

  it('keeps functional panels inside a complete translucent boundary without backdrop blur', () => {
    const source = readRendererSource('shared/components/panel/PanelShell.vue')
    const basePanel = source.match(/\.panel-shell\s*\{([^}]*)\}/)?.[1] ?? ''

    expect(basePanel).toMatch(/border\s*:\s*1px solid var\(--yui-panel-outline/)
    expect(basePanel).toMatch(/background\s*:\s*var\(--yui-panel-surface/)
    expect(basePanel).not.toContain('backdrop-filter')
    expect(basePanel).toMatch(/background-clip\s*:\s*padding-box/)
  })

  it('lazy-renders every main settings tab', () => {
    const source = readRendererSource('domains/settings/views/SettingsPanel.vue')
    const tabPanes = source.match(/<el-tab-pane\b[^>]*>/g) || []

    expect(tabPanes).toHaveLength(8)
    expect(tabPanes.every((pane) => /\slazy(?:\s|>)/.test(pane))).toBe(true)
  })
})
