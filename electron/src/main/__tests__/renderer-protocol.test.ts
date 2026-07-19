import path from 'node:path'
import { describe, expect, it, vi } from 'vitest'
import {
  buildPackagedRendererUrl,
  registerRendererProtocol,
  registerRendererProtocolPrivileges,
  resolveRendererRequestFile,
} from '../renderer-protocol'

const electronMock = vi.hoisted(() => ({
  handle: vi.fn(),
  netFetch: vi.fn(),
  registerSchemesAsPrivileged: vi.fn(),
}))

vi.mock('electron', () => ({
  net: { fetch: electronMock.netFetch },
  protocol: {
    handle: electronMock.handle,
    registerSchemesAsPrivileged: electronMock.registerSchemesAsPrivileged,
  },
}))

describe('packaged renderer protocol', () => {
  it('registers a standard secure scheme without bypassing CSP', () => {
    registerRendererProtocolPrivileges()

    expect(electronMock.registerSchemesAsPrivileged).toHaveBeenCalledWith([
      {
        scheme: 'yuizaki-app',
        privileges: {
          standard: true,
          secure: true,
          supportFetchAPI: true,
          codeCache: true,
        },
      },
    ])
  })

  it('builds trusted entry URLs with query parameters', () => {
    expect(buildPackagedRendererUrl('index.html', { tab: 'chat', token: 'a b' }))
      .toBe('yuizaki-app://renderer/index.html?tab=chat&token=a+b')
    expect(buildPackagedRendererUrl('pet-window.html'))
      .toBe('yuizaki-app://renderer/pet-window.html')
  })

  it('maps only renderer-host assets inside the packaged root', () => {
    const root = path.resolve('C:/app/renderer')

    expect(resolveRendererRequestFile('yuizaki-app://renderer/', root))
      .toBe(path.join(root, 'index.html'))
    expect(resolveRendererRequestFile('yuizaki-app://renderer/assets/main.js', root))
      .toBe(path.join(root, 'assets/main.js'))
    expect(resolveRendererRequestFile('yuizaki-app://other/index.html', root)).toBeNull()
    expect(resolveRendererRequestFile('https://renderer/index.html', root)).toBeNull()
    expect(resolveRendererRequestFile('yuizaki-app://renderer/%2e%2e/secret.txt', root)).toBeNull()
    expect(resolveRendererRequestFile('yuizaki-app://renderer/%5c..%5csecret.txt', root)).toBeNull()
  })

  it('serves only GET and HEAD requests from the packaged renderer root', async () => {
    electronMock.netFetch.mockResolvedValue(new Response('ok'))
    registerRendererProtocol()

    const handler = electronMock.handle.mock.calls[0]?.[1] as (request: Request) => Response | Promise<Response>
    expect(electronMock.handle).toHaveBeenCalledWith('yuizaki-app', expect.any(Function))

    const invalidMethod = await handler(new Request('yuizaki-app://renderer/index.html', { method: 'POST' }))
    expect(invalidMethod.status).toBe(405)

    const invalidHost = await handler(new Request('yuizaki-app://other/index.html'))
    expect(invalidHost.status).toBe(404)
    expect(electronMock.netFetch).not.toHaveBeenCalled()

    const valid = await handler(new Request('yuizaki-app://renderer/index.html'))
    expect(valid.status).toBe(200)
    expect(electronMock.netFetch).toHaveBeenCalledWith(
      expect.stringMatching(/^file:\/\/\/.+dist\/renderer\/index\.html$/i),
      { method: 'GET' },
    )
  })
})
