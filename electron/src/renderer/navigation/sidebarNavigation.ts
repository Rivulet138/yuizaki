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

export const advancedSidebarGroups = [
  { id: 'companion', label: '桌宠', hint: '人格、外观与记录', ids: ['prompt', 'pet', 'persona-memory'] },
  { id: 'system', label: '运行', hint: '服务与启动', ids: ['infrastructure', 'deploy'] },
  { id: 'tools', label: '工具', hint: '本地能力与插件', ids: ['tool', 'svc', 'plugins'] },
  { id: 'audit', label: '审计', hint: '任务与权限追踪', ids: ['agent-trace', 'agent-governance'] },
  { id: 'settings', label: '设置', hint: '语言与界面', ids: ['i18n'] },
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
  const otherItems = menus.filter((menu) => remaining.has(menu.id))
  if (otherItems.length) advanced.push({ id: 'other', label: '其他', hint: '其他可用模块', items: otherItems })

  return { primary, advanced }
}

export const isPrimarySidebarMenu = (menuId: string): boolean => (
  primarySidebarMenuIds.some((id) => id === menuId)
)

export const buildSidebarRoute = (workspaceId: string, menuId: string): string => (
  `/w/${encodeURIComponent(workspaceId)}/${encodeURIComponent(menuId)}`
)
