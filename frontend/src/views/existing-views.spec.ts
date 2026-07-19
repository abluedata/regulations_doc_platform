import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter, type Router } from 'vue-router'
import ChatInput from '@/components/ChatInput.vue'
import SessionTable from '@/components/SessionTable.vue'
import { useChatStore } from '@/stores/chat'
import type { SessionRecord } from '@/types'
import ChatView from './ChatView.vue'
import DetailView from './DetailView.vue'
import DocPreviewView from './DocPreviewView.vue'
import DocsListView from './DocsListView.vue'
import FavoritesView from './FavoritesView.vue'
import HistoryView from './HistoryView.vue'

vi.mock('@/api/chat', () => ({
  fetchExamples: vi.fn().mockResolvedValue({ data: { examples: [] } }),
  saveSession: vi.fn().mockResolvedValue({ data: { success: true } }),
  stopChat: vi.fn().mockResolvedValue({ data: { success: true } }),
  streamChat: vi.fn().mockResolvedValue(undefined),
}))

vi.mock('@/api/docs', () => ({
  listDocs: vi.fn().mockResolvedValue({ data: { items: [], total: 0 } }),
  getDocPreview: vi.fn().mockResolvedValue({
    data: {
      id: 'doc-1',
      status: 'ready',
      stage_label: '已入库',
      ready: true,
      message: null,
      markdown: '',
      outline: [],
      tables: [],
      meta: {
        id: 'doc-1',
        filename: 'example.pdf',
        ext: 'pdf',
        status: 'ready',
        stage_label: '已入库',
        page_count: 1,
        chunk_count: 1,
        file_size: 1024,
        created_at: '2026-07-19 12:00:00',
      },
      ir_summary: { block_count: 1, pages: 1 },
    },
  }),
  deleteDoc: vi.fn().mockResolvedValue({ data: { message: '已删除', success: true } }),
  reparseDoc: vi.fn().mockResolvedValue({ data: { message: '已重析', success: true } }),
  uploadDoc: vi.fn().mockResolvedValue({ data: { message: '已上传' } }),
}))

vi.mock('@/api/history', () => ({
  listHistory: vi.fn().mockResolvedValue({ data: { items: [], total: 0 } }),
  getHistoryDetail: vi.fn().mockResolvedValue({
    data: {
      id: 'session-1',
      timestamp: '2026-07-19 12:00:00',
      question: '示例问题',
      answer: '示例回答',
      route: 'local',
      has_web: false,
      messages: [],
    },
  }),
  deleteHistory: vi.fn().mockResolvedValue({ data: { success: true } }),
  clearHistory: vi.fn().mockResolvedValue({ data: { message: '已清空' } }),
  batchDeleteHistory: vi.fn().mockResolvedValue({ data: { ok: 1, message: '已删除' } }),
  batchFavoriteHistory: vi.fn().mockResolvedValue({ data: { ok: 1, message: '已收藏' } }),
}))

vi.mock('@/api/favorites', () => ({
  listFavorites: vi.fn().mockResolvedValue({ data: { items: [], total: 0 } }),
  addFavorite: vi.fn().mockResolvedValue({ data: { success: true } }),
  batchDeleteFavorites: vi.fn().mockResolvedValue({ data: { ok: 1, message: '已删除' } }),
}))

function createTestRouter() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', name: 'chat', component: ChatView },
      { path: '/docs', name: 'docs', component: DocsListView },
      { path: '/docs/:id', name: 'doc-preview', component: DocPreviewView },
      { path: '/history', name: 'history', component: HistoryView },
      { path: '/favorites', name: 'favorites', component: FavoritesView },
      { path: '/detail/:id?', name: 'detail', component: DetailView },
    ],
  })
}

async function mountView(
  component: Parameters<typeof mount>[0],
  path: string,
): Promise<{ wrapper: VueWrapper; router: Router }> {
  const pinia = createPinia()
  setActivePinia(pinia)
  const router = createTestRouter()
  await router.push(path)
  await router.isReady()
  const wrapper = mount(component, {
    global: {
      plugins: [pinia, router, ElementPlus],
      stubs: {
        ElTable: { template: '<div><slot /></div>' },
        ElTableColumn: true,
        ElSelect: true,
        ElOption: true,
      },
    },
  })
  await flushPromises()
  return { wrapper, router }
}

describe('existing API-backed views', () => {
  beforeEach(() => vi.clearAllMocks())

  it('keeps the chat composer and new conversation command in a page header', async () => {
    const { wrapper } = await mountView(ChatView, '/')
    const chat = useChatStore()
    chat.messages = [
      { role: 'user', content: '问题' },
      { role: 'assistant', content: '回答' },
    ]
    await flushPromises()

    expect(wrapper.get('[data-test="page-header"] h1').text()).toBe('智能问答')
    expect(wrapper.findComponent(ChatInput).exists()).toBe(true)
    expect(wrapper.find('.chat-input-row').exists()).toBe(true)

    await wrapper.get('[data-test="new-chat"]').trigger('click')
    await flushPromises()
    expect(chat.messages).toHaveLength(0)
  })

  it('keeps the document uploader and table inside distinct surfaces', async () => {
    const { wrapper } = await mountView(DocsListView, '/docs')

    expect(wrapper.get('[data-test="page-header"] h1').text()).toBe('知识库')
    expect(wrapper.find('.docs-uploader').exists()).toBe(true)
    expect(wrapper.find('.docs-table').exists()).toBe(true)
    expect(wrapper.find('[data-test="docs-toolbar"]').exists()).toBe(true)
  })

  it('keeps history search, favorite selection and delete selection commands', async () => {
    const { wrapper } = await mountView(HistoryView, '/history')

    expect(wrapper.get('[data-test="page-header"] h1').text()).toBe('历史记录')
    expect(wrapper.find('[data-test="history-search"]').exists()).toBe(true)
    expect(wrapper.get('[data-test="favorite-selected"]').text()).toContain('收藏选中')
    expect(wrapper.get('[data-test="delete-selected"]').text()).toContain('删除选中')
  })

  it('keeps the favorites delete selection command', async () => {
    const { wrapper } = await mountView(FavoritesView, '/favorites')

    expect(wrapper.get('[data-test="page-header"] h1').text()).toBe('我的收藏')
    expect(wrapper.get('[data-test="delete-selected"]').text()).toContain('删除选中')
  })

  it('gives preview and detail routes consistent page headers', async () => {
    const preview = await mountView(DocPreviewView, '/docs/doc-1')
    expect(preview.wrapper.get('[data-test="page-header"] h1').text()).toBe('example.pdf')

    const detail = await mountView(DetailView, '/detail')
    expect(detail.wrapper.get('[data-test="page-header"] h1').text()).toBe('对话详情')
    expect(detail.wrapper.find('[data-test="detail-toolbar"]').exists()).toBe(true)
  })
})

describe('SessionTable', () => {
  it('navigates to detail when a session row is clicked', async () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    const router = createTestRouter()
    await router.push('/history')
    await router.isReady()
    const row: SessionRecord = {
      id: 'session-42',
      timestamp: '2026-07-19 12:00:00',
      question: '测试问题',
      answer: '测试回答',
      route: 'local',
      has_web: false,
    }
    const wrapper = mount(SessionTable, {
      props: { rows: [row] },
      global: { plugins: [pinia, router, ElementPlus] },
    })
    await flushPromises()

    await wrapper.get('.el-table__body-wrapper .el-table__row').trigger('click')
    await flushPromises()

    expect(router.currentRoute.value.name).toBe('detail')
    expect(router.currentRoute.value.params.id).toBe('session-42')
  })
})
