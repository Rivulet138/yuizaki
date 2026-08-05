<template>
  <aside class="sidebar" :aria-label="t('sidebar.aria')">
    <div class="brand">
      <img
        v-if="yuizakiConfig.decorations.letterDecor"
        class="brand-wordmark"
        :src="yuizakiConfig.decorations.letterDecor"
        alt="Yuizaki"
      />
      <span class="brand-name">結崎</span>
    </div>

    <div class="menu-section-label">{{ t('sidebar.primary') }}</div>
    <nav class="menu">
      <router-link
        v-for="menu in menus"
        :key="menu.id"
        :to="`/w/${activeWorkspaceId}/${menu.id}`"
        class="menu-item"
        active-class="active"
        :aria-label="menu.title"
        :title="menu.title"
      >
        <el-icon class="menu-icon"><component :is="menu.icon" /></el-icon>
        <span class="menu-label">{{ menu.title }}</span>
      </router-link>
    </nav>

    <div v-if="adminMenus.length" class="menu-divider" />

    <button
      v-if="adminMenus.length"
      class="admin-toggle"
      type="button"
      :aria-expanded="adminExpanded"
      :aria-label="t('sidebar.admin')"
      :title="t('sidebar.admin')"
      @click="adminExpanded = !adminExpanded"
    >
      <span class="admin-toggle-label">{{ t('sidebar.admin') }}</span>
      <el-icon class="admin-toggle-icon" :class="{ expanded: adminExpanded }"><ArrowDown /></el-icon>
    </button>
    <nav v-if="adminMenus.length && adminExpanded" class="menu admin-menu">
      <section v-for="group in adminMenuGroups" :key="group.id" class="admin-group" :aria-label="group.label">
        <div class="admin-group-label">{{ group.label }}</div>
        <router-link
          v-for="menu in group.items"
          :key="`admin-${menu.id}`"
          :to="`/w/${activeWorkspaceId}/${menu.id}`"
          class="menu-item admin"
          active-class="active"
          :aria-label="menu.title"
          :title="menu.title"
        >
          <el-icon class="menu-icon"><component :is="menu.icon" /></el-icon>
          <span class="menu-label">{{ menu.title }}</span>
        </router-link>
        <details v-if="group.relatedItems.length" class="related-routes">
          <summary>{{ t('sidebar.related') }}</summary>
          <router-link
            v-for="menu in group.relatedItems"
            :key="`related-${menu.id}`"
            :to="`/w/${activeWorkspaceId}/${menu.id}`"
            class="menu-item admin related"
            active-class="active"
            :aria-label="menu.title"
            :title="menu.title"
          >
            <el-icon class="menu-icon"><component :is="menu.icon" /></el-icon>
            <span class="menu-label">{{ menu.title }}</span>
          </router-link>
        </details>
      </section>
    </nav>

    <div class="sidebar-footer">
      <button
        class="menu-item settings-action"
        type="button"
        title="桌宠场景设置"
        aria-label="桌宠场景设置"
        data-testid="workspace-settings"
        @click="$emit('open-workspace-settings')"
      >
        <el-icon class="menu-icon"><Setting /></el-icon>
        <span class="menu-label">场景设置</span>
      </button>
    </div>
  </aside>
</template>

<script setup lang="ts">
import { ArrowDown, Setting } from '@element-plus/icons-vue'
import { computed, ref } from 'vue'
import type { Component } from 'vue'
import { yuizakiConfig } from '@/config/yuizaki'
import { t } from '@/i18n'

type SidebarMenu = { id: string; title: string; icon: Component; desc?: string }

const props = defineProps<{
  activeWorkspaceId: string
  menus: SidebarMenu[]
  adminMenus: SidebarMenu[]
}>()
defineEmits<{
  (e: 'open-workspace-settings'): void
}>()
const adminExpanded = ref(false)

