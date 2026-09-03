<template>
  <div class="agent-page">
    <section class="agent-shell" :class="{ 'sidebar-open': sidebarOpen }">
      <!-- 左侧：历史会话列表 -->
      <aside class="session-sidebar">
        <div class="sidebar-header">
          <el-button type="primary" class="new-chat-btn" :icon="Plus" @click="newConversation">
            新建对话
          </el-button>
          <el-button
            class="clear-chat-btn"
            :icon="Delete"
            :loading="clearingSessions"
            :disabled="loadingList || sessions.length === 0"
            title="一键清除历史对话"
            @click="clearAllSessions"
          >
            清除
          </el-button>
          <el-button class="sidebar-close" :icon="Close" link @click="sidebarOpen = false" />
        </div>

        <div v-loading="loadingList" class="sidebar-scroll">
          <p v-if="!loadingList && sessions.length === 0" class="sidebar-empty">
            还没有历史对话
          </p>
          <div
            v-for="item in sessions"
            :key="item.id"
            class="session-item"
            :class="{ active: item.id === activeSessionId }"
            @click="selectSession(item.id)"
          >
            <div class="session-item-main">
              <div class="session-title">{{ item.title || '未命名对话' }}</div>
              <div class="session-preview">{{ item.last_message || '（暂无消息）' }}</div>
              <div class="session-meta">
                <span class="session-time">{{ formatRelativeTime(item.updated_at) }}</span>
              </div>
            </div>
            <el-dropdown trigger="click" placement="bottom-end" @command="onSessionMenu">
              <span class="menu-trigger" @click.stop>
                <el-icon><MoreFilled /></el-icon>
              </span>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item :command="{ action: 'rename', item }">
                    <el-icon><EditPen /></el-icon>重命名
                  </el-dropdown-item>
                  <el-dropdown-item :command="{ action: 'archive', item }">
                    <el-icon><Box /></el-icon>归档
                  </el-dropdown-item>
                  <el-dropdown-item :command="{ action: 'delete', item }" divided>
                    <el-icon><Delete /></el-icon>删除
                  </el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </div>
        </div>
      </aside>

      <!-- 右侧：聊天区 -->
      <div class="chat-pane">
        <div class="chat-toolbar">
          <el-button class="sidebar-toggle" :icon="Menu" link @click="sidebarOpen = true" />
          <div class="toolbar-title">
            <h2>{{ activeSessionTitle || 'AutoGEO 智能体' }}</h2>
            <p>用自然语言整理生成、发布和任务查询需求。信息齐全后会自动生成并发布。</p>
          </div>
        </div>

        <div ref="messageListRef" v-loading="loadingHistory" class="message-list">
          <div
            v-for="(item, idx) in messages"
            :key="item.id"
            class="message-row"
            :class="item.role"
          >
            <div class="message-bubble">
              <div v-if="item.content" class="message-text markdown-body" v-html="renderMarkdown(item.content)"></div>

              <!-- 该轮附带的已上传文件 -->
              <div v-if="item.attachments?.length" class="attachment-list">
                <span v-for="(att, idx) in item.attachments" :key="idx" class="attachment-chip">
                  <el-icon><Paperclip /></el-icon>{{ att.filename }}
                </span>
              </div>

              <div v-if="item.questions?.length" class="question-list">
                <button
                  v-for="(question, qIdx) in item.questions"
                  :key="qIdx"
                  type="button"
                  @click="useQuestion(question)"
                >
                  {{ typeof question === 'string' ? question : (question as Record<string, any>).question || (question as Record<string, any>).q || '' }}
                </button>
              </div>

              <!-- 文章生成完成后挂到气泡上的文章卡片：标题 + 内容预览 + 状态 + 去发布/查看按钮 -->
              <div v-if="item.articles?.length" class="article-preview-list">
                <div v-for="(art, aIdx) in item.articles" :key="aIdx" class="article-preview-card">
                  <div class="ap-title">
                    <el-icon><Document /></el-icon>
                    <span>{{ art.title || `文章 #${art.id}` }}</span>
                    <el-tag size="small" :type="art.publish_status === 'completed' ? 'success' : 'info'">
                      {{ art.publish_status || 'completed' }}
                    </el-tag>
                  </div>
                  <div v-if="art.content" class="ap-content">{{ truncatePreview(art.content, 180) }}</div>
                  <div class="ap-actions">
                    <el-button size="small" type="primary" @click="openArticleListFromPreview(art)">去发布</el-button>
                    <el-button size="small" link @click="copyArticleContent(art)">复制正文</el-button>
                  </div>
                </div>
              </div>

              <!-- 动作卡片：确认发布 / 去绑定 / 上传资料 / 新手引导 等 -->
              <div v-if="displayActions(item).length" class="action-list">
                <el-button
                  v-for="(act, idx) in displayActions(item)"
                  :key="idx"
                  size="small"
                  :type="actionBtnType(act.type)"
                  @click="onAction(act)"
                >
                  {{ act.label }}
                </el-button>
              </div>

              <!-- 新手引导卡片：集中渲染在最新助手消息气泡内，不单独占聊天区下方空间。
                   助手气泡正在流式输出"正在思考/正在执行…"时（sending=true）不显示，
                   避免与正在执行的工具动作重复、误导用户。等待本轮 done 后再渲染下一步卡片。 -->
              <div
                v-if="item.role === 'assistant' && idx === lastAssistantIndex && onboardingActive && !sending && (onboardingNextCards.length || onboardingOptionalCards.length)"
                class="onboarding-action-list"
              >
                <span class="oal-hint">点击卡片继续：</span>
                <el-button
                  v-for="(act, idx3) in onboardingOptionalCards"
                  :key="'o' + idx3"
                  class="oal-optional"
                  size="small"
                  :type="actionBtnType(act.type)"
                  @click="onAction(act)"
                >
                  {{ act.label }}
                </el-button>
                <el-button
                  v-for="(act, idx2) in onboardingNextCards"
                  :key="'n' + idx2"
                  size="small"
                  :type="actionBtnType(act.type)"
                  :disabled="act.disabled"
                  :loading="act.type === 'article_generating'"
                  @click="onAction(act)"
                >
                  {{ act.label }}
                </el-button>
                <el-button class="oal-skip" link type="info" size="small" @click="dismissOnboardingFlow">跳过引导</el-button>
              </div>

            </div>
          </div>
        </div>

        <div class="composer">
          <!-- 待发送的附件 chips -->
          <div v-if="pendingAttachments.length" class="pending-attachments">
            <span
              v-for="(att, idx) in pendingAttachments"
              :key="idx"
              class="attachment-chip removable"
            >
              <el-icon><Paperclip /></el-icon>{{ att.filename }}
              <el-icon class="remove" @click="pendingAttachments.splice(idx, 1)"><Close /></el-icon>
            </span>
          </div>

          <el-input
            v-model="inputText"
            type="textarea"
            :rows="3"
            resize="none"
            maxlength="1000"
            show-word-limit
            placeholder="例如：帮我建个客户XX科技，再建个项目，发布到知乎"
            @keydown="onComposerKeydown"
          />
          <div class="composer-actions">
            <div class="quick-prompts">
              <el-button size="small" @click="fillPrompt('帮我建一个客户，公司叫XX科技，行业AI')">建客户</el-button>
              <el-button size="small" @click="fillPrompt('给XX科技建个项目，关键词数字人')">建项目</el-button>
              <el-button size="small" @click="triggerAttach()">上传资料</el-button>
              <el-button size="small" @click="fillPrompt('帮我绑定知乎账号')">绑账号</el-button>
              <el-button size="small" @click="fillPrompt('帮我写一篇关于数字人项目推广的文章，发布到知乎')">生成并发布</el-button>
              <el-button size="small" @click="fillPrompt('查询最近任务进度')">查进度</el-button>
            </div>
            <div class="composer-right">
              <input ref="fileInputRef" type="file" hidden @change="onFilePicked" />
              <el-button :icon="Paperclip" circle title="上传资料" @click="triggerAttach()" />
              <el-button v-if="!sending" type="primary" @click="sendMessage()">
                <el-icon><Promotion /></el-icon>
                发送
              </el-button>
              <el-button v-else type="danger" title="取消当前请求" @click="cancelStreaming()">
                <el-icon><Close /></el-icon>
                取消
              </el-button>
            </div>
          </div>
        </div>
      </div>
    </section>

    <!-- 窄屏遮罩 -->
    <div v-if="sidebarOpen" class="sidebar-mask" @click="sidebarOpen = false" />

    <!-- 弹窗组件 -->
    <AgentListDialog
      v-model="listDialogVisible"
      :title="listDialogConfig.title"
      :items="listDialogConfig.items"
      :columns="listDialogConfig.columns"
      :total="listDialogConfig.total"
      :loading="listDialogConfig.loading"
      :show-actions="listDialogConfig.showActions"
      @select="handleListSelect"
      @page-change="handlePageChange"
    />

    <AgentFormDialog
      v-model="formDialogVisible"
      :title="formDialogConfig.title"
      :fields="formDialogConfig.fields"
      :initial-values="formDialogConfig.initialValues"
      :submit-text="formDialogConfig.submitText"
      :submitting="formDialogConfig.submitting"
      @submit="handleFormSubmit"
    />

    <AgentSelectDialog
      v-model="selectDialogVisible"
      :title="selectDialogConfig.title"
      :items="selectDialogConfig.items"
      :default-value="selectDialogConfig.defaultValue"
      @select="handleSelectConfirm"
    />

    <!-- ============ 定制化：文章列表弹窗（带项目筛选、分页、去发布按钮） ============ -->
    <el-dialog
      v-model="articleListDialogVisible"
      title="文章列表"
      width="960px"
      :close-on-click-modal="false"
      top="6vh"
    >
      <!-- 顶部筛选栏 -->
      <div class="article-list-toolbar">
        <div class="toolbar-left">
          <el-select
            v-model="articleListFilter.projectId"
            placeholder="按项目筛选（全部）"
            clearable
            style="width: 240px"
            @change="reloadArticleList(1)"
          >
            <el-option
              v-for="p in articleListFilter.projectOptions"
              :key="p.id"
              :label="p.name"
              :value="p.id"
            />
          </el-select>
        </div>
        <div class="toolbar-right">
          <el-tag size="small" type="info">共 {{ articleListData.total }} 篇文章</el-tag>
        </div>
      </div>

      <!-- 表格 -->
      <el-table
        :data="articleListData.items"
        v-loading="articleListData.loading"
        stripe
        border
        style="width: 100%; margin-top: 12px"
        max-height="520"
      >
        <el-table-column prop="id" label="ID" width="70" align="center" />
        <el-table-column prop="title" label="文章标题" min-width="280">
          <template #default="{ row }">
            <div class="article-title-cell" :title="row.title">
              {{ row.title || '（无标题）' }}
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="project_name" label="所属项目" min-width="160" show-overflow-tooltip />
        <el-table-column prop="publish_status_label" label="状态" width="100" align="center">
          <template #default="{ row }">
            <el-tag :type="statusTagType(row.publish_status)" size="small">
              {{ row.publish_status_label || '待发布' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="创建时间" width="170" align="center">
          <template #default="{ row }">
            {{ formatDate(row.created_at) }}
          </template>
        </el-table-column>
        <!-- 操作列：去发布按钮 -->
        <el-table-column label="操作" width="140" fixed="right" align="center">
          <template #default="{ row }">
            <el-button
              type="primary"
              size="small"
              :icon="Promotion"
              :disabled="!canPublish(row)"
              @click="openPublishDialog(row)"
            >
              去发布
            </el-button>
          </template>
        </el-table-column>
      </el-table>

      <!-- 分页 -->
      <template #footer>
        <div class="article-list-footer">
          <el-pagination
            v-model:current-page="articleListFilter.page"
            v-model:page-size="articleListFilter.limit"
            :total="articleListData.total"
            :page-sizes="[10, 20, 50]"
            layout="total, sizes, prev, pager, next"
            background
            @size-change="reloadArticleList(1)"
            @current-change="(p: number) => reloadArticleList(p)"
          />
          <el-button @click="articleListDialogVisible = false">关闭</el-button>
        </div>
      </template>
    </el-dialog>

    <!-- ============ 定制化：发布文章弹窗（下拉选择平台/账号后发布，与文章管理页一致） ============ -->
    <el-dialog v-model="showPublishDialog" title="发布文章" width="560px" destroy-on-close>
      <div v-if="publishArticle" class="publish-summary">
        <div class="publish-title">{{ publishArticle.title || '未命名文章' }}</div>
        <div class="text-muted">选择发布账号后即可提交发布任务</div>
      </div>

      <el-form :model="publishForm" label-width="90px" class="publish-form">
        <el-form-item label="发布方式">
          <el-radio-group v-model="publishForm.mode">
            <el-radio label="immediate">立即发布</el-radio>
            <el-radio label="scheduled">定时发布</el-radio>
          </el-radio-group>
        </el-form-item>

        <el-form-item label="发布平台">
          <el-select
            v-model="publishForm.platform"
            placeholder="请选择平台"
            style="width: 100%"
            @change="onPublishPlatformChange"
          >
            <el-option
              v-for="platform in PLATFORM_OPTIONS"
              :key="platform.value"
              :label="platform.label"
              :value="platform.value"
            />
          </el-select>
        </el-form-item>

        <el-form-item label="发布账号">
          <el-select
            :key="publishForm.platform"
            v-model="publishForm.accountId"
            placeholder="请选择已授权账号"
            style="width: 100%"
            :loading="accountsLoading"
            :disabled="!publishForm.platform"
          >
            <el-option
              v-for="account in availablePublishAccounts"
              :key="account.id"
              :label="account.account_name || account.username || `账号 ${account.id}`"
              :value="account.id"
            >
              <div class="account-option">
                <span>{{ account.account_name || account.username || `账号 ${account.id}` }}</span>
                <el-tag size="small" type="success">可用</el-tag>
              </div>
            </el-option>
          </el-select>
          <div v-if="publishForm.platform && availablePublishAccounts.length === 0" class="publish-form-tip">
            当前平台暂无可用账号，请先在账号管理中完成授权。
          </div>
        </el-form-item>

        <el-form-item v-if="publishForm.mode === 'scheduled'" label="发布时间">
          <el-date-picker
            v-model="publishForm.scheduledTime"
            type="datetime"
            placeholder="选择发布时间"
            format="YYYY-MM-DD HH:mm"
            value-format="YYYY-MM-DDTHH:mm"
            :disabled-date="disabledPastDate"
            :disabled-hours="disabledPastHours"
            :disabled-minutes="disabledPastMinutes"
            style="width: 100%"
          />
        </el-form-item>
      </el-form>

      <template #footer>
        <el-button @click="showPublishDialog = false">取消</el-button>
        <el-button type="primary" :loading="submittingPublish" @click="submitPublish">
          {{ publishForm.mode === 'scheduled' ? '配置定时发布' : '立即发布' }}
        </el-button>
      </template>
    </el-dialog>

    <!-- 上传资料弹窗（复用客户管理的上传知识库样式） -->
    <el-dialog
      v-model="uploadDialogVisible"
      title="上传资料到知识库"
      width="600px"
    >
      <div class="upload-content">
        <el-alert
          title="资料上传说明"
          type="info"
          :closable="false"
          style="margin-bottom: 16px"
        >
          <p>支持的文件格式：PDF、Word、TXT、Markdown</p>
          <p>单个文件大小限制：10MB</p>
        </el-alert>

        <el-form :model="uploadForm" label-width="100px">
          <el-form-item label="公司名称">
            <el-input :value="uploadForm.companyName" disabled />
          </el-form-item>
          <el-form-item label="资料分类">
            <el-select v-model="uploadForm.category" placeholder="选择分类" style="width: 100%">
              <el-option label="公司资料" value="company" />
              <el-option label="产品文档" value="product" />
              <el-option label="行业报告" value="industry" />
              <el-option label="技术文档" value="technical" />
              <el-option label="其他" value="other" />
            </el-select>
          </el-form-item>
          <el-form-item label="文件上传">
            <el-upload
              ref="agentUploadRef"
              :auto-upload="false"
              :limit="5"
              :on-change="handleAgentFileChange"
              :on-exceed="handleAgentFileExceed"
              :file-list="agentFileList"
              drag
              multiple
            >
              <el-icon class="el-icon--upload"><UploadFilled /></el-icon>
              <div class="el-upload__text">
                将文件拖到此处，或<em>点击上传</em>
              </div>
              <template #tip>
                <div class="el-upload__tip">
                  支持扩展名：.pdf .doc .docx .txt .md
                </div>
              </template>
            </el-upload>
          </el-form-item>
          <el-form-item label="备注说明">
            <el-input
              v-model="uploadForm.description"
              type="textarea"
              :rows="3"
              placeholder="请输入资料备注说明（可选）"
            />
          </el-form-item>
        </el-form>
      </div>
      <template #footer>
        <el-button @click="uploadDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="uploading" @click="confirmAgentUpload">
          <el-icon><Upload /></el-icon>
          确认上传
        </el-button>
      </template>
    </el-dialog>

    <!-- ============ 添加账号弹窗 ============ -->
    <el-dialog
      v-model="addAccountDialogVisible"
      title="添加账号"
      width="500px"
      :close-on-click-modal="false"
    >
      <el-form label-width="80px">
        <el-form-item label="平台">
          <el-select v-model="addAccountForm.platform" placeholder="选择平台" style="width: 100%">
            <el-option
              v-for="p in addAccountPlatforms"
              :key="p.platform_id"
              :label="p.platform_name"
              :value="p.platform_id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="名称">
          <el-input v-model="addAccountForm.account_name" placeholder="备注名称 (如: 知乎大号)" />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="addAccountForm.remark" type="textarea" placeholder="选填" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="addAccountDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="confirmAddAccount">启动浏览器授权</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { UploadFile, UploadUserFile } from 'element-plus'
import MarkdownIt from 'markdown-it'
import {
  Box,
  Close,
  Delete,
  EditPen,
  Menu,
  MoreFilled,
  Paperclip,
  Plus,
  Promotion,
  Upload,
  UploadFilled,
  Document,
} from '@element-plus/icons-vue'
import { useRouter } from 'vue-router'
import { get, post, geoArticleApi } from '@/services/api'
import {
  accountApi,
  autoPublishApi,
  clientApi,
  type ConversationAction,
  type ConversationAttachment,
  type ConversationResult,
  type ConversationSessionItem,
} from '@/services/api'
import { getEnabledPlatforms, IMPLEMENTED_PLATFORM_IDS, PLATFORMS } from '@/core/config/platform'
import { defaultScheduleTime, disabledPastDate, disabledPastHours, disabledPastMinutes, isPastScheduleTime } from '@/utils/scheduleTime'
// Agent V2 SSE 客户端（流式响应）
import {
  sseClient,
  type SSEHandlers,
  getOnboarding,
  listSessions as v2ListSessions,
  getSession as v2GetSession,
  renameSession as v2RenameSession,
  archiveSession as v2ArchiveSession,
  deleteSession as v2DeleteSession,
} from '@/services/sse'
// 弹窗组件
import AgentListDialog from '@/components/agent/AgentListDialog.vue'
import AgentFormDialog from '@/components/agent/AgentFormDialog.vue'
import AgentSelectDialog from '@/components/agent/AgentSelectDialog.vue'

interface ChatMessage {
  id: string
  role: 'assistant' | 'user'
  content: string
  questions?: string[]
  // 文章生成完成后挂到气泡上的文章详情（id/title/content/preview…），用于在对话内展示并支持"去发布"直传。
  articles?: ArticlePreview[]
  actions?: ConversationAction[]
  attachments?: ConversationAttachment[]
  meta?: ConversationResult
}

// 气泡里挂的文章预览结构（只取后端 _convert_article_to_dict 关心的字段，按需扩展）
interface ArticlePreview {
  id: number
  title?: string
  content?: string
  publish_status?: string
  quality_status?: string
  platform?: string
  target_platforms?: string[]
}

const STORAGE_KEY = 'autogeo_agent_active_session'

const router = useRouter()
const inputText = ref('')
const sending = ref(false)
const loadingList = ref(false)
const loadingHistory = ref(false)
const clearingSessions = ref(false)
const messageListRef = ref<HTMLElement>()
const fileInputRef = ref<HTMLInputElement>()
const pendingAttachments = ref<ConversationAttachment[]>([])
const uploadActionTarget = ref<ConversationAction | null>(null)

// ============ 新手引导（确定性状态机，前端只负责渲染）============
interface OnboardingStep {
  key: string
  label: string
  done: boolean
}
interface OnboardingState {
  active: boolean
  dismissed: boolean
  completed: boolean
  checklist: OnboardingStep[]
  next_actions: ConversationAction[]
  optional_actions: ConversationAction[]
  can_skip: boolean
}

const onboarding = ref<OnboardingState | null>(null)
const onboardingActive = computed(() => !!onboarding.value?.active)
const onboardingNextCards = computed<ConversationAction[]>(() => onboarding.value?.next_actions ?? [])
const onboardingOptionalCards = computed<ConversationAction[]>(() => onboarding.value?.optional_actions ?? [])

// 引导流程严格按本会话内实际完成的动作推进；不依赖后端 DB 累计状态，
// 因此新会话不会被历史数据“带偏”，也不会跳步。
const ONBOARDING_STEP_ORDER = ['client', 'project', 'questions', 'articles', 'account', 'publish']
const ONBOARDING_STEP_LABELS: Record<string, string> = {
  client: '建客户',
  project: '建项目',
  questions: '规划问题',
  articles: '生成文章',
  account: '绑定发布账号',
  publish: '审核发布首篇',
}
// 前端卡片 action type → 引导步骤 key
const ONBOARDING_ACTION_TO_STEP: Record<string, string> = {
  show_client_form: 'client',
  show_project_form: 'project',
  generate_questions: 'questions',
  generate_articles: 'articles',
  show_add_account: 'account',
  show_article_list: 'publish',
}
// 后端工具名 → 引导步骤 key（从 SSE done.tool_results 提取）
const ONBOARDING_TOOL_TO_STEP: Record<string, string> = {
  create_client: 'client',
  create_project: 'project',
  generate_questions: 'questions',
  generate_articles: 'articles',
  bind_platform: 'account',
  publish_article: 'publish',
}

// 本会话已完成的引导步骤集合；新/空会话时重置。
const sessionProgress = ref<Set<string>>(new Set())
// 本会话是否已上传过资料（用于控制可选卡片的显隐，避免重复提示）
const sessionUploadDone = ref(false)
// 本会话内最新创建的客户信息，用于后续“新建项目/上传资料”自动带入公司。
const sessionLatestClient = ref<{ client_id: number; company_name: string } | null>(null)
// 本会话内最新创建的项目 ID，用于后续“生成问题/生成文章”自动带入选定项目。
const sessionLatestProject = ref<{ project_id: number } | null>(null)
const sessionDismissed = ref(false)
// 文章是否正在异步生成中：生成文章阶段需要等文章真正生成完成（publish_status=completed）
// 才推进到下一步（绑定账号），否则演示时文章还没出来引导就跳走了。期间引导卡显示"生成中"。
const sessionArticleGenerating = ref(false)

// 根据本会话进度生成引导状态；步骤严格按 ONBOARDING_STEP_ORDER 顺序解锁。
function buildSessionOnboarding(): OnboardingState {
  const completed = sessionProgress.value
  const checklist = ONBOARDING_STEP_ORDER.map((key) => ({
    key,
    label: ONBOARDING_STEP_LABELS[key],
    done: completed.has(key),
  }))
  const currentStep = ONBOARDING_STEP_ORDER.find((k) => !completed.has(k))

  const next_actions: ConversationAction[] = []
  const optional_actions: ConversationAction[] = []

  if (currentStep === 'client') {
    next_actions.push({ type: 'show_client_form', label: '新建客户', payload: {} })
  } else if (currentStep === 'project') {
    const projPayload: Record<string, unknown> = {}
    if (sessionLatestClient.value) {
      projPayload.client_id = sessionLatestClient.value.client_id
      projPayload.company_name = sessionLatestClient.value.company_name
    }
    next_actions.push({ type: 'show_project_form', label: '新建项目', payload: projPayload })
  } else if (currentStep === 'questions') {
    const qPayload: Record<string, unknown> = { count: 1 }
    if (sessionLatestProject.value) {
      qPayload.project_id = sessionLatestProject.value.project_id
    }
    next_actions.push({ type: 'generate_questions', label: '生成问题', payload: qPayload })
  } else if (currentStep === 'articles') {
    if (sessionArticleGenerating.value) {
      // 文章正在异步生成中：展示"生成中"占位卡（禁用+loading），不要给出"生成文章"下一步卡，
      // 否则演示时文章还没出来引导就跳到"绑定账号"了。生成完成后由轮询函数推进到下一步。
      next_actions.push({ type: 'article_generating', label: '文章生成中…', payload: {}, disabled: true })
    } else {
      const aPayload: Record<string, unknown> = { count: 1 }
      if (sessionLatestProject.value) {
        aPayload.project_id = sessionLatestProject.value.project_id
      }
      next_actions.push({ type: 'generate_articles', label: '生成文章', payload: aPayload })
    }
  } else if (currentStep === 'account') {
    const accountPayload: Record<string, unknown> = {
      platforms: IMPLEMENTED_PLATFORM_IDS.map((id) => ({
        platform_id: id,
        platform_name: PLATFORMS[id]?.name || id,
      })),
    }
    next_actions.push({ type: 'show_add_account', label: '绑定发布账号', payload: accountPayload })
  } else if (currentStep === 'publish') {
    next_actions.push({ type: 'show_article_list', label: '去发布', payload: {} })
  }

  // 可选：客户已建、项目未建、且本会话尚未上传过资料 → 提示一次“上传资料(可选)”
  if (completed.has('client') && !completed.has('project') && !sessionUploadDone.value) {
    const uploadPayload: Record<string, unknown> = {}
    if (sessionLatestClient.value) {
      uploadPayload.client_id = sessionLatestClient.value.client_id
      uploadPayload.company_name = sessionLatestClient.value.company_name
    }
    optional_actions.push({ type: 'upload_files', label: '上传资料(可选)', payload: uploadPayload })
  }

  const active = !sessionDismissed.value && !!currentStep
  return {
    active,
    dismissed: sessionDismissed.value,
    completed: !currentStep,
    can_skip: active,
    checklist,
    next_actions,
    optional_actions,
  }
}

// 用后端 onboarding 接口补充 action payload（如新建项目自动带 client_id、上传资料自动带客户信息），
// 但步骤顺序仍由前端本会话进度决定，避免被历史数据带偏。
async function buildSessionOnboardingWithPayloads(): Promise<OnboardingState> {
  const localState = buildSessionOnboarding()
  try {
    const backendState = (await getOnboarding()) as OnboardingState
    const backendActions = [...(backendState.next_actions ?? []), ...(backendState.optional_actions ?? [])]
    for (const localAct of [...localState.next_actions, ...localState.optional_actions]) {
      const backendAct = backendActions.find((a) => a.type === localAct.type)
      if (backendAct?.payload) {
        localAct.payload = { ...localAct.payload, ...(backendAct.payload as Record<string, unknown>) }
      }
    }
  } catch {
    // 后端异常时仍使用本地生成的无 payload 状态，保证引导不中断
  }
  return localState
}

// 重置本会话引导到初始状态（新/空会话入口调用）。
async function resetSessionOnboarding() {
  sessionProgress.value = new Set()
  sessionUploadDone.value = false
  sessionLatestClient.value = null
  sessionLatestProject.value = null
  sessionDismissed.value = false
  sessionArticleGenerating.value = false
  onboarding.value = await buildSessionOnboardingWithPayloads()
}

// 当前最新一条助手消息的索引；引导卡片渲染在该消息气泡内，避免再占用聊天区下方空间
const lastAssistantIndex = computed(() => {
  for (let i = messages.value.length - 1; i >= 0; i--) {
    if (messages.value[i].role === 'assistant') return i
  }
  return -1
})

async function loadOnboarding() {
  // 本会话引导完全由前端根据 tool_results 推进，不再用后端状态覆盖。
  // 保留本函数仅用于需要补充 payload 的场景（如异步任务完成后刷新 payloads）。
  try {
    const data = (await getOnboarding()) as OnboardingState
    const backendActions = [...(data.next_actions ?? []), ...(data.optional_actions ?? [])]
    if (!onboarding.value) {
      onboarding.value = buildSessionOnboarding()
    }
    for (const localAct of [...onboarding.value.next_actions, ...onboarding.value.optional_actions]) {
      const backendAct = backendActions.find((a) => a.type === localAct.type)
      if (backendAct?.payload) {
        localAct.payload = { ...localAct.payload, ...(backendAct.payload as Record<string, unknown>) }
      }
    }
  } catch (e) {
    // 引导接口异常不应阻断聊天；静默降级
  }
}

function dismissOnboardingFlow() {
  // 跳过引导仅影响当前会话，不再持久化到后端。
  sessionDismissed.value = true
  onboarding.value = buildSessionOnboarding()
  ElMessage.success('已跳过当前会话的引导')
}

// 生成类任务（问题规划同步、文章生成为后台异步）完成后可能需要刷新 action payload（如 project_id 关联）。
// 本会话的步骤推进由 SSE done.tool_results 完成，轮询只负责补充/更新 payloads。
let onboardingRefreshTimer: number | null = null
function scheduleOnboardingRefresh(rounds = 36, intervalMs = 5000) {
  if (onboardingRefreshTimer !== null) {
    clearTimeout(onboardingRefreshTimer)
    onboardingRefreshTimer = null
  }
  const tick = (n: number) => {
    if (n <= 0) {
      onboardingRefreshTimer = null
      return
    }
    onboardingRefreshTimer = window.setTimeout(async () => {
      await loadOnboarding()
      if (onboardingActive.value && !onboarding.value?.completed) {
        tick(n - 1)
      } else {
        onboardingRefreshTimer = null
      }
    }, intervalMs)
  }
  tick(rounds)
}

// ============ 文章生成异步完成轮询 ============
// 生成文章是后台异步任务（publish_status: generating → completed）。本会话引导要求文章真正生成完成
// 才推进到"绑定发布账号"步骤，否则演示时文章还没出来引导就跳走了。
// 思路：以"项目内 completed 文章数"为信号——轮询起点记录基线，当 completed 数量增加即判定生成完成。
// 完成后拉取文章详情（标题/正文），写到对应 assistant 气泡上让用户立即看到生成结果，
// 并让"去发布"卡片有真实数据可展示。
let articlePollTimer: number | null = null
async function countCompletedArticles(projectId: number): Promise<number> {
  try {
    const list = (await geoArticleApi.getArticles({ project_id: projectId })) as any[]
    return (list || []).filter((a) => a.publish_status === 'completed').length
  } catch (e) {
    console.warn('[onboarding] 文章列表查询异常:', e)
    return -1 // 异常标记，轮询里忽略本次
  }
}

async function fetchCompletedArticles(projectId: number): Promise<ArticlePreview[]> {
  try {
    const list = (await geoArticleApi.getArticles({ project_id: projectId })) as any[]
    return (list || [])
      .filter((a) => a.publish_status === 'completed')
      .map((a) => ({
        id: a.id,
        title: a.title,
        content: a.content,
        publish_status: a.publish_status,
        quality_status: a.quality_status,
        platform: a.platform,
        target_platforms: a.target_platforms,
      }))
  } catch (e) {
    console.warn('[onboarding] 文章详情获取失败:', e)
    return []
  }
}

// 文章生成完成后推进引导到"绑定账号"步骤；同步把文章详情挂到对应气泡上。
function finishArticleGeneration(bubbleId?: string, articles: ArticlePreview[] = []) {
  if (!sessionProgress.value.has('articles')) {
    sessionProgress.value.add('articles')
  }
  sessionArticleGenerating.value = false
  articlePollTimer !== null && clearTimeout(articlePollTimer)
  articlePollTimer = null
  // 把文章挂到发起生成的气泡上，让用户立即看到标题/正文预览，并让"去发布"有真实数据可走
  if (bubbleId && articles.length > 0) {
    const idx = messages.value.findIndex((m) => m.id === bubbleId)
    if (idx >= 0) {
      const cur = messages.value[idx]
      const titles = articles.map((a) => a.title || `文章#${a.id}`).join('、')
      const newContent = `✅ 文章已生成（${articles.length} 篇）：\n${articles
        .map((a, i) => `${i + 1}. 《${a.title || `文章#${a.id}`}》`)
        .join('\n')}\n\n标题：${titles}\n\n接下来请绑定发布账号，完成后即可一键发布。`
      messages.value[idx] = {
        ...cur,
        content: cur.content ? `${cur.content}\n\n${newContent}` : newContent,
        articles,
      }
      scrollToBottom()
    }
  }
  onboarding.value = buildSessionOnboarding()
  void loadOnboarding()
}

// 启动文章生成完成轮询。projectId 缺失（极端边界：本会话未走建项目）时，
// 无法精确判定，保守地直接推进到下一步，避免引导卡死。
// bubbleId 用于把生成结果回写到对应 assistant 气泡上。
function pollArticleGeneration(bubbleId?: string) {
  const projectId = sessionLatestProject.value?.project_id
  if (projectId == null) {
    console.warn('[onboarding] 未缓存 project_id，无法精确轮询文章生成，直接推进步骤')
    finishArticleGeneration(bubbleId, [])
    return
  }
  // 防重入：已在轮询中则不重复启动
  if (articlePollTimer !== null) return
  sessionArticleGenerating.value = true
  let rounds = 0
  const maxRounds = 72 // 72 * 5s = 6 分钟上限，超时保守推进，避免卡死
  const baselineP = countCompletedArticles(projectId)
  const tick = async () => {
    if (!sessionArticleGenerating.value) {
      // 已被重置/取消（如切换会话），停止轮询
      articlePollTimer = null
      return
    }
    rounds++
    if (rounds > maxRounds) {
      console.warn('[onboarding] 文章生成轮询超时，保守推进到下一步')
      finishArticleGeneration(bubbleId, [])
      return
    }
    const baseline = await baselineP
    const now = await countCompletedArticles(projectId)
    if (now > baseline) {
      const articles = await fetchCompletedArticles(projectId)
      finishArticleGeneration(bubbleId, articles)
      return
    }
    articlePollTimer = window.setTimeout(tick, 5000)
  }
  articlePollTimer = window.setTimeout(tick, 3000)
}

// ============ 文章列表定制弹窗 & 发布流程状态 ============
const articleListDialogVisible = ref(false)
const articleListFilter = ref({
  projectId: null as number | null,
  page: 1,
  limit: 10,
  projectOptions: [] as { id: number; name: string }[],
})
const articleListData = ref({
  items: [] as any[],
  total: 0,
  loading: false,
})

// ==================== 发布对话框状态（与文章管理页一致） ====================
const showPublishDialog = ref(false)
const publishArticle = ref<any>(null)
const accounts = ref<any[]>([])
const accountsLoading = ref(false)
const submittingPublish = ref(false)
const publishForm = ref({
  mode: 'immediate' as 'immediate' | 'scheduled',
  platform: '',
  accountId: null as number | null,
  scheduledTime: '',
})
const PLATFORM_OPTIONS = getEnabledPlatforms()
  .filter(platform => platform.features?.article)
  .map(platform => ({ label: platform.name, value: platform.id }))
const availablePublishAccounts = computed(() => {
  if (!publishForm.value.platform) return []
  return accounts.value.filter(account =>
    account.platform === publishForm.value.platform && Number(account.status) === 1
  )
})

// 弹窗状态管理
const listDialogVisible = ref(false)
const listDialogConfig = ref({
  title: '',
  items: [] as any[],
  columns: [] as any[],
  total: 0,
  loading: false,
  showActions: true,
  onSelect: null as ((item: any) => void) | null,
})

const formDialogVisible = ref(false)
const formDialogConfig = ref({
  title: '',
  fields: [] as any[],
  initialValues: {} as any,
  submitText: '确认',
  submitting: false,
  onSubmit: null as ((data: any) => void) | null,
})

const selectDialogVisible = ref(false)
const selectDialogConfig = ref({
  title: '',
  items: [] as any[],
  defaultValue: null as any,
  onSelect: null as ((item: any) => void) | null,
})

// 上传资料弹窗状态
const uploadDialogVisible = ref(false)
const uploading = ref(false)
const agentUploadRef = ref()
const agentFileList = ref<UploadUserFile[]>([])
const uploadForm = ref({
  companyName: '',
  clientId: null as number | null,
  category: '',
  description: '',
})

// 添加账号弹窗状态
const addAccountDialogVisible = ref(false)
const addAccountPlatforms = ref<any[]>([])
const addAccountForm = ref({
  platform: 'zhihu',
  account_name: '',
  remark: '',
})

// Markdown 渲染器（智能体回复用）
const md = new MarkdownIt({ html: false, linkify: true, breaks: true })
function renderMarkdown(content: string): string {
  if (!content) return ''
  // 已经是 HTML 的不再渲染
  if (content.trimStart().startsWith('<')) return content
  return md.render(content)
}

const sessions = ref<ConversationSessionItem[]>([])
const activeSessionId = ref('')
const sidebarOpen = ref(false)
const messages = ref<ChatMessage[]>([initialWelcome()])

const activeSessionTitle = computed(() => {
  if (!activeSessionId.value) return ''
  return sessions.value.find((s) => s.id === activeSessionId.value)?.title || ''
})

function welcomeMessage(): ChatMessage {
  return {
    id: 'welcome',
    role: 'assistant',
    content: `你好，我是 **AutoGEO 智能体**，你的 GEO 内容生成与发布助手。

我能帮你把企业的品牌信息，自动整理成可在知乎、百家号、今日头条等平台发布的文章，并持续追踪 AI 搜索里有没有提到你的品牌。

**新手建议按这 7 步走：**

1. **建客户** — 录入企业名称、行业、官网等基础信息  
2. **上传企业资料（可选）** — 上传官网/产品手册，让内容更贴合企业  
3. **建项目** — 为这个品牌创建一个内容主题项目  
4. **规划问题** — AI 根据项目生成用户可能搜索的问题清单  
5. **生成文章** — 批量生成针对这些问题的 GEO 文章  
6. **绑定账号** — 添加知乎/百家号/今日头条等发布账号  
7. **审核发布** — 检查文章并一键发布到已绑定的平台`,
  }
}

// 每个新会话都从完整 7 步引导开始；引导状态是会话级，不跨会话持久化。
function initialWelcome(): ChatMessage {
  return welcomeMessage()
}

function fillPrompt(text: string) {
  inputText.value = text
}

// 输入框键盘行为：Enter（含 Ctrl/Cmd+Enter）直接发送，Shift+Enter 换行；
// 输入法组合输入中（如拼音选词的回车）不拦截，避免误发消息。
// Element Plus 的 keydown 会透传原生事件，参数声明为更宽的联合类型再断言。
function onComposerKeydown(e: Event | KeyboardEvent) {
  const ev = e as KeyboardEvent
  if (ev.isComposing) return
  if (ev.key !== 'Enter') return
  if (ev.shiftKey) return // Shift+Enter → 保留默认换行
  ev.preventDefault()
  sendMessage()
}

function useQuestion(question: string | Record<string, any>) {
  // 兼容字符串数组与对象数组（后端 generate_questions 返回 {id, question, ...}）
  const text = typeof question === 'string' ? question : (question.question || question.q || '')
  if (text) inputText.value = text
}

// ==================== 附件上传 ====================
function triggerAttach(action?: ConversationAction) {
  uploadActionTarget.value = action || null
  fileInputRef.value?.click()
}

async function onFilePicked(e: Event) {
  const target = e.target as HTMLInputElement
  const files = target.files
  if (!files || !files.length) {
    uploadActionTarget.value = null
    return
  }
  const file = files[0]
  target.value = '' // 允许重复选同一文件

  // 普通资料：上传到通用 /api/upload 暂存，拿到 ref；正式入 RAGFlow 知识库由 Agent 处理
  const formData = new FormData()
  formData.append('file', file)
  try {
    const res = await post<{ url: string }>('/upload', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 300000,
    })
    const targetPayload = uploadActionTarget.value?.payload ?? {}
    pendingAttachments.value.push({
      ref: res.url,
      filename: file.name,
      kind: 'material',
      client_id: targetPayload.client_id,
      company_name: targetPayload.company_name,
    })
    ElMessage.success(`已添加附件：${file.name}`)
    if (uploadActionTarget.value) {
      const action = uploadActionTarget.value
      uploadActionTarget.value = null
      await sendMessage('上传公司资料', action)
    }
  } catch {
    ElMessage.error('附件上传失败')
    uploadActionTarget.value = null
  }
}

// ==================== 通用工具函数 ====================
function formatDate(v: any): string {
  if (!v) return '-'
  const d = new Date(v)
  if (isNaN(d.getTime())) return String(v)
  const pad = (n: number) => n.toString().padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

function statusTagType(s: string): 'success' | 'warning' | 'danger' | 'info' | undefined {
  switch (s) {
    case 'published': return 'success'
    case 'completed': return 'info'
    case 'draft': return undefined
    case 'generating':
    case 'scheduled':
    case 'publishing': return 'warning'
    case 'failed': return 'danger'
    default: return 'info'
  }
}

function canPublish(row: any): boolean {
  if (!row) return false
  const s = row.publish_status
  // 已发布/发布中 不允许重复发布（用户可选重试，但这里按钮禁用）
  if (s === 'published' || s === 'publishing') return false
  return true
}

// ==================== 文章列表弹窗：加载数据（直接调用 REST API，不发消息到对话框）====================
async function reloadArticleList(page: number) {
  articleListFilter.value.page = page
  const projectId = articleListFilter.value.projectId

  articleListData.value.loading = true
  try {
    // 静默调用 REST API，不在对话框中产生消息
    const res: any = await get('/articles', {
      page: articleListFilter.value.page,
      limit: articleListFilter.value.limit,
      ...(projectId ? { project_id: projectId } : {}),
    }, { silent: true })

    const items = Array.isArray(res?.items) ? res.items : []
    const total = Number(res?.total || items.length)

    // 为每篇文章补充前端需要的字段
    const enrichedItems = items.map((a: any) => {
      const statusLabelMap: Record<string, string> = {
        draft: '草稿', generating: '生成中', completed: '待发布',
        scheduled: '已排期', publishing: '发布中', published: '已发布', failed: '发布失败',
      }
      const ps = a.publish_status || 'completed'
      return {
        id: a.id,
        title: a.title || '（无标题）',
        project_id: a.project_id,
        project_name: a.project_name || '-',
        publish_status: ps,
        publish_status_label: statusLabelMap[ps] || '待发布',
        created_at: a.created_at,
      }
    })

    articleListData.value = { items: enrichedItems, total, loading: false }
  } catch {
    articleListData.value = { items: [], total: 0, loading: false }
  }
}

// 加载项目列表（用于文章弹窗的项目筛选下拉框）
async function loadArticleProjectOptions() {
  try {
    const res: any = await get('/clients/projects', {}, { silent: true })
    const items = Array.isArray(res?.items) ? res.items : (Array.isArray(res) ? res : [])
    articleListFilter.value.projectOptions = items.map((p: any) => ({
      id: p.id,
      name: p.name || `项目${p.id}`,
    }))
  } catch {
    // 静默失败
  }
}

// 应用 action 中的文章列表数据到弹窗
function applyArticleListPayload(payload: any) {
  const items = Array.isArray(payload.items) ? payload.items : []
  const total = Number(payload.total || items.length)
  const projectOptions = Array.isArray(payload.project_options)
    ? payload.project_options
    : articleListFilter.value.projectOptions
  articleListFilter.value.projectOptions = projectOptions
  if (payload.project_id != null) {
    articleListFilter.value.projectId = Number(payload.project_id) || null
  }
  if (payload.page) articleListFilter.value.page = Number(payload.page)
  if (payload.limit) articleListFilter.value.limit = Number(payload.limit)
  articleListData.value = { items, total, loading: false }
}

// 用户点击"去发布"（新手引导卡）且后端没带 items 时，主动按项目拉文章填充弹窗。
// 否则用户只会看到空列表（之前 issue：生成文章完成 → 卡片"去发布" → 弹窗"共 0 条"）。
async function fetchArticlesForDialog(projectId: number) {
  articleListData.value = { ...articleListData.value, loading: true }
  try {
    const list = (await geoArticleApi.getArticles({ project_id: projectId })) as any[]
    const items = Array.isArray(list) ? list : []
    articleListData.value = { items, total: items.length, loading: false }
  } catch (e) {
    console.warn('[去发布] 文章列表拉取失败:', e)
    articleListData.value = { items: [], total: 0, loading: false }
    ElMessage.warning('文章列表加载失败，请稍后重试')
  }
}

// 截断文章正文预览（去掉 Markdown/HTML 标记，避免气泡里出现一堆星号或尖括号）
function truncatePreview(content: string, max: number): string {
  if (!content) return ''
  const cleaned = String(content).replace(/[#>*_`~\-]/g, ' ').replace(/\s+/g, ' ').trim()
  return cleaned.length > max ? cleaned.slice(0, max) + '…' : cleaned
}

// 在气泡内点"去发布"：直接打开文章列表弹窗并定位到当前文章
function openArticleListFromPreview(art: ArticlePreview) {
  const projId = (art as any).project_id || sessionLatestProject.value?.project_id
  articleListDialogVisible.value = true
  if (projId != null) {
    articleListFilter.value.projectId = Number(projId)
    void fetchArticlesForDialog(Number(projId))
  } else {
    void fetchArticlesForDialog(0 as any) // 不带项目时取全量
  }
  // 兜底：若弹窗已经有数据，确保把当前文章放在列表第一项（点击行可直接打开发布）
  const list = articleListData.value.items
  if (art && art.id && Array.isArray(list) && !list.some((it: any) => it.id === art.id)) {
    articleListData.value = {
      ...articleListData.value,
      items: [art, ...list],
      total: list.length + 1,
    }
  }
}

// 复制文章正文到剪贴板（兼容 Clipboard API 与降级 execCommand）
async function copyArticleContent(art: ArticlePreview) {
  const text = art.content || art.title || `文章 #${art.id}`
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text)
    } else {
      const ta = document.createElement('textarea')
      ta.value = text
      document.body.appendChild(ta)
      ta.select()
      document.execCommand('copy')
      document.body.removeChild(ta)
    }
    ElMessage.success('已复制到剪贴板')
  } catch (e) {
    console.warn('[文章] 复制失败:', e)
    ElMessage.error('复制失败，请手动复制')
  }
}

// ==================== 发布逻辑（与文章管理页完全一致） ====================
function normalizeListResponse(res: any) {
  if (Array.isArray(res)) return res
  if (Array.isArray(res?.data)) return res.data
  if (Array.isArray(res?.data?.items)) return res.data.items
  if (Array.isArray(res?.items)) return res.items
  return []
}
async function loadAccounts() {
  accountsLoading.value = true
  try {
    accounts.value = normalizeListResponse(await accountApi.getList({ status: 1 }))
  } catch (error) {
    console.error('加载账号失败:', error)
    accounts.value = []
  } finally {
    accountsLoading.value = false
  }
}
function getAccountById(accountId: number | null) {
  if (!accountId) return null
  return accounts.value.find(account => account.id === accountId) || null
}
function pickAccountForPlatform(platform: string, preferredAccountId?: number | null) {
  const platformAccounts = accounts.value.filter(account =>
    account.platform === platform && Number(account.status) === 1
  )
  if (!platformAccounts.length) return null
  const preferred = preferredAccountId
    ? platformAccounts.find(account => account.id === preferredAccountId)
    : null
  return preferred?.id || platformAccounts[0].id
}
function getDefaultPlatform(article: any) {
  const row = article || {}
  if (row.platform) return row.platform
  if (Array.isArray(row.target_platforms) && row.target_platforms.length > 0) {
    return row.target_platforms[0]
  }
  const firstAvailableAccount = accounts.value.find(account => Number(account.status) === 1)
  return firstAvailableAccount?.platform || PLATFORM_OPTIONS[0]?.value || ''
}
function getElectronServerBaseUrl() {
  const configured = import.meta.env.VITE_API_BASE_URL || ''
  if (!configured || configured.startsWith('/')) return undefined
  return configured.replace(/\/api\/?$/, '').replace(/\/+$/, '')
}
async function ensureLocalPublishEngineStarted() {
  if (!window.electronAPI?.publishEngine?.start) {
    throw new Error('请在 AutoGEO 客户端中执行本地发布')
  }
  const token = localStorage.getItem('autogeo_token') || ''
  if (!token) throw new Error('本地发布需要先登录')
  const result = await window.electronAPI.publishEngine.start(token, getElectronServerBaseUrl(), 2000)
  if (!result?.success) throw new Error(result?.error || '本地发布引擎启动失败')
}
function openPublishDialog(article: any) {
  if (!article || !article.id) {
    ElMessage.warning('文章信息不完整，请稍后重试')
    return
  }
  // 网页端无法拉取浏览器，直接提示使用客户端
  if (!window.electronAPI?.publishEngine?.start) {
    ElMessageBox.alert(
      '发布文章需要启动本地浏览器，请在 AutoGEO 客户端中执行本地发布。',
      '需要桌面客户端',
      { type: 'info', confirmButtonText: '知道了' }
    )
    return
  }
  publishArticle.value = article
  if (accounts.value.length === 0) loadAccounts()
  const row = article || {}
  const platform = getDefaultPlatform(article)
  publishForm.value = {
    mode: article?.publish_status === 'scheduled' ? 'scheduled' : 'immediate',
    platform,
    accountId: pickAccountForPlatform(platform, row.account_id),
    scheduledTime: article?.publish_status === 'scheduled' ? defaultScheduleTime() : '',
  }
  showPublishDialog.value = true
}
function onPublishPlatformChange() {
  publishForm.value.accountId = pickAccountForPlatform(publishForm.value.platform)
}
async function submitPublish() {
  if (submittingPublish.value || !publishArticle.value) return
  if (!publishForm.value.platform) return ElMessage.warning('请选择发布平台')
  if (!publishForm.value.accountId) return ElMessage.warning('请选择发布账号')
  if (publishForm.value.mode === 'scheduled' && !publishForm.value.scheduledTime) {
    return ElMessage.warning('请选择发布时间')
  }
  if (
    publishForm.value.mode === 'scheduled' &&
    publishForm.value.scheduledTime &&
    isPastScheduleTime(publishForm.value.scheduledTime)
  ) {
    return ElMessage.warning('定时发布时间必须晚于当前时间')
  }

  const accountId = publishForm.value.accountId
  const selectedAccount = getAccountById(accountId)
  if (!selectedAccount || selectedAccount.platform !== publishForm.value.platform) {
    publishForm.value.accountId = pickAccountForPlatform(publishForm.value.platform)
    return ElMessage.warning('发布账号与发布平台不匹配，已为你切换到当前平台的可用账号')
  }

  submittingPublish.value = true
  try {
    const payload = { article_ids: [publishArticle.value.id], account_ids: [accountId] }
    if (publishForm.value.mode === 'scheduled') {
      await autoPublishApi.create({
        name: `定时发布-${publishArticle.value.title || publishArticle.value.id}`,
        article_ids: payload.article_ids,
        account_ids: payload.account_ids,
        exec_type: 'scheduled',
        scheduled_at: publishForm.value.scheduledTime,
        execution_mode: 'local_client',
      })
      await ensureLocalPublishEngineStarted()
      ElMessage.success('定时发布已配置，将在设定时间由本地客户端自动执行')
    } else {
      await autoPublishApi.create({
        name: `立即发布-${publishArticle.value.title || publishArticle.value.id}`,
        article_ids: payload.article_ids,
        account_ids: payload.account_ids,
        exec_type: 'immediate',
        execution_mode: 'local_client',
      })
      await ensureLocalPublishEngineStarted()
      ElMessage.success('本地发布任务已创建，客户端正在执行')
    }
    showPublishDialog.value = false
    reloadArticleList(articleListFilter.value.page)
  } catch (error) {
    console.error('提交发布失败:', error)
    ElMessage.error((error as any)?.message || '提交发布失败')
  } finally {
    submittingPublish.value = false
  }
}

// ==================== 添加账号 ====================
async function confirmAddAccount() {
  const form = addAccountForm.value
  if (!form.platform) {
    ElMessage.warning('请选择平台')
    return
  }
  if (!form.account_name) {
    form.account_name = `${form.platform}账号`
  }
  addAccountDialogVisible.value = false
  const platformName = addAccountPlatforms.value.find(p => p.platform_id === form.platform)?.platform_name || form.platform
  await sendMessage(
    `绑定${platformName}平台账号，名称为${form.account_name}`,
    {
      type: 'bind_platform',
      label: `绑定${platformName}`,
      payload: { platform: form.platform, account_name: form.account_name },
    } as any,
  )
}

// ==================== 弹窗处理函数 ====================
function handleListSelect(item: any) {
  if (listDialogConfig.value.onSelect) {
    listDialogConfig.value.onSelect(item)
  }
}

function handlePageChange(page: number, size: number) {
  // 分页变化时重新加载数据（由具体业务实现）
  console.log('Page changed:', page, size)
}

function handleFormSubmit(data: any) {
  if (formDialogConfig.value.onSubmit) {
    formDialogConfig.value.onSubmit(data)
  }
}

function handleSelectConfirm(item: any) {
  if (selectDialogConfig.value.onSelect) {
    selectDialogConfig.value.onSelect(item)
  }
}

// ==================== 动作卡片 ====================
function actionBtnType(type: string) {
  if (type === 'confirm') return 'success'
  if (type === 'cancel') return 'info'
  if (type === 'dismiss_onboarding') return 'info'
  if (type === 'bind') return 'warning'
  return 'primary'
}

function displayActions(item: ChatMessage): ConversationAction[] {
  // 引导期间只展示统一引导卡片，屏蔽工具自带建议（避免与下一步卡片重复/干扰）
  if (onboardingActive.value) return []
  const actions = item.actions ?? []
  const seen = new Set<string>()
  return actions.filter((act) => {
    const key = `${act.type}:${act.label}:${JSON.stringify(act.payload ?? {})}:${act.link ?? ''}`
    if (seen.has(key)) return false
    seen.add(key)
    return true
  })
}

async function onAction(act: ConversationAction) {
  // 跳过新手引导：仅影响当前会话，不再发消息给后端。
  if (act.type === 'dismiss_onboarding') {
    dismissOnboardingFlow()
    return
  }
  // 选择候选客户：把完整 payload 作为 action 回传后端，由后端直接对该客户入库
  if (act.type === 'select_client') {
    await sendMessage(act.label, act)
    return
  }
  if (act.type === 'upload') {
    triggerAttach(act)
    return
  }
  // V2 无独立 confirm/cancel 端点，规则短路能识别"确认/取消"
  if (act.type === 'confirm') {
    await sendMessage('确认')
    return
  }
  if (act.type === 'cancel') {
    await sendMessage('取消')
    return
  }
  
  // ==================== 新弹窗处理逻辑 ====================
  // 显示客户列表弹窗
  if (act.type === 'show_client_list') {
    const payload = act.payload || {}
    listDialogConfig.value = {
      title: '客户列表',
      items: payload.items || [],
      columns: [
        { prop: 'id', label: 'ID', width: 80 },
        { prop: 'company_name', label: '公司名称' },
        { prop: 'industry', label: '行业' },
        { prop: 'location', label: '所在地' },
      ],
      total: payload.total || 0,
      loading: false,
      showActions: true,
      onSelect: (item) => {
        sendMessage(`选择客户 ${item.company_name}`, { type: 'select_client', label: item.company_name, payload: { client_id: item.id } }, true)
      },
    }
    listDialogVisible.value = true
    return
  }
  
  // 显示项目列表弹窗
  if (act.type === 'show_project_list') {
    const payload = act.payload || {}
    listDialogConfig.value = {
      title: '项目列表',
      items: payload.items || [],
      columns: [
        { prop: 'id', label: 'ID', width: 80 },
        { prop: 'name', label: '项目名称' },
        { prop: 'client_name', label: '关联客户' },
        { prop: 'industry', label: '行业' },
      ],
      total: payload.total || 0,
      loading: false,
      showActions: true,
      onSelect: (item) => {
        sendMessage(`选择项目 ${item.name}`, { type: 'select_project', label: item.name, payload: { project_id: item.id } }, true)
      },
    }
    listDialogVisible.value = true
    return
  }

  // 显示问题列表弹窗
  if (act.type === 'show_question_list') {
    const payload = act.payload || {}
    listDialogConfig.value = {
      title: '问题列表',
      items: payload.items || [],
      columns: [
        { prop: 'id', label: 'ID', width: 80 },
        { prop: 'question', label: '问题内容' },
        { prop: 'project_name', label: '项目' },
        { prop: 'client_name', label: '客户' },
        { prop: 'article_generation_status', label: '文章状态' },
        { prop: 'created_at', label: '创建时间' },
      ],
      total: payload.total || 0,
      loading: false,
      showActions: true,
      onSelect: (item) => {
        sendMessage(`查看问题详情：${item.question}`, { type: 'select_question', label: item.question, payload: { question_id: item.id } }, true)
      },
    }
    listDialogVisible.value = true
    return
  }

  // 显示绑定平台列表弹窗
  if (act.type === 'show_binding_list') {
    const payload = act.payload || {}
    const items = (payload.items || []).map((it: any) => ({
      ...it,
      status_text: it.invalid_reason || (it.session_valid ? '正常' : '登录失效'),
    }))
    listDialogConfig.value = {
      title: '绑定平台列表',
      items,
      columns: [
        { prop: 'platform_name', label: '平台' },
        { prop: 'account_name', label: '账号' },
        { prop: 'status_text', label: '状态' },
      ],
      total: payload.total || 0,
      loading: false,
      showActions: false,
      onSelect: null,
    }
    listDialogVisible.value = true
    return
  }

  // 定制化：文章列表弹窗（带项目筛选、分页、去发布按钮）
  if (act.type === 'show_article_list') {
    const payload = act.payload || {}
    // 应用/更新数据
    applyArticleListPayload(payload)
    // 如果项目选项为空，加载项目列表
    if (articleListFilter.value.projectOptions.length === 0) {
      loadArticleProjectOptions()
    }
    // payload 没带 items 时（典型：用户点击新手引导里的"去发布"卡）→ 主动拉取当前项目的文章。
    // 否则弹窗会一直显示 0 条，用户看不到刚生成好的文章。
    if (!Array.isArray(payload.items) || payload.items.length === 0) {
      const projId = payload.project_id || sessionLatestProject.value?.project_id
      if (projId != null) {
        articleListFilter.value.projectId = Number(projId)
        void fetchArticlesForDialog(projId)
      }
    }
    // 打开弹窗（如果之前已经打开，则仅刷新数据）
    articleListDialogVisible.value = true
    return
  }

  // 添加账号弹窗
  if (act.type === 'show_add_account') {
    const payload = act.payload || {}
    addAccountPlatforms.value =
      payload.platforms ||
      IMPLEMENTED_PLATFORM_IDS.map((id) => ({
        platform_id: id,
        platform_name: PLATFORMS[id]?.name || id,
      }))
    const defaultPlatform = (addAccountPlatforms.value[0]?.platform_id as string) || 'zhihu'
    const defaultName = (addAccountPlatforms.value[0]?.platform_name as string) || defaultPlatform
    addAccountForm.value = {
      platform: defaultPlatform,
      account_name: `${defaultName}账号`,
      remark: '',
    }
    addAccountDialogVisible.value = true
    return
  }

  // 选择平台弹窗（绑定平台时 LLM 无法确定平台，弹出选择）
  if (act.type === 'select_platform') {
    const payload = act.payload || {}
    const platforms =
      payload.platforms ||
      IMPLEMENTED_PLATFORM_IDS.map((id) => ({
        platform_id: id,
        platform_name: PLATFORMS[id]?.name || id,
      }))
    if (platforms.length > 0) {
      // 复用添加账号弹窗，展示完整平台列表
      addAccountPlatforms.value = platforms
      const defaultPlatform = (platforms[0]?.platform_id as string) || 'zhihu'
      const defaultName = (platforms[0]?.platform_name as string) || defaultPlatform
      addAccountForm.value = {
        platform: defaultPlatform,
        account_name: `${defaultName}账号`,
        remark: '',
      }
      addAccountDialogVisible.value = true
    }
    return
  }

  // 显示客户表单弹窗
  if (act.type === 'show_client_form') {
    formDialogConfig.value = {
      title: '新建客户',
      fields: [
        { prop: 'company_name', label: '公司名称', type: 'input', required: true },
        { prop: 'industry', label: '所属行业', type: 'input', required: true },
        { prop: 'location', label: '所在地', type: 'input', required: true },
        { prop: 'website', label: '公司官网', type: 'input', required: true },
        { prop: 'contact_person', label: '联系人', type: 'input' },
        { prop: 'phone', label: '联系电话', type: 'input' },
        { prop: 'email', label: '邮箱', type: 'input' },
      ],
      initialValues: {},
      submitText: '创建',
      submitting: false,
      onSubmit: async (data) => {
        formDialogConfig.value.submitting = true
        try {
          await sendMessage(`创建客户，公司名称是${data.company_name}，行业是${data.industry}，所在地是${data.location}，官网是${data.website}`, act, true)
          formDialogVisible.value = false
        } finally {
          formDialogConfig.value.submitting = false
        }
      },
    }
    formDialogVisible.value = true
    return
  }
  
  // 显示项目表单弹窗
  if (act.type === 'show_project_form') {
    const payload = act.payload || {}
    const clientId = payload.client_id
    const companyName = payload.company_name || ''
    
    formDialogConfig.value = {
      title: '新建项目',
      fields: [
        { prop: 'name', label: '项目名称', type: 'input', required: true },
        { prop: 'domain_keyword', label: '领域关键词', type: 'input', required: true, placeholder: '用于AI蒸馏生成用户提问句' },
        { prop: 'company_name', label: '所属公司', type: 'input', disabled: true },
        { prop: 'industry', label: '行业', type: 'input' },
        { prop: 'description', label: '项目描述', type: 'textarea' },
      ],
      initialValues: {
        company_name: companyName,
      },
      submitText: '创建',
      submitting: false,
      onSubmit: async (data) => {
        formDialogConfig.value.submitting = true
        try {
          await sendMessage(`创建项目，项目名称是${data.name}，领域关键词是${data.domain_keyword}，关联客户ID是${clientId}`, act, true)
          formDialogVisible.value = false
        } finally {
          formDialogConfig.value.submitting = false
        }
      },
    }
    formDialogVisible.value = true
    return
  }
  
  // 显示 AI 平台选择弹窗
  if (act.type === 'select_ai_platform') {
    const payload = act.payload || {}
    selectDialogConfig.value = {
      title: '选择 AI 平台',
      items: [
        { value: 'doubao', label: '豆包', description: '字节跳动 AI 助手' },
        { value: 'qianwen', label: '通义千问', description: '阿里巴巴 AI 助手' },
        { value: 'deepseek', label: 'DeepSeek', description: '深度求索 AI 助手' },
      ],
      defaultValue: null,
      onSelect: (item) => {
        sendMessage(`选择 AI 平台 ${item.label}`, { type: 'select_ai_platform', label: item.label, payload: { platform: item.value } }, true)
      },
    }
    selectDialogVisible.value = true
    return
  }
  
  // 显示诊断指标卡片
  if (act.type === 'show_diagnosis') {
    const payload = act.payload || {}
    const metrics = payload.metrics || {}
    const baseline = payload.baseline || {}

    // 这里可以弹出一个指标卡片弹窗，或者直接在消息中展示
    // 暂时先发送消息让 Agent 处理
    await sendMessage(`查看诊断指标`, act)
    return
  }

  // 上传资料弹窗
  if (act.type === 'upload_files') {
    const payload = act.payload || {}
    const clientId = payload.client_id
    const companyName = payload.company_name || ''

    // 重置表单
    uploadForm.value = {
      companyName,
      clientId: clientId || null,
      category: '',
      description: '',
    }
    agentFileList.value = []
    uploading.value = false

    uploadDialogVisible.value = true
    return
  }
  
  // ==================== 原有逻辑 ====================
  // 跳转到链接（如账号绑定页）
  if (act.link) {
    router.push(act.link)
    return
  }
  const promptConfig = actionInputPrompt(act)
  if (promptConfig) {
    await sendActionInput(act, promptConfig)
    return
  }
  // 生成问题：直接带上 project_id 发送
  if (act.type === 'generate_questions') {
    const payload = act.payload || {}
    const projectId = payload.project_id
    await sendMessage(`为项目生成用户问题`, act)
    return
  }
  // 生成文章：直接带上 project_id / question_id 等发送，走 generate_articles 工具（via_agent）
  if (act.type === 'generate_articles') {
    await sendMessage(act.label, act)
    return
  }

  // 其余动作（onboard/create/next/upload/clarify/bind 无 link）：把按钮文案作为消息发给 Agent 自然处理
  await sendMessage(act.label)
}

function actionInputPrompt(act: ConversationAction): { title: string; placeholder: string; messageBuilder: (value: string) => string } | null {
  const label = act.label || ''
  const payload = act.payload ?? {}
  if (act.type === 'create' && label.includes('客户')) {
    return {
      title: '创建客户',
      placeholder: '请输入公司或客户名称',
      messageBuilder: (value) => `创建客户，公司名称是${value}`,
    }
  }
  if (
    label.includes('建项目')
    || label.includes('创建项目')
    || (act.type === 'create' && label.includes('项目'))
  ) {
    const company = payload.company_name || payload.client_name
    return {
      title: '创建项目',
      placeholder: '请输入项目名称',
      messageBuilder: (value) => (
        company
          ? `为${company}创建项目，项目名称是${value}`
          : `创建项目，项目名称是${value}`
      ),
    }
  }
  return null
}

async function sendActionInput(
  act: ConversationAction,
  promptConfig: { title: string; placeholder: string; messageBuilder: (value: string) => string },
) {
  try {
    const { value } = await ElMessageBox.prompt('', promptConfig.title, {
      inputPlaceholder: promptConfig.placeholder,
      inputValidator: (v: string) => (v && v.trim().length > 0) || promptConfig.placeholder,
      confirmButtonText: '确认',
      cancelButtonText: '取消',
      autofocus: true,
      customClass: 'agent-action-prompt',
    })
    await sendMessage(promptConfig.messageBuilder(value.trim()), act)
  } catch {
    // 用户取消，忽略
  }
}

// ==================== 上传资料弹窗处理 ====================

function handleAgentFileChange(file: UploadFile, uploadFiles: UploadUserFile[]) {
  const allowedTypes = ['pdf', 'doc', 'docx', 'txt', 'md']
  const ext = file.name.split('.').pop()?.toLowerCase()
  if (!ext || !allowedTypes.includes(ext)) {
    ElMessage.error('不支持的文件格式，请上传 PDF、Word、TXT 或 Markdown 文件')
    agentFileList.value = uploadFiles.filter((item) => item.uid !== file.uid)
    return false
  }
  if ((file.size || 0) > 10 * 1024 * 1024) {
    ElMessage.error('文件大小不能超过 10MB')
    agentFileList.value = uploadFiles.filter((item) => item.uid !== file.uid)
    return false
  }
  agentFileList.value = uploadFiles
  return true
}

function handleAgentFileExceed() {
  ElMessage.warning('最多只能上传 5 个文件')
}

async function confirmAgentUpload() {
  if (!uploadForm.value.clientId) {
    ElMessage.warning('缺少客户ID，请先选择客户')
    return
  }
  if (agentFileList.value.length === 0) {
    ElMessage.warning('请至少选择一个文件')
    return
  }
  if (!uploadForm.value.category) {
    ElMessage.warning('请选择资料分类')
    return
  }

  uploading.value = true
  try {
    const formData = new FormData()
    formData.append('client_id', String(uploadForm.value.clientId))
    formData.append('category', uploadForm.value.category)
    formData.append('description', uploadForm.value.description)

    agentFileList.value.forEach((file: any) => {
      formData.append('files', file.raw)
    })

    const response = await clientApi.uploadFiles(formData)
    const result = response.data || {}

    if (response.success) {
      const successCount = result.success_count ?? result.uploaded?.length ?? agentFileList.value.length
      const failedCount = result.failed_count ?? result.failed?.length ?? 0
      if (failedCount > 0) {
        ElMessage.warning(`上传完成：成功 ${successCount} 个，失败 ${failedCount} 个`)
      } else {
        ElMessage.success(`成功上传 ${successCount} 个文件`)
      }

      // 关闭弹窗，把上传结果发给 Agent
      const fileNames = agentFileList.value.map((f) => f.name).filter(Boolean)
      const uploadedClientId = uploadForm.value.clientId
      uploadDialogVisible.value = false
      agentFileList.value = []
      agentUploadRef.value?.clearFiles()
      uploadForm.value = { companyName: '', clientId: null, category: '', description: '' }

      // 标记资料已上传成功：隐藏"上传资料(可选)"引导卡片，只保留主线步骤按钮
      sessionUploadDone.value = true
      onboarding.value = buildSessionOnboarding()

      // 将上传结果回传给 Agent，让 Agent 继续后续流程
      await sendMessage(
        `已上传 ${successCount} 个文件：${fileNames.join('、')}`,
        { type: 'upload_files', label: '上传完成', payload: { client_id: uploadedClientId, file_names: fileNames } }
      )
    } else {
      ElMessage.error(response.message || '上传失败')
    }
  } catch (e: any) {
    ElMessage.error('上传失败: ' + e.message)
  } finally {
    uploading.value = false
  }
}

async function newConversation() {
  activeSessionId.value = ''
  localStorage.removeItem(STORAGE_KEY)
  // 每个新会话都重新展示完整引导（从第 1 步建客户开始），
  // 不继承其他会话的跳过/完成状态。
  await resetSessionOnboarding()
  messages.value = [initialWelcome()]
  inputText.value = ''
  pendingAttachments.value = []
  sidebarOpen.value = false
}

async function loadSessions() {
  loadingList.value = true
  try {
    const res = await v2ListSessions(50, 0)
    sessions.value = res.items ?? []
  } catch {
    // 拦截器已统一提示
  } finally {
    loadingList.value = false
  }
}

async function selectSession(id: string) {
  if (id === activeSessionId.value) {
    sidebarOpen.value = false
    return
  }
  activeSessionId.value = id
  localStorage.setItem(STORAGE_KEY, id)
  loadingHistory.value = true
  sidebarOpen.value = false
  try {
    const res = await v2GetSession(id)
    const detail = res
    const hist: ChatMessage[] = (detail?.messages ?? []).map((m: any) => {
      const meta = (m.metadata ?? {}) as Record<string, any>
      return {
        id: `hist_${m.id}`,
        role: (m.role === 'user' ? 'user' : 'assistant') as 'user' | 'assistant',
        content: m.content,
        // 后端把用户上传的附件存在 message.metadata.attachments 里，回放历史时还原，避免文件"消失"
        attachments: meta.attachments as ConversationAttachment[] | undefined,
        actions: meta.actions as ConversationAction[] | undefined,
      }
    })
    if (hist.length) {
      // 历史消息只回放文本/附件，不再显示旧 action 按钮；引导由当前会话状态重新决定。
      messages.value = hist.map((m) => ({ ...m, actions: undefined }))
      // 已有历史消息的会话不再展示引导
      onboarding.value = { active: false, dismissed: false, completed: false, checklist: [], next_actions: [], optional_actions: [], can_skip: false }
    } else {
      // 空会话视为新会话，重新从第 1 步开始引导
      await resetSessionOnboarding()
      messages.value = [initialWelcome()]
    }
  } catch {
    await resetSessionOnboarding()
    messages.value = [initialWelcome()]
  } finally {
    loadingHistory.value = false
    await scrollToBottom()
  }
}

async function sendMessage(overrideText?: string, action?: ConversationAction, silent?: boolean) {
  const text = (overrideText ?? inputText.value).trim()
  const hasAttachment = pendingAttachments.value.length > 0
  if ((!text && !hasAttachment && !action) || sending.value) return

  const attachments = [...pendingAttachments.value]
  // 静默模式：不创建用户消息气泡（弹窗内操作）
  if (!silent && (text || attachments.length)) {
    messages.value.push({ id: `user_${Date.now()}`, role: 'user', content: text, attachments })
  }
  inputText.value = ''
  pendingAttachments.value = []
  sending.value = true
  await scrollToBottom()

  // 普通对话走 V2 SSE 流式端点
  await sendMessageViaSSE(text, attachments, action, silent)
}

// V2 SSE 流式路径
async function sendMessageViaSSE(
  text: string,
  attachments: ConversationAttachment[],
  action?: ConversationAction,
  silent?: boolean,
) {
  // 占位 assistant 气泡，边收 SSE 边更新
  const bubbleId = `v2_${Date.now()}`
  const bubble: ChatMessage = {
    id: bubbleId,
    role: 'assistant',
    content: '',
    actions: [],
  }
  messages.value.push(bubble)
  await scrollToBottom()

  // action 回调直接传给后端，由后端 _build_effective_message 注入 payload
  // （前端不再拼接文本，避免 payload 中的结构化数据如 client_id 丢失）
  const payloadMessage = text || (action ? '' : '（请处理我上传的资料）')

  // 附件格式适配：V1 ConversationAttachment → V2 SSE {type, path, filename}
  const sseAttachments = attachments.map((a) => ({
    type: a.kind || 'material',
    path: a.ref || '',
    filename: a.filename || '',
  }))

  const updateBubble = (patch: Partial<ChatMessage>) => {
    const idx = messages.value.findIndex((m) => m.id === bubbleId)
    if (idx >= 0) {
      messages.value[idx] = { ...messages.value[idx], ...patch }
      scrollToBottom()
    }
  }

  const handlers: SSEHandlers = {
    onThinking: (data) => {
      // Agent 思考过程（对应 PRD §11.7）
      updateBubble({ content: bubble.content || '正在思考...' })
    },
    onToolCalls: (data) => {
      // Agent 决策调用工具，展示即将调用的工具名
      if (data.tool_calls?.length) {
        const toolLabel = toolDisplayName(data.tool_calls[0].name)
        updateBubble({ content: `正在调用：${toolLabel}...` })
      }
    },
    onToolStart: (data) => {
      // 工具开始执行
      const toolLabel = toolDisplayName(data.tool_name)
      updateBubble({ content: bubble.content || `正在执行：${toolLabel}...` })
    },
    onToolEnd: (data) => {
      // 工具执行完成，累积 actions
      if (data.actions?.length) {
        const idx = messages.value.findIndex((m) => m.id === bubbleId)
        if (idx >= 0) {
          messages.value[idx] = {
            ...messages.value[idx],
            actions: [...(messages.value[idx].actions ?? []), ...data.actions],
          }
        }
      }
    },
    onActions: (data) => {
      // 前端按钮事件（列表弹窗/表单弹窗/选择弹窗/指标卡片等）
      if (data.actions?.length) {
        const idx = messages.value.findIndex((m) => m.id === bubbleId)
        if (idx >= 0) {
          messages.value[idx] = {
            ...messages.value[idx],
            actions: [...(messages.value[idx].actions ?? []), ...data.actions],
          }
        }
        // 即时处理需要弹窗的 action 类型（仅在对应弹窗已打开时自动更新数据）
        for (const act of data.actions) {
          // 文章列表弹窗已打开时，自动刷新数据（分页/筛选操作）
          if (act.type === 'show_article_list' && articleListDialogVisible.value) {
            onAction(act)
          }
        }
      }
    },
    onTextDelta: (delta) => {
      // 流式文本：打字机效果，追加到气泡
      const idx = messages.value.findIndex((m) => m.id === bubbleId)
      if (idx < 0) return
      const current = messages.value[idx].content || ''
      // 如果气泡当前是占位文案，先清空再追加
      const placeholderPrefixes = ['正在思考...', '正在执行：', '正在调用：']
      const cleanContent = placeholderPrefixes.some((p) => current.startsWith(p)) ? '' : current
      messages.value[idx] = { ...messages.value[idx], content: cleanContent + delta }
      scrollToBottom()
    },
    onClarification: (data) => {
      // 需要用户补充信息：替换气泡内容为反问文案
      updateBubble({
        content: data.reply,
        actions: [...(bubble.actions ?? []), ...(data.actions ?? [])],
      })
    },
    onAsyncTask: () => {
      // 异步任务已启动（如文章生成），不立即结束，等 done
    },
    onProgress: () => {
      // 心跳，无需更新 UI
    },
    onError: (data) => {
      updateBubble({
        content: `请求失败：${data.message || data.code}`,
      })
    },
    onDone: (data) => {
      // 本轮结束：拿到 session_id，刷新侧边栏
      if (data.session_id) {
        activeSessionId.value = data.session_id
        localStorage.setItem(STORAGE_KEY, data.session_id)
      }
      // 兜底：如果 text_delta 没来过（纯工具执行无回复），给个默认文案
      const idx = messages.value.findIndex((m) => m.id === bubbleId)
      const currentContent = idx >= 0 ? messages.value[idx].content : ''
      if (!currentContent) {
        updateBubble({ content: defaultReplyByStatus(data.status) })
      }
      // done 事件携带的最终 actions（兜底）
      if (data.actions?.length) {
        const curIdx = messages.value.findIndex((m) => m.id === bubbleId)
        if (curIdx >= 0 && !messages.value[curIdx].actions?.length) {
          messages.value[curIdx] = {
            ...messages.value[curIdx],
            actions: data.actions,
          }
        }
      }
      // 本会话引导进度：根据本轮成功执行的工具推进步骤，避免被历史 DB 数据带偏。
      if (!sessionDismissed.value && data.status !== 'failed') {
        const completedTools = (data.tool_results || []).map((tr: any) => tr.name)
        let progressed = false
        for (const tr of data.tool_results || []) {
          const toolName = tr.name
          const toolStatus = tr.result?.status
          // 后端 tool_results 结构：{ name, result: { data: {...}, ... } }
          // 此处兼容两种路径：result.data.*（规范）与直接 result.*（容错）。
          const rdata = (tr.result?.data ?? tr.result ?? {}) as Record<string, any>
          if (toolName === 'upload_documents') {
            sessionUploadDone.value = true
            progressed = true
            continue
          }
          // 缓存最新创建的客户信息，用于后续"新建项目/上传资料"自动带入公司。
          if (toolName === 'create_client' && rdata.client_id) {
            sessionLatestClient.value = {
              client_id: rdata.client_id as number,
              company_name: (rdata.company_name as string) || '',
            }
          }
          // 缓存最新创建的项目 ID，用于后续"生成问题/生成文章"自动带入选定项目。
          if (toolName === 'create_project' && rdata.project_id) {
            sessionLatestProject.value = { project_id: rdata.project_id as number }
          }
          // 生成问题：后端已同步生成完成，把问题列表展示在气泡里，用户可直接查看/点击。
          if (toolName === 'generate_questions' && (rdata.questions?.length ?? 0) > 0) {
            const curIdx = messages.value.findIndex((m) => m.id === bubbleId)
            if (curIdx >= 0) {
              messages.value[curIdx] = {
                ...messages.value[curIdx],
                questions: rdata.questions as any[],
              }
            }
          }
          const stepKey = ONBOARDING_TOOL_TO_STEP[toolName]
          if (!stepKey) continue
          // 绑定发布账号：只有真正授权成功（由下方 auth 轮询确认）才推进 account。
          // 工具同步返回 running 只代表授权任务已发起，不代表成功；failed 时更要回退，
          // 避免卡片错误跳到"去发布"。
          if (toolName === 'bind_platform') {
            if (toolStatus === 'failed') {
              sessionProgress.value.delete(stepKey)
              progressed = true
            }
            continue
          }
          // 生成文章为异步后台任务（publish_status: generating → completed）。此处不立即推进步骤，
          // 而是启动完成轮询，等文章真正生成完成才推进到"绑定账号"；否则演示时文章还没出来引导就跳走了。
          if (toolName === 'generate_articles') {
            if (!sessionArticleGenerating.value) {
              sessionArticleGenerating.value = true
              onboarding.value = buildSessionOnboarding()
              pollArticleGeneration(bubbleId)
            }
            continue
          }
          if (!sessionProgress.value.has(stepKey)) {
            sessionProgress.value.add(stepKey)
            progressed = true
          }
        }
        if (progressed) {
          onboarding.value = buildSessionOnboarding()
        }
        // 补充/更新当前 action payload（如新建项目带 client_id）
        void loadOnboarding()
      }
      // 生成类任务（问题/文章）为异步，定时刷新 payload 以获取最新关联数据。
      const hasGenTask = (data.async_task_refs || []).some(
        (r: any) => r.task_type === 'question_generation' || r.task_type === 'article_generation',
      )
      if (hasGenTask) scheduleOnboardingRefresh()
      // 授权类任务（绑定平台）：启动前端轮询，检测登录成功 → 推进引导 + 关闭浏览器弹窗。
      // 注意：SSE done 事件直接携带 async_task_refs，这里就地启动轮询，
      // 不要依赖消息 meta（历史 meta 写入逻辑缺失，会导致轮询永远不触发）。
      for (const ref of data.async_task_refs || []) {
        if (ref.task_type === 'auth' && ref.task_id) {
          startAuthPolling(String(ref.task_id), ref.platform || '', bubbleId)
        }
      }
      loadSessions()
    },
  }

  try {
    await sseClient.sendMessage(
      {
        message: payloadMessage,
        session_id: activeSessionId.value || undefined,
        attachments: sseAttachments,
        action: action
          ? {
              type: action.type,
              label: action.label,
              payload: action.payload,
            }
          : undefined,
        silent: silent || false,
      },
      handlers,
    )
  } catch {
    updateBubble({ content: '这次请求没有成功，请稍后再试，或检查登录状态和后端服务。' })
  } finally {
    sending.value = false
    await scrollToBottom()
  }
}

// 工具名 → 中文展示名（SSE tool_start 事件用）
function toolDisplayName(toolName: string): string {
  const map: Record<string, string> = {
    plan_questions: '生成问题',
    generate_articles_from_questions: '生成文章',
    generate_articles_batch: '批量生成文章',
    publish_articles: '发布文章',
    manage_binding: '绑定平台',
    manage_client: '客户管理',
    manage_project: '项目管理',
    manage_knowledge: '知识库管理',
    manage_user: '用户管理',
    query: '查询',
  }
  return map[toolName] || toolName || '处理中'
}

// V2 done 事件无 text_delta 时的兜底文案
function defaultReplyByStatus(status: string): string {
  switch (status) {
    case 'completed':
      return '已完成。'
    case 'running':
      return '任务已在后台执行，可随时查询进度。'
    case 'need_clarification':
      return '请补充以上信息，我继续处理。'
    case 'failed':
      return '操作失败，请重试或检查后端服务。'
    default:
      return '已完成。'
  }
}

// 取消当前 SSE 流（发送中显示取消按钮）
function cancelStreaming() {
  sseClient.cancel()
  sending.value = false
}

async function onSessionMenu(cmd: { action: string; item: ConversationSessionItem }) {
  if (cmd.action === 'rename') await renameSession(cmd.item)
  else if (cmd.action === 'archive') await archiveSession(cmd.item)
  else if (cmd.action === 'delete') await deleteSession(cmd.item)
}

async function renameSession(item: ConversationSessionItem) {
  try {
    const { value } = await ElMessageBox.prompt('请输入新的会话标题', '重命名对话', {
      inputValue: item.title || '',
      inputValidator: (v: string) => (v && v.trim().length > 0) || '标题不能为空',
      confirmButtonText: '保存',
      cancelButtonText: '取消',
    })
    await v2RenameSession(item.id, value.trim())
    ElMessage.success('已重命名')
    await loadSessions()
  } catch {
    // 用户取消，忽略
  }
}

async function archiveSession(item: ConversationSessionItem) {
  try {
    await v2ArchiveSession(item.id)
    ElMessage.success('已归档')
    if (item.id === activeSessionId.value) await newConversation()
    await loadSessions()
  } catch {
    // 拦截器已统一提示
  }
}

async function deleteSession(item: ConversationSessionItem) {
  try {
    await ElMessageBox.confirm(
      `确定删除对话「${item.title || '未命名'}」？此操作不可恢复。`,
      '删除对话',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  try {
    await v2DeleteSession(item.id)
    ElMessage.success('已删除')
    if (item.id === activeSessionId.value) await newConversation()
    await loadSessions()
  } catch {
    // 拦截器已统一提示
  }
}

async function clearAllSessions() {
  if (sessions.value.length === 0 || clearingSessions.value) return
  try {
    await ElMessageBox.confirm(
      `确定清除全部 ${sessions.value.length} 条历史对话？此操作不可恢复。`,
      '一键清除',
      { type: 'warning', confirmButtonText: '清除', cancelButtonText: '取消' },
    )
  } catch {
    return
  }

  clearingSessions.value = true
  try {
    const ids = sessions.value.map((item) => item.id)
    await Promise.all(ids.map((id) => v2DeleteSession(id)))
    ElMessage.success('历史对话已清除')
    await newConversation()
    await loadSessions()
  } catch {
    ElMessage.error('清除失败，请稍后再试')
    await loadSessions()
  } finally {
    clearingSessions.value = false
  }
}

async function scrollToBottom() {
  await nextTick()
  if (messageListRef.value) {
    messageListRef.value.scrollTop = messageListRef.value.scrollHeight
  }
}

function formatRelativeTime(iso?: string | null): string {
  if (!iso) return ''
  const then = new Date(iso).getTime()
  if (Number.isNaN(then)) return ''
  const diff = Date.now() - then
  const min = 60_000
  const hour = 3_600_000
  const day = 86_400_000
  if (diff < min) return '刚刚'
  if (diff < hour) return `${Math.floor(diff / min)} 分钟前`
  if (diff < day) return `${Math.floor(diff / hour)} 小时前`
  if (diff < 7 * day) return `${Math.floor(diff / day)} 天前`
  return new Date(then).toLocaleDateString('zh-CN')
}

onMounted(async () => {
  await loadSessions()
  const stored = localStorage.getItem(STORAGE_KEY)
  if (stored && sessions.value.some((s) => s.id === stored)) {
    await selectSession(stored)
  } else {
    // 没有历史会话：每个新会话都从完整引导开始（第 1 步建客户）
    await resetSessionOnboarding()
    messages.value = [initialWelcome()]
  }
})

// ==================== 授权任务轮询 ====================
const authPollTimers = ref<Map<string, NodeJS.Timeout>>(new Map())
const pendingAuthTasks = ref<Map<string, { taskId: string; platform: string; msgId: string }>>(new Map())

// 说明：授权轮询的启动入口在 sendMessageViaSSE 的 onDone 回调里（直接读 SSE done 携带的
// async_task_refs，遇到 auth 类型即 startAuthPolling）。旧实现依赖把 async_task_refs 写入
// 消息 meta 再由 watch(messages) 触发，但 meta 写入从未实现，导致轮询永远不启动，是引导卡死
// 与弹窗不关的根因。现已改为 onDone 直接启动，此处不再保留那个失效的 watch。

function startAuthPolling(taskId: string, platform: string, msgId: string) {
  if (authPollTimers.value.has(taskId)) return

  // 记录待确认的授权任务
  pendingAuthTasks.value.set(taskId, { taskId, platform, msgId })

  let pollCount = 0
  const maxPolls = 150 // 最多轮询 5 分钟（每 2 秒一次）

  const timer = setInterval(async () => {
    pollCount++
      if (pollCount > maxPolls) {
        clearInterval(timer)
        authPollTimers.value.delete(taskId)
        pendingAuthTasks.value.delete(taskId)
        ElMessage.warning('授权任务超时，请重试')
        // 超时未确认成功 → 视为授权未完成，回退到"绑定发布账号"步骤，避免卡片误跳"去发布"
        if (sessionProgress.value.has('account')) {
          sessionProgress.value.delete('account')
          onboarding.value = buildSessionOnboarding()
        }
        return
      }

    try {
      // 调用后端 API 检查授权状态（GET /accounts/auth/status/{task_id}）
      // 注意：后端 AuthStatusResponse 直接返回对象（无 success/data 包装），
      // axios 响应拦截器已返回 response.data，所以 res 直接是 { task_id, status, ... }
      const res = await get<any>(`/accounts/auth/status/${taskId}`)
      if (res.status === 'success') {
        clearInterval(timer)
        authPollTimers.value.delete(taskId)
        pendingAuthTasks.value.delete(taskId)

        // 拿到 success 的瞬间立即推进 sessionProgress，不依赖后续 confirm 调用。
        // confirm 只是补一刀（任务存在时设个去重机会、已不存在时后端直接 404），
        // 不能因为 confirm 失败而卡住引导——否则用户会一直停在"绑定发布账号"。
        if (!sessionProgress.value.has('account')) {
          sessionProgress.value.add('account')
          onboarding.value = buildSessionOnboarding()
        }
        ElMessage.success(`${PLATFORMS[platform]?.name || platform} 授权成功！账号已保存`)
        messages.value.push({
          id: `auth_${Date.now()}`,
          role: 'assistant',
          content: `✅ ${PLATFORMS[platform]?.name || platform} 平台授权成功！浏览器已自动关闭。`,
        })
        scrollToBottom()

        // 最佳努力 confirm（任务已被后端清理也会 404，吞掉错误即可）
        post<any>(`/accounts/auth/confirm/${taskId}`).catch((e) => {
          console.warn('[Auth] confirm 调用失败（任务可能已被清理，可忽略）:', e?.response?.status, e?.message)
        })
        return
      } else if (res.status === 'failed') {
        clearInterval(timer)
        authPollTimers.value.delete(taskId)
        pendingAuthTasks.value.delete(taskId)
        ElMessage.error(res.message || '授权失败')
        // 授权失败 → 回退到"绑定发布账号"步骤，引导用户重新绑定，绝不显示"去发布"
        if (sessionProgress.value.has('account')) {
          sessionProgress.value.delete('account')
          onboarding.value = buildSessionOnboarding()
        }
      }
      // 其他状态（pending/running）继续轮询
    } catch (e: any) {
      // 记录但不要静默：404 是后端主动关任务造成的，理论上后端已经走到 _finalize_auth 成功
      // （close 在 success 之后才发生）。这里打 warn 但不立即推进，等下下次 2s 轮询再确认：
      // 万一是后端 timeout 清理路径触发的 close，就不该误推进。
      const status = e?.response?.status
      console.warn(`[Auth] 授权状态检查异常 (status=${status}):`, e?.message)
    }
  }, 2000)

  authPollTimers.value.set(taskId, timer)
}

// 手动确认授权（用户点击按钮时调用）
async function confirmAuthManually(taskId: string) {
  const taskInfo = pendingAuthTasks.value.get(taskId)
  if (!taskInfo) {
    ElMessage.error('授权任务不存在')
    return
  }

  try {
    const confirmRes = await post<any>(`/accounts/auth/confirm/${taskId}`)
    if (confirmRes.success) {
      ElMessage.success(`${PLATFORMS[taskInfo.platform]?.name || taskInfo.platform} 授权成功！账号已保存`)
      // 停止轮询
      const timer = authPollTimers.value.get(taskId)
      if (timer) {
        clearInterval(timer)
        authPollTimers.value.delete(taskId)
      }
      pendingAuthTasks.value.delete(taskId)
      // 授权真正完成，推进引导到"去发布"（幂等守卫防止重复 add）
      if (!sessionProgress.value.has('account')) {
        sessionProgress.value.add('account')
        onboarding.value = buildSessionOnboarding()
      }
      // 在聊天中添加一条助手消息
      messages.value.push({
        id: `auth_${Date.now()}`,
        role: 'assistant',
        content: `✅ ${PLATFORMS[taskInfo.platform]?.name || taskInfo.platform} 平台授权成功！浏览器已自动关闭。`,
      })
      scrollToBottom()
    } else {
      ElMessage.warning(confirmRes.message || '还未完成登录，请在浏览器中完成登录后再点击')
    }
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '确认授权失败')
  }
}

onUnmounted(() => {
  // 清理所有轮询定时器
  for (const timer of authPollTimers.value.values()) {
    clearInterval(timer)
  }
  authPollTimers.value.clear()
  pendingAuthTasks.value.clear()
})
</script>

<style scoped lang="scss">
.article-list-toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
  :deep(.el-select) {
    min-width: 220px;
  }
}
.article-list-pager {
  display: flex;
  justify-content: flex-end;
  margin-top: 14px;
}
.publish-account-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
}
.publish-summary {
  padding: 16px 20px;
  margin-bottom: 20px;
  background: var(--surface-base);
  border: 1px solid var(--border-soft);
  border-radius: 10px;
}
.publish-title {
  margin-bottom: 6px;
  color: var(--text-head);
  font-size: 15px;
  font-weight: 600;
  line-height: 1.5;
}
.text-muted { color: var(--text-muted); }
.publish-form :deep(.el-form-item__label) { color: var(--text-muted); font-weight: 500; }
.account-option { display: flex; align-items: center; justify-content: space-between; width: 100%; }
.publish-form-tip { margin-top: 6px; color: var(--warning); font-size: 12px; line-height: 1.5; }
.article-cell-title {
  max-width: 340px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  display: inline-block;
  vertical-align: middle;
}
.account-cell {
  display: flex;
  align-items: center;
  gap: 8px;
}
.account-avatar {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  object-fit: cover;
  background: #eee;
}
.agent-page {
  position: relative;
  height: 100%;
  min-height: calc(100vh - 96px);
}

