import { createHash, randomUUID } from 'node:crypto'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import type { BrowserWindow, IpcMain, IpcMainEvent, IpcMainInvokeEvent, WebContents } from 'electron'

import { createE2ERedactor } from '../../scripts/e2e-redaction.cjs'
import { isTrustedRendererUrl } from './trusted-renderer-url'
import type { E2ERendererControl, E2ERendererControlRequest } from '../shared/e2e-preload'
import { staticNavigationModuleRecords } from '../shared/navigation'

export type E2EActivation = {
  active: boolean
  token: string
  packaged: boolean
}

export type E2ERequestEvent = {
  sender: unknown
  senderFrame?: { url?: string } | null
}

export const E2E_IPC_CHANNELS = [
  'e2e:activate',
  'e2e:voice-sequence',
  'e2e:pause-health-polling',
  'e2e:poll-health-once',
  'e2e:resume-health-polling',
  'e2e:pause-visual-sampling',
  'e2e:sample-visual-once',
  'e2e:resume-visual-sampling',
  'e2e:pause-companion-polling',
  'e2e:poll-companion-once',
  'e2e:resume-companion-polling',
  'e2e:advance-companion-cooldown',
  'e2e:pause-heartbeat',
  'e2e:emit-heartbeat-once',
  'e2e:teardown-runtime',
] as const

export type E2EIpcChannel = typeof E2E_IPC_CHANNELS[number]

export const buildE2EActivation = (
  env: Record<string, string | undefined>,
  packaged: boolean,
): E2EActivation => {
  const token = env['YUIZAKI_E2E_TOKEN']?.trim() ?? ''
  return {
    active: env['YUIZAKI_E2E'] === '1' && !packaged && token.length > 0,
    token,
    packaged,
  }
}

export const assertE2ERequest = (
  activation: E2EActivation,
  event: E2ERequestEvent,
  suppliedToken: string,
  suppliedProof: string,
  expectedProof: string | null,
  expectedSender: unknown,
  trustedUrl: (url: string) => boolean,
): void => {
  if (!activation.active || activation.packaged) throw new Error('E2E test mode is inactive')
  if (!suppliedToken || suppliedToken !== activation.token) throw new Error('Invalid E2E token')
  if (!suppliedProof || !expectedProof || suppliedProof !== expectedProof) throw new Error('Invalid E2E activation proof')
  if (event.sender !== expectedSender) throw new Error('Invalid E2E sender')
  const sender = event.sender as { getURL?: () => string }
  const url = event.senderFrame?.url || sender.getURL?.() || ''
  if (!trustedUrl(url)) throw new Error('Invalid E2E renderer origin')
}

export type E2EActivationProofState = { value: string | null }

type E2EHandlerContext = {
  ipcMain: Pick<IpcMain, 'handle' | 'removeHandler' | 'on' | 'removeListener'>
  activation: E2EActivation
  expectedSender: WebContents
  apiOrigin: string
  activationProof: E2EActivationProofState
}

export const registerE2EActivationHandshake = (context: E2EHandlerContext): (() => void) => {
  if (!context.activation.active || context.activation.packaged) return () => undefined
  const channel = 'e2e:activate'
  const onActivate = (event: IpcMainEvent, token: string) => {
    let response: { proof: string } | null = null
    if (token === context.activation.token && event.sender === context.expectedSender && !context.activationProof.value) {
      const proof = randomUUID()
      context.activationProof.value = proof
      response = { proof }
    }
    event.returnValue = response
  }
  context.ipcMain.on(channel, onActivate)
  return () => {
    context.ipcMain.removeListener(channel, onActivate)
    context.activationProof.value = null
  }
}

const rendererControlChannels = new Map<E2EIpcChannel, E2ERendererControl>([
  ['e2e:pause-health-polling', 'pauseHealthPolling'],
  ['e2e:poll-health-once', 'pollHealthOnce'],
  ['e2e:resume-health-polling', 'resumeHealthPolling'],
  ['e2e:pause-visual-sampling', 'pauseVisualSampling'],
  ['e2e:sample-visual-once', 'sampleVisualOnce'],
  ['e2e:resume-visual-sampling', 'resumeVisualSampling'],
  ['e2e:pause-companion-polling', 'pauseCompanionPolling'],
  ['e2e:poll-companion-once', 'pollCompanionOnce'],
  ['e2e:resume-companion-polling', 'resumeCompanionPolling'],
  ['e2e:advance-companion-cooldown', 'advanceCompanionCooldown'],
  ['e2e:pause-heartbeat', 'pauseHeartbeat'],
  ['e2e:emit-heartbeat-once', 'emitHeartbeatOnce'],
  ['e2e:teardown-runtime', 'teardownRuntime'],
])

type RendererControlResponse = { ok: true; result?: unknown } | { ok: false; error?: string }

export const registerE2ERendererControlHandlers = (context: E2EHandlerContext): (() => void) => {
  if (!context.activation.active) return () => undefined
  const pending = new Map<string, {
    resolve: (value: unknown) => void
    reject: (error: Error) => void
    timeout: NodeJS.Timeout
  }>()
  const resultChannel = 'e2e:renderer-control-result'
  const onResult = (
    event: IpcMainEvent,
    token: string,
    proof: string,
    requestId: string,
    response: RendererControlResponse,
  ) => {
    const request = pending.get(requestId)
    if (!request) return
    try {
      assertE2ERequest(context.activation, event, token, proof, context.activationProof.value, context.expectedSender, isTrustedRendererUrl)
    } catch (error) {
      clearTimeout(request.timeout)
      pending.delete(requestId)
      request.reject(error instanceof Error ? error : new Error(String(error)))
      return
    }
    clearTimeout(request.timeout)
    pending.delete(requestId)
    if (response?.ok) request.resolve(response.result)
    else request.reject(new Error(response?.error || 'E2E renderer control failed'))
  }
  context.ipcMain.on(resultChannel, onResult)

  for (const [channel, control] of rendererControlChannels) {
    context.ipcMain.removeHandler(channel)
    context.ipcMain.handle(channel, (event, token: string, proof: string, payload: unknown) => {
      assertE2ERequest(context.activation, event, token, proof, context.activationProof.value, context.expectedSender, isTrustedRendererUrl)
      const requestId = randomUUID()
      const request: E2ERendererControlRequest = { requestId, control, payload }
      return new Promise<unknown>((resolve, reject) => {
        const timeoutMs = control === 'sampleVisualOnce' ? 30_000 : 5_000
        const timeout = setTimeout(() => {
          pending.delete(requestId)
          reject(new Error(`E2E renderer control timed out: ${control}`))
        }, timeoutMs)
        pending.set(requestId, { resolve, reject, timeout })
        context.expectedSender.send('e2e:renderer-control', request)
      })
    })
  }

  return () => {
    for (const channel of rendererControlChannels.keys()) context.ipcMain.removeHandler(channel)
    context.ipcMain.removeListener(resultChannel, onResult)
    for (const [requestId, request] of pending) {
      clearTimeout(request.timeout)
      request.reject(new Error(`E2E renderer control disposed: ${requestId}`))
    }
    pending.clear()
  }
}

