import { createRouter, createWebHashHistory } from 'vue-router'
import { enabledNavigationModules } from './navigation/modules'

const routes = enabledNavigationModules().map(module => ({
  path: `/w/:workspaceId/${module.id}/:sessionId?`,
  name: module.id,
  component: module.loader ?? module.component,
  meta: {
    title: module.title,
    desc: module.desc,
  }
}))

routes.unshift({
  path: '/',
  redirect: '/w/default/companion'
})

routes.unshift({
  path: '/w/:workspaceId',
  redirect: (to) => `/w/${encodeURIComponent(String(to.params.workspaceId || 'default'))}/companion`
})

// Fallback 路由
routes.push({
  path: '/:pathMatch(.*)*',
  redirect: '/w/default/companion'
})

export const router = createRouter({
  history: createWebHashHistory(),
  routes
})
