import { defineComponent } from 'vue'
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import SettingsResourcesSection from '../domains/settings/components/SettingsResourcesSection.vue'

const ElButtonStub = defineComponent({
  inheritAttrs: false,
  emits: ['click'],
  template: '<button v-bind="$attrs" @click="$emit(\'click\', $event)"><slot /></button>',
})

describe('SettingsResourcesSection', () => {
  it('renders progress and emits the top-level resource commands', async () => {
    const wrapper = mount(SettingsResourcesSection, {
      props: {
        resourceMessage: '下载进行中',
        resourceMessageType: 'info',
        resourceLoading: false,
        storageLoading: false,
        cancellableResourceIds: ['sherpa'],
        resourceCancelLoading: false,
        activeDownloadProgress: [{
          resourceId: 'sherpa',
          phase: 'downloading',
          message: '正在下载',
          bytesDownloaded: 1024,
          bytesTotal: 2048,
          percent: 50,
          startedAt: '2026-08-07T09:00:00.000Z',
          updatedAt: '2026-08-07T09:00:01.000Z',
        }],
        resourceView: null,
        selectedResourceIds: ['sherpa'],
        resourceDownloadOptions: [{
          id: 'sherpa',
          label: '离线语音识别',
          ready: false,
          version: '1.0.0',
          license: 'Apache-2.0',
          downloadBytes: 2048,
          resumable: null,
        }],
        storageStatus: null,
        resourceActionKey: '',
        storageActionKey: '',
      },
      global: {
        stubs: {
          'el-alert': { props: ['title'], template: '<div>{{ title }}</div>' },
          'el-button': ElButtonStub,
          'el-card': { template: '<section><slot name="header" /><slot /></section>' },
          'el-checkbox': { template: '<label><slot /></label>' },
          'el-checkbox-group': { template: '<div><slot /></div>' },
          'el-empty': { template: '<div />' },
          'el-progress': { template: '<div />' },
          'el-table': { template: '<div><slot /></div>' },
          'el-table-column': { template: '<div><slot /></div>' },
          'el-tag': { template: '<span><slot /></span>' },
        },
      },
    })

    expect(wrapper.text()).toContain('下载进行中')
    expect(wrapper.text()).toContain('正在下载')

    const buttons = wrapper.findAll('button')
    await buttons.find((button) => button.text().includes('刷新'))?.trigger('click')
    await buttons.find((button) => button.text().includes('取消下载'))?.trigger('click')
    await buttons.find((button) => button.text().includes('下载选中项'))?.trigger('click')

    expect(wrapper.emitted('refresh')).toEqual([[]])
    expect(wrapper.emitted('cancel-downloads')).toEqual([[]])
    expect(wrapper.emitted('download-selected')).toEqual([[]])
  })
})