const controlFetch = async (
  context: E2EHandlerContext,
  event: IpcMainInvokeEvent,
  token: string,
  proof: string,
  path: string,
  body: unknown,
): Promise<unknown> => {
  assertE2ERequest(context.activation, event, token, proof, context.activationProof.value, context.expectedSender, isTrustedRendererUrl)
  const response = await fetch(new URL(path, context.apiOrigin), {
    method: 'POST',
    headers: {
      'content-type': 'application/json',
      'X-Yuizaki-E2E-Token': context.activation.token,
    },
    body: JSON.stringify(body),
    signal: AbortSignal.timeout(5_000),
  })
  const payload = await response.json()
  if (!response.ok) throw new Error(`E2E fixture control failed (${response.status})`)
  return payload
}

export const registerE2EVoiceHandler = (context: E2EHandlerContext): (() => void) => {
  if (!context.activation.active) return () => undefined
  const channel: E2EIpcChannel = 'e2e:voice-sequence'
  context.ipcMain.removeHandler(channel)
  context.ipcMain.handle(channel, (event, token: string, proof: string, payload: unknown) => (
    controlFetch(context, event, token, proof, '/__e2e__/voice-sequence', payload)
  ))
  return () => context.ipcMain.removeHandler(channel)
}

type E2ESuiteOptions = {
  activation: E2EActivation
  caseId: string
  runId: string
  tokenHash: string
  backendToken: string
  artifactDir: string
  apiOrigin: string
  panelWindow: BrowserWindow
  live2dWindow: BrowserWindow
  failureProbe: string | undefined
}

const writeE2EJsonArtifact = (options: E2ESuiteOptions, filename: string, value: unknown): void => {
  const redactor = createE2ERedactor([options.activation.token, options.backendToken])
  fs.writeFileSync(path.join(options.artifactDir, filename), `${redactor.stringify(value, 2)}\n`)
}

const assertFixtureSocketSecurityAudit = (options: E2ESuiteOptions): void => {
  const auditPath = path.join(options.artifactDir, 'fixture-security.json')
  assert.equal(fs.existsSync(auditPath), true, 'fixture socket security audit was not written')
  const audit = JSON.parse(fs.readFileSync(auditPath, 'utf8')) as Record<string, unknown>
  const expectedHash = createHash('sha256').update(options.backendToken).digest('hex')
  assert.equal(audit['backend_token_hash'], expectedHash, 'fixture expected a different backend token')
  assert.equal(audit['accepted_socket_token_hash'], expectedHash, 'renderer did not use the run backend token')
  assert.equal(audit['trusted_socket_origin'], 'yuizaki-app://renderer')
  assert.equal(audit['accepted_socket_origin'], 'yuizaki-app://renderer')
}

export type E2ERendererConsoleEntry = {
  source: 'panel' | 'live2d'
  level: number
  message: string
}

export type E2ELipSyncObservation = {
  event?: string
  payload?: Record<string, unknown>
}

export type E2ELipSyncAudit = {
  start_count: number
  end_count: number
  starts: Array<{ audio_url: string; token_hash: string }>
  ends: Array<{ interrupted: boolean | null }>
}

const NON_FATAL_RENDERER_CONSOLE = new Map<string, ReadonlySet<string>>()

export const findFatalRendererConsoleEntries = (
  caseId: string,
  entries: E2ERendererConsoleEntry[],
): E2ERendererConsoleEntry[] => {
  const whitelist = NON_FATAL_RENDERER_CONSOLE.get(caseId) ?? new Set<string>()
  return entries.filter((entry) => {
    const exactKey = `${entry.source}\u0000${entry.level}\u0000${entry.message}`
    if (whitelist.has(exactKey)) return false
    return entry.level >= 3
      || /\b(?:uncaught|unhandled(?:\s+(?:promise\s+)?rejection)?)\b/i.test(entry.message)
      || /\bfailed to\b/i.test(entry.message)
  })
}

export const assertE2E02LipSyncObservations = (
  observations: E2ELipSyncObservation[],
  apiOrigin: string,
  token: string,
): void => {
  const starts = observations.filter((item) => item.event === 'onSpeechStart')
  const stops = observations.filter((item) => item.event === 'onSpeechEnd')
  assert.ok(starts.length >= 2, `expected at least two lip-sync starts, received ${starts.length}`)
  assert.ok(stops.length >= 2, `expected at least two lip-sync stops, received ${stops.length}`)
  for (const start of starts) {
    const audioUrl = start.payload?.['audioUrl']
    assert.equal(typeof audioUrl, 'string', 'lip-sync start did not expose an audio URL')
    const parsed = new URL(audioUrl as string)
    assert.equal(parsed.origin, new URL(apiOrigin).origin, 'lip-sync audio origin was not the fixture')
    assert.equal(parsed.pathname, '/audio.wav', 'lip-sync audio path was not the bounded fixture asset')
    assert.deepEqual([...parsed.searchParams.keys()], ['token'], 'lip-sync audio URL had unexpected query parameters')
    if (parsed.searchParams.get('token') !== token) {
      throw new Error('lip-sync audio URL token did not match the run')
    }
  }
}

export const createE2E02LipSyncAudit = (
  observations: E2ELipSyncObservation[],
  apiOrigin: string,
  token: string,
  tokenHash: string,
): E2ELipSyncAudit => {
  assertE2E02LipSyncObservations(observations, apiOrigin, token)
  const starts = observations.filter((item) => item.event === 'onSpeechStart')
  const ends = observations.filter((item) => item.event === 'onSpeechEnd')
  return {
    start_count: starts.length,
    end_count: ends.length,
    starts: starts.map((item) => {
      const parsed = new URL(item.payload?.['audioUrl'] as string)
      return {
        audio_url: `${parsed.origin}${parsed.pathname}?token=[redacted]`,
        token_hash: tokenHash,
      }
    }),
    ends: ends.map((item) => ({
      interrupted: typeof item.payload?.['interrupted'] === 'boolean'
        ? item.payload['interrupted']
        : null,
    })),
  }
}

const waitForWindowLoad = async (window: BrowserWindow, label: string): Promise<void> => {
  if (window.isDestroyed()) throw new Error(`${label} E2E window was destroyed before readiness`)
  if (window.webContents.getURL() && !window.webContents.isLoadingMainFrame()) return
  await new Promise<void>((resolve, reject) => {
    const timeout = setTimeout(() => {
      cleanup()
      reject(new Error(`${label} E2E window did-finish-load timed out (url=${window.webContents.getURL()})`))
    }, 10_000)
    const onLoad = () => {
      cleanup()
      resolve()
    }
    const onFail = (_event: Electron.Event, code: number, description: string) => {
      cleanup()
      reject(new Error(`E2E window load failed (${code}): ${description}`))
    }
    const cleanup = () => {
      clearTimeout(timeout)
      window.webContents.off('did-finish-load', onLoad)
      window.webContents.off('did-fail-load', onFail)
    }
    window.webContents.once('did-finish-load', onLoad)
    window.webContents.once('did-fail-load', onFail)
    if (window.webContents.getURL() && !window.webContents.isLoadingMainFrame()) onLoad()
  })
}

