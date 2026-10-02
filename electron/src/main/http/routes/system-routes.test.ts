import { describe, expect, it } from 'vitest'

import {
  isProactivePythonProxyRoute,
  isPythonBlobProxyPath,
  isPythonJsonProxyPath,
} from './system-routes'

describe('control-server Python proxy route contract', () => {
  it('exposes memory audit, export/import and rebuild job routes', () => {
    expect(isPythonJsonProxyPath('/memory/operations')).toBe(true)
    expect(isPythonJsonProxyPath('/memory/export')).toBe(true)
    expect(isPythonBlobProxyPath('/api/settings/export')).toBe(true)
    expect(isPythonJsonProxyPath('/memory/import')).toBe(true)
    expect(isPythonJsonProxyPath('/memory/index/rebuild/job-1')).toBe(true)
    expect(isPythonJsonProxyPath('/memory/index/rebuild/job-1/cancel')).toBe(true)
    expect(isPythonJsonProxyPath('/memory/index/rebuild/job-1/retry')).toBe(true)
    expect(isPythonJsonProxyPath('/memory/index/rebuild/job-1/unknown')).toBe(false)
  })

  it('exposes activity-frame rebuild only for POST', () => {
    expect(isProactivePythonProxyRoute('POST', '/api/system/activity-frames/rebuild')).toBe(true)
    expect(isProactivePythonProxyRoute('GET', '/api/system/activity-frames/rebuild')).toBe(false)
  })

  it('keeps credential reload on the authenticated JSON proxy', () => {
    expect(isPythonJsonProxyPath('/api/settings/credentials/reload')).toBe(true)
    expect(isPythonBlobProxyPath('/api/settings/credentials/reload')).toBe(false)
  })
})
