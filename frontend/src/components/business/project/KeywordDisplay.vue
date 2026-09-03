<template>
  <div class="keyword-display">
    <!-- 头部 -->
    <div class="display-header">
      <div class="header-left">
        <div class="header-icon">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"/>
          </svg>
        </div>
        <div>
          <h3 class="header-title">已保存的关键词</h3>
          <span class="header-count">{{ keywords.length }} 个</span>
        </div>
      </div>
      <div class="header-actions">
        <div class="view-toggle">
          <button
            :class="{ active: viewMode === 'grid' }"
            @click="viewMode = 'grid'"
          >
            <svg viewBox="0 0 16 16" fill="currentColor" width="16">
              <path d="M1 2.5A1.5 1.5 0 012.5 1h3A1.5 1.5 0 017 2.5v3A1.5 1.5 0 015.5 7h-3A1.5 1.5 0 011 5.5v-3zm8 0A1.5 1.5 0 0110.5 1h3A1.5 1.5 0 0115 2.5v3A1.5 1.5 0 0113.5 7h-3A1.5 1.5 0 019 5.5v-3zm-8 8A1.5 1.5 0 012.5 9h3A1.5 1.5 0 017 10.5v3A1.5 1.5 0 015.5 15h-3A1.5 1.5 0 011 13.5v-3zm8 0A1.5 1.5 0 0110.5 9h3a1.5 1.5 0 011.5 1.5v3a1.5 1.5 0 01-1.5 1.5h-3A1.5 1.5 0 019 13.5v-3z"/>
            </svg>
          </button>
          <button
            :class="{ active: viewMode === 'list' }"
            @click="viewMode = 'list'"
          >
            <svg viewBox="0 0 16 16" fill="currentColor" width="16">
              <path fill-rule="evenodd" d="M2.5 12a.5.5 0 01.5-.5h10a.5.5 0 010 1H3a.5.5 0 01-.5-.5zm0-4a.5.5 0 01.5-.5h10a.5.5 0 010 1H3a.5.5 0 01-.5-.5zm0-4a.5.5 0 01.5-.5h10a.5.5 0 010 1H3a.5.5 0 01-.5-.5z"/>
            </svg>
          </button>
        </div>
      </div>
    </div>

    <!-- 空状态 -->
    <div v-if="!loading && keywords.length === 0" class="empty-state">
      <div class="empty-icon">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
          <path d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z"/>
        </svg>
      </div>
      <h4>还没有关键词</h4>
      <p>在左侧蒸馏面板输入关键词和公司名称，点击「开始蒸馏」</p>
    </div>

    <!-- 加载状态 -->
    <div v-if="loading" class="loading-grid">
      <div v-for="i in 6" :key="i" class="keyword-skeleton">
        <div class="skeleton-header">
          <div class="skeleton-keyword"></div>
          <div class="skeleton-difficulty"></div>
        </div>
        <div class="skeleton-questions">
          <div class="skeleton-q"></div>
          <div class="skeleton-q"></div>
        </div>
      </div>
    </div>

    <!-- 关键词网格 -->
    <div v-else class="keywords-container" :class="viewMode">
      <TransitionGroup name="keyword">
        <div
          v-for="keyword in keywords"
          :key="keyword.id"
          class="keyword-card"
          @click="viewDetail(keyword)"
        >
          <div class="card-header">
            <h4 class="keyword-text">{{ keyword.keyword }}</h4>
            <div v-if="keyword.difficulty_score" class="difficulty-badge" :class="getDifficultyClass(keyword.difficulty_score)">
              {{ keyword.difficulty_score }}
            </div>
          </div>
          <div class="card-body">
            <div class="questions-preview">
              <svg viewBox="0 0 16 16" fill="currentColor" width="12">
                <path d="M8 1a4 4 0 00-4 4v2H2v2h2v6a2 2 0 002 2h4a2 2 0 002-2V9h2V7h-2V5a4 4 0 00-4-4zm0 2a2 2 0 012 2v2H6V5a2 2 0 012-2z"/>
              </svg>
              <span>{{ getQuestionCount(keyword.id) }} 个问题变体</span>
            </div>
            <div class="card-actions">
              <button class="action-btn view" @click.stop="viewDetail(keyword)">
                <svg viewBox="0 0 16 16" fill="currentColor" width="14">
                  <path d="M10.5 8a2.5 2.5 0 11-5 0 2.5 2.5 0 015 0z"/>
                  <path d="M0 8s3-5.5 8-5.5S16 8 16 8s-3 5.5-8 5.5S0 8 0 8zm8 3.5a3.5 3.5 0 100-7 3.5 3.5 0 000 7z"/>
                </svg>
                查看
              </button>
              <button class="action-btn delete" @click.stop="deleteKeyword(keyword)">
                <svg viewBox="0 0 16 16" fill="currentColor" width="14">
                  <path d="M5.5 5.5A.5.5 0 016 6v6a.5.5 0 01-1 0V6a.5.5 0 01.5-.5zm2.5 0a.5.5 0 01.5.5v6a.5.5 0 01-1 0V6a.5.5 0 01.5-.5zm3 .5a.5.5 0 00-1 0v6a.5.5 0 001 0V6z"/>
                  <path fill-rule="evenodd" d="M14.5 3a1 1 0 01-1 1H13v9a2 2 0 01-2 2H5a2 2 0 01-2-2V4h-.5a1 1 0 01-1-1V2a1 1 0 011-1H6a1 1 0 011-1h2a1 1 0 011 1h3.5a1 1 0 011 1v1zM4.118 4L4 4.059V13a1 1 0 001 1h6a1 1 0 001-1V4.059L11.882 4H4.118zM2.5 3V2h11v1h-11z"/>
                </svg>
              </button>
            </div>
          </div>
        </div>
      </TransitionGroup>
    </div>

    <!-- 详情对话框 -->
    <el-dialog
      v-model="showDetail"
      :title="`关键词详情 - ${currentKeyword?.keyword}`"
      width="520px"
      class="detail-dialog"
    >
      <div v-if="currentKeyword" class="detail-content">
        <div class="detail-meta">
          <div class="meta-item">
            <span class="meta-label">关键词</span>
            <el-tag type="warning">{{ currentKeyword.keyword }}</el-tag>
          </div>
          <div class="meta-item">
            <span class="meta-label">难度评分</span>
            <el-tag v-if="currentKeyword.difficulty_score" :type="getDifficultyType(currentKeyword.difficulty_score)">
              {{ currentKeyword.difficulty_score }}
            </el-tag>
            <span v-else class="meta-empty">未评分</span>
          </div>
        </div>

        <el-divider />

        <div class="questions-section">
          <div class="questions-header">
            <h5>问题变体</h5>
            <el-button
              type="primary"
              size="small"
              :loading="generating"
              @click="generateQuestions"
            >
              <svg viewBox="0 0 16 16" fill="currentColor" width="14">
                <path d="M8 4a.5.5 0 01.5.5v3h3a.5.5 0 010 1h-3v3a.5.5 0 01-1 0v-3h-3a.5.5 0 010-1h3v-3A.5.5 0 018 4z"/>
              </svg>
              生成问题
            </el-button>
          </div>
          <div v-loading="loadingQuestions" class="questions-list">
            <TransitionGroup name="question">
              <div
                v-for="(q, index) in currentQuestions"
                :key="q.id"
                class="question-item"
              >
                <span class="q-number">{{ index + 1 }}</span>
                <span class="q-text">{{ q.question }}</span>
              </div>
            </TransitionGroup>
            <el-empty v-if="currentQuestions.length === 0" description="暂无问题变体，点击上方按钮生成" />
          </div>
        </div>
      </div>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { geoKeywordApi } from '@/services/api'

