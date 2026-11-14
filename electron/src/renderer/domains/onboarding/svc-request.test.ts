import { readFileSync } from 'node:fs'
import ts from 'typescript'
import { computed, createSSRApp, h, onUnmounted, reactive, ref, watch } from 'vue'
import { renderToString } from '@vue/server-renderer'
import { usePanelLifecycle } from '@/app/composables/usePanelLifecycle'
import { describe, expect, it, vi } from 'vitest'

// Execute the actual SFC setup with provider/device boundaries injected. No DOM,
// live backend, model or copied implementation is needed for the request races.
const source = readFileSync(new URL('../tools/views/SVCPanel.vue', import.meta.url), 'utf8').split('<script setup lang="ts">')[1]!.split('</script>')[0]!
const ast = ts.createSourceFile('SVCPanel.ts', source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TS)
const body = ast.statements.filter(node => !ts.isImportDeclaration(node)).map(node => node.getFullText(ast)).join('\n')
const compiled = ts.transpileModule(body, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS } }).outputText
const configuration = () => ({ provider: 'soulx-service', base_url: 'http://127.0.0.1:7861', speaker_id: 7, pitch: 2, timeout: 120 })
const deferred = <T>() => {
  let resolve!: (value: T) => void
  const promise = new Promise<T>(done => { resolve = done })
  return { promise, resolve }
}

const setup = async (beforeAction: () => Promise<boolean> = async () => true) => {
  const config = reactive(configuration())
  const settingsClient = { load: vi.fn(async () => ({ svc: configuration() })), testSvc: vi.fn(async () => ({ ok: true, ready: true, reachable: true })) }
  const requestJson = vi.fn()
  const env = {
    computed, reactive, ref, watch, onUnmounted, usePanelLifecycle,
    defineProps: () => ({ embedded: true, config, beforeAction }),
    useSettingsStore: () => ({ state: { svc: configuration() } }),
    useRoute: () => ({ params: {} }), useRouter: () => ({ push: vi.fn() }),
    t: (key: string) => key, settingsClient, requestJson,
    resolveBackendUrl: async (url: string) => `http://backend${url}`, API_ORIGIN: 'http://backend',
    ElMessage: { warning: vi.fn(), success: vi.fn(), error: vi.fn() },
    describeFailure: (error: Error) => error.message,
  }
  const run = new Function(...Object.keys(env), `${compiled}; return { startConversion, handleFileChange, selectedFile, resultAudioUrl, conversionError, conversionContext, isConverting, testService, svcCheckState, effectiveCheckState };`)
  let state!: ReturnType<typeof run>
  // Register the real composable in a component scope. These request tests
  // supply embedded settings; client mounted/activated refreshes are outside
  // their boundary and do not run during SSR.
  await renderToString(createSSRApp({ setup() {
    state = run(...Object.values(env))
    return () => h('div')
  } }))
  return { state, settingsClient, requestJson, config }
}

describe('SVC request binding', () => {
  it('freezes file A before settings flush and labels its late result as A after selecting B', async () => {
    const flush = deferred<boolean>()
    const conversion = deferred<{ audio_url: string }>()
    const { state, requestJson } = await setup(() => flush.promise)
    requestJson.mockReturnValue(conversion.promise)
    state.handleFileChange({ raw: new File(['a'], 'A.wav') })
    const operation = state.startConversion()
    expect(state.isConverting.value).toBe(true)
    state.handleFileChange({ raw: new File(['b'], 'B.wav') })
    await state.startConversion()
    flush.resolve(true)
    await vi.waitFor(() => expect(requestJson).toHaveBeenCalledOnce())
    const request = requestJson.mock.calls[0]![1]
    expect(request.body.get('file').name).toBe('A.wav')
    expect(request.body.get('speaker_id')).toBe('7')
    expect(request.headers['x-trace-id']).toBe(state.conversionContext.value.requestId)
    conversion.resolve({ audio_url: '/audio/A.wav' })
    await operation
    expect(state.selectedFile.value.name).toBe('B.wav')
    expect(state.conversionContext.value.fileName).toBe('A.wav')
    expect(state.resultAudioUrl.value).toBe('http://backend/audio/A.wav')
  })

  it('keeps save failure visible and sends no conversion with the old configuration', async () => {
    const { state, requestJson, settingsClient } = await setup(async () => false)
    state.handleFileChange({ raw: new File(['a'], 'A.wav') })
    await state.startConversion()
    expect(requestJson).not.toHaveBeenCalled()
    expect(settingsClient.load).not.toHaveBeenCalled()
    expect(state.conversionError.value).toBe('svcPanel.saveFailed')
    expect(state.isConverting.value).toBe(false)
  })

  it('rejects a saved config that differs from the clicked snapshot', async () => {
    const { state, requestJson, settingsClient } = await setup()
    settingsClient.load.mockResolvedValue({ svc: { ...configuration(), pitch: 5 } })
    state.handleFileChange({ raw: new File(['a'], 'A.wav') })
    await state.startConversion()
    expect(requestJson).not.toHaveBeenCalled()
    expect(state.conversionError.value).toBe('svcPanel.saveFailed')
  })

  it('does not mark reachable-only or model-not-ready probes as ready', async () => {
    const { state, settingsClient } = await setup()
    settingsClient.testSvc.mockResolvedValue({ ok: false, reachable: true, ready: false })
    await state.testService()
    expect(state.svcCheckState.value).toBe('error')
    expect(state.effectiveCheckState.value).toBe('error')
    settingsClient.testSvc.mockResolvedValue({ ok: true, reachable: true, ready: true })
    await state.testService()
    expect(state.svcCheckState.value).toBe('ready')
    expect(state.effectiveCheckState.value).toBe('ready')
  })
})
