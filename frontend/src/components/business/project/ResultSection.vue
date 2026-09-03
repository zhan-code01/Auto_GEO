<template>
  <section class="result-section">
    <div class="section-title">
      <slot name="icon" />
      <span>{{ title }}</span>
      <em>{{ count }}</em>
    </div>
    <div class="tag-list">
      <span
        v-for="item in items"
        :key="item.key"
        class="result-tag"
        :class="tagClass"
      >
        {{ item.label }}
      </span>
    </div>
  </section>
</template>

<script setup lang="ts">
interface ResultItem {
  key: string
  label: string
}

defineProps<{
  title: string
  items: ResultItem[]
  count: number
  tagClass?: string
}>()
</script>

<style scoped lang="scss">
.result-section {
  padding: 12px 0;

  .section-title {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 10px;
    font-size: 14px;
    font-weight: 600;

    em {
      color: var(--text-secondary);
      font-style: normal;
      font-weight: 400;
    }
  }

  .tag-list {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
  }

  .result-tag {
    padding: 6px 10px;
    border-radius: 6px;
    background: var(--bg-secondary);
    color: var(--text-primary);
    font-size: 13px;
  }
}
</style>
