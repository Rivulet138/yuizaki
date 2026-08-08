import { createRouter, createWebHashHistory, type RouteRecordRaw } from 'vue-router'
import { enabledNavigationModules } from './navigation/modules'

const routes: RouteRecordRaw[] = enabledNavigationModules().map((module) => {
  const path = `/w/:workspaceId/${module.id}/:sessionId?`
  const meta = { title: module.title, desc: module.desc }

  if (module.id === 'companion') {
    return {
      path,
      name: module.id,
      redirect: (to) => {
        const workspaceId = encodeURIComponent(String(to.params.workspaceId || 'default'))
        const sessionId = to.params.sessionId
          ? `/${encodeURIComponent(String(to.params.sessionId))}`
          : ''
        return `/w/${workspaceId}/chat${sessionId}`
      },
      meta,
    }
  }

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

// Fallback 路由
routes.push({
  path: '/:pathMatch(.*)*',
  redirect: '/w/default/chat'
})

export const router = createRouter({
  history: createWebHashHistory(),
  routes
})
