import type { PetApi } from '@/../shared/pet-api'
import type { Live2dApi } from '@/../shared/live2d-api'

declare global {
  interface Window {
    petApi?: PetApi
    live2dApi: Live2dApi
  }
}

export {}