.agent-shell {
  display: grid;
  grid-template-columns: 280px 1fr;
  gap: 16px;
  height: calc(100vh - 112px);
}

/* 左侧历史会话 */
.session-sidebar {
  display: flex;
  flex-direction: column;
  min-height: 0;
  border: 1px solid var(--border-soft);
  background: var(--surface-raised);
  border-radius: 8px;
  overflow: hidden;
}

.sidebar-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px;
  border-bottom: 1px solid var(--border-thin);
}

.new-chat-btn {
  flex: 1;
}

.clear-chat-btn {
  flex-shrink: 0;
  padding: 8px 10px;
  border-color: rgba(220, 38, 38, 0.22);
  background: rgba(220, 38, 38, 0.06);
  color: #b91c1c;

  &:hover:not(.is-disabled) {
    border-color: rgba(220, 38, 38, 0.38);
    background: rgba(220, 38, 38, 0.1);
    color: #991b1b;
  }
}

.sidebar-close {
  display: none;
}

.sidebar-scroll {
  flex: 1;
  overflow-y: auto;
  padding: 8px;
}

.sidebar-empty {
  margin: 24px 12px;
  color: var(--text-muted);
  font-size: 13px;
  text-align: center;
}

.session-item {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 10px;
  border-radius: 6px;
  cursor: pointer;
  border: 1px solid transparent;

  &:hover {
    background: var(--surface-field);
  }

  &.active {
    background: var(--accent-soft);
    border-color: var(--accent);
  }
}

