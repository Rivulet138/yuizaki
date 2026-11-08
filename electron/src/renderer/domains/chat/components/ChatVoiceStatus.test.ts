import { readFileSync } from 'node:fs'
import { parse, type SFCTemplateBlock } from '@vue/compiler-sfc'
import { createSSRApp, h } from 'vue'
import { renderToString } from '@vue/server-renderer'
import { ID_INJECTION_KEY } from 'element-plus'
import { describe, expect, it, vi } from 'vitest'
import ChatVoiceStatus from './ChatVoiceStatus.vue'

vi.mock('@/i18n', () => ({ t: (key: string) => key }))
vi.mock('element-plus/es/components/icon/style/css', () => ({}))
vi.mock('element-plus/es/components/segmented/style/css', () => ({}))

describe('chat recording controls', () => {
  it('binds the parent recording state to the voice controls', () => {
    const source = readFileSync(new URL('../views/ChatPanel.vue', import.meta.url), 'utf8')
    const { descriptor } = parse(source)
    const template = descriptor.template as SFCTemplateBlock
    const children = template.ast!.children
    const findVoiceControl = (nodes: typeof children): typeof children[number] | undefined => {
      for (const node of nodes) {
        if (node.type !== 1) continue
        if (node.tag === 'ChatVoiceStatus') return node
        const child = findVoiceControl(node.children)
        if (child) return child
      }
    }
    const control = findVoiceControl(children)
    expect(control?.type).toBe(1)
    if (control?.type !== 1) throw new Error('ChatVoiceStatus missing')
    const recording = control.props.find(prop => prop.type === 7 && prop.name === 'bind'
      && prop.arg?.type === 4 && prop.arg.content === 'recording')
    expect(recording?.type === 7 && recording.exp?.type === 4 && recording.exp.content).toBe('isRecording')
  })

  it.each(['hold', 'tap'])('renders recording and idle states in %s mode', async (mode) => {
    const render = (recording: boolean) => {
      const app = createSSRApp({
        render: () => h(ChatVoiceStatus, {
          recording, mode, modeOptions: [], holdActive: false, connected: true,
          shortcutTitle: '', interruptible: false, showRecoveryAction: false,
        }),
      })
      app.provide(ID_INJECTION_KEY, { prefix: 1, current: 0 })
      return renderToString(app)
    }
    const active = await render(true)
    const idle = await render(false)
    expect(active).toMatch(/class="(?=[^"]*\bhold-to-talk\b)(?=[^"]*\bactive\b)[^"]*"/)
    expect(idle).not.toMatch(/class="(?=[^"]*\bhold-to-talk\b)(?=[^"]*\bactive\b)[^"]*"/)
    expect(active).toContain(mode === 'hold' ? 'releaseToSend' : 'stopRecording')
    expect(idle).toContain(mode === 'hold' ? 'holdToTalk' : 'voiceInput')
  })
})