// ==================== 类型定义 ====================
interface Keyword {
  id: number
  keyword: string
  difficulty_score?: number
  status: string
  created_at: string
}

interface QuestionVariant {
  id: number
  keyword_id: number
  question: string
  created_at: string
}

// ==================== Props ====================
interface Props {
  keywords: Keyword[]
  loading?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  loading: false,
})

// ==================== 状态 ====================
const viewMode = ref<'grid' | 'list'>('grid')
const showDetail = ref(false)
const currentKeyword = ref<Keyword | null>(null)
const currentQuestions = ref<QuestionVariant[]>([])
const loadingQuestions = ref(false)
const generating = ref(false)

// ==================== 计算属性 ====================

// ==================== 方法 ====================

// 获取问题数量
const getQuestionCount = (keywordId: number) => {
  return currentQuestions.value.filter(q => q.keyword_id === keywordId).length ||
    (currentKeyword.value?.id === keywordId ? currentQuestions.value.length : 0)
}

// 获取难度样式类
const getDifficultyClass = (score: number) => {
  if (score >= 80) return 'high'
  if (score >= 60) return 'medium'
  return 'low'
}

// 获取难度标签类型
const getDifficultyType = (score: number) => {
  if (score >= 80) return 'danger'
  if (score >= 60) return 'warning'
  return 'success'
}

// 查看详情
const viewDetail = async (keyword: Keyword) => {
  currentKeyword.value = keyword
  showDetail.value = true
  await loadQuestions(keyword.id)
}

// 加载问题
const loadQuestions = async (keywordId: number) => {
  loadingQuestions.value = true
  try {
    const result = await geoKeywordApi.getKeywordQuestions(keywordId)
    currentQuestions.value = result || []
  } catch (error) {
    console.error('加载问题失败:', error)
  } finally {
    loadingQuestions.value = false
  }
}