.session-item-main {
  flex: 1;
  min-width: 0;
}

.session-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-body);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.session-preview {
  margin-top: 4px;
  font-size: 12px;
  color: var(--text-muted);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.session-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 6px;
}

.session-time {
  font-size: 11px;
  color: var(--text-muted);
}

.menu-trigger {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  border-radius: 4px;
  color: var(--text-muted);
  flex-shrink: 0;

  &:hover {
    background: var(--border-soft);
    color: var(--text-body);
  }
}

/* 右侧聊天 */
.chat-pane {
  display: grid;
  grid-template-rows: auto 1fr auto;
  min-width: 0;
  height: 100%;
  border: 1px solid var(--border-soft);
  background: var(--surface-raised);
  border-radius: 8px;
  overflow: hidden;
}

.chat-toolbar {
  grid-row: 1;
}

.message-list {
  grid-row: 2;
  overflow-y: auto;
  padding: 20px;
}

.composer {
  grid-row: 3;
  padding: 14px;
  border-top: 1px solid var(--border-thin);
}

.chat-toolbar {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 18px 20px;
  border-bottom: 1px solid var(--border-thin);

  .toolbar-title {
    h2 {
      margin: 0 0 6px;
      font-size: 20px;
    }

    p {
      margin: 0;
      color: var(--text-muted);
      font-size: 13px;
    }
  }
}

