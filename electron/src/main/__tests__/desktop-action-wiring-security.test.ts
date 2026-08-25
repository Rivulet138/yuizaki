import { readFileSync, readdirSync, statSync } from 'node:fs'
import path from 'node:path'
import { defineComponent } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { InputBindingRegistrationStatus } from '../../shared/input-bindings'
import SettingsDesktopInputSection from '../../renderer/domains/settings/components/SettingsDesktopInputSection.vue'
import { fenceDesktopActionsWhenHotkeyUnavailable } from '../desktop-action-hotkey-coordinator'

const electronRoot = path.resolve(__dirname, '../../..')

const readSource = (relativePath: string): string =>
  readFileSync(path.join(electronRoot, relativePath), 'utf8')

const listSourceFiles = (directory: string): string[] => readdirSync(directory).flatMap((entry) => {
  const absolutePath = path.join(directory, entry)
  if (statSync(absolutePath).isDirectory()) return listSourceFiles(absolutePath)
  return /\.(?:html|ts|vue)$/.test(entry) && !entry.endsWith('.test.ts') ? [absolutePath] : []
})

const inputBindingStatus = (emergencyStop: boolean): InputBindingRegistrationStatus => ({
  mouseHookAvailable: true,
  pushToTalkActive: true,
  keyboard: {
    interact: true,
    lock: true,
    openPanel: true,
    toggleVision: true,
    emergencyStop,
  },
  errors: [],
})

const desktopActionStatus = (emergencyStopped: boolean) => ({
  enabled: false,
  windowActionsAvailable: true,
  nativeInputAvailable: false,
  emergencyHotkeyAvailable: true,
  emergencyStopped,
  revision: 4,
  stopEpoch: emergencyStopped ? 2 : 0,
  operationInFlight: false,
  degraded: false,
  leaseState: 'inactive' as const,
  leaseExpiresAt: null,
  lastHeartbeatAt: null,
  authorizationGranted: false,
  authorizationExpiresAt: null,
  reason: null,
  lastError: null,
})

const settingsState = () => ({
  settings: {
    pushToTalk: { enabled: true, mouseButton: 4 as const },
    keyboard: {
      interact: 'Control+Space',
      lock: 'Control+L',
      openPanel: 'Control+O',
      toggleVision: 'Control+V',
      emergencyStop: 'Control+Shift+Escape',
    },
  },
  status: inputBindingStatus(true),
  available: true,
  loading: false,
})

const ElButtonStub = defineComponent({
  inheritAttrs: false,
  emits: ['click'],
  template: '<button v-bind="$attrs" @click="$emit(\'click\')"><slot /></button>',
})

const mountSettings = () => mount(SettingsDesktopInputSection, {
  props: { state: settingsState() },
  global: {
    stubs: {
      'el-alert': true,
      'el-button': ElButtonStub,
      'el-card': { template: '<section><slot name="header" /><slot /></section>' },
      'el-form': { template: '<form><slot /></form>' },
      'el-icon': true,
      'el-input': true,
      'el-option': true,
      'el-select': true,
      'el-switch': true,
      'el-tag': { template: '<span><slot /></span>' },
    },
  },
})

describe('desktop action security wiring', () => {
  afterEach(() => {
    Reflect.deleteProperty(window, 'petApi')
  })

  it('creates a fresh dedicated desktop token and passes that token to both host peers', () => {
    const source = readSource('src/main/index.ts')

    expect(source).toMatch(
      /const hostDesktopActionToken = randomBytes\(32\)\.toString\('base64url'\)/,
    )
    expect(source).toMatch(
      /createAuthenticatedDesktopActionBackendPort\([\s\S]*?hostDesktopActionToken[\s\S]*?\)/,
    )
    expect(source).toMatch(
      /new PythonService\([\s\S]*?hostDesktopActionToken[\s\S]*?\)/,
    )
    expect(source).not.toMatch(
      /hostDesktopActionToken\s*=\s*(?:process\.env|controlServer\.getControlToken)/,
    )
  })

  it('does not expose the desktop host token name or secret variable to renderer sources', () => {
    const rendererRoot = path.join(electronRoot, 'src/renderer')
    const rendererSource = listSourceFiles(rendererRoot)
      .map((file) => readFileSync(file, 'utf8'))
      .join('\n')

    expect(rendererSource).not.toContain('YUIZAKI_HOST_DESKTOP_ACTION_TOKEN')
    expect(rendererSource).not.toContain('hostDesktopActionToken')
  })

  it('keeps Settings desktop actions on the closed control-only preload API', () => {
    const source = readSource('src/renderer/domains/settings/components/SettingsDesktopInputSection.vue')

    expect(source).toContain("operation: 'status' | 'enable' | 'disable' | 'rearm' | 'manageAuthorization'")
    expect(source).not.toMatch(/desktopAction\.(?:preview|execute|perform|emergencyStop|heartbeat|renew|invoke)/)
  })

  it('shows Rearm while the emergency-stop latch is set', async () => {
    const stopped = desktopActionStatus(true)
    Object.defineProperty(window, 'petApi', {
      configurable: true,
      value: {
        desktopAction: {
          status: vi.fn(async () => ({ ok: true as const, data: stopped, status: stopped })),
          enable: vi.fn(),
          disable: vi.fn(),
          rearm: vi.fn(),
        },
      },
    })

    const wrapper = mountSettings()
    await flushPromises()

    expect(wrapper.get('[data-testid="desktop-action-rearm"]').text()).toBe('Rearm')
  })

  it('does not stop desktop actions while the emergency hotkey remains registered', () => {
    const bridge = { emergencyStop: vi.fn() }

    const fenced = fenceDesktopActionsWhenHotkeyUnavailable(inputBindingStatus(true), bridge)

    expect(fenced).toBe(false)
    expect(bridge.emergencyStop).not.toHaveBeenCalled()
  })

  it('stops desktop actions immediately when the emergency hotkey becomes unavailable', () => {
    const bridge = { emergencyStop: vi.fn(async () => ({ ok: true as const })) }

    const fenced = fenceDesktopActionsWhenHotkeyUnavailable(inputBindingStatus(false), bridge)

    expect(fenced).toBe(true)
    expect(bridge.emergencyStop).toHaveBeenCalledOnce()
  })
})
