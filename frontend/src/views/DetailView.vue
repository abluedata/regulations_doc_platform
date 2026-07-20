<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { marked } from 'marked'
import {
  Collection,
  Connection,
  Cpu,
  Delete,
  Search,
  Star,
  UserFilled,
} from '@element-plus/icons-vue'
import { getHistoryDetail, deleteHistory } from '@/api/history'
import { addFavorite } from '@/api/favorites'
import type { SessionRecord } from '@/types'

const route = useRoute()
const router = useRouter()
const sessionId = ref('')
const detail = ref<SessionRecord | null>(null)
const loading = ref(false)

marked.setOptions({ breaks: true, gfm: true })

async function load(id?: string) {
  const sid = (id ?? sessionId.value).trim()
  if (!sid) {
    ElMessage.warning('请输入 ID')
    return
  }
  sessionId.value = sid
  loading.value = true
  try {
    const { data } = await getHistoryDetail(sid)
    detail.value = data
  } catch (e: any) {
    detail.value = null
    ElMessage.error(e.message || '未找到')
  } finally {
    loading.value = false
  }
}

async function onFavorite() {
  if (!sessionId.value.trim()) return
  try {
    await addFavorite(sessionId.value.trim())
    ElMessage.success('已收藏')
  } catch (e: any) {
    ElMessage.error(e.message || '收藏失败')
  }
}

async function onDelete() {
  if (!sessionId.value.trim()) return
  try {
    await deleteHistory(sessionId.value.trim())
    ElMessage.success('已删除')
    detail.value = null
  } catch (e: any) {
    ElMessage.error(e.message || '删除失败')
  }
}

function renderMd(s: string) {
  return marked.parse(s || '') as string
}

onMounted(() => {
  const id = route.params.id
  if (typeof id === 'string' && id) {
    sessionId.value = id
    load(id)
  }
})

watch(
  () => route.params.id,
  (id) => {
    if (typeof id === 'string' && id) {
      sessionId.value = id
      load(id)
    }
  },
)
</script>

<template>
  <main class="enterprise-page detail-page" v-loading="loading">
    <header class="page-header" data-test="page-header">
      <div class="page-header__copy">
        <h1>对话详情</h1>
        <p>按完整会话 ID 查看回答内容与检索来源</p>
      </div>
      <div class="page-header__actions">
        <el-tag :type="detail ? 'success' : 'info'" effect="plain">
          {{ detail ? '详情已加载' : '等待查询' }}
        </el-tag>
      </div>
    </header>

    <section class="surface-panel detail-query" aria-label="详情查询">
      <div class="task-toolbar detail-toolbar" data-test="detail-toolbar">
        <div class="task-toolbar__group detail-search">
          <el-input
            v-model="sessionId"
            aria-label="完整会话 ID"
            placeholder="输入完整 ID 后点击查看"
            clearable
            @keyup.enter="load()"
          />
          <el-button type="primary" :icon="Search" @click="load()">查看</el-button>
        </div>
        <div class="task-toolbar__group">
          <el-button :icon="Star" @click="onFavorite">收藏</el-button>
          <el-button type="danger" :icon="Delete" @click="onDelete">删除</el-button>
        </div>
      </div>
    </section>

    <section class="surface-panel detail-surface" aria-label="对话内容">
      <template v-if="detail">
        <div class="surface-panel__header detail-meta">
          <div>
            <h2>会话内容</h2>
            <p>{{ detail.timestamp }}</p>
          </div>
          <el-tag :type="detail.has_web ? 'primary' : 'info'" effect="plain">
            <el-icon aria-hidden="true"><Connection v-if="detail.has_web" /><Collection v-else /></el-icon>
            <span>{{ detail.has_web ? '网络补充' : '本地知识库' }}</span>
          </el-tag>
        </div>

        <div class="detail-block markdown-content">
          <template v-if="detail.messages?.length">
            <article
              v-for="(m, i) in detail.messages"
              :key="i"
              class="detail-msg"
              :class="m.role"
            >
              <div class="detail-msg__role" aria-hidden="true">
                <el-icon><UserFilled v-if="m.role === 'user'" /><Cpu v-else /></el-icon>
              </div>
              <div v-if="m.role === 'user'" class="detail-msg__content">
                <strong>{{ m.content }}</strong>
              </div>
              <div v-else class="detail-msg__content" v-html="renderMd(m.content)" />
            </article>
          </template>
          <template v-else>
            <article class="detail-msg user">
              <div class="detail-msg__role" aria-hidden="true"><el-icon><UserFilled /></el-icon></div>
              <div class="detail-msg__content"><strong>{{ detail.question }}</strong></div>
            </article>
            <article class="detail-msg assistant">
              <div class="detail-msg__role" aria-hidden="true"><el-icon><Cpu /></el-icon></div>
              <div class="detail-msg__content" v-html="renderMd(detail.answer)" />
            </article>
          </template>
        </div>
      </template>
      <el-empty v-else description="输入 ID 查看对话详情" />
    </section>
  </main>
</template>
