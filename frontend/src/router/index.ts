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
    {
      path: '/review/upload',
      name: 'review-upload',
      component: () => import('@/views/review/ReviewUploadView.vue'),
      meta: { title: '文档上传', reviewStep: 1 },
    },
    {
      path: '/review/templates',
      name: 'review-templates',
      component: () => import('@/views/review/ReviewTemplatesView.vue'),
      meta: { title: '范本选择', reviewStep: 2 },
    },
    {
      path: '/review/rules',
      name: 'review-rules',
      component: () => import('@/views/review/ReviewRulesView.vue'),
      meta: { title: '条款设置', reviewStep: 3 },
    },
    {
      path: '/review/console',
      name: 'review-console',
      component: () => import('@/views/review/ReviewConsoleView.vue'),
      meta: { title: '智能审查', reviewStep: 4 },
    },
  ],
})

export default router
