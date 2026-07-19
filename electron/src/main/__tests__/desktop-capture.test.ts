import { describe, expect, it, vi } from 'vitest'
import type { DesktopCapturerSource, Display } from 'electron'
import { captureDisplayPng, selectDesktopCaptureSource } from '../desktop-capture'

const source = (id: string, displayId = ''): DesktopCapturerSource => ({
  id,
  display_id: displayId,
  name: id,
  thumbnail: {
    isEmpty: () => false,
    toPNG: () => Buffer.from(id),
  },
  appIcon: null,
} as DesktopCapturerSource)

describe('desktop capture', () => {
  it('selects the source that declares the Electron display id', () => {
    const sources = [source('screen:1:0', '1'), source('screen:2:0', '2')]
    expect(selectDesktopCaptureSource(sources, 2, 0)).toBe(sources[1])
  })

  it('accepts the single source returned by a Wayland portal', () => {
    const portalSource = source('screen:portal:0')
    expect(selectDesktopCaptureSource([portalSource], 42, 3)).toBe(portalSource)
  })

  it('falls back to source order when display ids are unavailable', () => {
    const sources = [source('screen:first:0'), source('screen:second:0')]
    expect(selectDesktopCaptureSource(sources, 42, 1)).toBe(sources[1])
  })

  it('requests a physical-size thumbnail and returns PNG bytes', async () => {
    const getSources = vi.fn(async () => [source('screen:7:0', '7')])
    const display = {
      id: 7,
      bounds: { x: 0, y: 0, width: 1280, height: 720 },
      scaleFactor: 1.5,
    } as Display

    await expect(captureDisplayPng(display, 0, getSources)).resolves.toEqual(Buffer.from('screen:7:0'))
    expect(getSources).toHaveBeenCalledWith({
      types: ['screen'],
      thumbnailSize: { width: 1920, height: 1080 },
      fetchWindowIcons: false,
    })
  })
})
