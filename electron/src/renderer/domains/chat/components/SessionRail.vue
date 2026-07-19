<template>
  <aside class="session-rail">
    <div class="session-rail-header">
      <div class="session-title-stack">
        <span class="session-title">会话</span>
        <small>{{ railSummary }}</small>
      </div>
      <button class="new-session-btn" :class="{ loading: creating }" type="button" :disabled="creating" :aria-busy="creating" aria-label="新建会话" title="新建会话" @click="$emit('create-session')">
        <el-icon><Loading v-if="creating" /><Plus v-else /></el-icon>
        <span>新建</span>
      </button>
    </div>

    <div class="session-search">
      <el-icon class="session-search-icon"><Search /></el-icon>
      <input
        v-model="searchQuery"
        class="search-input"
        type="search"
        aria-label="搜索会话"
        placeholder="搜索会话"
      />
    </div>

    <div v-if="filteredSessions.length" class="session-list">
      <section v-for="section in sessionSections" :key="section.key" class="session-section">
        <div class="section-title">
          <span>{{ section.title }}</span>
          <small>{{ section.sessions.length }}</small>
        </div>
        <article
          v-for="session in section.sessions"
          :key="session.id"
          role="button"
          tabindex="0"
          class="session-item"
          :class="{ active: session.id === activeSessionId }"
          :aria-current="session.id === activeSessionId ? 'true' : undefined"
          :aria-label="sessionAriaLabel(session)"
          :title="sessionTooltip(session)"
          @click="$emit('select-session', session.id)"
          @keydown.enter.prevent="$emit('select-session', session.id)"
          @keydown.space.prevent="$emit('select-session', session.id)"
        >
          <div class="title-row">
            <span class="title">{{ session.title || '未命名会话' }}</span>
            <span v-if="session.pinned" class="pin-dot">置顶</span>
          </div>
          <div class="meta-row">
            <span v-if="workspaceLabel(session.workspace_id)" class="workspace-chip">{{ workspaceLabel(session.workspace_id) }}</span>
            <span>{{ formatSessionTime(session.updated_at || session.created_at) }}</span>
            <span>{{ formatMessageCount(session.message_count) }}</span>
          </div>
          <p v-if="session.summary" class="session-preview">{{ session.summary }}</p>
          <div class="quick-actions" aria-label="会话操作">
            <button type="button" class="quick-btn" :aria-label="session.pinned ? '取消置顶会话' : '置顶会话'" :title="session.pinned ? '取消置顶' : '置顶'" @click.stop="$emit('toggle-pin', session.id, !session.pinned)">
              <el-icon><StarFilled v-if="session.pinned" /><Star v-else /></el-icon>
            </button>
            <el-dropdown trigger="click" @command="(command: string) => handleMoreCommand(command, session)">
              <button type="button" class="quick-btn" aria-label="更多会话操作" title="更多" @click.stop>
                <el-icon><MoreFilled /></el-icon>
              </button>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item command="export-json">导出 JSON</el-dropdown-item>
                  <el-dropdown-item command="export-csv">导出 CSV</el-dropdown-item>
                  <el-dropdown-item divided command="delete">
                    <span class="session-danger-action">删除</span>
                  </el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </div>
        </article>
      </section>
    </div>

    <div v-else class="session-empty">
      <strong>{{ searchQuery ? '没有匹配会话' : '还没有会话' }}</strong>
      <el-button size="small" type="primary" plain :loading="creating" @click="$emit('create-session')">新建</el-button>
    </div>
  </aside>
</template>

<script setup lang="ts">
import { ElMessage } from 'element-plus'
import { Loading, MoreFilled, Plus, Search, Star, StarFilled } from '@element-plus/icons-vue'
import { computed, ref } from 'vue'
import { systemClient } from '@/api/client'

interface SessionRailRecord {
  id: string
  workspace_id: string
  title: string
  summary?: string | null
  pinned: boolean
  created_at?: string | null
  updated_at?: string | null
  message_count: number
}

