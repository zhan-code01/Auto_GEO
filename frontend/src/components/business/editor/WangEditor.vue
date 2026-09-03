<template>
  <div class="wang-editor-wrapper">
    <Toolbar
      class="editor-toolbar"
      :editor="editorRef"
      :defaultConfig="toolbarConfig"
      :mode="mode"
    />
    <Editor
      class="editor-content"
      :style="{ height: editorHeight }"
      :model-value="modelValue"
      :defaultConfig="editorConfig"
      :mode="mode"
      @onCreated="handleCreated"
      @onChange="handleChange"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, shallowRef, onBeforeUnmount, watch } from 'vue'
import { Editor, Toolbar } from '@wangeditor/editor-for-vue'
import { ElMessage } from 'element-plus'
import type { IDomEditor, IEditorConfig, IToolbarConfig } from '@wangeditor/editor'
import '@wangeditor/editor/dist/css/style.css'

// Props
const props = defineProps<{
  modelValue: string
  height?: string
  readonly?: boolean
}>()

// Emits
const emit = defineEmits<{
  (e: 'update:modelValue', value: string): void
  (e: 'change', value: string): void
}>()

// 编辑器实例，必须用 shallowRef
const editorRef = shallowRef<IDomEditor>()

// 模式
const mode = 'default'

// 编辑器高度
const editorHeight = props.height || '500px'

// 工具栏配置
const toolbarConfig: Partial<IToolbarConfig> = {
  // 排除的工具
  excludeKeys: ['group-video'],

  // 工具栏排列
  toolbarKeys: [
    'headerSelect',
    'bold',
    'italic',
    'underline',
    'through',
    '|',
    'fontSize',
    'fontFamily',
    'lineHeight',
    'color',
    'bgColor',
    '|',
    'bulletedList',
    'numberedList',
    'todo',
    '|',
    'justifyLeft',
    'justifyCenter',
    'justifyRight',
    'justifyJustify',
    '|',
    'link',
    'uploadImage',
    'codeBlock',
    'divider',
    'emotion',
    '|',
    'undo',
    'redo',
    'fullScreen',
  ],
}

// 编辑器配置
const editorConfig: Partial<IEditorConfig> = {
  placeholder: '请输入文章内容...',
  readOnly: props.readonly || false,
  autoFocus: true,

  // 菜单配置
  MENU_CONF: {
    // 图片上传配置
    uploadImage: {
      // 自定义上传
      async customUpload(file: File, insertFn: any) {
        try {
          const formData = new FormData()
          formData.append('file', file)

          const response = await fetch('/api/upload/image', {
            method: 'POST',
            body: formData,
          })

          const result = await response.json()

          if (result.success) {
            // 插入图片到编辑器
            insertFn(result.data.url, result.data.original_name || file.name, result.data.url)
            ElMessage.success('图片上传成功')
          } else {
            throw new Error(result.message || '上传失败')
          }
        } catch (error: any) {
          ElMessage.error(error.message || '图片上传失败')
        }
      },

      // 最多可上传的图片数量
      maxNumberOfFiles: 10,

      // 单个文件的最大体积限制，默认为 5M
      maxFileSize: 5 * 1024 * 1024,

      // 最多可上传的图片数量
      allowedFileTypes: ['image/*'],

      // 超时时间，默认为 10 秒
      timeout: 10 * 1000,

      // 自定义插入图片
      onInsertedImage(imageNode: any) {
        if (imageNode == null) return
        // 可选：插入后的回调
      },

      // 上传错误
      onError(file: File, err: any, res: any) {
        ElMessage.error(`图片 ${file.name} 上传失败`)
      },
    },

    // 代码块配置
    codeSelectLang: {
      // 代码语言列表
      codeLangs: [
        { text: 'CSS', value: 'css' },
        { text: 'HTML', value: 'html' },
        { text: 'XML', value: 'xml' },
        { text: 'JavaScript', value: 'javascript' },
        { text: 'TypeScript', value: 'typescript' },
        { text: 'Python', value: 'python' },
        { text: 'Java', value: 'java' },
        { text: 'C/C++', value: 'cpp' },
        { text: 'C#', value: 'csharp' },
        { text: 'Go', value: 'go' },
        { text: 'Rust', value: 'rust' },
        { text: 'SQL', value: 'sql' },
        { text: 'Shell', value: 'shell' },
        { text: 'JSON', value: 'json' },
        { text: 'Markdown', value: 'markdown' },
        { text: 'YAML', value: 'yaml' },
        { text: 'Bash', value: 'bash' },
        { text: 'PlainText', value: 'text' },
      ],
    },
  },
}

// 处理编辑器创建
function handleCreated(editor: IDomEditor) {
  editorRef.value = editor
}

// 处理内容变化
function handleChange(editor: IDomEditor) {
  const html = editor.getHtml()
  emit('update:modelValue', html)
  emit('change', html)
}

// 组件销毁时，销毁编辑器
onBeforeUnmount(() => {
  const editor = editorRef.value
  if (editor == null) return
  editor.destroy()
})

// 监听外部值变化
watch(
  () => props.modelValue,
  (newVal) => {
    if (editorRef.value && newVal !== editorRef.value.getHtml()) {
      editorRef.value.setHtml(newVal)
    }
  }
)
</script>

<style scoped lang="scss">
.wang-editor-wrapper {
  border: 1px solid var(--el-border-color);
  border-radius: 8px;
  overflow: hidden;
  background: var(--el-bg-color);

  .editor-toolbar {
    border-bottom: 1px solid var(--el-border-color);
    background: var(--el-fill-color-light);
  }

  .editor-content {
    overflow-y: auto;

    // 深色模式适配
    :deep(.w-e-text-container) {
      background: var(--el-bg-color);

      .w-e-text-placeholder {
        color: var(--el-text-color-placeholder);
      }

      // 编辑区文字颜色
      .w-e-text {
        color: var(--el-text-color-primary);
        background: var(--el-bg-color);

        p,
        span,
        div {
          color: var(--el-text-color-primary);
        }

        // 链接颜色
        a {
          color: var(--el-color-primary);
          &:hover {
            color: var(--el-color-primary-light-3);
          }
        }

        // 图片样式
        img {
          max-width: 100%;
          border-radius: 8px;
          margin: 10px 0;
        }

        // 代码块样式
        pre {
          background: var(--surface-field);
          color: var(--text-body);
          padding: 16px;
          border-radius: 8px;
          border: 1px solid var(--border-thin);
          overflow-x: auto;

          code {
            font-family: 'Consolas', 'Monaco', 'Courier New', monospace;
            font-size: 14px;
            line-height: 1.6;
          }
        }

        // 引用块
        blockquote {
          border-left: 4px solid var(--el-color-primary);
          padding-left: 16px;
          margin: 10px 0;
          color: var(--el-text-color-regular);
          background: var(--el-fill-color-lighter);
        }

        // 表格样式
        table {
          border-collapse: collapse;
          width: 100%;
          margin: 10px 0;

          th,
          td {
            border: 1px solid var(--el-border-color);
            padding: 8px 12px;
          }

          th {
            background: var(--el-fill-color-light);
            font-weight: bold;
          }
        }

        // 分割线
        hr {
          border: none;
          border-top: 1px solid var(--el-border-color);
          margin: 20px 0;
        }
      }
    }

    // 选中区域
    :deep(.w-e-textarea-selected) {
      background: var(--el-color-primary-light-7);
    }
  }
}
</style>