const fixtureControl = async (
  options: E2ESuiteOptions,
  pathname: string,
  body: unknown,
): Promise<Record<string, unknown>> => {
  const response = await fetch(new URL(pathname, options.apiOrigin), {
    method: 'POST',
    headers: {
      'content-type': 'application/json',
      'X-Yuizaki-E2E-Token': options.activation.token,
    },
    body: JSON.stringify(body),
    signal: AbortSignal.timeout(5_000),
  })
  const payload = await response.json() as Record<string, unknown>
  if (!response.ok) throw new Error(`${pathname} failed (${response.status}): ${JSON.stringify(payload)}`)
  return payload
}

const waitForPanelReady = (window: BrowserWindow) => window.webContents.executeJavaScript(`new Promise((resolve, reject) => {
  const deadline = Date.now() + 10000;
  const poll = () => {
    const host = document.querySelector('.view-host');
    if (host && window.petApi?.e2e && document.documentElement.dataset.yuizakiAppReady === 'true') return resolve(true);
    if (Date.now() >= deadline) return reject(new Error('panel readiness timed out: ' + JSON.stringify({
      host: Boolean(host),
      petApi: Boolean(window.petApi),
      e2e: Boolean(window.petApi?.e2e),
      url: location.href,
    })));
    setTimeout(poll, 25);
  };
  poll();
})`, true)

const invokeRendererControl = (window: BrowserWindow, method: E2ERendererControl) => (
  window.webContents.executeJavaScript(`window.petApi.e2e[${JSON.stringify(method)}]()`, true)
)

const assertNonblankCapture = (bitmap: Buffer): void => {
  let visible = 0
  let colored = 0
  for (let index = 0; index + 3 < bitmap.length; index += 4) {
    const blue = bitmap[index] ?? 0
    const green = bitmap[index + 1] ?? 0
    const red = bitmap[index + 2] ?? 0
    const alpha = bitmap[index + 3] ?? 0
    if (alpha > 8) visible += 1
    if (alpha > 8 && (red > 8 || green > 8 || blue > 8)) colored += 1
  }
  assert.ok(visible > 100, `avatar capture has only ${visible} visible pixels`)
  assert.ok(colored > 50, `avatar capture has only ${colored} colored pixels`)
}

const ensureE2ELive2DModel = async (options: E2ESuiteOptions): Promise<Record<string, unknown>> => {
  const selected = await options.panelWindow.webContents.executeJavaScript(
    `window.petApi.pet.setModelSelection('hiyori', 'live2d')`,
    true,
  ) as Record<string, unknown>
  assert.equal(selected['modelId'], 'hiyori')
  assert.equal(selected['modelType'], 'live2d')

  const deadline = Date.now() + 10_000
  let state: Record<string, unknown> = selected
  while (Date.now() < deadline) {
    state = await options.panelWindow.webContents.executeJavaScript(
      'window.petApi.pet.getState()',
      true,
    ) as Record<string, unknown>
    if (state['modelId'] === 'hiyori' && state['modelType'] === 'live2d' && state['ready'] === true) break
    await new Promise<void>((resolve) => setTimeout(resolve, 50))
  }
  assert.equal(state['ready'], true, `hiyori did not become renderer-ready: ${JSON.stringify(state)}`)

  const renderer = await options.live2dWindow.webContents.executeJavaScript(`(() => {
    const host = window.petRenderer;
    const config = host?.config || {};
    const notice = document.querySelector('.pet-notice');
    return {
      model_id: config.modelId || null,
      model_type: config.modelType || null,
      model_url: config.modelPath || null,
      notice_visible: notice instanceof HTMLElement && getComputedStyle(notice).display !== 'none',
    };
  })()`, true) as Record<string, unknown>
  assert.equal(renderer['model_id'], 'hiyori')
  assert.equal(renderer['model_type'], 'live2d')
  assert.match(String(renderer['model_url']), /\/live2d\/hiyori\/hiyori_pro_jp\.model3\.json$/)
  assert.equal(renderer['notice_visible'], false)
  return renderer
}

