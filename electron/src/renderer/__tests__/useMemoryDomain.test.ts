import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useMemoryDomain } from '../domains/memory/composables/useMemoryDomain'

const workspaceMock = vi.hoisted(() => ({
  activeWorkspace: {
    id: 'ws-1',
    memory_scope: 'workspace',
  },
}))

const memoryClientMocks = vi.hoisted(() => ({
  getDocs: vi.fn().mockResolvedValue({ docs: [] }),
  getOverview: vi.fn().mockResolvedValue({
    total: 0,
    recallable: 0,
    by_state: {},
    by_layer: {},
    by_source: {},
    by_review_status: {},
    latest_activity: [],
    index_health: { status: 'ready', healthy: true },
  }),
  addMemory: vi.fn().mockResolvedValue({ status: 'ok' }),
  updateDoc: vi.fn().mockResolvedValue({ status: 'updated' }),
  softForgetDoc: vi.fn().mockResolvedValue({ status: 'forgotten' }),
  restoreDoc: vi.fn().mockResolvedValue({ status: 'restored' }),
  query: vi.fn().mockResolvedValue({ query: '', results: [] }),
  queryPipeline: vi.fn().mockResolvedValue({ query: '', results: [] }),
  queryRag: vi.fn().mockResolvedValue({ query: '', results: [] }),
  getIndexStatus: vi.fn().mockResolvedValue({ status: 'ready', count: 0 }),
}))

vi.mock('@/stores/workspaceStore', () => ({
  useWorkspaceStore: () => ({
    activeWorkspace: workspaceMock.activeWorkspace,
  }),
}))

vi.mock('@/api/client', () => ({
  memoryClient: memoryClientMocks,
}))

describe('useMemoryDomain scoped workspace defaults', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    workspaceMock.activeWorkspace.id = 'ws-1'
    workspaceMock.activeWorkspace.memory_scope = 'workspace'
  })

  it('does not attach a workspace id to global memory writes or updates', async () => {
    const domain = useMemoryDomain()

    await domain.addMemory({ text: 'global memory', scope: 'global' })
    await domain.updateDoc('doc-1', { text: 'updated global memory', scope: 'global' })

    expect(memoryClientMocks.addMemory).toHaveBeenCalledWith(expect.objectContaining({
      scope: 'global',
      workspace_id: undefined,
    }))
    expect(memoryClientMocks.updateDoc).toHaveBeenCalledWith('doc-1', expect.objectContaining({
      scope: 'global',
      workspace_id: undefined,
    }))
  })

  it('uses the active workspace id for workspace-scoped requests', async () => {
    const domain = useMemoryDomain()

    await domain.addMemory({ text: 'workspace memory', scope: 'workspace' })
    await domain.updateDoc('doc-2', { text: 'updated workspace memory', scope: 'workspace' })
    await domain.queryMemory({ query: 'workspace memory', scope: 'workspace' })
    await domain.queryRawRag({ query: 'workspace memory', scope: 'workspace' })

    expect(memoryClientMocks.addMemory).toHaveBeenCalledWith(expect.objectContaining({
      scope: 'workspace',
      workspace_id: 'ws-1',
    }))
    expect(memoryClientMocks.updateDoc).toHaveBeenCalledWith('doc-2', expect.objectContaining({
      scope: 'workspace',
      workspace_id: 'ws-1',
    }))
    expect(memoryClientMocks.query).toHaveBeenCalledWith(expect.objectContaining({
      query: 'workspace memory',
      scope: 'workspace',
      workspace_id: 'ws-1',
    }))
    expect(memoryClientMocks.queryRag).toHaveBeenCalledWith(expect.objectContaining({
      scope: 'workspace',
      workspace_id: 'ws-1',
    }))
  })

  it('loads scoped overview and restores a forgotten memory through the canonical domain', async () => {
    const domain = useMemoryDomain()

    await domain.loadOverview({ scope: 'workspace', workspaceId: 'ws-1' })
    await domain.restoreDoc('doc-forgotten', { reason: 'user_restore' })

    expect(memoryClientMocks.getOverview).toHaveBeenCalledWith({
      scope: 'workspace',
      workspaceId: 'ws-1',
    })
    expect(memoryClientMocks.restoreDoc).toHaveBeenCalledWith('doc-forgotten', {
      reason: 'user_restore',
    })
  })

  it('loads forgotten memories with an explicit lifecycle filter', async () => {
    memoryClientMocks.getDocs.mockResolvedValueOnce({
      docs: [{ id: 'doc-forgotten', text: 'old preference', metadata: { soft_forgotten: true } }],
    })
    const domain = useMemoryDomain()

    await domain.loadForgottenDocs({ scope: 'workspace', workspaceId: 'ws-1' })

    expect(memoryClientMocks.getDocs).toHaveBeenCalledWith({
      scope: 'workspace',
      workspaceId: 'ws-1',
      includeState: 'forgotten',
    })
    expect(domain.forgottenDocs.value).toEqual([
      expect.objectContaining({ id: 'doc-forgotten', state: 'forgotten' }),
    ])
  })

  it('preserves an explicit null expiry when updating a document', async () => {
    const domain = useMemoryDomain()

    await domain.updateDoc('doc-expiry', {
      text: 'keep forever',
      scope: 'workspace',
      metadata: { expires_at: null, extension_field: 'preserved' },
    })

    expect(memoryClientMocks.updateDoc).toHaveBeenCalledWith('doc-expiry', expect.objectContaining({
      metadata: { expires_at: null, extension_field: 'preserved' },
    }))
  })

  it('preserves retrieval score components for result explanations', async () => {
    memoryClientMocks.query.mockResolvedValueOnce({
      query: 'preference',
      results: [{
        id: 'doc-score',
        text: 'prefers tea',
        score: 0.82,
        score_components: { semantic: 0.9, lexical: 0.4, recency: 0.8, quality: 0.7, learned: 0.2, final: 0.82 },
      }],
    })
    const domain = useMemoryDomain()

    await domain.queryMemory({ query: 'preference', scope: 'workspace' })

    expect(domain.queryResult.value?.results[0]).toEqual(expect.objectContaining({
      score_components: {
        semantic: 0.9,
        lexical: 0.4,
        recency: 0.8,
        quality: 0.7,
        learned: 0.2,
        final: 0.82,
      },
    }))
  })
})
