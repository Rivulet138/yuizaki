export interface PetRendererWindowHandlers {
  handleWindowMouseDown: (event: MouseEvent) => void
  handleWindowMouseMove: (event: MouseEvent) => void
  handleWindowMouseUp: (event: MouseEvent) => void
  handleWindowPointerCancel: (event: PointerEvent) => void
  handleWindowMouseLeave: () => void
  handleWindowBlur: () => void
  handleWindowWheel: (event: WheelEvent) => void
  handleResize: () => void
  handleWindowContextMenu: (event: MouseEvent) => void
  handleWindowError: (event: ErrorEvent) => void
  handleUnhandledRejection: (event: PromiseRejectionEvent) => void
}

export function attachWindowListeners(handlers: PetRendererWindowHandlers): void {
  window.addEventListener('mousedown', handlers.handleWindowMouseDown)
  window.addEventListener('mousemove', handlers.handleWindowMouseMove)
  window.addEventListener('mouseup', handlers.handleWindowMouseUp)
  window.addEventListener('pointercancel', handlers.handleWindowPointerCancel)
  window.addEventListener('mouseleave', handlers.handleWindowMouseLeave)
  window.addEventListener('blur', handlers.handleWindowBlur)
  window.addEventListener('wheel', handlers.handleWindowWheel, { passive: false })
  window.addEventListener('resize', handlers.handleResize)
  window.addEventListener('contextmenu', handlers.handleWindowContextMenu)
  window.addEventListener('error', handlers.handleWindowError)
  window.addEventListener('unhandledrejection', handlers.handleUnhandledRejection)
}

export function detachWindowListeners(handlers: PetRendererWindowHandlers): void {
  window.removeEventListener('mousedown', handlers.handleWindowMouseDown)
  window.removeEventListener('mousemove', handlers.handleWindowMouseMove)
  window.removeEventListener('mouseup', handlers.handleWindowMouseUp)
  window.removeEventListener('pointercancel', handlers.handleWindowPointerCancel)
  window.removeEventListener('mouseleave', handlers.handleWindowMouseLeave)
  window.removeEventListener('blur', handlers.handleWindowBlur)
  window.removeEventListener('wheel', handlers.handleWindowWheel)
  window.removeEventListener('resize', handlers.handleResize)
  window.removeEventListener('contextmenu', handlers.handleWindowContextMenu)
  window.removeEventListener('error', handlers.handleWindowError)
  window.removeEventListener('unhandledrejection', handlers.handleUnhandledRejection)
}
