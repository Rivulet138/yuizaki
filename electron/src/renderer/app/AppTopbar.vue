<template>
  <header class="topbar drag">
    <div class="topbar-left">
      <h1 class="topbar-title">{{ title }}</h1>
    </div>

    <div class="top-actions no-drag">
      <el-select
        :model-value="locale"
        size="small"
        class="language-select"
        :title="t('language.title')"
        :aria-label="t('language.title')"
        @change="handleLocaleChange"
      >
        <el-option v-for="option in languageOptions" :key="option.value" :label="option.label" :value="option.value" />
      </el-select>

      <button class="icon-action" type="button" :title="adminMode ? t('topbar.admin.hide') : t('topbar.admin.show')" :aria-label="adminMode ? t('topbar.admin.hide') : t('topbar.admin.show')" @click="$emit('toggle-admin-mode')">
        <el-icon><Operation /></el-icon>
      </button>

      <button class="icon-action" type="button" :title="theme === 'dark' ? t('shell.theme.light') : t('shell.theme.dark')" :aria-label="theme === 'dark' ? t('shell.theme.light') : t('shell.theme.dark')" @click="$emit('toggle-theme')">
        <el-icon>
          <Sunny v-if="theme === 'dark'" />
          <Moon v-else />
        </el-icon>
      </button>

      <el-select
        :model-value="companionId"
        size="small"
        class="top-select"
        :aria-label="t('topbar.companion')"
        @change="$emit('change-companion', $event)"
      >
        <el-option v-for="companion in companions" :key="companion.id" :label="companion.name" :value="companion.id" />
      </el-select>

      <el-badge :value="notificationCount" :hidden="!notificationCount" class="notification-bell">
        <button class="win-btn" type="button" :title="t('topbar.notifications')" :aria-label="t('topbar.notifications')" @click="$emit('toggle-notifications')">
          <el-icon><Bell /></el-icon>
        </button>
      </el-badge>

      <div v-if="isElectronPanel" class="window-actions">
        <button class="win-btn" type="button" :title="t('topbar.minimize')" :aria-label="t('topbar.minimize')" @click="$emit('minimize')"><el-icon><Minus /></el-icon></button>
        <button class="win-btn" type="button" :title="t('topbar.maximize')" :aria-label="t('topbar.maximize')" @click="$emit('maximize')"><el-icon><FullScreen /></el-icon></button>
        <button class="win-btn danger" type="button" :title="t('topbar.close')" :aria-label="t('topbar.close')" @click="$emit('close')"><el-icon><Close /></el-icon></button>
      </div>
    </div>
  </header>
</template>

<script setup lang="ts">
import { Bell, Close, FullScreen, Minus, Moon, Operation, Sunny } from '@element-plus/icons-vue'
import { computed } from 'vue'
import { useI18n } from '@/i18n'

defineProps<{
  title: string
  activeWorkspace: {
    id: string
    name: string
    context: {
      layoutPreset: 'focus' | 'balanced' | 'wide'
    }
  }
  companionId: string
  companions: Array<{ id: string; name: string }>
  isElectronPanel?: boolean
  notificationCount?: number
  adminMode?: boolean
  theme?: 'light' | 'dark'
}>()

const emit = defineEmits<{
  (e: 'toggle-admin-mode'): void
  (e: 'change-locale', value: string): void
  (e: 'change-companion', value: string): void
  (e: 'minimize'): void
  (e: 'maximize'): void
  (e: 'close'): void
  (e: 'toggle-notifications'): void
  (e: 'toggle-theme'): void
}>()

const { locale, localeLabel, supportedLocales, t } = useI18n()
const languageOptions = computed(() => supportedLocales.map((value) => ({ value, label: localeLabel(value) })))
const handleLocaleChange = (value: string | number | boolean) => {
  emit('change-locale', String(value))
}
</script>

<style scoped>
.topbar {
  position: relative;
  z-index: 2;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  min-height: 54px;
  margin-bottom: 14px;
  padding: 0 12px 0 20px;
  overflow: visible;
  border: 1px solid var(--yui-border);
  border-radius: 18px;
  background: var(--yui-surface);
  box-shadow: var(--yui-shadow-card);
  box-sizing: border-box;
}

.topbar::before {
  content: none;
}

.topbar-left,
.top-actions {
  position: relative;
  z-index: 1;
}

.topbar-left {
  display: flex;
  align-items: center;
  flex: 1 1 0;
  min-width: 0;
}

.topbar-title {
  margin: 0;
  overflow: hidden;
  color: var(--yui-text);
  font-family: var(--yui-font-display);
  font-size: 16px;
  font-weight: 500;
  letter-spacing: 0;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.top-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  flex: 0 1 auto;
  flex-wrap: wrap;
  gap: 7px;
  max-width: 100%;
  min-width: 0;
  -webkit-app-region: no-drag;
}

.icon-action,
.win-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 40px;
  height: 40px;
  border: 1px solid var(--yui-border);
  border-radius: 10px;
  color: var(--yui-muted);
  background: var(--yui-surface-raised);
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
  cursor: pointer;
  transition: transform 0.18s ease, color 0.18s ease, background 0.18s ease, box-shadow 0.18s ease;
}

.icon-action:hover,
.win-btn:hover {
  color: var(--yui-accent);
  background: var(--yui-accent-soft);
  box-shadow: var(--yui-shadow-card);
  transform: translateY(-1px);
}

.win-btn.danger:hover {
  color: #e11d48;
  background: rgba(255, 235, 242, 0.56);
}

.top-select {
  width: clamp(118px, 16vw, 154px);
}

.language-select {
  width: clamp(92px, 12vw, 108px);
}

:deep(.top-select .el-select__wrapper),
:deep(.language-select .el-select__wrapper) {
  min-height: 40px;
  border-radius: 10px;
  background: var(--yui-surface-raised);
  box-shadow: 0 0 0 1px var(--yui-border) inset;
}

.notification-bell {
  line-height: 1;
}

.window-actions {
  display: flex;
  align-items: center;
  gap: 4px;
}

@media (max-width: 980px) {
  .topbar {
    align-items: flex-start;
    min-height: 0;
    padding: 10px;
    gap: 10px;
  }

  .topbar-title {
    max-width: 180px;
    font-size: 15px;
    line-height: 34px;
  }

  .top-actions {
    gap: 6px;
  }

  .top-select {
    width: 132px;
  }

  .language-select {
    width: 98px;
  }

  .icon-action,
  .win-btn {
    width: 40px;
    height: 40px;
  }
}

@media (max-width: 720px) {
  .topbar {
    flex-direction: column;
  }

  .topbar-left,
  .top-actions {
    width: 100%;
  }

  .topbar-title {
    max-width: 100%;
    line-height: 1.3;
  }

  .top-actions {
    justify-content: flex-start;
  }

  .icon-action,
  .win-btn {
    width: 44px;
    height: 44px;
  }

  :deep(.top-select .el-select__wrapper),
  :deep(.language-select .el-select__wrapper) {
    min-height: 44px;
  }
}
</style>
