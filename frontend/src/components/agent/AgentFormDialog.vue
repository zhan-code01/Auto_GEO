<template>
  <el-dialog
    v-model="visible"
    :title="title"
    width="600px"
    :close-on-click-modal="false"
    @close="handleClose"
  >
    <el-form
      ref="formRef"
      :model="formData"
      :rules="formRules"
      label-width="120px"
      label-position="right"
    >
      <el-form-item
        v-for="field in fields"
        :key="field.prop"
        :label="field.label"
        :prop="field.prop"
      >
        <!-- 文本输入 -->
        <el-input
          v-if="field.type === 'input'"
          v-model="formData[field.prop]"
          :placeholder="field.placeholder"
          :disabled="field.disabled"
        />

        <!-- 文本域 -->
        <el-input
          v-else-if="field.type === 'textarea'"
          v-model="formData[field.prop]"
          type="textarea"
          :rows="3"
          :placeholder="field.placeholder"
          :disabled="field.disabled"
        />

        <!-- 下拉选择 -->
        <el-select
          v-else-if="field.type === 'select'"
          v-model="formData[field.prop]"
          :placeholder="field.placeholder || '请选择'"
          :disabled="field.disabled"
          style="width: 100%"
        >
          <el-option
            v-for="opt in field.options"
            :key="opt.value"
            :label="opt.label"
            :value="opt.value"
          />
        </el-select>

        <!-- 数字输入 -->
        <el-input-number
          v-else-if="field.type === 'number'"
          v-model="formData[field.prop]"
          :min="field.min"
          :max="field.max"
          :placeholder="field.placeholder"
          :disabled="field.disabled"
          style="width: 100%"
        />
      </el-form-item>
    </el-form>

    <template #footer>
      <el-button @click="handleClose">取消</el-button>
      <el-button type="primary" :loading="submitting" @click="handleSubmit">
        {{ submitText }}
      </el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { ref, reactive, watch } from 'vue'
import type { FormInstance, FormRules } from 'element-plus'

interface Field {
  prop: string
  label: string
  type: 'input' | 'textarea' | 'select' | 'number'
  placeholder?: string
  required?: boolean
  disabled?: boolean
  options?: Array<{ label: string; value: any }>
  min?: number
  max?: number
}

const props = defineProps<{
  modelValue: boolean
  title: string
  fields: Field[]
  initialValues?: Record<string, any>
  submitText?: string
  submitting?: boolean
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  'submit': [data: Record<string, any>]
}>()

const visible = ref(props.modelValue)
const formRef = ref<FormInstance>()
const formData = reactive<Record<string, any>>({})
const formRules = reactive<FormRules>({})

watch(() => props.modelValue, (val) => {
  visible.value = val
  if (val) {
    initForm()
  }
})

watch(visible, (val) => {
  emit('update:modelValue', val)
})

function initForm() {
  // 初始化表单数据和验证规则
  Object.keys(formData).forEach(key => delete formData[key])
  Object.keys(formRules).forEach(key => delete formRules[key])

  props.fields.forEach(field => {
    // 设置初始值
    formData[field.prop] = props.initialValues?.[field.prop] ?? ''

    // 设置验证规则
    if (field.required) {
      formRules[field.prop] = [
        { required: true, message: `请输入${field.label}`, trigger: 'blur' }
      ]
    }
  })
}

function handleClose() {
  visible.value = false
  formRef.value?.resetFields()
}

async function handleSubmit() {
  if (!formRef.value) return

  try {
    await formRef.value.validate()
    emit('submit', { ...formData })
  } catch (error) {
    // 验证失败，不提交
  }
}
</script>

<style scoped lang="scss">
.el-form {
  padding: 20px 0;
}
</style>
