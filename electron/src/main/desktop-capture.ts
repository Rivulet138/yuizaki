import type { DesktopCapturerSource, Display } from 'electron'

type CaptureSourceProvider = (options: {
  types: Array<'screen'>
  thumbnailSize: { width: number; height: number }
  fetchWindowIcons: false
}) => Promise<DesktopCapturerSource[]>

export const selectDesktopCaptureSource = (
  sources: DesktopCapturerSource[],
  displayId: number,
  displayIndex: number,
): DesktopCapturerSource | null => {
  const id = String(displayId)
  return sources.find((source) => source.display_id === id)
    ?? sources.find((source) => source.id.startsWith(`screen:${id}:`))
    ?? (sources.length === 1 ? sources[0] : sources[displayIndex])
    ?? null
}

export const captureDisplayPng = async (
  display: Display,
  displayIndex: number,
  getSources: CaptureSourceProvider,
): Promise<Buffer> => {
  const scaleFactor = Number.isFinite(display.scaleFactor) && display.scaleFactor > 0
    ? display.scaleFactor
    : 1
  const thumbnailSize = {
    width: Math.max(1, Math.round(display.bounds.width * scaleFactor)),
    height: Math.max(1, Math.round(display.bounds.height * scaleFactor)),
  }
  const sources = await getSources({
    types: ['screen'],
    thumbnailSize,
    fetchWindowIcons: false,
  })
  const source = selectDesktopCaptureSource(sources, display.id, displayIndex)
  if (!source || source.thumbnail.isEmpty()) {
    throw new Error(`Desktop capture source unavailable for display ${display.id}`)
  }
  return source.thumbnail.toPNG()
}