const runE2E07 = async (options: E2ESuiteOptions): Promise<void> => {
  assert.equal(await options.live2dWindow.webContents.executeJavaScript('window.petApi?.e2e === undefined', true), true)
  options.panelWindow.show()
  options.panelWindow.focus()
  assert.equal(await options.panelWindow.webContents.executeJavaScript('document.hidden', true), false)
  await invokeRendererControl(options.panelWindow, 'pollCompanionOnce')
  await invokeRendererControl(options.panelWindow, 'sampleVisualOnce')
  await ensureE2ELive2DModel(options)

  const captureDeadline = Date.now() + 10_000
  let capture = await options.live2dWindow.capturePage()
  while (Date.now() < captureDeadline) {
    try {
      assertNonblankCapture(capture.toBitmap())
      break
    } catch {
      await new Promise<void>((resolve) => setTimeout(resolve, 100))
      capture = await options.live2dWindow.capturePage()
    }
  }
  const screenshotPath = path.join(options.artifactDir, 'live2d-window.png')
  fs.writeFileSync(screenshotPath, capture.toPNG())
  assertNonblankCapture(capture.toBitmap())

  options.panelWindow.webContents.setZoomFactor(2)
  const layout = await options.panelWindow.webContents.executeJavaScript(`new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => {
    const root = document.documentElement;
    const host = document.querySelector('.view-host');
    const shell = document.querySelector('.shell');
    const main = document.querySelector('.main');
    const topbar = document.querySelector('.topbar');
    const topbarLeft = document.querySelector('.topbar-left');
    const topActions = document.querySelector('.top-actions');
    const rect = host?.getBoundingClientRect();
    const leftRect = topbarLeft?.getBoundingClientRect();
    const actionsRect = topActions?.getBoundingClientRect();
    resolve({
      rootClientWidth: root.clientWidth,
      rootScrollWidth: root.scrollWidth,
      horizontalOverflow: root.scrollWidth > root.clientWidth + 1,
      mainOverflow: Boolean(main && main.scrollWidth > main.clientWidth + 1),
      topbarOverflow: Boolean(topbar && topbar.scrollWidth > topbar.clientWidth + 1),
      topbarOverlap: Boolean(leftRect && actionsRect
        && leftRect.right > actionsRect.left + 1
        && leftRect.bottom > actionsRect.top + 1
        && actionsRect.right > leftRect.left + 1
        && actionsRect.bottom > leftRect.top + 1),
      hostVisible: Boolean(rect && rect.width > 0 && rect.height > 0),
      shellVisible: Boolean(shell && shell.getBoundingClientRect().width > 0),
      overflow: [...document.querySelectorAll('body *')].filter((element) => {
        const item = element;
        const itemRect = item.getBoundingClientRect();
        return item.scrollWidth > item.clientWidth + 1 || itemRect.right > root.clientWidth + 1 || itemRect.left < -1;
      }).slice(0, 20).map((element) => ({
        tag: element.tagName,
        classes: element.className,
        clientWidth: element.clientWidth,
        scrollWidth: element.scrollWidth,
        rect: element.getBoundingClientRect().toJSON(),
      })),
    });
  })))`, true) as {
    horizontalOverflow: boolean
    rootClientWidth: number
    rootScrollWidth: number
    mainOverflow: boolean
    topbarOverflow: boolean
    topbarOverlap: boolean
    hostVisible: boolean
    shellVisible: boolean
    overflow: unknown[]
  }
  const layoutEvidence = JSON.stringify(layout)
  assert.equal(layout.horizontalOverflow, false, layoutEvidence)
  assert.equal(layout.mainOverflow, false, layoutEvidence)
  assert.equal(layout.topbarOverflow, false, layoutEvidence)
  assert.equal(layout.topbarOverlap, false, layoutEvidence)
  assert.equal(layout.hostVisible, true)
  assert.equal(layout.shellVisible, true)

  const debuggerApi = options.panelWindow.webContents.debugger
  if (!debuggerApi.isAttached()) debuggerApi.attach('1.3')
  try {
    await debuggerApi.sendCommand('Emulation.setEmulatedMedia', {
      features: [{ name: 'prefers-reduced-motion', value: 'reduce' }],
    })
    const reduced = await options.panelWindow.webContents.executeJavaScript(`(() => ({
      matches: matchMedia('(prefers-reduced-motion: reduce)').matches,
      animated: [...document.querySelectorAll('*')].slice(0, 500).filter((element) => {
        const style = getComputedStyle(element);
        return parseFloat(style.animationDuration) > 0.02 || parseFloat(style.transitionDuration) > 0.02;
      }).length,
    }))()`, true) as { matches: boolean; animated: number }
    assert.equal(reduced.matches, true)
    assert.equal(reduced.animated, 0, `${reduced.animated} elements retain nonessential motion`)
  } finally {
    if (debuggerApi.isAttached()) debuggerApi.detach()
    options.panelWindow.webContents.setZoomFactor(1)
  }
}

