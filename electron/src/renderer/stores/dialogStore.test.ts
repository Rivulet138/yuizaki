import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'
import { isPermissionRequestPayload, useDialogStore, type PermissionRequestPayload } from './dialogStore'

const request = (requestId: string): PermissionRequestPayload => ({
  request_id: requestId,
  tool_name: 'delegate.test',
  risk_level: 'high',
  reason: 'test',
})

describe('dialog permission queue', () => {
  it('validates socket permission payloads before queueing them', () => {
    expect(isPermissionRequestPayload({ ...request('request-1'), args: { path: '/tmp' } })).toBe(true)
    for (const invalid of [null, [], {}, { ...request(''), reason: 'test' },
      { ...request('request-1'), risk_level: 3 }, { ...request('request-1'), capability_id: false }]) {
      expect(isPermissionRequestPayload(invalid)).toBe(false)
    }
  })

  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('keeps permission requests FIFO and ignores duplicate request ids', () => {
    const store = useDialogStore()
    store.openPermissionRequest(request('request-1'))
    store.openPermissionRequest(request('request-1'))
    store.openPermissionRequest(request('request-2'))

    expect(store.permissionRequests).toHaveLength(2)
    expect(store.permissionRequest?.request_id).toBe('request-1')
    expect(store.permissionDialogVisible).toBe(true)

    store.completePermissionRequest('request-1')
    expect(store.permissionRequest?.request_id).toBe('request-2')
    expect(store.permissionDialogVisible).toBe(true)

    store.completePermissionRequest('request-2')
    expect(store.permissionRequest).toBeNull()
    expect(store.permissionDialogVisible).toBe(false)
  })

  it('does not remove a request when a non-current id is completed', () => {
    const store = useDialogStore()
    store.openPermissionRequest(request('request-1'))
    store.openPermissionRequest(request('request-2'))

    store.completePermissionRequest('request-2')

    expect(store.permissionRequests.map(({ request_id }) => request_id)).toEqual([
      'request-1',
      'request-2',
    ])
  })

  it('removes an invalid request and advances the queue', () => {
    const store = useDialogStore()
    store.openPermissionRequest(request('request-1'))
    store.openPermissionRequest(request('request-2'))

    store.removePermissionRequest('request-1')

    expect(store.permissionRequest?.request_id).toBe('request-2')
    expect(store.permissionDialogVisible).toBe(true)
  })

  it('clears queued requests when the socket session is gone', () => {
    const store = useDialogStore()
    store.openPermissionRequest(request('request-1'))
    store.clearPermissionRequests()

    expect(store.permissionRequests).toEqual([])
    expect(store.permissionDialogVisible).toBe(false)
  })
})
