export const clamp = (value: number, min: number, max: number): number =>
  Math.min(max, Math.max(min, value))

export function extractClientPoint(event: any): { x: number; y: number } | null {
  const source = event?.nativeEvent ?? event?.data?.originalEvent ?? event?.srcEvent ?? event

  const x = source?.clientX
  const y = source?.clientY

  return Number.isFinite(x) && Number.isFinite(y) ? { x, y } : null
}

export function extractScreenPoint(event: any): { x: number; y: number } | null {
  const source = event?.nativeEvent ?? event?.data?.originalEvent ?? event?.srcEvent ?? event

  const x = source?.screenX
  const y = source?.screenY

  return Number.isFinite(x) && Number.isFinite(y) ? { x, y } : null
}

export function extractMouseButton(event: any): number {
  const source = event?.nativeEvent ?? event?.data?.originalEvent ?? event?.srcEvent ?? event
  return typeof source?.button === 'number' ? source.button : 0
}

export function shouldTriggerClick(options: {
  button: number
  mouseDownOnModel: boolean
  moved: boolean
  isDraggingWindow: boolean
}): boolean {
  return (
    options.button === 0 &&
    options.mouseDownOnModel &&
    !options.moved &&
    !options.isDraggingWindow
  )
}
