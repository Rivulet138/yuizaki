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
  addMemory: vi.fn().mockResolvedValue({ status: 'ok' }),
  updateDoc: vi.fn().mockResolvedValue({ status: 'updated' }),
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
    expect(memoryClientMocks.queryPipeline).toHaveBeenCalledWith('workspace memory', expect.objectContaining({
      scope: 'workspace',
      workspaceId: 'ws-1',
    }))
    expect(memoryClientMocks.queryRag).toHaveBeenCalledWith(expect.objectContaining({
      scope: 'workspace',
      workspace_id: 'ws-1',
    }))
  })
})
