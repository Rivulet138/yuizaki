import { readFileSync } from 'node:fs'

import { describe, expect, it } from 'vitest'

import { staticNavigationModuleRecords } from '../../shared/navigation'
import { router } from '../router'

const readRenderer = (path: string) => readFileSync(`src/renderer/${path}`, 'utf8')

describe('G005 administration consolidation', () => {
  it('preserves all 17 route IDs, names, and deep links', () => {
    expect(staticNavigationModuleRecords).toHaveLength(17)
    expect(new Set(staticNavigationModuleRecords.map((item) => item.id))).toHaveLength(17)

    for (const item of staticNavigationModuleRecords) {
      expect(router.resolve(`/w/default/${item.id}`).name).toBe(item.id)
    }
  })

  it('presents canonical administration destinations and discloses compatibility routes', () => {
    const sidebar = readRenderer('app/AppSidebar.vue')

    expect(sidebar).toContain("canonicalIds: ['tool']")
    expect(sidebar).toContain("canonicalIds: ['agent-trace']")
    expect(sidebar).toContain("canonicalIds: ['overview', 'infrastructure']")
    expect(sidebar).toContain("relatedIds: ['plugins', 'agent-governance']")
    expect(sidebar).toContain("relatedIds: ['agent-trace-admin']")
    expect(sidebar).toContain("relatedIds: ['deploy']")
    expect(sidebar).toContain('<details')
  })

  it('keeps canonical landings linked to the compatible specialist routes', () => {
    const tool = readRenderer('domains/tools/views/ToolPanel.vue')
    const trace = readRenderer('domains/system/views/AgentTracePanel.vue')
    const overview = readRenderer('domains/system/views/OverviewPanel.vue')

    expect(tool).toContain("canonicalPath('plugins')")
    expect(tool).toContain("canonicalPath('agent-governance')")
    expect(trace).toContain("canonicalPath('agent-trace-admin')")
    expect(overview).toContain("canonicalPath('infrastructure')")
    expect(overview).toContain("canonicalPath('deploy')")
  })

  it('extracts focused Chat and Settings boundaries without moving client ownership', () => {
    const chat = readRenderer('domains/chat/views/ChatPanel.vue')
    const settings = readRenderer('domains/settings/views/SettingsPanel.vue')
    const composerStatus = readRenderer('domains/chat/components/ChatComposerStatusLine.vue')
    const voiceStatus = readRenderer('domains/chat/components/ChatVoiceStatus.vue')
    const settingsAsr = readRenderer('domains/settings/components/SettingsAsrSection.vue')
    const settingsSection = readRenderer('domains/settings/components/SettingsSectionHeader.vue')

    expect(chat).toContain('<ChatComposerStatusLine')
    expect(chat).toContain('<ChatVoiceStatus')
    expect(settings).toContain('<SettingsAsrSection')
    expect(settingsAsr).toContain('<SettingsSectionHeader')
    expect(composerStatus).not.toMatch(/Client\.|fetch\(|requestJson/)
    expect(voiceStatus).not.toMatch(/Client\.|fetch\(|requestJson/)
    expect(settingsAsr).not.toMatch(/Client\.|fetch\(|requestJson/)
    expect(settingsSection).not.toMatch(/Client\.|fetch\(|requestJson/)
  })

  it('does not add duplicate mount-time client calls to extracted boundaries', () => {
    for (const path of [
      'domains/chat/components/ChatComposerStatusLine.vue',
      'domains/chat/components/ChatVoiceStatus.vue',
      'domains/settings/components/SettingsAsrSection.vue',
      'domains/settings/components/SettingsSectionHeader.vue',
    ]) {
      const source = readRenderer(path)
      expect(source).not.toContain('onMounted')
      expect(source).not.toContain('watch(')
    }
  })
})