const props = defineProps<{
  sessions: SessionRailRecord[]
  activeSessionId: string
  activeWorkspaceId: string
  workspaceNames?: Record<string, string>
  creating?: boolean
}>()

const emit = defineEmits<{
  (e: 'create-session'): void
  (e: 'select-session', sessionId: string): void
  (e: 'toggle-pin', sessionId: string, pinned: boolean): void
  (e: 'delete-session', sessionId: string): void
}>()

const searchQuery = ref('')

const normalizeWorkspaceId = (workspaceId?: string | null) => (workspaceId || 'default').trim() || 'default'
const isDefaultWorkspace = (workspaceId?: string | null) => normalizeWorkspaceId(workspaceId) === 'default'
const normalizedActiveWorkspaceId = computed(() => normalizeWorkspaceId(props.activeWorkspaceId))
const workspaceName = (workspaceId?: string | null) => {
  const id = normalizeWorkspaceId(workspaceId)
  if (id === 'default') return '普通对话'
  return props.workspaceNames?.[id] || id
}
const workspaceLabel = (workspaceId?: string | null) => {
  const id = normalizeWorkspaceId(workspaceId)
  if (id === normalizedActiveWorkspaceId.value) return ''
  return workspaceName(id)
}

const filteredSessions = computed(() => {
  const q = searchQuery.value.toLowerCase().trim()
  if (!q) return props.sessions
  return props.sessions.filter((session) =>
    session.title?.toLowerCase().includes(q) ||
    session.summary?.toLowerCase().includes(q) ||
    workspaceName(session.workspace_id).toLowerCase().includes(q)
  )
})
const activeWorkspaceSessionCount = computed(() => props.sessions.filter((session) =>
  normalizeWorkspaceId(session.workspace_id) === normalizedActiveWorkspaceId.value,
).length)
const visibleSessionCount = computed(() => props.sessions.length)
const railSummary = computed(() => {
  if (!props.sessions.length) return '准备开始'
  return `本项目 ${activeWorkspaceSessionCount.value} / 全部 ${visibleSessionCount.value}`
})

const sessionTimestamp = (session: SessionRailRecord) => {
  const value = session.updated_at || session.created_at
  if (!value) return 0
  const time = new Date(value).getTime()
  return Number.isNaN(time) ? 0 : time
}

const sortSessions = (sessions: SessionRailRecord[]) => [...sessions].sort((left, right) => {
  if (left.pinned !== right.pinned) return left.pinned ? -1 : 1
  return sessionTimestamp(right) - sessionTimestamp(left)
})

const createSection = (key: string, title: string, sessions: SessionRailRecord[]) => ({
  key,
  title,
  sessions: sortSessions(sessions),
})

const sessionSections = computed(() => {
  const currentWorkspace = filteredSessions.value.filter((session) =>
    normalizeWorkspaceId(session.workspace_id) === normalizedActiveWorkspaceId.value,
  )
  const general = filteredSessions.value.filter((session) =>
    isDefaultWorkspace(session.workspace_id) &&
    normalizedActiveWorkspaceId.value !== 'default',
  )
  const otherProjectGroups = new Map<string, SessionRailRecord[]>()
  filteredSessions.value.forEach((session) => {
    const workspaceId = normalizeWorkspaceId(session.workspace_id)
    if (isDefaultWorkspace(workspaceId) || workspaceId === normalizedActiveWorkspaceId.value) return
    const group = otherProjectGroups.get(workspaceId) || []
    group.push(session)
    otherProjectGroups.set(workspaceId, group)
  })
  const otherProjectSections = Array.from(otherProjectGroups.entries())
    .sort(([leftId, leftSessions], [rightId, rightSessions]) => {
      const latestDelta = Math.max(...rightSessions.map(sessionTimestamp)) - Math.max(...leftSessions.map(sessionTimestamp))
      if (latestDelta !== 0) return latestDelta
      return workspaceName(leftId).localeCompare(workspaceName(rightId), 'zh-CN')
    })
    .map(([workspaceId, sessions]) => createSection(`project:${workspaceId}`, `${workspaceName(workspaceId)} 项目`, sessions))
  return [
    createSection('current', normalizedActiveWorkspaceId.value === 'default' ? '普通对话' : `${workspaceName(normalizedActiveWorkspaceId.value)} 项目`, currentWorkspace),
    createSection('general', '普通对话', general),
    ...otherProjectSections,
  ].filter((section) => section.sessions.length > 0)
})

