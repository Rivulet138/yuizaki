import { createRouter, createWebHashHistory, type RouteRecordRaw } from 'vue-router'
import { enabledNavigationModules } from './navigation/modules'

const routes: RouteRecordRaw[] = enabledNavigationModules().map((module) => {
  const path = `/w/:workspaceId/${module.id}/:sessionId?`
  const meta = { title: module.title, desc: module.desc }

  return {
    path,
    name: module.id,
    component: module.loader ?? module.component,
    meta,
  }
})

routes.unshift({
  path: '/',
  redirect: '/w/default/chat'
})

routes.unshift({
  path: '/w/:workspaceId',
  redirect: (to) => `/w/${encodeURIComponent(String(to.params.workspaceId || 'default'))}/chat`
})

// 桌宠总览已移除，保留旧链接到对话中心，避免书签或历史状态进入通用默认页。
routes.push({
  path: '/w/:workspaceId/companion/:sessionId?',
  redirect: (to) => {
    const workspaceId = encodeURIComponent(String(to.params.workspaceId || 'default'))
    const sessionId = to.params.sessionId
    return sessionId
      ? `/w/${workspaceId}/chat/${encodeURIComponent(String(sessionId))}`
      : `/w/${workspaceId}/chat`
  },
})

// Fallback 路由
routes.push({
  path: '/:pathMatch(.*)*',
  redirect: '/w/default/chat'
})

export const router = createRouter({
  history: createWebHashHistory(),
  routes
})
