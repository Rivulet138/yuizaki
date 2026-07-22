import { app, desktopCapturer } from 'electron'
import path from 'path'
import { ControlServer } from './control-server'
import { Live2DWindow } from './live2d-window'
import { PetStateStore } from './pet-state-store'
import { PetShortcuts } from './shortcuts'
import { PetTray } from './tray'
import { PythonService } from './python'
import { AdminTokenStore } from './admin-token-store'
import { PetWindow, type PetWindowRuntimeOptions } from './window'
import { PetModelCatalog } from './pet-model-catalog'
import { registerIpcHandlers, type IpcContext } from './ipc-handlers'
import { PluginRegistry } from './plugin-registry'
import { loadPluginsFromDisk } from './plugin-loader'
import { recordRuntimeException } from './runtime-diagnostics'
import { BackendApiTokenStore } from './backend-api-token-store'
import { InputBindingStore } from './input-binding-store'
import { resolvePythonApiOrigin } from './http/python-origin'
import { ProviderCredentialStore } from './provider-credential-store'
import {
  mouseButtonLabel,
  type InputBindingRegistrationStatus,
  type InputBindingSettings,
  type InputBindingSettingsPatch,
  type InputBindingSnapshot,
} from '../shared/input-bindings'
import type {
  PetControlConfigPatch,
  PetControlState,
} from '../shared/pet-control'
import {
  registerRendererProtocol,
  registerRendererProtocolPrivileges,
} from './renderer-protocol'
import { captureDisplayPng } from './desktop-capture'
import { cancelAllModelResourceTasks } from './resource-manager'

registerRendererProtocolPrivileges()

let petWindow: PetWindow
let live2dWindow: Live2DWindow
let petTray: PetTray
let petShortcuts: PetShortcuts
let pythonService: PythonService
let petStateStore: PetStateStore
let controlServer: ControlServer
let petModelCatalog: PetModelCatalog
let pluginRegistry: PluginRegistry
let adminTokenStore: AdminTokenStore
let backendApiTokenStore: BackendApiTokenStore
let inputBindingStore: InputBindingStore
let providerCredentialStore: ProviderCredentialStore
let inputBindingStatus: InputBindingRegistrationStatus = {
  mouseHookAvailable: false,
  pushToTalkActive: false,
  keyboard: { interact: false, lock: false, openPanel: false, toggleVision: false },
  errors: [],
}
let ipcReady = false
let isQuitting = false

const togglePetLock = () => {
  const nextState = petStateStore.applyConfigPatch({ locked: !petStateStore.getState().locked })
  live2dWindow.setLocked(nextState.locked)
  applyPetStateToRenderer(nextState)
}

const togglePetInteract = () => {
  const interactMode = live2dWindow.toggleInteract()
  let nextState = petStateStore.setInteractMode(interactMode)
  if (interactMode) {
    live2dWindow.show()
    live2dWindow.setLocked(false)
    live2dWindow.setClickThrough(false)
    nextState = petStateStore.applyConfigPatch({ visible: true, locked: false, clickThrough: false })
  }
  applyPetStateToRenderer(nextState)
}

const togglePetClickThrough = () => {
  const clickThrough = !petStateStore.getState().clickThrough
  let nextState = petStateStore.applyConfigPatch({ clickThrough })
  if (clickThrough) {
    live2dWindow.setInteractMode(false)
    petStateStore.setInteractMode(false)
    nextState = petStateStore.applyConfigPatch({ clickThrough: true })
  }
  live2dWindow.setClickThrough(nextState.clickThrough)
  applyPetStateToRenderer(nextState)
}

const hasSingleInstanceLock = app.requestSingleInstanceLock()

if (!hasSingleInstanceLock) {
  app.quit()
}

function buildPanelRuntimeOptions(tab?: string): PetWindowRuntimeOptions {
  return {
    controlOrigin: controlServer.panelUrl.replace(/\/$/, ''),
    apiOrigin: resolvePythonApiOrigin(),
    controlToken: controlServer.getControlToken(),
    ...(tab ? { tab } : {}),
  }
}

async function openPanel(tab?: string): Promise<void> {
  if (!petWindow.window) {
    petWindow.create(buildPanelRuntimeOptions(tab))
  }
  if (tab) {
    petWindow.send('panel:open-tab', tab)
  }
  petWindow.show()
}

function toggleVoiceConversation(): void {
  sendVoiceShortcut('shortcut:toggle-mic')
}

function sendVoiceShortcut(channel: 'shortcut:start-mic' | 'shortcut:stop-mic' | 'shortcut:toggle-mic'): void {
  if (!petWindow?.window) {
    petWindow?.create(buildPanelRuntimeOptions('chat'))
  }
  petWindow?.send(channel)
}

