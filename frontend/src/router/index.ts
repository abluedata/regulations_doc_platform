import { createRouter, createWebHistory } from 'vue-router'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      name: 'chat',
      component: () => import('@/views/knowledge/ChatView.vue'),
      meta: { title: '智能问答' },
    },
    {
      path: '/history',
      name: 'history',
      component: () => import('@/views/knowledge/HistoryView.vue'),
      meta: { title: '历史记录' },
    },
    {
      path: '/favorites',
      name: 'favorites',
      component: () => import('@/views/knowledge/FavoritesView.vue'),
      meta: { title: '收藏' },
    },
    {
      path: '/detail/:id?',
      name: 'detail',
      component: () => import('@/views/knowledge/DetailView.vue'),
      meta: { title: '详情管理' },
    },
    {
      path: '/docs',
      name: 'docs',
      component: () => import('@/views/knowledge/DocsListView.vue'),
      meta: { title: '知识库' },
    },
    {
      path: '/docs/:id',
      name: 'doc-preview',
      component: () => import('@/views/knowledge/DocPreviewView.vue'),
      meta: { title: '文档预览' },
    },
    {
      path: '/review/upload',
      name: 'review-upload',
      component: () => import('@/views/review/ReviewUploadView.vue'),
      meta: { title: '文档上传', reviewStep: 1 },
    },
    {
      path: '/review/upload',
      name: 'review-upload',
      component: () => import('@/views/review/ReviewUploadView.vue'),
      meta: { title: '文档上传', reviewStep: 1 },
    },
    {
      // 范本选择与条款设置已集成进智能审查页：旧路由重定向，保证入口兼容
      path: '/review/templates',
      redirect: { name: 'review-console' },
    },
    {
      path: '/review/rules',
      redirect: { name: 'review-console' },
    },
    {
      path: '/review/console',
      name: 'review-console',
      component: () => import('@/views/review/ReviewConsoleView.vue'),
      meta: { title: '智能审查', reviewStep: 4 },
    },
    {
      // 单 PDF 审查：从文件队列点击已就绪文件进入，针对单个文档
      path: '/review/document/:documentId',
      name: 'review-document',
      component: () => import('@/views/review/ReviewConsoleView.vue'),
      meta: { title: '智能审查', reviewStep: 4 },
    },
  ],
})

export default router
