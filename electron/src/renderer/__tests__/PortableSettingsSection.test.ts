import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import PortableSettingsSection from '../domains/settings/components/PortableSettingsSection.vue'
import { settingsClient } from '../api/clients/settings-client'
import { setLocale } from '../i18n'

vi.mock('element-plus', () => ({
  ElMessage: { success: vi.fn() },
}))

const global = {
  stubs: {
    'el-alert': { template: '<div><slot /></div>' },
    'el-button': {
      props: ['loading', 'type', 'plain'],
      emits: ['click'],
      template: '<button @click="$emit(\'click\')"><slot /></button>',
    },
    'el-icon': { template: '<i><slot /></i>' },
    'el-tag': { template: '<span><slot /></span>' },
  },
}

describe('PortableSettingsSection', () => {
  beforeEach(async () => {
    await setLocale('zh-CN', { persistSettings: false })
    vi.restoreAllMocks()
  })

  it('exports a redacted backend config blob as a dated JSON download', async () => {
    const blob = new Blob(['{}'], { type: 'application/json' })
    vi.spyOn(settingsClient, 'exportBlob').mockResolvedValue(blob)
    const createUrl = vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:test')
    const revokeUrl = vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => undefined)
    const click = vi.fn()
    const originalCreateElement = document.createElement.bind(document)
    vi.spyOn(document, 'createElement').mockImplementation((tagName: string) => {
      if (tagName === 'a') return { href: '', download: '', click } as unknown as HTMLElement
      return originalCreateElement(tagName)
    })

    const wrapper = mount(PortableSettingsSection, { global })
    await wrapper.findAll('button')[0]!.trigger('click')
    await flushPromises()

    expect(settingsClient.exportBlob).toHaveBeenCalledOnce()
    expect(createUrl).toHaveBeenCalledWith(blob)
    expect(click).toHaveBeenCalledOnce()
    expect(revokeUrl).toHaveBeenCalledWith('blob:test')
    expect(wrapper.text()).toContain('配置包已下载')
  })

  it('imports a JSON config and emits a refresh signal', async () => {
    const importPayload = vi.spyOn(settingsClient, 'importPayload').mockResolvedValue({
      status: 'imported',
      filepath: 'inline-upload',
      runtime_applied: ['llm.provider'],
      runtime_changed: ['llm.provider'],
    })
    const wrapper = mount(PortableSettingsSection, { global })
    const input = wrapper.find('input[type="file"]')
    const file = new File(['{"llm":{"model":"portable-model"}}'], 'settings.json', { type: 'application/json' })
    Object.defineProperty(input.element, 'files', { configurable: true, value: [file] })
    await input.trigger('change')
    await flushPromises()

    expect(importPayload).toHaveBeenCalledWith({ llm: { model: 'portable-model' } })
    expect(wrapper.emitted('imported')).toHaveLength(1)
    expect(wrapper.text()).toContain('已应用 1 项运行时变更')
  })

  it('flushes pending settings before importing and aborts on a failed flush', async () => {
    const beforeImport = vi.fn().mockResolvedValue(false)
    const importPayload = vi.spyOn(settingsClient, 'importPayload')
    const wrapper = mount(PortableSettingsSection, { global, props: { beforeImport } })
    const input = wrapper.find('input[type="file"]')
    const file = new File(['{"llm":{"model":"portable-model"}}'], 'settings.json', { type: 'application/json' })
    Object.defineProperty(input.element, 'files', { configurable: true, value: [file] })

    await input.trigger('change')
    await flushPromises()

    expect(beforeImport).toHaveBeenCalledOnce()
    expect(importPayload).not.toHaveBeenCalled()
    expect(wrapper.emitted('imported')).toBeUndefined()
    expect(wrapper.text()).toContain('保存配置失败')
  })
})
