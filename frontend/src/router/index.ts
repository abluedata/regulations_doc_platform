import { createRouter, createWebHistory } from 'vue-router'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      name: 'chat',
      component: () => import('@/views/ChatView.vue'),
      meta: { title: '智能问答' },
    },
    {
      path: '/history',
      name: 'history',
      component: () => import('@/views/HistoryView.vue'),
      meta: { title: '历史记录' },
    },
    {
      path: '/favorites',
      name: 'favorites',
      component: () => import('@/views/FavoritesView.vue'),
      meta: { title: '收藏' },
    },
    {
      path: '/detail/:id?',
      name: 'detail',
      component: () => import('@/views/DetailView.vue'),
      meta: { title: '详情管理' },
    },
    {
      path: '/docs',
      name: 'docs',
      component: () => import('@/views/DocsListView.vue'),
      meta: { title: '知识库' },
    },
    {
      path: '/docs/:id',
      name: 'doc-preview',
      component: () => import('@/views/DocPreviewView.vue'),
      meta: { title: '文档预览' },
    },
  ],
})

export default router
