import type { AsyncComponentLoader, Component } from 'vue'
import type { NavigationAudience, NavigationCapability, NavigationSlot } from '../../shared/navigation'

export interface NavigationModule {
  id: string
  title: string
  desc: string
  icon?: Component
  component: Component
  loader?: AsyncComponentLoader
  order?: number
  enabled?: boolean
  capabilities?: NavigationCapability
  slot?: NavigationSlot
  audience?: NavigationAudience
  primary?: boolean
}
