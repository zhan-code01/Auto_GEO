<template>
  <div class="result-item">
    <div class="result-index">{{ index + 1 }}</div>
    <div class="result-body">
      <div class="result-keyword">{{ result.keyword }}</div>
      <ul>
        <li v-for="question in result.questions" :key="question">{{ question }}</li>
      </ul>
    </div>
    <button
      type="button"
      :disabled="result.saved"
      @click="$emit('save', result)"
    >
      {{ result.saved ? '已保存' : '保存' }}
    </button>
  </div>
</template>

<script setup lang="ts">
interface DistillResult {
  id: string
  keyword: string
  questions: string[]
  saved: boolean
}

defineProps<{
  result: DistillResult
  index: number
}>()

defineEmits<{
  (e: 'save', result: DistillResult): void
}>()
</script>

<style scoped lang="scss">
.result-item {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 12px 0;

  .result-index {
    width: 24px;
    height: 24px;
    border-radius: 50%;
    display: grid;
    place-items: center;
    background: var(--bg-secondary);
    font-size: 12px;
  }

  .result-body {
    flex: 1;
  }

  .result-keyword {
    margin-bottom: 6px;
    font-weight: 600;
  }

  ul {
    margin: 0;
    padding-left: 18px;
    color: var(--text-secondary);
  }

  button {
    border: 0;
    border-radius: 6px;
    padding: 5px 10px;
    background: var(--el-color-primary);
    color: #fff;
    cursor: pointer;

    &:disabled {
      opacity: 0.55;
      cursor: default;
    }
  }
}
</style>