.sidebar-toggle {
  display: none;
  margin-top: 2px;
}

.message-list {
  overflow-y: auto;
  padding: 20px;
}

.message-row {
  display: flex;
  margin-bottom: 14px;

  &.user {
    justify-content: flex-end;
  }
}

.message-bubble {
  max-width: min(680px, 82%);
  padding: 12px 14px;
  border-radius: 8px;
  background: var(--surface-field);
  color: var(--text-body);
  border: 1px solid var(--border-thin);
  line-height: 1.6;
}

.message-row.user .message-bubble {
  background: #95ec69; /* 微信同款浅绿 */
  color: #1a1a1a;
  border-color: transparent;
}

/* 用户气泡里的附件 chip：半透明白底，在绿底上更清晰（默认橙 chip 在绿色上会撞色） */
.message-row.user .attachment-chip {
  background: rgba(255, 255, 255, 0.6);
  color: #1a1a1a;
}

.message-text {
  word-break: break-word;

  // Markdown 渲染样式
  :deep(p) {
    margin: 0 0 0.5em 0;
    &:last-child {
      margin-bottom: 0;
    }
  }

  :deep(strong) {
    font-weight: 600;
    color: var(--text-primary);
  }

  :deep(em) {
    font-style: italic;
  }

  :deep(ul), :deep(ol) {
    margin: 0.5em 0;
    padding-left: 1.5em;
  }

  :deep(li) {
    margin: 0.25em 0;
    line-height: 1.6;
  }

  :deep(code) {
    background: rgba(0, 0, 0, 0.06);
    padding: 2px 6px;
    border-radius: 4px;
    font-size: 0.9em;
    font-family: 'Consolas', 'Monaco', monospace;
  }

  :deep(pre) {
    background: #f5f5f5;
    padding: 12px 16px;
    border-radius: 8px;
    overflow-x: auto;
    margin: 0.5em 0;

    code {
      background: transparent;
      padding: 0;
      font-size: 0.9em;
    }
  }

  :deep(blockquote) {
    border-left: 3px solid var(--border-color);
    padding-left: 1em;
    margin: 0.5em 0;
    color: var(--text-muted);
  }

  :deep(a) {
    color: var(--primary-color);
    text-decoration: underline;
    &:hover {
      opacity: 0.8;
    }
  }

  :deep(h1), :deep(h2), :deep(h3), :deep(h4) {
    margin: 0.8em 0 0.4em 0;
    font-weight: 600;
    line-height: 1.4;
  }

  :deep(h1) { font-size: 1.4em; }
  :deep(h2) { font-size: 1.25em; }
  :deep(h3) { font-size: 1.15em; }
  :deep(h4) { font-size: 1.05em; }

  :deep(hr) {
    border: none;
    border-top: 1px solid var(--border-color);
    margin: 1em 0;
  }
}

