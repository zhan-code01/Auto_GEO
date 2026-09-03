<template>
  <section class="phrase-list">
    <div class="section-title">{{ title }}</div>
    <div
      v-for="phrase in phrases"
      :key="phrase.question"
      class="phrase-item"
    >
      <span>{{ phrase.question }}</span>
      <button
        type="button"
        :disabled="phrase.saved"
        @click="$emit('save', phrase)"
      >
        {{ phrase.saved ? '已保存' : '保存' }}
      </button>
    </div>
  </section>
</template>

<script setup lang="ts">
interface ConversionPhrase {
  question: string
  keyword?: string
  saved: boolean
}

defineProps<{
  title: string
  phrases: ConversionPhrase[]
}>()

defineEmits<{
  (e: 'save', phrase: ConversionPhrase): void
}>()
</script>

<style scoped lang="scss">
.phrase-list {
  padding: 12px 0;

  .section-title {
    margin-bottom: 10px;
    font-size: 14px;
    font-weight: 600;
  }

  .phrase-item {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    padding: 8px 0;

    span {
      flex: 1;
      font-size: 13px;
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
}
</style>
