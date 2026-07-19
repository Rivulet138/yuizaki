import { getSocketClient } from '@/net/socketClient'
import { API_ORIGIN } from './http-client'

export const shortcutClient = {
  on: (event: string, handler: (...args: any[]) => void) => {
    window.petApi?.on?.(event, handler)
  },
  off: (event: string, handler: (...args: any[]) => void) => {
    window.petApi?.off?.(event, handler)
  },
}

export const chatClient = {
  getSocketClient: () => getSocketClient(import.meta.env.VITE_YUIZAKI_SOCKET_ORIGIN || API_ORIGIN),
}