.message-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
  margin-top: 10px;
  color: var(--text-muted);
  font-size: 12px;

  .trace {
    opacity: 0.85;
  }
}

.attachment-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 8px;
}

.attachment-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 3px 8px;
  border-radius: 6px;
  background: var(--accent-soft);
  color: var(--accent);
  font-size: 12px;

  &.removable .remove {
    cursor: pointer;
    margin-left: 2px;
  }
}

.action-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 10px;
}

// 新手引导操作卡片：渲染在最新助手消息气泡底部，与正文用虚线分隔
.onboarding-action-list {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 12px;
  padding-top: 10px;
  border-top: 1px dashed var(--border-thin);

  .oal-hint {
    font-size: 13px;
    color: var(--text-muted);
    white-space: nowrap;
  }

  // 可选步骤卡片：仅用虚线边框与必需卡区分，字色与"新建项目"等必需卡保持一致
  .oal-optional {
    border-style: dashed;
  }

  // 跳过引导：放在卡片区末尾，弱链接样式
  .oal-skip {
    margin-left: auto;
    font-size: 12px;
    padding: 0;
  }
}

:global(.agent-action-prompt) {
  width: min(360px, calc(100vw - 32px));
  border-radius: 8px;
  box-shadow: 0 16px 44px rgba(15, 23, 42, 0.18);

  .el-message-box__header {
    padding-bottom: 8px;
  }

  .el-message-box__content {
    padding-top: 4px;
  }

  .el-message-box__message {
    display: none;
  }
}