const formatMessageCount = (count: number) => `${Math.max(0, count)} 条消息`

const formatSessionTime = (value?: string | null) => {
  if (!value) return '未同步'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '未同步'
  const now = new Date()
  const sameDay = date.toDateString() === now.toDateString()
  return sameDay
    ? date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
    : date.toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' })
}

const sessionTooltip = (session: SessionRailRecord) => {
  const title = session.title || '未命名会话'
  return `${title}\n${workspaceName(session.workspace_id)}\n${session.message_count} 条消息`
}

const sessionAriaLabel = (session: SessionRailRecord) => {
  const title = session.title || '未命名会话'
  const state = [
    workspaceLabel(session.workspace_id) || null,
    session.pinned ? '已置顶' : null,
    session.id === props.activeSessionId ? '当前会话' : null,
  ].filter(Boolean).join('，')
  return `${title}，${session.message_count} 条消息${state ? `，${state}` : ''}`
}

const handleMoreCommand = (command: string, session: SessionRailRecord) => {
  if (command === 'export-json') {
    void exportSession(session.id, session.workspace_id, 'json')
    return
  }
  if (command === 'export-csv') {
    void exportSession(session.id, session.workspace_id, 'csv')
    return
  }
  if (command === 'delete') {
    emit('delete-session', session.id)
  }
}

const exportSession = async (sessionId: string, workspaceId: string, format: 'json' | 'csv') => {
  try {
    const blob = await systemClient.exportData(format, sessionId, workspaceId)
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `chat-${sessionId}.${format}`
    document.body.appendChild(link)
    link.click()
    link.remove()
    URL.revokeObjectURL(url)
  } catch (error) {
    console.warn('[SessionRail] failed to export session:', error)
    ElMessage.error('导出会话失败')
  }
}
</script>

<style scoped>
.session-rail {
  display: flex;
  flex-direction: column;
  width: 276px;
  box-sizing: border-box;
  border-right: 1px solid rgba(203, 213, 225, 0.82);
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.92), rgba(241, 245, 249, 0.96)),
    #f1f5f9;
  padding: 14px 11px;
}

.session-rail-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 10px;
  padding: 2px 2px 0;
  color: #111827;
}

