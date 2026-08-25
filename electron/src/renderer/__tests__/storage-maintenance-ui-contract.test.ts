import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const source = readFileSync(
  resolve(process.cwd(), 'src/renderer/domains/settings/views/SettingsPanel.vue'),
  'utf8',
)
const clientSource = readFileSync(
  resolve(process.cwd(), 'src/renderer/api/clients/resource-client.ts'),
  'utf8',
)
const resourceStatusSource = readFileSync(
  resolve(process.cwd(), 'src/renderer/domains/settings/resourceStatus.ts'),
  'utf8',
)
const proxySource = readFileSync(
  resolve(process.cwd(), 'src/main/http/routes/system-routes.ts'),
  'utf8',
)

describe('storage maintenance UI contract', () => {
  it('exposes canonical storage categories and permanent actions only', () => {
    expect(resourceStatusSource).toContain('tts_audio')
    expect(resourceStatusSource).toContain('runtime_temp')
    expect(resourceStatusSource).toContain('visual_frames')
    expect(source).toContain('cleanupStorage')
    expect(clientSource).toContain('PERMANENT_CLEAN')
    expect(source).not.toContain('softDeleteStorage')
    expect(proxySource).toContain("'/api/system/storage'")
    expect(proxySource).toContain("'/api/system/storage/cleanup'")
  })

  it('reuses the resource refresh orchestration during initialization', () => {
    expect(source).toContain('await Promise.all([refreshResourcePanel(), loadTtsStatus(), loadLlmStatus()])')
    expect(source).not.toContain('await Promise.all([loadResourceStatus(), loadStorageStatus(), loadTtsStatus()])')
  })
})
