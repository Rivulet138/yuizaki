import { describe, expect, it } from 'vitest'
import { normalizeResourceStatus, normalizeStorageStatus } from '../domains/settings/resourceStatus'

describe('settings resource status normalization', () => {
  it('rejects invalid roots and filters unsupported progress records', () => {
    expect(normalizeResourceStatus(null)).toBeNull()
    const status = normalizeResourceStatus({
      modelRoots: { live2d: 12, vrm: 'C:/models/vrm' },
      activeDownloads: [
        { resourceId: 'embedding', phase: 'downloading', percent: 140, bytesDownloaded: -2, bytesTotal: 8 },
        { resourceId: 'unknown', phase: 'downloading' },
        { resourceId: 'tts', phase: 'unknown' },
      ],
      resumableDownloads: [
        { resourceId: 'tts', bytesDownloaded: 20, bytesTotal: 10, percent: -5 },
        { resourceId: 'tts', bytesDownloaded: 0 },
      ],
    })

    expect(status?.modelRoots).toEqual({ live2d: '12', vrm: 'C:/models/vrm' })
    expect(status?.activeDownloads).toEqual([
      expect.objectContaining({ resourceId: 'embedding', phase: 'downloading', percent: 100, bytesDownloaded: 0 }),
    ])
    expect(status?.resumableDownloads).toEqual([
      expect.objectContaining({ resourceId: 'tts', bytesDownloaded: 20, bytesTotal: 20, percent: 0 }),
    ])
  })

  it('normalizes storage counters and ignores unknown categories', () => {
    expect(normalizeStorageStatus({})).toBeNull()
    expect(normalizeStorageStatus({
      categories: [
        { id: 'tts_audio', bytes: -1, files: 3, action: 'delete_files', persistence: 'disk' },
        { id: 'unknown', bytes: 100 },
      ],
      total_bytes: -10,
      reclaimable_bytes: 25,
    })).toEqual({
      categories: [{
        id: 'tts_audio',
        bytes: 0,
        files: 3,
        action: 'delete_files',
        persistence: 'disk',
        failed_files: 0,
      }],
      total_bytes: 0,
      reclaimable_bytes: 25,
    })
  })
})
