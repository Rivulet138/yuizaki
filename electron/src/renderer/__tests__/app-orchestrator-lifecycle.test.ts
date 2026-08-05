import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it, vi } from 'vitest'
import { bootstrapAppDomains, switchWorkspaceAndLoadSessions } from '../app/orchestrators/useAppOrchestrator'

describe('application orchestrator workspace lifecycle', () => {
  it('waits for store-owned workspace synchronization before loading sessions', async () => {
    const order: string[] = []
    let releaseSync!: () => void
    const syncBarrier = new Promise<void>((resolve) => { releaseSync = resolve })
    const syncFromBackend = vi.fn(async () => {
      order.push('sync:start')
      await syncBarrier
      order.push('sync:end')
    })
    const loadSessions = vi.fn(async () => { order.push('sessions') })

    const pending = bootstrapAppDomains({
      initChatStore: vi.fn(),
      loadCompanions: vi.fn(),
      syncFromBackend,
      applyActiveCompanionRuntime: vi.fn(),
      loadSessions,
    })
    await Promise.resolve()
    expect(loadSessions).not.toHaveBeenCalled()
    releaseSync()
    await pending

    expect(order).toEqual(['sync:start', 'sync:end', 'sessions'])
  })

  it('keeps the workspace/session watcher local-only', () => {
    const source = readFileSync(resolve(process.cwd(), 'src/renderer/app/orchestrators/useAppOrchestrator.ts'), 'utf8')
    const watcher = source.slice(source.indexOf('() => [workspaceStore.activeWorkspaceId'))
    expect(watcher).toContain('chatStore.setWorkspaceContext')
    expect(watcher).not.toContain('systemClient.setActiveWorkspace')
    expect(watcher).not.toContain("sync active workspace")
  })

  it('recovers a failed workspace backend sync before continuing bootstrap in order', async () => {
    const order: string[] = []
    const recoveredLabels: string[] = []

    await expect(bootstrapAppDomains({
      initChatStore: () => { order.push('chat') },
      loadCompanions: async () => { order.push('companions') },
      syncFromBackend: async () => {
        order.push('workspace-sync')
        throw new Error('backend offline')
      },
      applyActiveCompanionRuntime: async () => { order.push('companion-runtime') },
      loadSessions: async () => { order.push('sessions') },
      run: async (label, task) => {
        try {
          await task()
        } catch {
          recoveredLabels.push(label)
        }
      },
    })).resolves.toBeUndefined()

    expect(recoveredLabels).toEqual(['sync workspaces'])
    expect(order).toEqual(['chat', 'companions', 'workspace-sync', 'companion-runtime', 'sessions'])
  })

  it('finishes one manual workspace sync before loading its sessions', async () => {
    const order: string[] = []
    const setActiveWorkspaceSynced = vi.fn(async (workspaceId: string) => {
      order.push(`post:${workspaceId}`)
    })
    const loadSessions = vi.fn(async () => { order.push('sessions') })

    await switchWorkspaceAndLoadSessions('focus', setActiveWorkspaceSynced, loadSessions)

    expect(setActiveWorkspaceSynced).toHaveBeenCalledTimes(1)
    expect(loadSessions).toHaveBeenCalledTimes(1)
    expect(order).toEqual(['post:focus', 'sessions'])
  })
})
