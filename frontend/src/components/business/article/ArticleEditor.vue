<template>
  <div class="article-editor">
    <div class="editor-toolbar">
      <div class="toolbar-group">
        <el-button text @click="execCommand('bold')" title="加粗">
          <el-icon><Bold /></el-icon>
        </el-button>
        <el-button text @click="execCommand('italic')" title="斜体">
          <el-icon><Italic /></el-icon>
        </el-button>
        <el-button text @click="execCommand('underline')" title="下划线">
          <el-icon><Underline /></el-icon>
        </el-button>
      </div>
      <div class="toolbar-divider"></div>
      <div class="toolbar-group">
        <el-button text @click="execCommand('insertUnorderedList')" title="无序列表">
          <el-icon><List /></el-icon>
        </el-button>
        <el-button text @click="execCommand('insertOrderedList')" title="有序列表">
          <el-icon><Bottom /></el-icon>
        </el-button>
      </div>
      <div class="toolbar-divider"></div>
      <div class="toolbar-group">
        <el-button text @click="insertLink" title="插入链接">
          <el-icon><Link /></el-icon>
        </el-button>
        <el-button text @click="clearFormat" title="清除格式">
          <el-icon><Remove /></el-icon>
        </el-button>
      </div>
      <div class="toolbar-spacer"></div>
      <div class="toolbar-info">
        <span>{{ charCount }} 字</span>
      </div>
    </div>

    <div
      ref="editorRef"
      class="editor-content"
      :contenteditable="true"
      @input="handleInput"
      @blur="handleBlur"
    ></div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { EditPen as Bold, Edit as Italic, Minus as Underline, List, Bottom, Link, Remove } from '@element-plus/icons-vue'

interface Props {
  modelValue: string
  placeholder?: string
  minHeight?: number
}

interface Emits {
  (e: 'update:modelValue', value: string): void
}

const props = withDefaults(defineProps<Props>(), {
  placeholder: '请输入文章内容...',
  minHeight: 300,
})

const emit = defineEmits<Emits>()

const editorRef = ref<HTMLDivElement>()
const innerContent = ref('')

const charCount = computed(() => {
  return innerContent.value.replace(/<[^>]*>/g, '').length
})

onMounted(() => {
  if (editorRef.value) {
    editorRef.value.innerHTML = props.modelValue
    innerContent.value = props.modelValue
  }
})

watch(() => props.modelValue, (newVal) => {
  if (editorRef.value && editorRef.value.innerHTML !== newVal) {
    editorRef.value.innerHTML = newVal
  }
})

const handleInput = () => {
  if (editorRef.value) {
    innerContent.value = editorRef.value.innerHTML
    emit('update:modelValue', editorRef.value.innerHTML)
  }
}

const handleBlur = () => {
  if (editorRef.value) {
    emit('update:modelValue', editorRef.value.innerHTML)
  }
}

const execCommand = (command: string, value?: string) => {
  document.execCommand(command, false, value)
  editorRef.value?.focus()
}

const insertLink = () => {
  const url = prompt('请输入链接地址：')
  if (url) {
    execCommand('createLink', url)
  }
}

const clearFormat = () => {
  execCommand('removeFormat')
}

// 暴露方法供外部调用
defineExpose({
  focus: () => editorRef.value?.focus(),
  getContent: () => editorRef.value?.innerHTML || '',
  setContent: (content: string) => {
    if (editorRef.value) {
      editorRef.value.innerHTML = content
      innerContent.value = content
    }
  },
})
</script>

<style scoped lang="scss">
.article-editor {
  border: 1px solid var(--border);
  border-radius: 8px;
  overflow: hidden;
  background: var(--bg-secondary);

  &:focus-within {
    border-color: var(--primary);
  }
}

.editor-toolbar {
  display: flex;
  align-items: center;
  padding: 8px 12px;
  background: var(--bg-tertiary);
  border-bottom: 1px solid var(--border);

  .toolbar-group {
    display: flex;
    gap: 4px;
  }

  .toolbar-divider {
    width: 1px;
    height: 20px;
    background: var(--border);
    margin: 0 8px;
  }

  .toolbar-spacer {
    flex: 1;
  }

  .toolbar-info {
    font-size: 12px;
    color: var(--text-secondary);
  }

  .el-button {
    color: var(--text-secondary);

    &:hover {
      color: var(--text-primary);
      background: rgba(255, 255, 255, 0.1);
    }
  }
}

.editor-content {
  min-height: v-bind('props.minHeight + "px"');
  max-height: 500px;
  overflow-y: auto;
  padding: 16px;
  outline: none;
  line-height: 1.8;
  color: var(--text-primary);

  &:empty:before {
    content: attr(placeholder);
    color: var(--text-secondary);
    pointer-events: none;
  }

  // 基础样式
  h1, h2, h3, h4, h5, h6 {
    margin: 16px 0 8px 0;
    font-weight: 600;
  }

  p {
    margin: 8px 0;
  }

  ul, ol {
    padding-left: 24px;
    margin: 8px 0;
  }

  a {
    color: var(--primary);
    text-decoration: none;

    &:hover {
      text-decoration: underline;
    }
  }

  blockquote {
    margin: 12px 0;
    padding-left: 16px;
    border-left: 4px solid var(--primary);
    color: var(--text-secondary);
  }

  code {
    padding: 2px 6px;
    background: var(--bg-tertiary);
    border-radius: 4px;
    font-family: 'JetBrains Mono', monospace;
    font-size: 14px;
  }

  pre {
    padding: 12px;
    background: var(--bg-tertiary);
    border-radius: 8px;
    overflow-x: auto;

    code {
      padding: 0;
      background: transparent;
    }
  }

  img {
    max-width: 100%;
    border-radius: 8px;
  }
}
</style>