.session-title-stack {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.session-title {
  font-size: 16px;
  font-weight: 800;
  line-height: 1.2;
}

.session-title-stack small {
  overflow: hidden;
  color: #64748b;
  font-size: 11px;
  font-weight: 600;
  line-height: 1.2;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.new-session-btn {
  display: inline-flex;
  min-width: 72px;
  height: 34px;
  align-items: center;
  justify-content: center;
  gap: 5px;
  border: 1px solid rgba(15, 23, 42, 0.12);
  border-radius: 9px;
  background: #0f172a;
  color: #fff;
  cursor: pointer;
  flex: 0 0 auto;
  font-size: 12px;
  font-weight: 760;
  box-shadow: 0 8px 18px rgba(15, 23, 42, 0.14);
  transition: background 0.15s ease, box-shadow 0.15s ease, transform 0.15s ease, opacity 0.15s ease;
}

.new-session-btn:hover {
  background: #111827;
  box-shadow: 0 10px 22px rgba(15, 23, 42, 0.18);
}

.new-session-btn:active {
  transform: translateY(1px);
}

.new-session-btn:focus-visible {
  outline: 2px solid rgba(37, 99, 235, 0.62);
  outline-offset: 2px;
}

.new-session-btn:disabled {
  cursor: wait;
  opacity: 0.72;
}

.new-session-btn.loading .el-icon {
  animation: spin 0.9s linear infinite;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

.session-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
  overflow: auto;
  padding: 2px 2px 8px 0;
  min-height: 0;
}

.session-list::-webkit-scrollbar {
  width: 4px;
}

.session-list::-webkit-scrollbar-thumb {
  background: rgba(148, 163, 184, 0.32);
  border-radius: 999px;
}

.session-search {
  position: relative;
  margin-bottom: 11px;
}

.session-search-icon {
  position: absolute;
  left: 11px;
  top: 50%;
  transform: translateY(-50%);
  color: #94a3b8;
  font-size: 14px;
  pointer-events: none;
}

.search-input {
  width: 100%;
  height: 36px;
  box-sizing: border-box;
  border: 1px solid rgba(203, 213, 225, 0.88);
  border-radius: 9px;
  background: rgba(255, 255, 255, 0.84);
  color: #334155;
  font-size: 13px;
  outline: none;
  padding: 8px 10px 8px 32px;
  transition: border-color 0.15s ease, box-shadow 0.15s ease, background 0.15s ease;
}

.search-input:focus {
  border-color: rgba(37, 99, 235, 0.46);
  background: #fff;
  box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.1);
}

.session-section {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.section-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 0 5px 1px;
  color: #64748b;
  font-size: 11px;
  font-weight: 800;
  letter-spacing: 0;
}

.section-title small {
  display: inline-flex;
  min-width: 19px;
  height: 19px;
  align-items: center;
  justify-content: center;
  border: 1px solid rgba(203, 213, 225, 0.72);
  border-radius: 7px;
  background: rgba(255, 255, 255, 0.72);
  color: #64748b;
  font-size: 10px;
}

.session-item {
  position: relative;
  overflow: hidden;
  border: 1px solid rgba(226, 232, 240, 0.84);
  border-radius: 9px;
  background: rgba(255, 255, 255, 0.76);
  cursor: pointer;
  padding: 9px 10px;
  text-align: left;
  transition: border-color 0.16s ease, box-shadow 0.16s ease, background 0.16s ease, transform 0.16s ease;
}

.session-item:hover {
  border-color: rgba(148, 163, 184, 0.56);
  background: #fff;
  box-shadow: 0 7px 16px rgba(15, 23, 42, 0.06);
  transform: translateY(-1px);
}

.session-item:focus-visible {
  border-color: rgba(37, 99, 235, 0.42);
  box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.1);
  outline: none;
}

.session-item.active {
  border-color: rgba(16, 185, 129, 0.34);
  background: #f0fdfa;
  box-shadow: inset 0 0 0 1px rgba(16, 185, 129, 0.12);
}

.title-row {
  display: flex;
  align-items: center;
  gap: 8px;
  justify-content: space-between;
  min-width: 0;
  padding-right: 82px;
}

.title {
  display: block;
  flex: 1 1 auto;
  min-width: 0;
  color: #111827;
  font-size: 13px;
  font-weight: 750;
  line-height: 1.35;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.pin-dot {
  flex-shrink: 0;
  padding: 2px 6px;
  border-radius: 7px;
  color: #047857;
  background: rgba(16, 185, 129, 0.1);
  font-size: 10px;
  font-weight: 800;
}

.meta-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 6px;
  color: #64748b;
  font-size: 11px;
  line-height: 1.3;
}

.meta-row span:not(.workspace-chip) + span::before {
  content: '·';
  margin-right: 6px;
  color: #cbd5e1;
}

.workspace-chip {
  display: inline-flex;
  max-width: 100%;
  align-items: center;
  border: 1px solid rgba(37, 99, 235, 0.16);
  border-radius: 7px;
  background: rgba(14, 165, 233, 0.1);
  color: #0369a1;
  font-size: 10.5px;
  font-weight: 800;
  line-height: 1;
  padding: 3px 7px;
}

