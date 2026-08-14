import { mount } from '@vue/test-utils'
import ElementPlus, { ElSelect, ElSwitch } from 'element-plus'
import { describe, expect, it } from 'vitest'
import { DEFAULT_PET_CONTROL_STATE, type PetModelDefinition } from '../../shared/pet-control'
import PetModelManager from '../domains/pet/components/PetModelManager.vue'
import PetResidenceControls from '../domains/pet/components/PetResidenceControls.vue'

const mountResidence = (overrides: Record<string, unknown> = {}) => mount(PetResidenceControls, {
  props: {
    state: { ...DEFAULT_PET_CONTROL_STATE, ready: true },
    displayLabel: 'Display 1 · 1920×1080',
    loading: false,
    pendingAction: null,
    ...overrides,
  },
  global: { plugins: [ElementPlus] },
})

const model: PetModelDefinition = {
  id: 'local:yui',
  name: 'Yui',
  type: 'live2d',
  source: 'local',
  modelPath: 'E:/models/yui/yui.model3.json',
  motions: [{ id: 'idle:0', label: 'Idle', group: 'Idle', index: 0 }],
  expressions: [{ id: 'happy', label: 'Happy', kind: 'expression' }],
  emotions: [],
  manifest: null,
  promptContext: '',
}

const mountModels = (overrides: Record<string, unknown> = {}) => mount(PetModelManager, {
  props: {
    models: [model],
    currentModel: model,
    sourceLabel: 'Local',
    capabilities: {
      revision: 'live2d:local:yui:1',
      modelType: 'live2d',
      modelId: model.id,
      generatedAt: 1,
      actions: {
        behavior: true,
        affect: true,
        gaze: false,
        motion: true,
        expression: true,
        parameterPatch: false,
        viseme: false,
        cancel: true,
      },
      expressions: ['happy'],
      motions: [{ group: 'Idle', index: 0 }],
      parameters: [],
    },
    syncHint: '',
    sourcePlaceholder: '.model3.json',
    loading: false,
    refreshing: false,
    pendingAction: null,
    optionLabel: (item: PetModelDefinition) => item.name,
    selectedModelId: model.id,
    localModelType: 'live2d',
    sourcePath: '',
    ...overrides,
  },
  global: { plugins: [ElementPlus] },
})

describe('desktop pet control components', () => {
  it('offers one explicit fullscreen adjustment action and blocks conflicts while adjusting', async () => {
    const wrapper = mountResidence()
    await wrapper.get('.pet-residence__primary').trigger('click')
    expect(wrapper.emitted('begin-adjustment')).toHaveLength(1)

    await wrapper.setProps({ state: { ...DEFAULT_PET_CONTROL_STATE, ready: true, interactMode: true } })
    expect(wrapper.get('.pet-residence__primary').attributes('disabled')).toBeDefined()
    const switches = wrapper.findAllComponents(ElSwitch)
    expect(switches[0]?.props('disabled')).toBe(true)
    expect(switches[1]?.props('disabled')).toBe(true)
    expect(switches[2]?.props('disabled')).toBe(false)
  })

  it('forwards residence settings as normalized boolean events', () => {
    const wrapper = mountResidence()
    const switches = wrapper.findAllComponents(ElSwitch)
    switches[0]?.vm.$emit('change', true)
    switches[1]?.vm.$emit('change', false)
    switches[2]?.vm.$emit('change', true)

    expect(wrapper.emitted('update-click-through')?.[0]).toEqual([true])
    expect(wrapper.emitted('update-locked')?.[0]).toEqual([false])
    expect(wrapper.emitted('update-dnd')?.[0]).toEqual([true])
  })

  it('keeps model actions focused and exposes supported capability state', async () => {
    const wrapper = mountModels({ pendingAction: 'model-apply', loading: true })
    const select = wrapper.getComponent(ElSelect)
    select.vm.$emit('update:modelValue', 'bundled:other')
    await wrapper.vm.$nextTick()
    expect(wrapper.emitted('update:selectedModelId')?.[0]).toEqual(['bundled:other'])

    const capabilities = wrapper.findAll('.pet-model-manager__capabilities span')
    expect(capabilities).toHaveLength(4)
    expect(capabilities.filter((item) => item.classes('supported'))).toHaveLength(2)
    expect(capabilities.map((item) => item.attributes('aria-label'))).toEqual(expect.arrayContaining([
      expect.stringMatching(/Expression|表达|表情/),
      expect.stringMatching(/Gaze|注视|視線/),
    ]))
    expect(wrapper.find('.pet-model-manager__danger').exists()).toBe(true)
  })

  it('renders a focused empty-state import action without model controls', () => {
    const wrapper = mountModels({ models: [], currentModel: null, capabilities: null })
    expect(wrapper.find('.pet-model-manager__selection').exists()).toBe(false)
    expect(wrapper.find('.pet-model-manager__empty').exists()).toBe(true)
    expect(wrapper.find('.pet-model-manager__danger').exists()).toBe(false)
  })
})
