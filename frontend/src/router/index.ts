import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '../stores/auth'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/login', component: () => import('../views/Login.vue') },
    {
      path: '/',
      component: () => import('../layouts/AppLayout.vue'),
      children: [
        { path: '', redirect: '/dashboard' },
        { path: 'dashboard', component: () => import('../views/Dashboard.vue') },
        { path: 'connections', component: () => import('../views/Connections.vue') },
        // 四页合一:旧路由 redirect 到 /backups 对应 Tab(兼容书签)
        { path: 'schedules', redirect: { path: '/backups', query: { tab: 'schedules' } } },
        { path: 'backups', component: () => import('../views/Backups.vue') },
        { path: 'restore', redirect: { path: '/backups', query: { tab: 'restore' } } },
        { path: 'cloud', component: () => import('../views/CloudSync.vue') },
        { path: 'history', redirect: { path: '/backups', query: { tab: 'files' } } },
        { path: 'settings', component: () => import('../views/Settings.vue') },
        { path: 'logs', component: () => import('../views/Logs.vue') },
      ],
    },
    { path: '/:pathMatch(.*)*', component: () => import('../views/NotFound.vue') },
  ],
})

router.beforeEach(async (to) => {
  const auth = useAuthStore()
  if (!auth.ready) await auth.fetchMe()
  if (!auth.user && to.path !== '/login') return '/login'
  if (auth.user && to.path === '/login') return '/'
})

export default router
