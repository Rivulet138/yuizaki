import { defineComponent } from 'vue'
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import SettingsMemorySection, { type MemorySettings } from '../domains/settings/components/SettingsMemorySection.vue'

const ElButtonStub = defineComponent({
  inheritAttrs: false,
  emits: ['click'],
  template: '<button v-bind="$attrs" @click="$emit(\'click\')"><slot /></button>',
})

const ElRadioGroupStub = defineComponent({
  emits: ['change'],
  template: '<button data-testid="select-qdrant" @click="$emit(\'change\', \'qdrant\')"><slot /></button>',
})

const ElSwitchStub = defineComponent({
  emits: ['change'],
  template: '<button data-testid="toggle-reranker" @click="$emit(\'change\', true)">toggle</button>',
})

const memory = (): MemorySettings => ({
  backend: 'sqlite',
  sqlite_path: 'python/data/memory.db',
  qdrant_url: 'http://127.0.0.1:6333',
  qdrant_api_key: '',
  qdrant_collection: 'memories',
  qdrant_timeout: 10,
  qdrant_auto_start: false,
  qdrant_docker_image: 'qdrant/qdrant:v1.18.3',
  qdrant_docker_container: 'yuizaki-qdrant',
  qdrant_docker_volume: 'yuizaki-qdrant-storage',
  embedding_model: 'Qwen/Qwen3-Embedding-0.6B',
  reranker_enabled: false,
  reranker_model: 'BAAI/bge-reranker-v2-m3',
  reranker_candidate_count: 32,
})

const mountSection = () => mount(SettingsMemorySection, {
  props: {
    modelValue: memory(),
    discoveryLoading: false,
    rebuildLoading: false,
  },
  global: {
    stubs: {
      'el-button': ElButtonStub,
      'el-card': { template: '<section><slot name="header" /><slot /></section>' },
      'el-form': { template: '<form><slot /></form>' },
      'el-form-item': { props: ['label'], template: '<label>{{ label }}<slot /></label>' },
      'el-icon': { template: '<i><slot /></i>' },
      'el-input': true,
      'el-input-number': true,
      'el-radio-button': { template: '<span><slot /></span>' },
      'el-radio-group': ElRadioGroupStub,
      'el-switch': ElSwitchStub,
    },
  },
})

describe('SettingsMemorySection', () => {
  it('exposes memory commands without owning runtime side effects', async () => {
    const wrapper = mountSection()

    await wrapper.get('[data-testid="discover-memory"]').trigger('click')
    await wrapper.get('[data-testid="rebuild-memory"]').trigger('click')
    await wrapper.get('[data-testid="select-qdrant"]').trigger('click')
    await wrapper.get('[data-testid="toggle-reranker"]').trigger('click')

    expect(wrapper.emitted('discover-local')).toEqual([[]])
    expect(wrapper.emitted('rebuild')).toEqual([[]])
    expect(wrapper.emitted('change-backend')).toEqual([['qdrant']])
    expect(wrapper.emitted('update-field')).toContainEqual(['reranker_enabled', true])
  })

  it('keeps SQLite and Qdrant controls mutually scoped', async () => {
    const wrapper = mountSection()
    expect(wrapper.text()).toContain('SQLite 存储文件')

    await wrapper.setProps({ modelValue: { ...memory(), backend: 'qdrant', qdrant_auto_start: true } })
    expect(wrapper.text()).not.toContain('SQLite 存储文件')
    expect(wrapper.text()).toContain('Qdrant URL')
    expect(wrapper.text()).toContain('Qdrant Docker 镜像')
  })
})
