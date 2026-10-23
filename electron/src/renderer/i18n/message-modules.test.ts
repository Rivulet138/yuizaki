import { describe, expect, it } from 'vitest'

import { connectorPaneMessages } from './connectorPaneMessages'
import { deployMessages } from './deployMessages'
import { infrastructureMessages } from './infrastructureMessages'
import { keyGapMessages } from './keyGapMessages'
import { pluginPanelMessages } from './pluginPanelMessages'
import { toolPanelMessages } from './toolPanelMessages'
import { governancePanelMessages } from './governancePanelMessages'
import { overviewPanelMessages } from './overviewPanelMessages'
import { agentTracePanelMessages } from './agentTracePanelMessages'
import { petControlPanelMessages } from './petControlPanelMessages'
import { chatPanelMessages } from './chatPanelMessages'
import { promptAndPetPanelMessages } from './promptAndPetPanelMessages'
import { settingsSectionsMessages } from './settingsSectionsMessages'
import { memoryComponentsMessages } from './memoryComponentsMessages'
import { errorMessages } from './errorMessages'
import { appChromeMessages } from './appChromeMessages'
import { runtimeMessages } from './runtimeMessages'
import { memoryPanelMessages } from './memoryPanelMessages'
import { settingsPanelMessages } from './settingsPanelMessages'
import { productMetricsMessages } from './productMetricsMessages'

type Table = Record<string, string>

const LOCALES = ['zh-CN', 'en-US', 'ja-JP'] as const

/**
 * Per-module invariants for every localised message module.
 *
 * Add a module here when you add one: this is the cheap gate that catches a key
 * added to one locale only, which used to surface as a Chinese string on the
 * English and Japanese builds.
 */
const modules: Array<{ name: string; tables: Record<string, Table> }> = [
  { name: 'connectorPaneMessages', tables: connectorPaneMessages as unknown as Record<string, Table> },
  { name: 'deployMessages', tables: deployMessages as unknown as Record<string, Table> },
  { name: 'infrastructureMessages', tables: infrastructureMessages as unknown as Record<string, Table> },
  { name: 'keyGapMessages', tables: keyGapMessages as unknown as Record<string, Table> },
  { name: 'productMetricsMessages', tables: productMetricsMessages as unknown as Record<string, Table> },
  { name: 'pluginPanelMessages', tables: pluginPanelMessages as unknown as Record<string, Table> },
  { name: 'toolPanelMessages', tables: toolPanelMessages as unknown as Record<string, Table> },
  { name: 'governancePanelMessages', tables: governancePanelMessages as unknown as Record<string, Table> },
  { name: 'overviewPanelMessages', tables: overviewPanelMessages as unknown as Record<string, Table> },
  { name: 'agentTracePanelMessages', tables: agentTracePanelMessages as unknown as Record<string, Table> },
  { name: 'petControlPanelMessages', tables: petControlPanelMessages as unknown as Record<string, Table> },
  { name: 'chatPanelMessages', tables: chatPanelMessages as unknown as Record<string, Table> },
  { name: 'promptAndPetPanelMessages', tables: promptAndPetPanelMessages as unknown as Record<string, Table> },
  { name: 'settingsSectionsMessages', tables: settingsSectionsMessages as unknown as Record<string, Table> },
  { name: 'memoryComponentsMessages', tables: memoryComponentsMessages as unknown as Record<string, Table> },
  { name: 'errorMessages', tables: errorMessages as unknown as Record<string, Table> },
  { name: 'appChromeMessages', tables: appChromeMessages as unknown as Record<string, Table> },
  { name: 'runtimeMessages', tables: runtimeMessages as unknown as Record<string, Table> },
  { name: 'memoryPanelMessages', tables: memoryPanelMessages as unknown as Record<string, Table> },
  { name: 'settingsPanelMessages', tables: settingsPanelMessages as unknown as Record<string, Table> },
]

const placeholders = (value: string): string[] =>
  [...value.matchAll(/\{([A-Za-z0-9_]+)\}/g)].map((match) => match[1]).sort()

describe.each(modules)('$name', ({ tables }) => {
  it('defines the same keys in every locale', () => {
    const zh = Object.keys(tables['zh-CN']).sort()
    for (const locale of LOCALES) {
      expect(Object.keys(tables[locale]).sort(), locale).toEqual(zh)
    }
  })

  it('has no empty translation', () => {
    for (const locale of LOCALES) {
      for (const [key, value] of Object.entries(tables[locale])) {
        expect(value.trim(), `${locale} ${key}`).not.toBe('')
      }
    }
  })

  it('keeps the same placeholders in every locale', () => {
    for (const key of Object.keys(tables['zh-CN'])) {
      const expected = placeholders(tables['zh-CN'][key])
      for (const locale of LOCALES) {
        // A locale that drops `{name}` renders the sentence with the value
        // missing entirely, which is worse than an untranslated string.
        expect(placeholders(tables[locale][key]), `${locale} ${key}`).toEqual(expected)
      }
    }
  })
})
