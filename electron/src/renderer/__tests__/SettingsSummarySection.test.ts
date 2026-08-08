import { defineComponent } from 'vue'
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import SettingsSummarySection, { type SummarySettings } from '../domains/settings/components/SettingsSummarySection.vue'

const ElInputNumberStub = defineComponent({
  props: ['modelValue'],
  emits: ['update:modelValue', 'change'],
  template: '<button data-testid="change-number" @click="$emit(\'change\', 42)">{{ modelValue }}</button>',
})

const ElSelectStub = defineComponent({
  emits: ['update:modelValue', 'change'],
  template: '<button data-testid="change-scorer" @click="$emit(\'change\', \'llm\')"><slot /></button>',
})

const summary: SummarySettings = {
  trigger_messages: 24,
  keep_recent_messages: 8,
  item_max_chars: 140,
  rewrite_interval_messages: 6,
  quality_scorer_mode: 'rule',
  quality_score_budget_per_hour: 20,
  quality_score_cooldown_seconds: 300,
}

describe('SettingsSummarySection', () => {
  it('emits narrow field updates for summary policy controls', async () => {
    const wrapper = mount(SettingsSummarySection, {
      props: { modelValue: summary },
      global: {
        stubs: {
          'el-card': { template: '<section><slot name="header" /><slot /></section>' },
          'el-form': { template: '<form><slot /></form>' },
          'el-form-item': { props: ['label'], template: '<label>{{ label }}<slot /></label>' },
          'el-input-number': ElInputNumberStub,
          'el-select': ElSelectStub,
          'el-option': { template: '<option><slot /></option>' },
        },
      },
    })

    await wrapper.get('[data-testid="change-number"]').trigger('click')
    await wrapper.get('[data-testid="change-scorer"]').trigger('click')

    expect(wrapper.emitted('update-field')).toContainEqual(['trigger_messages', 42])
    expect(wrapper.emitted('update-field')).toContainEqual(['quality_scorer_mode', 'llm'])
  })
})
