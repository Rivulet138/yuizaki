import { readFileSync } from 'node:fs'
import { compileScript, parse } from '@vue/compiler-sfc'
import { ModuleKind, transpileModule } from 'typescript'
import * as Vue from 'vue'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { createRenderer, h, nextTick, reactive, ssrContextKey } from 'vue'
import type { RuntimeReloadSection, RuntimeReloadStatusResponse } from '@/api/clients/settings-client'
import { settingsPanelMessages } from '@/i18n/settingsPanelMessages'
// Vitest's Node environment compiles SFC imports for SSR. Compile this same SFC
// with its client template so the custom renderer exercises real DOM and events.
const locale = { value: 'en-US' as 'zh-CN' | 'en-US' | 'ja-JP' }
const t = (key: string, params?: Record<string, string>) => {
  const messages = settingsPanelMessages[locale.value] as Record<string, string>
  return (messages[key] ?? key).replace(/\{(\w+)\}/g, (_, name: string) => params?.[name] ?? `{${name}}`)
}
const filename = new URL('./SettingsRuntimeFeedback.vue', import.meta.url)
const { descriptor } = parse(readFileSync(filename, 'utf8'), { filename: filename.pathname })
const script = compileScript(descriptor, { id: 'settings-runtime-feedback-test', inlineTemplate: true })
const compiled = transpileModule(script.content, { compilerOptions: { module: ModuleKind.CommonJS } }).outputText
const componentModule = { exports: {} as { default: Vue.Component } }
new Function('require', 'module', 'exports', compiled)((id: string) => {
  if (id === 'vue') return Vue
  if (id === '@/i18n') return { t }
  throw new Error(`Unexpected component dependency: ${id}`)
}, componentModule, componentModule.exports)
const SettingsRuntimeFeedback = componentModule.exports.default
interface HostNode {
  tag: string
  text: string
  props: Record<string, unknown>
  children: HostNode[]
  parent: HostNode | null
}
const node = (tag = 'root', text = ''): HostNode => ({ tag, text, props: {}, children: [], parent: null })
const remove = (child: HostNode) => {
  if (child.parent) child.parent.children.splice(child.parent.children.indexOf(child), 1)
  child.parent = null
}
const renderer = createRenderer<HostNode, HostNode>({
  createElement: tag => node(tag),
  createText: text => node('#text', text),
  createComment: text => node('#comment', text),
  setText: (element, text) => { element.text = text },
  setElementText: (element, text) => {
    element.children.forEach(child => { child.parent = null })
    element.children = []
    element.text = text
  },
  patchProp: (element, key, _previous, value) => { element.props[key] = value },
  insert(child, parent, anchor) {
    remove(child)
    const index = anchor ? parent.children.indexOf(anchor) : -1
    parent.children.splice(index < 0 ? parent.children.length : index, 0, child)
    child.parent = parent
  },
  remove,
  parentNode: child => child.parent,
  nextSibling: child => {
    const siblings = child.parent?.children ?? []
    return siblings[siblings.indexOf(child) + 1] ?? null
  },
})
const descendants = (root: HostNode): HostNode[] => [root, ...root.children.flatMap(descendants)]
const textContent = (root: HostNode): string => root.tag === '#comment' ? '' : root.text + root.children.map(textContent).join('')
const section = (state: RuntimeReloadSection['state'], revision = 7, error?: string): RuntimeReloadSection => ({
  state, target_revision: revision, applied_revision: null, error,
})
interface Props {
  status: RuntimeReloadStatusResponse | null
  statusError: string
  retryError: string
  loading: boolean
  sectionLabels?: Record<string, string>
}
let app: ReturnType<typeof renderer.createApp> | undefined
const mount = (overrides: Partial<Props> = {}) => {
  const props = reactive<Props>({ status: null, statusError: '', retryError: '', loading: false, ...overrides })
  const retry = vi.fn()
  const refresh = vi.fn()
  const root = node()
  app = renderer.createApp({ render: () => h(SettingsRuntimeFeedback, { ...props, onRetry: retry, onRefresh: refresh }) })
  app.provide(ssrContextKey, { modules: new Set() })
  app.mount(root)
  const find = (tag: string) => descendants(root).filter(element => element.tag === tag)
  const button = (key: 'retryRuntime' | 'refreshRuntime') => find('button').find(element => textContent(element) === settingsPanelMessages[locale.value][`settings.status.${key}`])!
  const click = (element: HostNode) => (element.props.onClick as () => void)()
  return { root, props, retry, refresh, find, button, click, text: () => textContent(root) }
}
afterEach(() => {
  app?.unmount()
  app = undefined
  locale.value = 'en-US'
})