const adminGroupDefinitions = [
  { id: 'permissions', labelKey: 'sidebar.groups.skillsConnectionsPermissions', canonicalIds: ['tool'], relatedIds: ['plugins', 'agent-governance'] },
  { id: 'tasks', labelKey: 'sidebar.groups.audit', canonicalIds: ['agent-trace'], relatedIds: ['agent-trace-admin'] },
  { id: 'system', labelKey: 'sidebar.groups.runtime', canonicalIds: ['overview', 'infrastructure'], relatedIds: ['deploy'] },
  { id: 'developer', labelKey: 'sidebar.groups.debug', canonicalIds: ['settings', 'pet'], relatedIds: ['prompt', 'persona-memory', 'svc', 'i18n'] },
]

const adminMenuGroups = computed(() => {
  const remaining = new Set(props.adminMenus.map((menu) => menu.id))
  const groups = adminGroupDefinitions
    .map((group) => {
      const items = group.canonicalIds
        .map((id) => props.adminMenus.find((menu) => menu.id === id))
        .filter((menu): menu is SidebarMenu => Boolean(menu))
      const relatedItems = group.relatedIds
        .map((id) => props.adminMenus.find((menu) => menu.id === id))
        .filter((menu): menu is SidebarMenu => Boolean(menu))
      items.forEach((menu) => remaining.delete(menu.id))
      relatedItems.forEach((menu) => remaining.delete(menu.id))
      return { ...group, label: t(group.labelKey), items, relatedItems }
    })
    .filter((group) => group.items.length > 0 || group.relatedItems.length > 0)

  const otherItems = props.adminMenus.filter((menu) => remaining.has(menu.id))
  if (otherItems.length) {
    groups.push({
      id: 'other',
      labelKey: 'sidebar.groups.other',
      label: t('sidebar.groups.other'),
      canonicalIds: otherItems.map((item) => item.id),
      relatedIds: [],
      items: otherItems,
      relatedItems: [],
    })
  }
  return groups
})
</script>

<style scoped>
.sidebar {
  position: relative;
  z-index: 3;
  display: flex;
  flex-direction: column;
  width: 232px;
  min-width: 232px;
  height: calc(100% - 36px);
  margin: 18px 0 18px 18px;
  padding: 18px 12px 14px;
  overflow: hidden;
  border: 1px solid var(--yui-border);
  border-radius: var(--yui-radius-panel);
  background: var(--yui-surface);
  box-shadow: var(--yui-shadow-card);
  box-sizing: border-box;
}

.sidebar::before {
  content: none;
}

.brand,
.menu,
.menu-divider {
  position: relative;
  z-index: 1;
}

.brand {
  display: flex;
  align-items: center;
  justify-content: flex-start;
  padding: 0 6px 16px 12px;
}

.brand-wordmark {
  display: block;
  width: min(124px, 100%);
  height: auto;
  object-fit: contain;
  object-position: left center;
  filter: drop-shadow(0 8px 16px rgba(244, 114, 182, 0.14));
}

.brand-name {
  display: none;
  color: var(--yui-text);
  font-size: 18px;
  font-weight: 800;
  letter-spacing: 0;
}

.menu {
  display: flex;
  flex-direction: column;
  gap: 7px;
  min-height: 0;
  overflow-y: auto;
}

.sidebar > .menu:not(.admin-menu) {
  flex: 0 0 auto;
}

.menu::-webkit-scrollbar {
  width: 4px;
}

.menu::-webkit-scrollbar-thumb {
  border-radius: 999px;
  background: rgba(124, 58, 237, 0.22);
}

.menu-item {
  position: relative;
  display: flex;
  align-items: center;
  gap: 10px;
  min-height: 42px;
  padding: 0 11px;
  overflow: hidden;
  border: 1px solid transparent;
  border-radius: 12px;
  color: var(--yui-text);
  text-decoration: none;
  transition: transform 0.18s ease, background 0.18s ease, color 0.18s ease, box-shadow 0.18s ease, border-color 0.18s ease;
}

.menu-item::before {
  content: none;
}