const runE2E08 = async (options: E2ESuiteOptions): Promise<void> => {
  for (const module of staticNavigationModuleRecords) {
    const route = `/w/default/${module.id}`
    const result = await options.panelWindow.webContents.executeJavaScript(`new Promise((resolve, reject) => {
      location.hash = ${JSON.stringify(`#${route}`)};
      const deadline = Date.now() + 5000;
      const poll = () => {
        const host = document.querySelector('.view-host');
        const component = host?.querySelector('.view-component');
        if (location.hash.endsWith(${JSON.stringify(route)}) && component && component.getBoundingClientRect().height > 0 && component.textContent?.trim()) {
          return resolve({ hash: location.hash, textLength: component.textContent.trim().length });
        }
        if (Date.now() >= deadline) return reject(new Error(${JSON.stringify(`route ${module.id} did not render`)}));
        setTimeout(poll, 25);
      };
      poll();
    })`, true) as { hash: string; textLength: number }
    assert.ok(result.textLength > 0, `${module.id} rendered empty content`)
  }

  await options.panelWindow.webContents.executeJavaScript(`new Promise((resolve, reject) => {
    document.querySelector('[data-testid="workspace-settings"]')?.click();
    const deadline = Date.now() + 5000;
    const poll = () => {
      const input = document.querySelector('[data-testid="workspace-name"] input, input[data-testid="workspace-name"]');
      if (input instanceof HTMLInputElement) {
        input.value = 'E2E Renamed Workspace';
        input.dispatchEvent(new Event('input', { bubbles: true }));
        input.dispatchEvent(new Event('change', { bubbles: true }));
        input.blur();
        return resolve(true);
      }
      if (Date.now() >= deadline) return reject(new Error('workspace name input did not open: ' + JSON.stringify({
        button: Boolean(document.querySelector('[data-testid="workspace-settings"]')),
        drawer: Boolean(document.querySelector('.workspace-drawer')),
        testIds: [...document.querySelectorAll('[data-testid]')].map((item) => item.getAttribute('data-testid')),
      })));
      setTimeout(poll, 25);
    };
    poll();
  })`, true)

  await options.panelWindow.webContents.executeJavaScript(`new Promise((resolve, reject) => {
    const deadline = Date.now() + 5000;
    const poll = () => {
      const workspaces = JSON.parse(localStorage.getItem('deskpet-workspaces') || '[]');
      const workspace = workspaces.find((item) => item.id === 'default');
      if (workspace?.name === 'E2E Renamed Workspace' && workspace?.context?.activeTab === 'deploy') return resolve(true);
      if (Date.now() >= deadline) return reject(new Error('workspace name/activeTab was not persisted'));
      setTimeout(poll, 25);
    };
    poll();
  })`, true)
}

const sendChatMessage = async (window: BrowserWindow, text: string): Promise<void> => {
  await window.webContents.executeJavaScript(`new Promise((resolve, reject) => {
    location.hash = '#/w/default/chat';
    const deadline = Date.now() + 5000;
    const poll = () => {
      const input = document.querySelector('.chat-input textarea');
      const send = document.querySelector('.send-button:not(.is-warning)');
      const connected = document.body.textContent?.includes('实时通道已连接');
      if (connected && input instanceof HTMLTextAreaElement && send instanceof HTMLButtonElement) {
        input.value = ${JSON.stringify(text)};
        input.dispatchEvent(new Event('input', { bubbles: true }));
        setTimeout(() => {
          const enabledSend = document.querySelector('.send-button:not(.is-warning)');
          if (!(enabledSend instanceof HTMLButtonElement) || enabledSend.disabled) {
            reject(new Error('chat send button did not become enabled'));
            return;
          }
          enabledSend.click();
          resolve(true);
        }, 0);
        return;
      }
      if (Date.now() >= deadline) return reject(new Error('chat composer did not render'));
      setTimeout(poll, 25);
    };
    poll();
  })`, true)
}

const runE2E01 = async (options: E2ESuiteOptions): Promise<void> => {
  await invokeRendererControl(options.panelWindow, 'pollCompanionOnce')
  await sendChatMessage(options.panelWindow, 'E2E first completed turn')
  await options.panelWindow.webContents.executeJavaScript(`new Promise((resolve, reject) => {
    const deadline = Date.now() + 5000;
    const poll = () => {
      if (document.body.textContent?.includes('fixture response')) return resolve(true);
      if (Date.now() >= deadline) return reject(new Error('first assistant final did not render'));
      setTimeout(poll, 25);
    };
    poll();
  })`, true)

  await sendChatMessage(options.panelWindow, 'E2E interrupted turn')
  await options.panelWindow.webContents.executeJavaScript(`new Promise((resolve, reject) => {
    const deadline = Date.now() + 5000;
    const poll = () => {
      const interrupt = document.querySelector('.send-button.is-warning');
      if (interrupt instanceof HTMLButtonElement) {
        interrupt.click();
        return resolve(true);
      }
      if (Date.now() >= deadline) return reject(new Error('interrupt button did not render'));
      setTimeout(poll, 25);
    };
    poll();
  })`, true)
}

const runE2E02 = async (options: E2ESuiteOptions): Promise<void> => {
  await invokeRendererControl(options.panelWindow, 'pollCompanionOnce')
  await options.live2dWindow.webContents.executeJavaScript(`(() => {
    const observations = [];
    window.__yuizakiE2ELipSyncObservations = observations;
    window.addEventListener('yuizaki:pet-event', (event) => {
      const detail = event.detail || {};
      if (detail.event === 'onSpeechStart' || detail.event === 'onSpeechEnd') {
        observations.push({ event: detail.event, payload: detail.payload || {} });
      }
    });
    return true;
  })()`, true)
  await options.panelWindow.webContents.executeJavaScript(`new Promise((resolve, reject) => {
    location.hash = '#/w/default/chat';
    const observations = [];
    window.__yuizakiE2EVoiceObservations = observations;
    for (const name of ['pet:audio-started', 'pet:audio-ended', 'pet:tts-stop']) {
      window.addEventListener(name, (event) => observations.push({ name, detail: event.detail || null }));
    }
    const deadline = Date.now() + 5000;
    const poll = () => {
      if (document.body.textContent?.includes('实时通道已连接')) return resolve(true);
      if (Date.now() >= deadline) return reject(new Error('voice Chat route did not connect'));
      setTimeout(poll, 25);
    };
    poll();
  })`, true)
  const voiceResult = await options.panelWindow.webContents.executeJavaScript(`window.petApi.e2e.voiceSequence({
    case_id: 'E2E-02',
    session_id: 'e2e-voice-session',
    request_id: 'e2e-voice-request-1',
    partial_text: 'E2E voice partial',
    final_text: 'E2E voice completed turn',
    audio_chunks: 1,
  })`, true) as { status?: string }
  assert.equal(voiceResult.status, 'scheduled')
  await waitForText(options.panelWindow, 'fixture voice response')
  await options.panelWindow.webContents.executeJavaScript(`new Promise((resolve, reject) => {
    const deadline = Date.now() + 5000;
    const poll = () => {
      const observations = window.__yuizakiE2EVoiceObservations || [];
      if (observations.some(item => item.name === 'pet:audio-started' && item.detail?.generationId === 'e2e-generation-1')) return resolve(true);
      if (Date.now() >= deadline) return reject(new Error('first voice generation did not start playback'));
      setTimeout(poll, 25);
    };
    poll();
  })`, true)
  await new Promise(resolve => setTimeout(resolve, 250))

  await sendChatMessage(options.panelWindow, 'E2E second voice generation')
  await options.panelWindow.webContents.executeJavaScript(`new Promise((resolve, reject) => {
    const deadline = Date.now() + 5000;
    const poll = () => {
      const observations = window.__yuizakiE2EVoiceObservations || [];
      const started = observations.some(item => item.name === 'pet:audio-started' && item.detail?.generationId === 'e2e-generation-2');
      const interrupt = document.querySelector('.send-button.is-warning');
      if (started && interrupt instanceof HTMLButtonElement) {
        interrupt.click();
        return resolve(true);
      }
      if (Date.now() >= deadline) return reject(new Error('second voice generation did not reach interruptible playback'));
      setTimeout(poll, 25);
    };
    poll();
  })`, true)
  await options.panelWindow.webContents.executeJavaScript(`new Promise((resolve, reject) => {
    const deadline = Date.now() + 5000;
    const poll = () => {
      const observations = window.__yuizakiE2EVoiceObservations || [];
      const stopped = observations.some(item => item.name === 'pet:tts-stop' && item.detail?.interrupted === true);
      if (stopped && !document.querySelector('.send-button.is-warning')) return resolve(true);
      if (Date.now() >= deadline) return reject(new Error('voice interrupt did not stop playback and return idle'));
      setTimeout(poll, 25);
    };
    poll();
  })`, true)
  await new Promise(resolve => setTimeout(resolve, 250))
  const lipSyncObservations = await options.live2dWindow.webContents.executeJavaScript(
    'window.__yuizakiE2ELipSyncObservations || []',
    true,
  ) as E2ELipSyncObservation[]
  if (options.failureProbe === 'redaction') {
    const token = options.activation.token
    await options.live2dWindow.webContents.executeJavaScript(
      `console.error(${JSON.stringify(`probe URL ${options.apiOrigin}/audio.wav?token=${token} --token ${token} X-Yuizaki-E2E-Token: ${token} Authorization: Bearer ${token}`)})`,
      true,
    )
    const tamperedObservations = lipSyncObservations.map((observation, index) => {
      if (index !== 0 || observation.event !== 'onSpeechStart') return observation
      return {
        ...observation,
        payload: { ...observation.payload, audioUrl: `${options.apiOrigin}/audio.wav?token=wrong-token` },
      }
    })
    try {
      createE2E02LipSyncAudit(tamperedObservations, options.apiOrigin, token, options.tokenHash)
    } catch (error) {
      const probeError = error instanceof Error ? error : new Error(String(error))
      probeError.stack = `${probeError.stack || probeError.message}\nargv=--token ${token}\nX-Yuizaki-E2E-Token: ${token}\nAuthorization: Bearer ${token}`
      throw probeError
    }
    throw new Error('redaction failure probe did not fail')
  }
  const lipSyncAudit = createE2E02LipSyncAudit(
    lipSyncObservations,
    options.apiOrigin,
    options.activation.token,
    options.tokenHash,
  )
  writeE2EJsonArtifact(options, 'lipsync-audit.json', lipSyncAudit)
}

const resolvePermissionCard = async (window: BrowserWindow, allowed: boolean): Promise<void> => {
  await window.webContents.executeJavaScript(`new Promise((resolve, reject) => {
    const deadline = Date.now() + 5000;
    const poll = () => {
      const card = document.querySelector('.permission-card');
      const buttons = [...(card?.querySelectorAll('button') || [])];
      const button = buttons.find((item) => item.textContent?.trim() === ${JSON.stringify(allowed ? '允许' : '拒绝')});
      if (card?.textContent?.includes('fixture.write') && button instanceof HTMLButtonElement) {
        button.click();
        return resolve(true);
      }
      if (Date.now() >= deadline) return reject(new Error('permission card did not render expected receipt'));
      setTimeout(poll, 25);
    };
    poll();
  })`, true)
}

const waitForText = async (window: BrowserWindow, expected: string): Promise<void> => {
  await window.webContents.executeJavaScript(`new Promise((resolve, reject) => {
    const deadline = Date.now() + 5000;
    const poll = () => {
      if (document.body.textContent?.includes(${JSON.stringify(expected)})) return resolve(true);
      if (Date.now() >= deadline) return reject(new Error(${JSON.stringify(`${expected} did not render`)}));
      setTimeout(poll, 25);
    };
    poll();
  })`, true)
}

const runE2E03 = async (options: E2ESuiteOptions): Promise<void> => {
  await sendChatMessage(options.panelWindow, 'E2E deny permission')
  await resolvePermissionCard(options.panelWindow, false)
  await waitForText(options.panelWindow, 'permission denied receipt')
  await sendChatMessage(options.panelWindow, 'E2E allow permission')
  await resolvePermissionCard(options.panelWindow, true)
  await waitForText(options.panelWindow, 'permission allowed receipt')

  const rest = await options.panelWindow.webContents.executeJavaScript(`(async () => {
    const origin = new URL(location.href).searchParams.get('api_origin');
    if (!origin) throw new Error('runtime api_origin hint is missing');
    const backendToken = window.sessionStorage.getItem('yuizaki.control.token') || '';
    if (!backendToken) throw new Error('runtime backend token is missing');
    const invoke = async (stream) => {
      const response = await fetch(origin + '/v1/chat/completions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + backendToken },
        body: JSON.stringify({ messages: [{ role: 'user', content: 'must fail closed' }], stream, autonomy_mode: 'strict' }),
      });
      return { ok: response.ok, status: response.status, text: await response.text() };
    };
    return { documentOrigin: location.origin, apiOrigin: origin, nonStream: await invoke(false), stream: await invoke(true) };
  })()`, true) as {
    documentOrigin: string
    apiOrigin: string
    nonStream: { ok: boolean; status: number; text: string }
    stream: { ok: boolean; status: number; text: string }
  }
  assert.equal(rest.nonStream.ok, true, JSON.stringify(rest))
  assert.match(rest.nonStream.text, /side_effects.*0/)
  assert.equal(rest.stream.ok, true, JSON.stringify(rest))
  assert.match(rest.stream.text, /side_effects.*0/)
}

const runE2E04 = async (options: E2ESuiteOptions): Promise<void> => {
  await options.panelWindow.webContents.executeJavaScript(`(async () => {
    location.hash = '#/w/default/memory';
    const deadline = Date.now() + 10000;
    const waitFor = async (predicate, message) => {
      while (!predicate()) {
        if (Date.now() >= deadline) throw new Error(message);
        await new Promise(resolve => setTimeout(resolve, 25));
      }
    };
    const element = (selector) => {
      const found = document.querySelector(selector);
      if (!(found instanceof HTMLElement)) throw new Error('missing element: ' + selector);
      return found;
    };
    const setInput = (selector, value) => {
      const root = element(selector);
      const input = root.matches('input, textarea') ? root : root.querySelector('input, textarea');
      if (!(input instanceof HTMLInputElement || input instanceof HTMLTextAreaElement)) {
        throw new Error('missing input: ' + selector);
      }
      input.value = value;
      input.dispatchEvent(new Event('input', { bubbles: true }));
    };
    const clickEnabled = async (selector) => {
      await waitFor(() => {
        const button = document.querySelector(selector);
        return button instanceof HTMLButtonElement && !button.disabled && !button.classList.contains('is-loading');
      }, 'button did not become enabled: ' + selector);
      element(selector).click();
    };

    await waitFor(() => document.querySelector('[data-testid="memory-refresh"]') instanceof HTMLButtonElement, 'Memory panel did not render');
    await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    await waitFor(() => !element('[data-testid="memory-refresh"]').classList.contains('is-loading'), 'initial Memory list did not settle');
    if (document.querySelector('[data-memory-id]')) throw new Error('initial Memory list was not empty');

    element('[data-testid="memory-advanced-tools-toggle"]').click();
    await waitFor(() => element('[data-testid="memory-advanced-tools-toggle"]').getAttribute('aria-expanded') === 'true', 'advanced Memory disclosure did not open');
    setInput('[data-testid="memory-document-text"]', 'E2E durable memory original');
    setInput('[data-testid="memory-document-metadata"]', JSON.stringify({
      source: 'manual',
      timestamp: '2026-08-04T12:00:00Z',
      scope: 'workspace',
      workspace_id: 'default',
      confidence: 0.91,
      importance: 0.82,
      expires_at: '2027-08-04T12:00:00Z',
      layer: 'semantic',
      type: 'fact',
    }));
    await clickEnabled('[data-testid="memory-document-submit"]');
    await waitFor(() => document.querySelector('[data-memory-id="memory-e2e-1"]') instanceof HTMLElement, 'created Memory document did not render');
    const createdText = element('[data-memory-id="memory-e2e-1"]').textContent || '';
    for (const expected of ['E2E durable memory original', '0.9100', '手动', '工作区', '2027-08-04', '2026-08-04']) {
      if (!createdText.includes(expected)) throw new Error('created Memory metadata missing: ' + expected);
    }

    setInput('[data-testid="memory-inspector-text"]', 'E2E durable memory corrected');
    await clickEnabled('[data-testid="memory-inspector-save"]');
    await waitFor(() => {
      const card = document.querySelector('[data-memory-id="memory-e2e-1"]');
      return card?.textContent?.includes('E2E durable memory corrected') && !element('[data-testid="memory-refresh"]').classList.contains('is-loading');
    }, 'corrected Memory document did not persist after reload');

    setInput('[data-testid="memory-query-input"]', 'E2E-memory');
    await clickEnabled('[data-testid="memory-query-submit"]');
    await waitFor(() => document.querySelector('.query-result-card')?.textContent?.includes('E2E durable memory corrected') === true, 'corrected Memory document was not retrievable');

    await clickEnabled('[data-testid="memory-maintenance-preview"]');
    await waitFor(() => document.querySelector('.maintenance-summary') instanceof HTMLElement && !element('[data-testid="memory-maintenance-preview"]').classList.contains('is-loading'), 'Memory maintenance preview did not render');

    await clickEnabled('[data-testid="memory-inspector-delete"]');
    await waitFor(() => document.querySelector('.el-message-box') instanceof HTMLElement, 'permanent delete confirmation did not render');
    const confirm = [...document.querySelectorAll('.el-message-box button')]
      .find(button => button.textContent?.trim() === '永久删除');
    if (!(confirm instanceof HTMLButtonElement)) throw new Error('permanent delete confirmation button missing');
    confirm.click();
    await waitFor(() => !document.querySelector('[data-memory-id="memory-e2e-1"]') && !element('[data-testid="memory-refresh"]').classList.contains('is-loading'), 'deleted Memory document remained after reload');

    await clickEnabled('[data-testid="memory-query-submit"]');
    await waitFor(() => !element('[data-testid="memory-query-submit"]').classList.contains('is-loading'), 'post-delete Memory query did not settle');
    if (document.querySelector('.query-result-card')) throw new Error('deleted Memory document remained retrievable');
  })()`, true)
}

const scheduleProactiveEvent = (options: E2ESuiteOptions, eventId: 'A' | 'B' | 'C') => (
  fixtureControl(options, '/__e2e__/proactive-event', {
    case_id: 'E2E-05',
    event_id: eventId,
    eligible: true,
    interruptible: true,
  })
)

const assertDeliveredProactiveResult = (value: unknown, eventId: 'A' | 'C'): void => {
  assert.ok(value && typeof value === 'object', `proactive ${eventId} returned no delivery result`)
  const result = value as { status?: unknown; attempted?: unknown; succeeded?: unknown; failed?: unknown }
  assert.equal(result.status, 'delivered', JSON.stringify(result))
  assert.deepEqual(result.attempted, ['motion', 'advice', 'notification'])
  assert.deepEqual(result.succeeded, ['motion', 'advice', 'notification'])
  assert.deepEqual(result.failed, [])
}

const runE2E05 = async (options: E2ESuiteOptions): Promise<void> => {
  await options.panelWindow.webContents.executeJavaScript(`new Promise((resolve, reject) => {
    location.hash = '#/w/default/companion';
    const deadline = Date.now() + 5000;
    const poll = () => {
      const preset = document.querySelector('[data-testid="companion-proactivity-preset"]');
      const dnd = document.querySelector('[data-testid="companion-dnd-toggle"]');
      if (preset && dnd) return resolve(true);
      if (Date.now() >= deadline) return reject(new Error('Companion controls did not render'));
      setTimeout(poll, 25);
    };
    poll();
  })`, true)

  const modelAudit = await ensureE2ELive2DModel(options)

  await scheduleProactiveEvent(options, 'A')
  assertDeliveredProactiveResult(await invokeRendererControl(options.panelWindow, 'pollCompanionOnce'), 'A')

  await options.panelWindow.webContents.executeJavaScript(`new Promise((resolve, reject) => {
    location.hash = '#/w/default/chat';
    requestAnimationFrame(() => {
      location.hash = '#/w/default/companion';
      const deadline = Date.now() + 5000;
      const poll = () => {
        if (document.querySelector('[data-testid="companion-dnd-toggle"]')) return resolve(true);
        if (Date.now() >= deadline) return reject(new Error('Companion route did not remount'));
        setTimeout(poll, 25);
      };
      poll();
    });
  })`, true)
  await scheduleProactiveEvent(options, 'A')
  assert.equal(await invokeRendererControl(options.panelWindow, 'pollCompanionOnce'), 'duplicate_or_invalid')

  await options.panelWindow.webContents.executeJavaScript(`new Promise((resolve, reject) => {
    const toggle = document.querySelector('[data-testid="companion-dnd-toggle"]');
    if (!(toggle instanceof HTMLElement)) return reject(new Error('DND toggle is missing'));
    const control = toggle.querySelector('input,button,[role="switch"]') || toggle;
    if (!(control instanceof HTMLElement)) return reject(new Error('DND native control is missing'));
    control.click();
    const deadline = Date.now() + 5000;
    const poll = () => {
      const checked = control.getAttribute('aria-checked') === 'true' || (control instanceof HTMLInputElement && control.checked);
      if (checked && !toggle.classList.contains('is-loading')) return resolve(true);
      if (Date.now() >= deadline) return reject(new Error('DND did not enable through Companion UI'));
      setTimeout(poll, 25);
    };
    poll();
  })`, true)
  await scheduleProactiveEvent(options, 'B')
  assert.equal(await invokeRendererControl(options.panelWindow, 'pollCompanionOnce'), 'dnd')

  await options.panelWindow.webContents.executeJavaScript(`new Promise((resolve, reject) => {
    const toggle = document.querySelector('[data-testid="companion-dnd-toggle"]');
    if (!(toggle instanceof HTMLElement)) return reject(new Error('DND toggle is missing'));
    const control = toggle.querySelector('input,button,[role="switch"]') || toggle;
    if (!(control instanceof HTMLElement)) return reject(new Error('DND native control is missing'));
    control.click();
    const deadline = Date.now() + 5000;
    const poll = () => {
      const checked = control.getAttribute('aria-checked') === 'true' || (control instanceof HTMLInputElement && control.checked);
      if (!checked && !toggle.classList.contains('is-loading')) return resolve(true);
      if (Date.now() >= deadline) return reject(new Error('DND did not disable through Companion UI'));
      setTimeout(poll, 25);
    };
    poll();
  })`, true)
  assert.deepEqual(await invokeRendererControl(options.panelWindow, 'advanceCompanionCooldown'), { advancedMs: 16 * 60_000 })
  await scheduleProactiveEvent(options, 'C')
  assertDeliveredProactiveResult(await invokeRendererControl(options.panelWindow, 'pollCompanionOnce'), 'C')

  const motion = await options.live2dWindow.webContents.executeJavaScript(`(() => {
    const state = window.__petTestState || {};
    return { group: state.lastMotionGroup || null, index: state.lastMotionIndex ?? null };
  })()`, true) as Record<string, unknown>
  assert.deepEqual(motion, { group: 'Tap@Body', index: 0 })
  writeE2EJsonArtifact(options, 'avatar-motion-audit.json', { model: modelAudit, motion })
}

const runE2E05T = async (options: E2ESuiteOptions): Promise<void> => {
  assert.deepEqual(await invokeRendererControl(options.panelWindow, 'pauseHeartbeat'), { paused: true })
  const result = await invokeRendererControl(options.panelWindow, 'emitHeartbeatOnce') as Record<string, unknown>
  assert.equal(result['emitted'], true)
  assert.equal(result['echoed'], true)
  assert.equal(result['echo_count'], 1)
  assert.deepEqual(result['correlation'], {
    timestamp: (result['correlation'] as Record<string, unknown>)['timestamp'],
    request_id: '[verified]',
    client_id: '[verified]',
  })
  assert.equal(Number.isFinite((result['correlation'] as Record<string, unknown>)['timestamp']), true)
  writeE2EJsonArtifact(options, 'heartbeat-correlation-audit.json', result)
}

const prepareE2ECase = async (window: BrowserWindow): Promise<unknown> => {
  await invokeRendererControl(window, 'pauseHealthPolling')
  await invokeRendererControl(window, 'pauseVisualSampling')
  await invokeRendererControl(window, 'pauseCompanionPolling')
  return invokeRendererControl(window, 'pollHealthOnce')
}

const assertHealthState = (
  value: unknown,
  expected: { controlRunning: boolean; pythonRunning: boolean; sioConnected?: boolean },
): void => {
  assert.ok(value && typeof value === 'object', 'health control returned no state')
  const actual = value as Record<string, unknown>
  assert.equal(actual['checked'], true, JSON.stringify(actual))
  assert.equal(actual['controlRunning'], expected.controlRunning, JSON.stringify(actual))
  assert.equal(actual['pythonRunning'], expected.pythonRunning, JSON.stringify(actual))
  if (expected.sioConnected !== undefined) {
    assert.equal(actual['sioConnected'], expected.sioConnected, JSON.stringify(actual))
  }
}

const runE2E06 = async (options: E2ESuiteOptions, baselineHealth: unknown): Promise<void> => {
  assertHealthState(baselineHealth, { controlRunning: true, pythonRunning: true })
  assert.equal(await invokeRendererControl(options.panelWindow, 'pollCompanionOnce'), 'empty')

  assert.deepEqual(
    await fixtureControl(options, '/__e2e__/backend-mode', { case_id: 'E2E-06', mode: 'unavailable' }),
    { status: 'ok', mode: 'unavailable' },
  )
  assertHealthState(
    await invokeRendererControl(options.panelWindow, 'pollHealthOnce'),
    { controlRunning: true, pythonRunning: false },
  )
  assert.equal(await invokeRendererControl(options.panelWindow, 'pollCompanionOnce'), 'unavailable')
  const localState = await options.panelWindow.webContents.executeJavaScript(`(async () => ({
    pet: await window.petApi.pet.getState(),
    workspace: window.localStorage.getItem('yuizaki.workspaces'),
  }))()`, true) as { pet?: unknown }
  assert.ok(localState.pet && typeof localState.pet === 'object', 'local pet controls became unavailable during backend outage')

  assert.deepEqual(
    await fixtureControl(options, '/__e2e__/backend-mode', { case_id: 'E2E-06', mode: 'online' }),
    { status: 'ok', mode: 'online' },
  )
  assertHealthState(
    await invokeRendererControl(options.panelWindow, 'pollHealthOnce'),
    { controlRunning: true, pythonRunning: true, sioConnected: true },
  )
  assert.equal(await invokeRendererControl(options.panelWindow, 'pollCompanionOnce'), 'empty')

  await invokeRendererControl(options.panelWindow, 'pauseHealthPolling')
  assert.deepEqual(await invokeRendererControl(options.panelWindow, 'resumeHealthPolling'), { resumed: true, checked: true })
  await invokeRendererControl(options.panelWindow, 'pauseHealthPolling')
  assert.deepEqual(await invokeRendererControl(options.panelWindow, 'resumeCompanionPolling'), { resumed: true, polled: true })
  await invokeRendererControl(options.panelWindow, 'pauseCompanionPolling')
}

export const runE2ESuite = async (options: E2ESuiteOptions): Promise<void> => {
  fs.mkdirSync(options.artifactDir, { recursive: true })
  const redactor = createE2ERedactor([options.activation.token, options.backendToken])
  const consoleEntries: E2ERendererConsoleEntry[] = []
  const captureConsole = (source: E2ERendererConsoleEntry['source']) => (
    _event: Electron.Event,
    level: number,
    message: string,
  ) => {
    consoleEntries.push({ source, level, message: message.slice(0, 2000) })
  }
  const capturePanelConsole = captureConsole('panel')
  const captureLive2DConsole = captureConsole('live2d')
  options.panelWindow.webContents.on('console-message', capturePanelConsole)
  options.live2dWindow.webContents.on('console-message', captureLive2DConsole)
  let status: 'passed' | 'failed' = 'failed'
  let errorMessage: string | undefined
  try {
    assert.equal(options.activation.active, true)
    await Promise.all([
      waitForWindowLoad(options.panelWindow, 'panel'),
      waitForWindowLoad(options.live2dWindow, 'live2d'),
    ])
    await waitForPanelReady(options.panelWindow)
    const baselineHealth = await prepareE2ECase(options.panelWindow)
    if (options.caseId === 'E2E-01') await runE2E01(options)
    else if (options.caseId === 'E2E-02') await runE2E02(options)
    else if (options.caseId === 'E2E-03') await runE2E03(options)
    else if (options.caseId === 'E2E-04') await runE2E04(options)
    else if (options.caseId === 'E2E-05') await runE2E05(options)
    else if (options.caseId === 'E2E-05T') await runE2E05T(options)
    else if (options.caseId === 'E2E-06') await runE2E06(options, baselineHealth)
    else if (options.caseId === 'E2E-07') await runE2E07(options)
    else if (options.caseId === 'E2E-08') await runE2E08(options)
    else throw new Error(`Required E2E case is not implemented: ${options.caseId}`)

    assertFixtureSocketSecurityAudit(options)

    await invokeRendererControl(options.panelWindow, 'teardownRuntime')
    await fixtureControl(options, '/__e2e__/case/wait-disconnect', { case_id: options.caseId })
    const ledger = await fixtureControl(options, '/__e2e__/case/assert', { case_id: options.caseId })
    assert.equal(ledger['ok'], true, JSON.stringify(ledger))
    if (options.caseId === 'E2E-06') {
      assert.deepEqual(ledger['transport'], { connect_count: 2, disconnect_count: 2 })
    }
    const fatalConsoleEntries = findFatalRendererConsoleEntries(options.caseId, consoleEntries)
    assert.deepEqual(fatalConsoleEntries, [], `fatal renderer console entries: ${JSON.stringify(fatalConsoleEntries)}`)
    status = 'passed'
  } catch (error) {
    errorMessage = redactor.redactText(error instanceof Error ? error.stack || error.message : String(error))
    fs.writeFileSync(path.join(options.artifactDir, 'electron-error.txt'), errorMessage)
    try {
      const failureCapture = await options.panelWindow.capturePage()
      fs.writeFileSync(path.join(options.artifactDir, 'panel-failure.png'), failureCapture.toPNG())
    } catch {
      // Preserve the original assertion failure when the window is already unavailable.
    }
  } finally {
    options.panelWindow.webContents.off('console-message', capturePanelConsole)
    options.live2dWindow.webContents.off('console-message', captureLive2DConsole)
    fs.writeFileSync(
      path.join(options.artifactDir, 'renderer-console.jsonl'),
      consoleEntries.map((entry) => redactor.stringify(entry)).join('\n'),
    )
  }
  console.log(redactor.stringify({
    type: 'yuizaki-e2e-result',
    run_id: options.runId,
    token_hash: options.tokenHash,
    backend_token_hash: createHash('sha256').update(options.backendToken).digest('hex'),
    case: options.caseId,
    status,
    artifact_dir: options.artifactDir,
    ...(errorMessage ? { error: errorMessage.slice(0, 1200) } : {}),
  }))
}