.question-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-top: 10px;

  button {
    width: 100%;
    padding: 8px 10px;
    border: 1px solid var(--border-soft);
    border-radius: 6px;
    background: var(--accent-soft);
    color: var(--accent);
    text-align: left;
    cursor: pointer;

    &:hover {
      border-color: var(--accent);
      background: rgba(196, 116, 28, 0.18);
    }
  }
}

// 文章预览卡：生成文章完成后挂到气泡上，展示标题/正文预览/状态，并提供去发布、复制正文快捷入口。
.article-preview-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-top: 10px;

  .article-preview-card {
    border: 1px solid var(--border-soft);
    border-radius: 8px;
    padding: 10px 12px;
    background: var(--surface-soft, #fafafa);
  }

  .ap-title {
    display: flex;
    align-items: center;
    gap: 6px;
    font-weight: 600;
    color: var(--text-head);
    margin-bottom: 6px;

    span {
      flex: 1;
      min-width: 0;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
  }

  .ap-content {
    font-size: 12px;
    line-height: 1.6;
    color: var(--text-body);
    opacity: 0.85;
    margin-bottom: 8px;
    word-break: break-word;
  }

  .ap-actions {
    display: flex;
    gap: 8px;
    flex-wrap: wrap;
  }
}

.pending-attachments {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 8px;
}

.composer-actions {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  margin-top: 10px;
}

.composer-right {
  display: flex;
  align-items: center;
  flex-shrink: 0;
  gap: 8px;
}

.quick-prompts {
  display: flex;
  flex-wrap: nowrap;
  align-items: center;
  min-width: 0;
  gap: 6px;

  :deep(.el-button) {
    padding: 7px 10px;
    font-size: 12px;
  }
}

/* 窄屏遮罩（默认隐藏） */
.sidebar-mask {
  display: none;
}

/* 响应式：窄屏把侧边栏改为可切换抽屉 */
@media (max-width: 1100px) {
  .agent-shell {
    grid-template-columns: 1fr;
    height: auto;
  }

  .session-sidebar {
    position: fixed;
    top: 0;
    left: 0;
    bottom: 0;
    width: 300px;
    max-width: 84vw;
    z-index: 50;
    transform: translateX(-100%);
    transition: transform 0.2s ease;
    border-radius: 0;
  }

  .agent-shell.sidebar-open .session-sidebar {
    transform: translateX(0);
  }

  .sidebar-close {
    display: inline-flex;
  }

  .sidebar-toggle {
    display: inline-flex;
  }

  .sidebar-mask {
    display: block;
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.35);
    z-index: 40;
  }

  .chat-pane {
    min-height: 680px;
  }
}
</style>