.menu-item:hover,
.menu-item.active {
  border-color: var(--yui-border-strong);
  color: var(--yui-text);
  background: var(--yui-surface-muted);
  box-shadow: 0 8px 18px rgba(15, 23, 42, 0.06);
  transform: translateX(2px);
}

.menu-item:hover::before,
.menu-item.active::before {
  opacity: 1;
}

.menu-item.active {
  background: var(--yui-accent-soft);
}

.menu-section-label {
  position: relative;
  z-index: 1;
  margin: 0 8px 8px;
  color: var(--yui-muted);
  font-size: 11px;
  font-weight: 800;
  letter-spacing: 0;
}

.admin-toggle {
  position: relative;
  z-index: 1;
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  min-height: 34px;
  padding: 0 9px;
  border: 0;
  color: var(--yui-muted);
  background: transparent;
  font: inherit;
  cursor: pointer;
}

.admin-toggle-label {
  font-size: 11px;
  font-weight: 800;
}

.admin-toggle-icon {
  transition: transform 0.18s ease;
}

.admin-toggle-icon.expanded {
  transform: rotate(180deg);
}

.menu-item.active::after {
  content: '';
  position: absolute;
  right: 10px;
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #ff7abd;
  box-shadow: 0 0 18px rgba(255, 122, 189, 0.9);
}

.menu-icon,
.menu-label {
  position: relative;
  z-index: 1;
}

.menu-icon {
  flex-shrink: 0;
  font-size: 18px;
}

.menu-label {
  overflow: hidden;
  font-size: 14px;
  font-weight: 700;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.menu-divider {
  height: 1px;
  margin: 12px 8px;
  background: var(--yui-border);
}

.admin-menu {
  flex: 1 1 auto;
  gap: 10px;
  padding-right: 2px;
}

.sidebar-footer {
  position: relative;
  z-index: 1;
  margin-top: auto;
  padding-top: 10px;
  border-top: 1px solid var(--yui-border);
}

.settings-action {
  width: 100%;
  font: inherit;
  text-align: left;
  cursor: pointer;
}

.menu-item.admin {
  min-height: 42px;
  color: var(--yui-text);
}

.admin-group {
  display: flex;
  flex-direction: column;
  gap: 5px;
}

.admin-group-label {
  color: var(--yui-muted);
  font-size: 10.5px;
  font-weight: 800;
  line-height: 1;
  padding: 0 10px 2px;
}

.related-routes {
  display: grid;
  gap: 5px;
}

.related-routes summary {
  padding: 5px 10px;
  color: var(--yui-muted);
  font-size: 11px;
  font-weight: 700;
  cursor: pointer;
}

.related-routes summary:focus-visible {
  outline: 3px solid var(--yui-accent);
  outline-offset: 1px;
}

.menu-item.related {
  margin-top: 4px;
}

@media (max-width: 980px) {
  .sidebar {
    width: 76px;
    min-width: 76px;
    margin: 10px 0 10px 10px;
    padding: 12px 8px;
  }

  .brand-wordmark,
  .brand-name,
    .menu-section-label,
    .menu-label,
    .admin-toggle-label,
  .admin-group-label,
  .menu-divider,
  .menu-item.active::after {
    display: none;
  }

  .brand {
    display: none;
  }

  .admin-toggle {
    justify-content: center;
    padding: 0;
  }

  .menu {
    gap: 8px;
  }

  .admin-menu {
    gap: 8px;
  }

  .admin-group {
    gap: 8px;
  }

  .sidebar-footer {
    padding-top: 8px;
  }

  .menu-item {
    justify-content: center;
    min-height: 42px;
    padding: 0;
  }

  .menu-item:hover,
  .menu-item.active {
    transform: none;
  }

  .menu-icon {
    font-size: 19px;
  }
}

@media (max-width: 760px) {
  .sidebar {
    width: 64px;
    min-width: 64px;
    margin: 8px 0 8px 8px;
    padding: 10px 7px;
  }
}
</style>
