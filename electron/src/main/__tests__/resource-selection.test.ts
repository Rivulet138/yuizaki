import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { describe, expect, it, vi } from 'vitest'
import type { ModelResourceStatusPayload } from '../../shared/resource-manager'

vi.mock('electron', () => ({ dialog: {} }))

import {
  buildProcessTreeTerminationPlan,
  cancelAllModelResourceTasks,
  cancelModelResources,
  classifyResourceFailure,
  getModelResourceStatus,
  isManagedResourceRemovalTarget,
  missingModelResources,
  parseResourceProgressLine,
  readResumableResourceDownload,
  readResumableResourceDirectories,
  removeManagedResourceDirectory,
  resourceManagerPaths,
} from '../resource-manager'

const summary = (ready: boolean) => ({
  ready,
  state: ready ? 'ready' as const : 'missing' as const,
  message: ready ? 'Ready' : 'Missing',
  details: [],
})

const status = {
  soulx: { ...summary(false) },
  sherpa: { ...summary(true) },
  sherpaOnline: { ...summary(false) },
  embedding: { ...summary(false) },
  tts: { ...summary(true) },
} as ModelResourceStatusPayload

describe('model resource selection', () => {
  it('returns each requested missing resource once and skips ready resources', () => {
    expect(missingModelResources(status, ['tts', 'embedding', 'embedding', 'sherpa_online', 'sherpa'])).toEqual([
      'embedding',
      'sherpa_online',
    ])
  })

  it('exposes locked resource metadata from the repository manifest', () => {
    const catalog = {
      getLocalModelRoots: () => ({ live2d: 'live2d', vrm: 'vrm' }),
      getLocalModelCounts: () => ({ live2d: 0, vrm: 0 }),
    }

    const resourceStatus = getModelResourceStatus(catalog as never)

    expect(resourceStatus.sherpa.metadata.version).toBe('2025-09-09-int8')
    expect(resourceStatus.sherpa.metadata.integrity).toBe('sha256')
    expect(resourceStatus.embedding.metadata.integrity).toBe('revision')
    expect(resourceStatus.tts.metadata.integrity).toBe('package+revision')
    expect(resourceStatus.activeDownloads).toEqual([])
    expect(resourceStatus.resumableDownloads).toEqual(expect.any(Array))
    expect(resourceManagerPaths.resourceLockPath).toMatch(/resources\.lock\.json$/)
  })

  it('restores resumable download state from the partial archive journal', () => {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), 'yuizaki-resume-test-'))
    const partialPath = path.join(root, 'archive.part')
    try {
      fs.writeFileSync(partialPath, Buffer.alloc(25))
      fs.writeFileSync(`${partialPath}.json`, JSON.stringify({
        bytesTotal: 100,
        updatedAt: '2026-07-20T00:00:00.000Z',
      }))

      expect(readResumableResourceDownload('sherpa', partialPath, 120)).toEqual({
        resourceId: 'sherpa',
        bytesDownloaded: 25,
        bytesTotal: 100,
        percent: 25,
        updatedAt: '2026-07-20T00:00:00.000Z',
      })
    } finally {
      fs.rmSync(root, { recursive: true, force: true })
    }
  })

  it('reports persistent Hugging Face cache bytes without inventing a percentage', () => {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), 'yuizaki-hf-resume-test-'))
    try {
      fs.mkdirSync(path.join(root, 'blobs'), { recursive: true })
      fs.writeFileSync(path.join(root, 'blobs', 'model.incomplete'), Buffer.alloc(64))

      const state = readResumableResourceDirectories('embedding', [root, path.join(root, 'blobs')])
      expect(state).toMatchObject({
        resourceId: 'embedding',
        bytesDownloaded: 64,
        bytesTotal: null,
        percent: null,
      })
    } finally {
      fs.rmSync(root, { recursive: true, force: true })
    }
  })

  it('classifies actionable resource failures', () => {
    expect(classifyResourceFailure('httpx.ReadTimeout: timed out')).toEqual({
      errorCode: 'network_timeout',
      retryable: true,
      message: 'Resource download timed out',
    })
    expect(classifyResourceFailure('OSError: [Errno 28] No space left on device')).toEqual({
      errorCode: 'disk_full',
      retryable: false,
      message: 'Insufficient disk space',
    })
    expect(classifyResourceFailure('', true).errorCode).toBe('cancelled')
  })

  it('keeps permanent removal inside a child of the managed root', () => {
    const root = path.resolve('managed', 'models')
    expect(isManagedResourceRemovalTarget(path.join(root, 'sherpa'), root)).toBe(true)
    expect(isManagedResourceRemovalTarget(root, root)).toBe(false)
    expect(isManagedResourceRemovalTarget(path.resolve(root, '..', 'outside'), root)).toBe(false)
  })

  it('permanently removes only the selected managed directory', () => {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), 'yuizaki-resource-test-'))
    const target = path.join(root, 'sherpa')
    const sibling = path.join(root, 'keep')
    try {
      fs.mkdirSync(target)
      fs.mkdirSync(sibling)
      fs.writeFileSync(path.join(target, 'model.onnx'), 'model')
      fs.writeFileSync(path.join(sibling, 'keep.txt'), 'keep')

      expect(removeManagedResourceDirectory(target, root)).toBe(5)
      expect(fs.existsSync(target)).toBe(false)
      expect(fs.existsSync(sibling)).toBe(true)
    } finally {
      fs.rmSync(root, { recursive: true, force: true })
    }
  })

  it('treats cancellation as idempotent when no resource task is active', () => {
    const catalog = {
      getLocalModelRoots: () => ({ live2d: 'live2d', vrm: 'vrm' }),
      getLocalModelCounts: () => ({ live2d: 0, vrm: 0 }),
    }

    expect(cancelModelResources(['sherpa'], catalog as never).cancelled).toEqual([])
    expect(cancelAllModelResourceTasks()).toEqual([])
  })

  it('parses structured resource progress without accepting arbitrary stdout', () => {
    expect(parseResourceProgressLine('ordinary output')).toBeNull()
    expect(parseResourceProgressLine(
      'YUIZAKI_RESOURCE_PROGRESS {"phase":"downloading","message":"archive","bytesDownloaded":25,"bytesTotal":100}',
    )).toEqual({
      phase: 'downloading',
      message: 'archive',
      bytesDownloaded: 25,
      bytesTotal: 100,
    })
  })

  it('builds platform-specific process-tree termination plans', () => {
    expect(buildProcessTreeTerminationPlan('win32', 4321)).toEqual({
      kind: 'windows',
      command: 'taskkill',
      args: ['/pid', '4321', '/T', '/F'],
    })
    expect(buildProcessTreeTerminationPlan('linux', 4321)).toEqual({ kind: 'posix', processGroupId: -4321 })
  })
})