describe('SettingsRuntimeFeedback', () => {
  it.each([null, { sections: {} }, { sections: { llm: section('applied') } }])('stays hidden with no outstanding status or errors: %j', status => {
    const view = mount({ status })
    expect(view.find('section')).toHaveLength(0)
    expect(view.find('button')).toHaveLength(0)
  })

  it('keeps refresh progress visible until the response confirms recovery', async () => {
    const view = mount({ statusError: 'Status unavailable' })
    view.props.loading = true
    view.props.statusError = ''
    await nextTick()
    expect(view.find('section')).toHaveLength(1)
    expect(view.find('section')[0].props['aria-busy']).toBe(true)
    view.props.loading = false
    view.props.status = { sections: { svc: section('applied') } }
    await nextTick()
    expect(view.find('section')).toHaveLength(0)
  })

  it('shows failures immediately and retries only the exact failed and unavailable revisions', () => {
    const view = mount({ status: { sections: {
      llm: section('failed', 12, 'Provider refused the configuration'),
      tts: section('unavailable', 0, 'Service offline'),
      asr: section('pending', 21),
      svc: section('applying', 22),
      memory: section('applied', 23),
    } } })
    expect(view.find('section')).toHaveLength(1)
    expect(view.find('li').map(element => [element.props['data-section'], element.props['data-target-revision']])).toEqual([['llm', 12], ['tts', 0]])
    expect(view.text()).toContain('LLM')
    expect(view.text()).toContain('r12')
    expect(view.text()).toContain('Provider refused the configuration')
    expect(view.text()).toContain('Service offline')
    view.click(view.button('retryRuntime'))
    expect(view.retry).toHaveBeenCalledExactlyOnceWith({ llm: 12, tts: 0 })
    view.click(view.button('refreshRuntime'))
    expect(view.refresh).toHaveBeenCalledExactlyOnceWith()
  })

  it.each(['pending', 'applying'] as const)('shows %s without offering retry', state => {
    const view = mount({ status: { sections: { llm: section(state) } } })
    expect(view.text()).toContain(settingsPanelMessages['en-US']['settings.status.runtimePending'].replace('{items}', 'LLM'))
    expect(view.find('button')).toHaveLength(1)
    view.click(view.button('refreshRuntime'))
    expect(view.refresh).toHaveBeenCalledExactlyOnceWith()
    expect(view.retry).not.toHaveBeenCalled()
  })

  it('uses supplied labels and falls back to uppercase section names', () => {
    const view = mount({
      status: { sections: { llm: section('failed'), tts: section('pending') } },
      sectionLabels: { llm: 'Language model' },
    })
    expect(view.text()).toContain('Language model')
    expect(view.text()).toContain('TTS')
    view.click(view.button('retryRuntime'))
    expect(view.retry).toHaveBeenCalledExactlyOnceWith({ llm: 7 })
  })

  it('disables both actions while loading and re-enables them when loading finishes', async () => {
    const view = mount({ status: { sections: { llm: section('failed') } }, loading: true })
    expect(view.find('section')[0].props['aria-busy']).toBe(true)
    for (const button of view.find('button')) {
      expect(button.props.disabled).toBe(true)
      view.click(button)
    }
    expect(view.retry).not.toHaveBeenCalled()
    expect(view.refresh).not.toHaveBeenCalled()
    view.props.loading = false
    await nextTick()
    expect(view.find('button').every(button => button.props.disabled === false)).toBe(true)
    view.click(view.button('retryRuntime'))
    view.click(view.button('refreshRuntime'))
    expect(view.retry).toHaveBeenCalledExactlyOnceWith({ llm: 7 })
    expect(view.refresh).toHaveBeenCalledExactlyOnceWith()
  })

  it.each(['statusError', 'retryError'] as const)('shows %s even without status and hides after recovery', async error => {
    const view = mount({ [error]: 'Connection lost' })
    expect(view.find('section')).toHaveLength(1)
    expect(view.find('p').filter(element => element.props.role === 'alert')).toHaveLength(1)
    expect(view.text()).toContain('Connection lost')
    if (error === 'statusError') expect(view.text()).toContain(settingsPanelMessages['en-US']['settings.status.runtimeUnknown'])
    view.click(view.button('refreshRuntime'))
    expect(view.refresh).toHaveBeenCalledExactlyOnceWith()
    view.props[error] = ''
    view.props.status = { sections: { llm: section('applied') } }
    await nextTick()
    expect(view.find('section')).toHaveLength(0)
  })

  it('keeps retry available after read and retry errors and clears error messages reactively', async () => {
    const view = mount({ status: { sections: { llm: section('failed', 3) } }, statusError: 'Read failed', retryError: 'Retry failed' })
    expect(view.text()).toContain('Read failed')
    expect(view.text()).toContain('Retry failed')
    view.props.statusError = ''
    view.props.retryError = ''
    view.props.status = { sections: { llm: section('failed', 9), tts: section('failed', 4) } }
    await nextTick()
    expect(view.text()).not.toContain('Read failed')
    expect(view.text()).not.toContain('Retry failed')
    view.click(view.button('retryRuntime'))
    expect(view.retry).toHaveBeenCalledExactlyOnceWith({ llm: 9, tts: 4 })
    view.props.status = { sections: { llm: section('applying', 9) } }
    await nextTick()
    expect(view.find('li')).toHaveLength(0)
    expect(view.find('button')).toHaveLength(1)
    view.props.status = { sections: { llm: section('applied', 9) } }
    await nextTick()
    expect(view.find('section')).toHaveLength(0)
  })

  it.each(['zh-CN', 'en-US', 'ja-JP'] as const)('renders existing translated runtime messages in %s', language => {
    locale.value = language
    const view = mount({ status: { sections: { llm: section('failed'), tts: section('pending') } }, statusError: 'Network' })
    const messages = settingsPanelMessages[language]
    expect(view.text()).toContain(messages['settings.status.runtimeApplication'])
    expect(view.text()).toContain(messages['settings.status.runtimeFailed'].replace('{items}', 'LLM'))
    expect(view.text()).toContain(messages['settings.status.runtimePending'].replace('{items}', 'TTS'))
    expect(view.text()).toContain(messages['settings.status.runtimeUnknown'])
    expect(view.button('retryRuntime')).toBeDefined()
    expect(view.button('refreshRuntime')).toBeDefined()
    expect(view.text()).not.toContain('settings.status.')
  })
})