// 生成问题
const generateQuestions = async () => {
  if (!currentKeyword.value) return

  generating.value = true
  try {
    const result = await geoKeywordApi.generateQuestions({
      keyword_id: currentKeyword.value.id,
      count: 3,
    })

    if (result.success) {
      await loadQuestions(currentKeyword.value.id)
      ElMessage.success(result.message || '问题生成成功')
    }
  } catch (error) {
    console.error('生成问题失败:', error)
    ElMessage.error('生成问题失败')
  } finally {
    generating.value = false
  }
}

// 删除关键词
const deleteKeyword = async (keyword: Keyword) => {
  try {
    await ElMessageBox.confirm(
      `确定要删除关键词"${keyword.keyword}"吗？`,
      '确认删除',
      { type: 'warning', confirmButtonText: '确定删除', cancelButtonText: '取消' }
    )

    await geoKeywordApi.deleteKeyword(keyword.id)
    emit('delete', keyword.id)
    ElMessage.success('删除成功')
  } catch (error) {
    if (error !== 'cancel') {
      console.error('删除失败:', error)
    }
  }
}

// ==================== Emits ====================
const emit = defineEmits<{
  delete: [id: number]
}>()
</script>

<style scoped lang="scss">
.keyword-display {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: #f8f9fc;
  border-radius: 12px;
  overflow: hidden;
}

// 头部
.display-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 20px;
  background: white;
  border-bottom: 1px solid #e8ecf1;

  .header-left {
    display: flex;
    align-items: center;
    gap: 12px;

    .header-icon {
      width: 36px;
      height: 36px;
      border-radius: 10px;
      background: linear-gradient(135deg, #8b5cf6 0%, #7c3aed 100%);
      display: flex;
      align-items: center;
      justify-content: center;
      color: white;

      svg {
        width: 18px;
        height: 18px;
      }
    }

    .header-title {
      margin: 0;
      font-size: 14px;
      font-weight: 600;
      color: #1a1f36;
    }

    .header-count {
      font-size: 12px;
      color: #9ca3af;
    }
  }

  .view-toggle {
    display: flex;
    background: #f3f4f6;
    border-radius: 8px;
    padding: 2px;

    button {
      padding: 6px 10px;
      background: transparent;
      border: none;
      border-radius: 6px;
      color: #9ca3af;
      cursor: pointer;
      transition: all 0.2s;

      &:hover {
        color: #6b7280;
      }

      &.active {
        background: white;
        color: #4a90e2;
        box-shadow: 0 1px 2px rgba(0, 0, 0, 0.05);
      }
    }
  }
}

// 空状态
.empty-state {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 60px 20px;
  text-align: center;

  .empty-icon {
    width: 64px;
    height: 64px;
    border-radius: 50%;
    background: linear-gradient(135deg, rgba(139, 92, 246, 0.1) 0%, rgba(139, 92, 246, 0.05) 100%);
    display: flex;
    align-items: center;
    justify-content: center;
    margin-bottom: 16px;

    svg {
      width: 32px;
      height: 32px;
      color: #8b5cf6;
    }
  }

  h4 {
    margin: 0 0 8px 0;
    font-size: 16px;
    font-weight: 500;
    color: #1a1f36;
  }

  p {
    margin: 0;
    font-size: 13px;
    color: #9ca3af;
    max-width: 280px;
  }
}

