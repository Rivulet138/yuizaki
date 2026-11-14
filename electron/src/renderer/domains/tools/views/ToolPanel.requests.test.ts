import { describe, expect, it, vi } from 'vitest'
import { ref } from 'vue'
import { panelDeclarations } from '../tests/panel-script.mjs'

const loaders = [
  ['loadStream', 'stream', 'loadingStream', { state: 'disconnected' }],
  ['loadStreamEvents', 'streamEvents', 'loadingStreamEvents', { events: [] }],
  ['loadStreamDrafts', 'streamDrafts', 'loadingStreamDrafts', { drafts: [] }],
  ['loadStreamActions', 'streamActions', 'loadingStreamActions', { ok: true, actions: [], unresolvedRequestIds: [] }],
  ['loadObsProfiles', 'obsProfiles', 'loadingObsProfiles', { profiles: [] }],
] as const

describe('tool list request ownership', () => {
  it.each(loaders)('%s retains the latest request loading state', async (name, api, flag, response) => {
    const pending: Array<(value: unknown) => void> = []
    const loading = ref(false)
    const env = {
      ref, pageGeneration: 0, listSequences: new Map(), listStatus: ref({}),
      systemClient: { [api]: vi.fn(() => new Promise(resolve => pending.push(resolve))) },
      [flag]: loading, streamLoadError: ref(''), streamSnapshot: ref(null),
      loadingStreamTakeover: ref(false), resolvingStreamAction: ref(false), streamTakeoverEnabled: ref(false),
      streamDraftsInitialized: true, streamEvents: ref([]), streamDrafts: ref([]),
      streamActionsLoaded: ref(false), streamActions: ref([]), uncertainStreamRequest: ref(''),
      obsProfiles: ref([]), obsCurrentProfile: ref(''), obsProfileDraft: ref(''),
      listSucceeded: vi.fn(), listFailed: vi.fn(), describeFailure: (error: Error) => error.message,
      ElMessage: { warning: vi.fn(), error: vi.fn() }, t: (key: string) => key,
    }
    const compiled = panelDeclarations(new URL('./ToolPanel.vue', import.meta.url), ['beginListRead', name])
    const load = new Function(...Object.keys(env), `${compiled}; return ${name}`)(...Object.values(env))
    const old = load()
    const latest = load()
    pending[0]!(response)
    await old
    expect(loading.value).toBe(true)
    pending[1]!(response)
    await latest
    expect(loading.value).toBe(false)
    expect(env.listFailed).not.toHaveBeenCalled()
  })
})