.session-preview {
  display: -webkit-box;
  overflow: hidden;
  margin: 7px 0 0;
  color: #475569;
  font-size: 11.5px;
  line-height: 1.45;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}

.quick-actions {
  position: absolute;
  top: 7px;
  right: 7px;
  display: flex;
  gap: 2px;
  padding: 2px;
  border: 1px solid rgba(226, 232, 240, 0.88);
  border-radius: 9px;
  background: rgba(255, 255, 255, 0.96);
  box-shadow: 0 7px 16px rgba(15, 23, 42, 0.08);
  opacity: 0;
  pointer-events: none;
  transition: opacity 0.14s ease;
}

.session-item:hover .quick-actions,
.session-item:focus-within .quick-actions,
.session-item.active .quick-actions {
  opacity: 1;
  pointer-events: auto;
}

.quick-btn {
  display: inline-flex;
  width: 24px;
  height: 24px;
  align-items: center;
  justify-content: center;
  border: 0;
  border-radius: 8px;
  background: transparent;
  color: #64748b;
  font-size: 12px;
  font-weight: 800;
  cursor: pointer;
}

.quick-btn .el-icon {
  font-size: 13px;
}

.quick-btn:hover {
  background: #f1f5f9;
  color: #111827;
}

.quick-btn:focus-visible {
  outline: 2px solid rgba(37, 99, 235, 0.72);
  outline-offset: 2px;
}

.quick-btn.danger:hover {
  color: #dc2626;
  background: rgba(254, 226, 226, 0.92);
}

.session-danger-action {
  color: #b91c1c;
}

.session-empty {
  margin-top: 10px;
  border: 1px dashed #cbd5e1;
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.72);
  color: #64748b;
  padding: 22px 14px;
  text-align: center;
}

.session-empty strong {
  display: block;
  margin-bottom: 13px;
  color: #334155;
  font-size: 14px;
}

:global([data-theme='dark']) .session-rail {
  border-right-color: rgba(51, 65, 85, 0.82);
  background:
    linear-gradient(180deg, rgba(15, 23, 42, 0.96), rgba(15, 23, 42, 0.9)),
    #0f172a;
}

:global([data-theme='dark']) .session-rail-header,
:global([data-theme='dark']) .title {
  color: #e5e7eb;
}

:global([data-theme='dark']) .session-title-stack small,
:global([data-theme='dark']) .section-title,
:global([data-theme='dark']) .meta-row,
:global([data-theme='dark']) .session-preview {
  color: #94a3b8;
}

:global([data-theme='dark']) .workspace-chip {
  border-color: rgba(96, 165, 250, 0.24);
  background: rgba(96, 165, 250, 0.12);
  color: #bfdbfe;
}

:global([data-theme='dark']) .search-input,
:global([data-theme='dark']) .quick-actions {
  border-color: rgba(51, 65, 85, 0.9);
  background: #111827;
  color: #cbd5e1;
}

:global([data-theme='dark']) .section-title small,
:global([data-theme='dark']) .session-empty,
:global([data-theme='dark']) .session-item {
  border-color: rgba(51, 65, 85, 0.78);
  background: rgba(17, 24, 39, 0.72);
  color: #cbd5e1;
}

:global([data-theme='dark']) .session-item:hover {
  border-color: rgba(71, 85, 105, 0.82);
  background: rgba(30, 41, 59, 0.92);
  box-shadow: none;
}

:global([data-theme='dark']) .session-item.active {
  border-color: rgba(96, 165, 250, 0.36);
  background: rgba(30, 41, 59, 0.98);
  box-shadow: inset 0 0 0 1px rgba(96, 165, 250, 0.12);
}

:global([data-theme='dark']) .quick-btn:hover {
  background: #1e293b;
  color: #f8fafc;
}
</style>
