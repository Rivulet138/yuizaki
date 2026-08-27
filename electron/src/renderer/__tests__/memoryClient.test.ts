import { afterEach, describe, expect, it, vi } from 'vitest'
import { CONTROL_ORIGIN, clearControlAuthToken } from '../api/clients/http-client'
import { memoryClient } from '../api/clients/memory-client'

describe('memoryClient', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    clearControlAuthToken()
    window.sessionStorage.clear()
  })

  it('routes memory panel JSON requests through the Electron control server', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: vi.fn().mockResolvedValue({ docs: [], results: [], trace: {} }),
    })
    vi.stubGlobal('fetch', fetchMock)

    await memoryClient.getDocs({ scope: 'workspace', workspaceId: 'default', includeState: 'active' })
    await memoryClient.getIndexStatus()
    await memoryClient.rebuildIndex()
    await memoryClient.updateDoc('doc 1', { text: 'updated memory' })
    await memoryClient.removeDocs(['doc 1', 'doc 2'])
    await memoryClient.queryPipeline('hello', { workspaceId: 'default', topK: 3 })

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      `${CONTROL_ORIGIN}/memory/docs?scope=workspace&workspace_id=default&include_state=active`,
      expect.any(Object),
    )
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      `${CONTROL_ORIGIN}/memory/index/status`,
      expect.any(Object),
    )
    expect(fetchMock).toHaveBeenNthCalledWith(
      3,
      `${CONTROL_ORIGIN}/memory/index/rebuild`,
      expect.objectContaining({
        method: 'POST',
      }),
    )
    expect(fetchMock).toHaveBeenNthCalledWith(
      4,
      `${CONTROL_ORIGIN}/memory/docs/doc%201`,
      expect.objectContaining({
        method: 'PUT',
        headers: expect.objectContaining({
          'Content-Type': 'application/json',
        }),
      }),
    )
    expect(fetchMock).toHaveBeenNthCalledWith(
      5,
      `${CONTROL_ORIGIN}/memory/docs/batch-delete`,
      expect.objectContaining({
        method: 'POST',
        headers: expect.objectContaining({
          'Content-Type': 'application/json',
        }),
        body: JSON.stringify({ ids: ['doc 1', 'doc 2'] }),
      }),
    )
    expect(fetchMock).toHaveBeenNthCalledWith(
      6,
      `${CONTROL_ORIGIN}/api/memory/pipeline/query?query=hello&top_k=3&workspace_id=default`,
      expect.any(Object),
    )
  })

  it('uses canonical overview, query, and restore contracts', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: vi.fn().mockResolvedValue({ status: 'ok', results: [] }),
    })
    vi.stubGlobal('fetch', fetchMock)

    await memoryClient.getOverview({ scope: 'workspace', workspaceId: 'default' })
    await memoryClient.query({ query: 'what matters', scope: 'workspace', workspace_id: 'default' })
    await memoryClient.restoreDoc('memory/1', { reason: 'user_restore' })
    await memoryClient.rollbackDoc('memory/1', 3)

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      `${CONTROL_ORIGIN}/memory/overview?scope=workspace&workspace_id=default`,
      expect.any(Object),
    )
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      `${CONTROL_ORIGIN}/memory/query`,
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ query: 'what matters', scope: 'workspace', workspace_id: 'default' }),
      }),
    )
    expect(fetchMock).toHaveBeenNthCalledWith(
      3,
      `${CONTROL_ORIGIN}/memory/docs/memory%2F1/restore`,
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ reason: 'user_restore' }),
      }),
    )
    expect(fetchMock).toHaveBeenNthCalledWith(
      4,
      `${CONTROL_ORIGIN}/memory/docs/memory%2F1/rollback`,
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ revision: 3 }),
      }),
    )
  })

  it('maps index rebuild progress, cancellation, and retry to job routes', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: vi.fn().mockResolvedValue({ status: 'running', index_status: 'indexing', job: { job_id: 'job/1' } }),
    })
    vi.stubGlobal('fetch', fetchMock)

    await memoryClient.getIndexRebuildJob('job/1')
    await memoryClient.cancelIndexRebuild('job/1')
    await memoryClient.retryIndexRebuild('job/1')

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      `${CONTROL_ORIGIN}/memory/index/rebuild/job%2F1`,
      expect.any(Object),
    )
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      `${CONTROL_ORIGIN}/memory/index/rebuild/job%2F1/cancel`,
      expect.objectContaining({ method: 'POST' }),
    )
    expect(fetchMock).toHaveBeenNthCalledWith(
      3,
      `${CONTROL_ORIGIN}/memory/index/rebuild/job%2F1/retry`,
      expect.objectContaining({ method: 'POST' }),
    )
  })

  it('encodes memory document ids before using them in route paths', async () => {
    window.sessionStorage.setItem('yuizaki.control.token', 'memory-token')
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: vi.fn().mockResolvedValue({ status: 'ok', id: 'folder/doc 1' }),
    })
    vi.stubGlobal('fetch', fetchMock)

    await memoryClient.updateDoc('folder/doc 1', { text: 'updated memory' })
    await memoryClient.removeDoc('folder/doc 1')

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      `${CONTROL_ORIGIN}/memory/docs/folder%2Fdoc%201`,
      expect.objectContaining({ method: 'PUT' }),
    )
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      `${CONTROL_ORIGIN}/memory/docs/folder%2Fdoc%201`,
      expect.objectContaining({ method: 'DELETE' }),
    )
  })

  it('soft-forgets a memory without issuing a destructive delete', async () => {
    window.sessionStorage.setItem('yuizaki.control.token', 'memory-token')
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: vi.fn().mockResolvedValue({ status: 'ok', id: 'memory-1', action: 'soft-forget' }),
    })
    vi.stubGlobal('fetch', fetchMock)

    await memoryClient.softForgetDoc('memory-1', { reason: 'chat_memory_feedback', turn_id: 'turn-1' })

    expect(fetchMock).toHaveBeenCalledWith(
      `${CONTROL_ORIGIN}/memory/docs/memory-1/soft-forget`,
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ reason: 'chat_memory_feedback', turn_id: 'turn-1' }),
      }),
    )
    expect(fetchMock).not.toHaveBeenCalledWith(
      `${CONTROL_ORIGIN}/memory/docs/memory-1`,
      expect.objectContaining({ method: 'DELETE' }),
    )
  })

  it('records low-friction recall feedback on the canonical memory route', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: vi.fn().mockResolvedValue({ status: 'recorded', id: 'memory-1', feedback: 'helpful', counts: { helpful: 1 } }),
    })
    vi.stubGlobal('fetch', fetchMock)

    await memoryClient.recordRecallFeedback('folder/memory 1', 'helpful')

    expect(fetchMock).toHaveBeenCalledWith(
      `${CONTROL_ORIGIN}/memory/docs/folder%2Fmemory%201/feedback`,
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ feedback: 'helpful' }),
      }),
    )
  })

  it('maps maintenance preview and purge controls to explicit backend contracts', async () => {
    window.sessionStorage.setItem('yuizaki.control.token', 'memory-token')
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: vi.fn().mockResolvedValue({ status: 'preview', summary: {}, candidates: [] }),
    })
    vi.stubGlobal('fetch', fetchMock)
    const policy = {
      scope: 'workspace',
      workspace_id: 'default',
      working_retention_days: 14,
      low_quality_threshold: 0.55,
      include_stale_working: true,
      include_low_quality: true,
      include_exact_duplicates: true,
    }

    await memoryClient.previewMaintenance(policy)
    const previewToken = 'a'.repeat(64)
    await memoryClient.applyMaintenance({
      ...policy,
      confirmation: 'PERMANENT_DELETE',
      preview_token: previewToken,
    })

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      `${CONTROL_ORIGIN}/memory/maintenance/preview`,
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify(policy),
      }),
    )
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      `${CONTROL_ORIGIN}/memory/maintenance/apply`,
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({
          ...policy,
          confirmation: 'PERMANENT_DELETE',
          preview_token: previewToken,
        }),
      }),
    )
  })
})
