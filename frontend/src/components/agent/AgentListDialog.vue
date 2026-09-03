<template>
  <el-dialog
    v-model="visible"
    :title="title"
    width="800px"
    :close-on-click-modal="false"
    @close="handleClose"
  >
    <el-table
      :data="items"
      v-loading="loading"
      stripe
      border
      style="width: 100%"
    >
      <el-table-column
        v-for="col in columns"
        :key="col.prop"
        :prop="col.prop"
        :label="col.label"
        :width="col.width"
        :min-width="col.minWidth"
      >
        <template #default="scope">
          <slot :name="col.prop" :row="scope.row">
            {{ scope.row[col.prop] }}
          </slot>
        </template>
      </el-table-column>
      <el-table-column
        v-if="showActions"
        label="操作"
        width="120"
        fixed="right"
      >
        <template #default="scope">
          <el-button
            type="primary"
            link
            @click="handleSelect(scope.row)"
          >
            选择
          </el-button>
        </template>
      </el-table-column>
    </el-table>

    <template #footer>
      <el-pagination
        v-if="(total || 0) > pageSize"
        v-model:current-page="currentPage"
        v-model:page-size="pageSize"
        :total="total"
        :page-sizes="[10, 20, 50]"
        layout="total, sizes, prev, pager, next"
        @size-change="handlePageChange"
        @current-change="handlePageChange"
      />
      <el-button @click="handleClose">关闭</el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'

interface Column {
  prop: string
  label: string
  width?: number | string
  minWidth?: number | string
}

const props = defineProps<{
  modelValue: boolean
  title: string
  items: any[]
  columns: Column[]
  total?: number
  loading?: boolean
  showActions?: boolean
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  'select': [item: any]
  'page-change': [page: number, size: number]
}>()

const visible = ref(props.modelValue)
const currentPage = ref(1)
const pageSize = ref(10)

watch(() => props.modelValue, (val) => {
  visible.value = val
})

watch(visible, (val) => {
  emit('update:modelValue', val)
})

function handleClose() {
  visible.value = false
}

function handleSelect(item: any) {
  emit('select', item)
  visible.value = false
}

function handlePageChange() {
  emit('page-change', currentPage.value, pageSize.value)
}
</script>

<style scoped lang="scss">
.el-pagination {
  margin-top: 16px;
  justify-content: flex-end;
}
</style>