// 加载骨架屏
.loading-grid {
  padding: 20px;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: 16px;

  .keyword-skeleton {
    background: white;
    border-radius: 12px;
    padding: 16px;

    .skeleton-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 12px;

      .skeleton-keyword {
        width: 120px;
        height: 20px;
        border-radius: 6px;
        background: linear-gradient(90deg, #e0e0e0 25%, #f0f0f0 50%, #e0e0e0 75%);
        background-size: 200% 100%;
        animation: shimmer 1.5s infinite;
      }

      .skeleton-difficulty {
        width: 40px;
        height: 20px;
        border-radius: 6px;
        background: linear-gradient(90deg, #e0e0e0 25%, #f0f0f0 50%, #e0e0e0 75%);
        background-size: 200% 100%;
        animation: shimmer 1.5s infinite;
      }
    }

    .skeleton-questions {
      .skeleton-q {
        height: 16px;
        border-radius: 4px;
        background: linear-gradient(90deg, #e0e0e0 25%, #f0f0f0 50%, #e0e0e0 75%);
        background-size: 200% 100%;
        animation: shimmer 1.5s infinite;
        margin-bottom: 6px;

        &:last-child {
          width: 70%;
          margin-bottom: 0;
        }
      }
    }
  }
}

// 关键词容器
.keywords-container {
  flex: 1;
  overflow-y: auto;
  padding: 20px;

  &.grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
    gap: 16px;
  }

  &.list {
    display: flex;
    flex-direction: column;
    gap: 10px;

    .keyword-card {
      flex-direction: row;
      align-items: center;

      .card-header {
        margin-bottom: 0;
        margin-right: 16px;
      }

      .card-body {
        flex: 1;
        flex-direction: row;
        align-items: center;
        justify-content: space-between;

        .questions-preview {
          margin-bottom: 0;
          margin-right: 16px;
        }
      }
    }
  }
}

// 关键词卡片
.keyword-card {
  background: white;
  border-radius: 12px;
  padding: 16px;
  cursor: pointer;
  transition: all 0.2s ease;
  border: 2px solid transparent;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04);

  &:hover {
    border-color: #8b5cf6;
    box-shadow: 0 8px 24px rgba(139, 92, 246, 0.15);
    transform: translateY(-2px);
  }

  .card-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 12px;

    .keyword-text {
      margin: 0;
      font-size: 15px;
      font-weight: 500;
      color: #1a1f36;
    }

    .difficulty-badge {
      padding: 4px 8px;
      border-radius: 6px;
      font-size: 11px;
      font-weight: 600;

      &.high {
        background: #fef2f2;
        color: #ef4444;
      }

      &.medium {
        background: #fef3c7;
        color: #d97706;
      }

      &.low {
        background: #d1fae5;
        color: #059669;
      }
    }
  }

  .card-body {
    display: flex;
    flex-direction: column;
    gap: 12px;

    .questions-preview {
      display: flex;
      align-items: center;
      gap: 6px;
      font-size: 12px;
      color: #9ca3af;

      svg {
        color: #8b5cf6;
      }
    }

    .card-actions {
      display: flex;
      gap: 8px;
      padding-top: 12px;
      border-top: 1px solid #f3f4f6;

      .action-btn {
        flex: 1;
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 6px;
        padding: 8px;
        border: none;
        border-radius: 8px;
        font-size: 12px;
        cursor: pointer;
        transition: all 0.2s;

        &.view {
          background: #f3f4f6;
          color: #6b7280;

          &:hover {
            background: #e5e7eb;
            color: #1a1f36;
          }
        }

        &.delete {
          background: #fef2f2;
          color: #ef4444;

          &:hover {
            background: #fee2e2;
          }
        }
      }
    }
  }
}

// 详情对话框
.detail-content {
  .detail-meta {
    display: flex;
    gap: 24px;

    .meta-item {
      display: flex;
      align-items: center;
      gap: 8px;

      .meta-label {
        font-size: 13px;
        color: #6b7280;
      }

      .meta-empty {
        font-size: 13px;
        color: #9ca3af;
      }
    }
  }

  .questions-section {
    .questions-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      margin-bottom: 16px;

      h5 {
        margin: 0;
        font-size: 14px;
        font-weight: 500;
        color: #1a1f36;
      }
    }

    .questions-list {
      display: flex;
      flex-direction: column;
      gap: 10px;
      min-height: 100px;

      .question-item {
        display: flex;
        gap: 12px;
        padding: 12px;
        background: #f9fafb;
        border-radius: 8px;

        .q-number {
          width: 24px;
          height: 24px;
          border-radius: 50%;
          background: #8b5cf6;
          color: white;
          display: flex;
          align-items: center;
          justify-content: center;
          font-size: 12px;
          font-weight: 500;
          flex-shrink: 0;
        }

        .q-text {
          flex: 1;
          font-size: 13px;
          color: #374151;
        }
      }
    }
  }
}

// 滚动条
.keywords-container::-webkit-scrollbar {
  width: 6px;
}

.keywords-container::-webkit-scrollbar-track {
  background: transparent;
}

.keywords-container::-webkit-scrollbar-thumb {
  background: #d1d5db;
  border-radius: 3px;

  &:hover {
    background: #9ca3af;
  }
}

// 动画
@keyframes shimmer {
  0% { background-position: -200% 0; }
  100% { background-position: 200% 0; }
}

.keyword-enter-active {
  transition: all 0.3s ease;
}

.keyword-enter-from {
  opacity: 0;
  transform: scale(0.9);
}

.keyword-enter-to {
  opacity: 1;
  transform: scale(1);
}

.question-enter-active {
  transition: all 0.2s ease;
}

.question-enter-from {
  opacity: 0;
  transform: translateX(-10px);
}

.question-enter-to {
  opacity: 1;
  transform: translateX(0);
}

// 对话框样式
:deep(.detail-dialog) {
  .el-dialog__header {
    padding: 20px 20px 10px;

    .el-dialog__title {
      font-size: 16px;
      font-weight: 600;
      color: #1a1f36;
    }
  }

  .el-dialog__body {
    padding: 20px;
  }
}
</style>
