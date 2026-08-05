import {
  ChatDotRound,
  Collection,
  Connection,
  Cpu,
  DataAnalysis,
  HomeFilled,
  MagicStick,
  Operation,
  Setting,
  StarFilled,
  Tickets,
  Tools,
  UserFilled,
} from '@element-plus/icons-vue'
import { type AsyncComponentLoader, type Component, defineAsyncComponent } from 'vue'
import { hasMessage, t } from '@/i18n'
import { staticNavigationModuleRecords, type StaticNavigationModuleId } from '../../shared/navigation'
import type { NavigationModule } from './types'

export type NavigationModuleId = StaticNavigationModuleId

interface NavigationModuleInput extends Omit<NavigationModule, 'component'> {
  id: NavigationModuleId
  icon: Component
  component?: Component
  loader?: AsyncComponentLoader
}

const createAsyncView = (loader: AsyncComponentLoader): Component =>
  defineAsyncComponent(loader)

const createNavigationModule = (module: NavigationModuleInput, order: number): NavigationModule => {
  const component = module.component ?? (module.loader ? createAsyncView(module.loader) : undefined)

  if (!component) {
    throw new Error(`Navigation module ${module.id} is missing a component loader`)
  }

  return {
    ...module,
    component,
    order: module.order ?? order,
    enabled: module.enabled ?? true,
  }
}

const moduleViewDefinitions: Record<NavigationModuleId, { icon: Component; loader: AsyncComponentLoader }> = {
  overview: { icon: HomeFilled, loader: () => import('@/domains/system/views/OverviewPanel.vue') },
  pet: { icon: StarFilled, loader: () => import('@/domains/pet/views/PetControlPanel.vue') },
  chat: { icon: ChatDotRound, loader: () => import('@/domains/chat/views/ChatPanel.vue') },
  prompt: { icon: Tickets, loader: () => import('@/domains/prompt/views/PromptPanel.vue') },
  companion: { icon: UserFilled, loader: () => import('@/domains/companion/views/CompanionPanel.vue') },
  svc: { icon: Cpu, loader: () => import('@/domains/tools/views/SVCPanel.vue') },
  tool: { icon: Tools, loader: () => import('@/domains/tools/views/ToolPanel.vue') },
  plugins: { icon: Operation, loader: () => import('@/domains/plugin/views/PluginManagementPanel.vue') },
  infrastructure: { icon: DataAnalysis, loader: () => import('@/domains/system/views/InfrastructurePanel.vue') },
  'agent-governance': { icon: Operation, loader: () => import('@/domains/system/views/AgentGovernancePanel.vue') },
  'agent-trace': { icon: Connection, loader: () => import('@/domains/system/views/AgentTracePanel.vue') },
  'agent-trace-admin': { icon: Connection, loader: () => import('@/domains/system/views/TasksPanel.vue') },
  'persona-memory': { icon: MagicStick, loader: () => import('@/domains/memory/views/PersonaMemoryPanel.vue') },
  settings: { icon: Setting, loader: () => import('@/domains/settings/views/SettingsPanel.vue') },
  i18n: { icon: Setting, loader: () => import('@/domains/i18n/views/I18nPanel.vue') },
  memory: { icon: Collection, loader: () => import('@/domains/memory/views/MemoryPanel.vue') },
  deploy: { icon: Connection, loader: () => import('@/domains/deploy/views/DeployPanel.vue') },
}

const staticModuleDefinitions: NavigationModuleInput[] = staticNavigationModuleRecords.map((module) => ({
  ...module,
  ...moduleViewDefinitions[module.id],
}))

export const navigationModules: NavigationModule[] = staticModuleDefinitions.map((module, index) =>
  createNavigationModule(module, index),
)

const localizeNavigationModule = (module: NavigationModule): NavigationModule => {
  const titleKey = `navigation.${module.id}.title`
  const descKey = `navigation.${module.id}.desc`

  return {
    ...module,
    title: hasMessage(titleKey) ? t(titleKey) : module.title,
    desc: hasMessage(descKey) ? t(descKey) : module.desc,
  }
}

export const enabledNavigationModules = (): NavigationModule[] =>
  navigationModules
    .filter((module) => module.enabled !== false)
    .map(localizeNavigationModule)
    .sort((a, b) => (a.order ?? 0) - (b.order ?? 0))

const primaryMenuOrder: NavigationModuleId[] = ['companion', 'chat', 'memory']

export const primaryNavigationModules = (): NavigationModule[] =>
  enabledNavigationModules()
    .filter((module) => module.primary !== false && module.audience !== 'admin')
    .sort((a, b) => {
      const aIndex = primaryMenuOrder.indexOf(a.id as NavigationModuleId)
      const bIndex = primaryMenuOrder.indexOf(b.id as NavigationModuleId)
      const aRank = aIndex === -1 ? Number.MAX_SAFE_INTEGER : aIndex
      const bRank = bIndex === -1 ? Number.MAX_SAFE_INTEGER : bIndex
      if (aRank !== bRank) return aRank - bRank
      return (a.order ?? 0) - (b.order ?? 0)
    })

export const adminNavigationModules = (): NavigationModule[] =>
  enabledNavigationModules().filter((module) => module.audience === 'admin' || module.slot === 'admin')

export const isPanelKey = (value: string): value is NavigationModuleId => {
  return staticModuleDefinitions.some((module) => module.id === value)
}
