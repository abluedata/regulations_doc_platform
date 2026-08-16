<script setup lang="ts">
import { Right } from '@element-plus/icons-vue'

defineProps<{ examples: string[]; disabled?: boolean }>()
const emit = defineEmits<{ select: [text: string] }>()
</script>

<template>
  <div class="examples" v-if="examples?.length">
    <h2>推荐问题</h2>
    <div class="example-chips">
      <el-button
        v-for="ex in examples"
        :key="ex"
        size="small"
        :disabled="disabled"
        @click="emit('select', ex)"
      >
        <span>{{ ex }}</span>
        <el-icon aria-hidden="true"><Right /></el-icon>
      </el-button>
    </div>
  </div>
</template>
