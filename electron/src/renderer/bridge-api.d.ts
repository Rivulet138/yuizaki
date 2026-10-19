import type { PetApi } from '@/../shared/pet-api'

declare global {
  interface Window {
    petApi?: PetApi
  }
}

export {}
