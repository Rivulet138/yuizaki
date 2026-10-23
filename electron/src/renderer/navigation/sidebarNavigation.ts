import { t } from '@/i18n'

export type SidebarNavigationItem = {
  id: string
}

export type SidebarNavigationGroup<T extends SidebarNavigationItem> = {
  id: string
  label: string
  hint: string
  items: T[]
}

export const primarySidebarMenuIds = ['chat', 'memory', 'settings'] as const

// Runtime diagnostics remain reachable through direct links, but do not occupy
// the compact browser sidebar alongside user-facing settings.
export const hiddenSidebarMenuIds = ['infrastructure', 'deploy'] as const

// Labels are lazy getters, not plain strings: this module is imported from plain
// .ts call sites where `computed` is not available, and the getters are read on
// every navigation rebuild so the labels follow the active locale.
export const advancedSidebarGroups = [
  {
    id: 'companion',
    get label(): string { return t('nav.groupCompanion') },
    get hint(): string { return t('nav.hintCompanion') },
    ids: ['prompt', 'pet', 'persona-memory'],
  },
  {
    id: 'tools',
    get label(): string { return t('nav.groupTools') },
    get hint(): string { return t('nav.hintTools') },
    ids: ['tool', 'svc', 'plugins'],
  },
  {
    id: 'audit',
    get label(): string { return t('nav.groupAudit') },
    get hint(): string { return t('nav.hintAudit') },
    ids: ['agent-trace', 'agent-governance'],
  },
  {
    id: 'settings',
    get label(): string { return t('nav.groupSettings') },
    get hint(): string { return t('nav.hintSettings') },
    ids: ['i18n'],
  },
] as const

export const buildSidebarNavigation = <T extends SidebarNavigationItem>(menus: readonly T[]): {
  primary: T[]
  advanced: Array<SidebarNavigationGroup<T>>
} => {
  const byId = new Map(menus.map((menu) => [menu.id, menu]))
  const primary = primarySidebarMenuIds.flatMap((id) => {
    const menu = byId.get(id)
    return menu ? [menu] : []
  })
  const remaining = new Set(menus.map((menu) => menu.id))
  primary.forEach((menu) => remaining.delete(menu.id))

  const advanced: Array<SidebarNavigationGroup<T>> = advancedSidebarGroups.flatMap((group) => {
    const items = group.ids.flatMap((id) => {
      const menu = byId.get(id)
      return menu && remaining.has(menu.id) ? [menu] : []
    })
    items.forEach((menu) => remaining.delete(menu.id))
    return items.length ? [{ id: group.id, label: group.label, hint: group.hint, items }] : []
  })
  hiddenSidebarMenuIds.forEach((id) => remaining.delete(id))
  const otherItems = menus.filter((menu) => remaining.has(menu.id))
  if (otherItems.length) advanced.push({ id: 'other', label: t('nav.groupOther'), hint: t('nav.hintOther'), items: otherItems })

  return { primary, advanced }
}

export const isPrimarySidebarMenu = (menuId: string): boolean => (
  primarySidebarMenuIds.some((id) => id === menuId)
)

export const buildSidebarRoute = (workspaceId: string, menuId: string): string => (
  `/w/${encodeURIComponent(workspaceId)}/${encodeURIComponent(menuId)}`
)