function refreshTrayVoiceBinding(settings: InputBindingSettings): void {
  petTray?.setVoiceBindingStatus(
    `按住${mouseButtonLabel(settings.pushToTalk.mouseButton)}说话`,
    inputBindingStatus.pushToTalkActive,
    live2dWindow,
  )
}

function applyInputBindings(settings: InputBindingSettings): InputBindingSnapshot {
  inputBindingStatus = petShortcuts.register(settings)
  refreshTrayVoiceBinding(settings)
  return { settings, status: inputBindingStatus }
}

function updateInputBindings(patch: InputBindingSettingsPatch): InputBindingSnapshot {
  return applyInputBindings(inputBindingStore.update(patch))
}

function resetInputBindings(): InputBindingSnapshot {
  return applyInputBindings(inputBindingStore.reset())
}

function dockPetToBottomRight(): void {
  const nextState = petStateStore.dockBottomRight()
  applyPetStateToRenderer(nextState)
}

function setPetVisible(visible: boolean): void {
  petStateStore.setVisible(visible)
  if (visible) {
    live2dWindow.show()
  } else {
    live2dWindow.hide()
  }
  petTray?.refresh(live2dWindow)
}

async function createApp(): Promise<void> {
  petWindow = new PetWindow()
  live2dWindow = new Live2DWindow()
  petTray = new PetTray()
  pluginRegistry = new PluginRegistry()
  adminTokenStore = new AdminTokenStore()
  backendApiTokenStore = new BackendApiTokenStore(path.join(app.getPath('userData'), 'auth'))
  providerCredentialStore = new ProviderCredentialStore(path.join(app.getPath('userData'), 'credentials'))
  providerCredentialStore.migratePlaintextSettings(path.resolve(__dirname, '../../../python/config/settings.json'))
  inputBindingStore = new InputBindingStore(path.join(app.getPath('userData'), 'input'))
  loadPluginsFromDisk(pluginRegistry)
  petModelCatalog = new PetModelCatalog(pluginRegistry)
  petStateStore = new PetStateStore()
  restorePersistedPetModelSelection()
  petShortcuts = new PetShortcuts(
    live2dWindow,
    togglePetLock,
    () => { void openPanel('companion') },
    () => sendVoiceShortcut('shortcut:start-mic'),
    () => sendVoiceShortcut('shortcut:stop-mic'),
    () => petWindow?.send('shortcut:toggle-vision'),
  )
  controlServer = new ControlServer(
    live2dWindow,
    petWindow,
    petStateStore,
    petModelCatalog,
    pluginRegistry,
    adminTokenStore,
    path.join(__dirname, '../../dist/renderer'),
    applyPetStateToRenderer,
    providerCredentialStore,
    backendApiTokenStore,
  )
  pythonService = new PythonService(
    controlServer.getControlToken(),
    providerCredentialStore.getPythonEnvironment(),
  )
  setupIPC()

  try {
    await pythonService.start()
  } catch (error) {
    console.error('Failed to start Python service:', error)
    app.quit()
    return
  }

  live2dWindow.create(controlServer.panelUrl.replace(/\/$/, ''))
  applyPetStateToRenderer(petStateStore.getState())
  setPetVisible(petStateStore.getState().visible)

  await controlServer.start()
  petWindow.create(buildPanelRuntimeOptions())

  const inputSettings = inputBindingStore.get()
  inputBindingStatus = petShortcuts.register(inputSettings)

  petTray.create(
    live2dWindow,
    openPanel,
    dockPetToBottomRight,
    togglePetInteract,
    togglePetLock,
    togglePetClickThrough,
    setPetVisible,
    () => petStateStore.getState(),
    () => live2dWindow.reloadRenderer(),
    toggleVoiceConversation,
    {
      label: `按住${mouseButtonLabel(inputSettings.pushToTalk.mouseButton)}说话`,
      available: inputBindingStatus.pushToTalkActive,
    },
  )
}

function restorePersistedPetModelSelection(): void {
  const state = petStateStore.getState()
  const restoredModelId = petModelCatalog.resolveModelId(state.modelId)
  const restoredModel = petModelCatalog.getModelById(restoredModelId)
  if (restoredModel) {
    if (state.modelId !== restoredModel.id || state.modelType !== restoredModel.type) {
      petStateStore.applyConfigPatch({ modelId: restoredModel.id, modelType: restoredModel.type })
    }
    return
  }

  if (state.modelId) {
    return
  }

  const defaultModelId = petModelCatalog.getDefaultModelId()
  const defaultModel = petModelCatalog.getModelById(defaultModelId)
  petStateStore.applyConfigPatch({
    modelId: defaultModelId,
    ...(defaultModel ? { modelType: defaultModel.type } : {}),
  })
}

