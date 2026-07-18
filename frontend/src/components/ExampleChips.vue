<script setup lang="ts">
defineProps<{ examples: string[]; disabled?: boolean }>()
const emit = defineEmits<{ select: [text: string] }>()
</script>

<template>
  <div class="examples" v-if="examples?.length">
    <h4>推荐问题</h4>
    <div class="example-chips">
      <el-button
        v-for="ex in examples"
        :key="ex"
        size="small"
        round
        :disabled="disabled"
        @click="emit('select', ex)"
      >
        {{ ex }}
      </el-button>
    </div>
  </div>
</template>
