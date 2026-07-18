<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { marked } from 'marked'
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
  <div class="page-card" v-loading="loading">
    <div class="toolbar-row">
      <el-input
        v-model="sessionId"
        placeholder="输入完整 ID 后点击查看"
        style="flex: 1; min-width: 240px"
        clearable
        @keyup.enter="load()"
      />
      <el-button type="primary" @click="load()">◎ 查看</el-button>
      <el-button @click="onFavorite">☆ 收藏</el-button>
      <el-button type="danger" @click="onDelete">✕ 删除</el-button>
    </div>

    <div v-if="detail" class="detail-block">
      <p>
        <strong>时间:</strong> {{ detail.timestamp }}
        &nbsp;
        <strong>路由:</strong>
        {{ detail.has_web ? '🌐 网络补充' : '📚 本地知识库' }}
      </p>
      <el-divider />

      <template v-if="detail.messages?.length">
        <div
          v-for="(m, i) in detail.messages"
          :key="i"
          class="detail-msg"
          :class="m.role"
        >
          <div v-if="m.role === 'user'">
            <strong>🙋 {{ m.content }}</strong>
          </div>
          <div v-else v-html="renderMd(m.content)" />
        </div>
      </template>
      <template v-else>
        <p><strong>问题:</strong> {{ detail.question }}</p>
        <el-divider />
        <div v-html="renderMd(detail.answer)" />
      </template>
    </div>
    <el-empty v-else description="输入 ID 查看对话详情" />
  </div>
</template>