function normalizePetPatch(patch: PetControlConfigPatch): PetControlConfigPatch {
  const nextPatch: PetControlConfigPatch = { ...patch }

  if ('modelType' in nextPatch && nextPatch.modelType !== 'live2d' && nextPatch.modelType !== 'vrm') {
    delete nextPatch.modelType
  }

  if ('modelId' in nextPatch) {
    if (typeof nextPatch.modelId === 'string') {
      const matchedModelId = petModelCatalog.resolveModelId(nextPatch.modelId)
      const matchedModel = petModelCatalog.getModelById(matchedModelId)
      if (matchedModel) {
        nextPatch.modelId = matchedModel.id
        if (!nextPatch.modelType) {
          nextPatch.modelType = matchedModel.type
        }
      } else {
        delete nextPatch.modelId
        delete nextPatch.modelType
      }
    } else if (nextPatch.modelId !== null) {
      delete nextPatch.modelId
    }
  }

  return nextPatch
}

function applyPetStateToRenderer(state: PetControlState): void {
  let nextState = state
  const layoutResult = live2dWindow.applyWindowLayout(state)

  if (layoutResult) {
    if (layoutResult.placement === 'free') {
      if (
        state.positionX !== layoutResult.positionX ||
        state.positionY !== layoutResult.positionY ||
        state.placement !== 'free'
      ) {
        nextState = petStateStore.applyConfigPatch({
          positionX: layoutResult.positionX,
          positionY: layoutResult.positionY,
          placement: 'free',
        })
      }
    }
    if (state.displayId !== layoutResult.displayId) {
      nextState = petStateStore.applyConfigPatch({ displayId: layoutResult.displayId })
    }
  }

  live2dWindow.setInteractMode(nextState.interactMode)
  live2dWindow.setClickThrough(nextState.clickThrough)
  live2dWindow.setLocked(nextState.locked)
  live2dWindow.applyPetConfig(petModelCatalog.buildRendererConfig(nextState))
  petTray?.refresh(live2dWindow)

  if (
    nextState.positionX !== state.positionX ||
    nextState.positionY !== state.positionY ||
    nextState.placement !== state.placement ||
    nextState.displayId !== state.displayId ||
    nextState.scale !== state.scale
  ) {
    petStateStore.applyConfigPatch({
      displayId: nextState.displayId,
      positionX: nextState.positionX,
      positionY: nextState.positionY,
      placement: nextState.placement,
      scale: nextState.scale,
    })
  }
}

function setupIPC(): void {
  if (ipcReady) {
    return
  }

  ipcReady = true
  const ipcContext: IpcContext = {
    live2dWindow,
    petWindow,
    petStateStore,
    petModelCatalog,
    applyPetStateToRenderer,
    normalizePetPatch,
    dockPetToBottomRight,
    captureDisplayPng: (display, displayIndex) => captureDisplayPng(
      display,
      displayIndex,
      (options) => desktopCapturer.getSources(options),
    ),
    pluginRegistry,
    backendApiToken: controlServer.getControlToken(),
    controlOrigin: controlServer.panelUrl.replace(/\/$/, ''),
    openPanel,
    pythonService,
    adminTokenStore,
    inputBindings: {
      getSnapshot: () => ({ settings: inputBindingStore.get(), status: inputBindingStatus }),
      update: updateInputBindings,
      reset: resetInputBindings,
    },
  }

  registerIpcHandlers(ipcContext)
}

app.on('second-instance', () => {
  petWindow?.show()
  setPetVisible(true)
})

app.on('ready', () => {
  if (!hasSingleInstanceLock) return
  registerRendererProtocol()
  void createApp()
})

process.on('uncaughtException', (error) => {
  recordRuntimeException('uncaughtException', error)
})

process.on('unhandledRejection', (reason) => {
  recordRuntimeException('unhandledRejection', reason)
})

app.on('window-all-closed', () => {
  if (isQuitting && process.platform !== 'darwin') {
    app.quit()
  }
})

app.on('before-quit', async () => {
  isQuitting = true
  cancelAllModelResourceTasks()
  petShortcuts?.unregister()
  petTray?.destroy()
  live2dWindow?.close()
  petWindow?.close()
  await controlServer?.stop()
  await pythonService?.stop()
})

app.on('activate', () => {
  if (!live2dWindow?.window) {
    void createApp()
  }
})
