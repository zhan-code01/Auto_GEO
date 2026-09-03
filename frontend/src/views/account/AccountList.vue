<template>
  <div class="account-list-page">
    <!-- 顶部操作栏 -->
    <div class="toolbar">
      <div class="toolbar-left">
        <el-select v-model="filterPlatform" placeholder="筛选平台" clearable style="width: 150px">
          <el-option
            v-for="p in platformOptions"
            :key="p.id"
            :label="p.name"
            :value="p.id"
          />
        </el-select>

        <el-select v-model="filterStatus" placeholder="状态筛选" clearable style="width: 120px; margin-left: 10px">
          <el-option label="全部" value="" />
          <el-option label="正常" :value="1" />
          <el-option label="授权过期" :value="-1" />
          <el-option label="禁用" :value="0" />
        </el-select>
      </div>
      <div class="toolbar-right">
        <el-button type="warning" :loading="checking" @click="handleCheckAll">
          <el-icon><Refresh /></el-icon>
          {{ checking ? `检测中 (${checkProgress.current}/${checkProgress.total})` : '一键检测所有' }}
        </el-button>

        <el-button type="primary" @click="showAddDialog">
          <el-icon><Plus /></el-icon> 添加账号
        </el-button>
      </div>
    </div>

    <!-- 账号卡片网格 -->
    <div class="accounts-grid">
      <div
        v-for="account in filteredAccounts"
        :key="account.id"
        class="account-card"
        :class="{ 'expired': account.status === -1 }"
      >
        <div class="account-header">
          <div class="platform-icon" :style="{ backgroundColor: getPlatformColor(account.platform) }">
            {{ getPlatformName(account.platform).substring(0,1) }}
          </div>
          <el-tooltip
            :content="account.status === 1 ? '登录有效' : account.status === -1 ? '授权已过期，请重新授权' : '未授权'"
            placement="top"
          >
            <div
              class="status-dot"
              :class="account.status === 1 ? 'online' : account.status === -1 ? 'expired' : 'offline'"
            ></div>
          </el-tooltip>
        </div>
        
        <h3 class="account-name">{{ account.account_name }}</h3>
        <p class="account-username">{{ account.username ? '@' + account.username : '已授权' }}</p>
        <p class="account-platform">{{ getPlatformName(account.platform) }}</p>

        <div class="account-actions">
          <el-button
            v-if="account.status !== 1"
            type="warning"
            size="small"
            plain
            @click="handleReAuth(account)"
          >
            去授权
          </el-button>
          <el-button
            v-if="account.platform === 'tieba'"
            type="primary"
            size="small"
            plain
            @click="openForumDialog(account)"
          >
            目标吧
          </el-button>
          <el-button size="small" @click="editAccount(account)">编辑</el-button>
          <el-button type="danger" size="small" text @click="deleteAccount(account)">删除</el-button>
        </div>
      </div>

      <!-- 空状态或添加卡片 -->
      <div class="account-card add-card" @click="showAddDialog">
        <div class="add-icon"><el-icon><Plus /></el-icon></div>
        <p>添加新账号</p>
      </div>
    </div>

    <!-- 添加/授权对话框 (核心逻辑) -->
    <el-dialog
      v-model="dialogVisible"
      :title="dialogTitle"
      width="500px"
      :close-on-click-modal="false"
      @close="resetForm"
    >
      <!-- 阶段1：填写信息 -->
      <div v-if="!authStep" class="form-step">
        <el-form :model="formData" label-width="80px">
          <el-form-item label="平台">
            <el-select v-model="formData.platform" placeholder="选择平台" :disabled="isEdit" style="width: 100%">
              <el-option
                v-for="p in platformOptions"
                :key="p.id"
                :label="p.name"
                :value="p.id"
              />
            </el-select>
          </el-form-item>
          <el-form-item label="名称">
            <el-input v-model="formData.account_name" placeholder="备注名称 (如: 知乎大号)" />
          </el-form-item>
          <el-form-item label="备注">
            <el-input v-model="formData.remark" type="textarea" placeholder="选填" />
          </el-form-item>
        </el-form>
      </div>

      <!-- 阶段2：等待授权 -->
      <div v-else class="auth-step">
        <div class="loading-container">
          <el-icon class="is-loading" size="40" color="#409eff"><Loading /></el-icon>
          <h3>{{ authView === 'remote' ? '请在远程授权窗口中完成登录' : '请在浏览器中完成登录' }}</h3>
          <p>
            {{ authView === 'remote' ? '服务器浏览器已打开' : 'Chrome 已打开' }}
            <strong>{{ getPlatformName(formData.platform) }}</strong>
            登录页
          </p>
          <p v-if="confirming" class="sub-text">正在提取登录凭证...</p>
          <p v-else class="sub-text">扫码或输入密码登录后，点击下方按钮</p>
        </div>
      </div>

      <template #footer>
        <span class="dialog-footer">
          <el-button @click="dialogVisible = false" :disabled="authStep && confirming">取消</el-button>
          
          <!-- 编辑模式下只保存信息 -->
          <el-button v-if="isEdit && !authStep" type="primary" @click="saveAccountInfo">
            保存信息
          </el-button>
          
          <!-- 授权等待阶段：手动确认按钮 -->
          <el-button v-if="authStep" type="primary" :loading="confirming" @click="confirmAuth">
            {{ confirming ? '提取中...' : '已完成登录' }}
          </el-button>

          <!-- 添加模式或重新授权模式 -->
          <el-button v-if="!isEdit && !authStep || (isEdit && authStep)" type="primary" :loading="loading" @click="startAuthProcess">
            启动浏览器授权
          </el-button>
        </span>
      </template>
    </el-dialog>

    <RemoteAuthDialog
      v-model="remoteAuthVisible"
      :platform-name="getPlatformName(formData.platform)"
      :url="remoteAuthUrl"
      :show-confirm="authStep"
      :confirm-loading="confirming"
      @confirm="confirmAuth"
    />

    <!-- 贴吧目标吧配置对话框 -->
    <el-dialog
      v-model="forumDialogVisible"
      title="配置目标贴吧"
      width="480px"
      :close-on-click-modal="false"
    >
      <div class="forum-dialog">
        <p class="forum-tip">
          贴吧发帖必须指定目标吧。可添加多个，<strong>列表第一个为默认发布吧</strong>；
          发布时使用默认吧，想发别的吧只需把它移到最前即可。
        </p>

        <div class="forum-add-row">
          <el-input
            v-model="forumInput"
            placeholder="输入吧名，如：餐饮创业（不用带“吧”字）"
            maxlength="30"
            clearable
            @keyup.enter="addForum"
          />
          <el-button type="primary" @click="addForum">添加</el-button>
        </div>

        <div v-if="forumList.length" class="forum-list">
          <div
            v-for="(name, index) in forumList"
            :key="name"
            class="forum-item"
            :class="{ 'is-default': index === 0 }"
          >
            <span class="forum-name">
              {{ name }}
              <el-tag v-if="index === 0" type="success" size="small" effect="plain">默认</el-tag>
            </span>
            <span class="forum-ops">
              <el-button
                v-if="index !== 0"
                size="small"
                text
                @click="makeDefaultForum(index)"
              >设为默认</el-button>
              <el-button size="small" text type="danger" @click="removeForum(index)">移除</el-button>
            </span>
          </div>
        </div>
        <el-empty v-else description="尚未配置目标吧" :image-size="60" />
      </div>

      <template #footer>
        <el-button @click="forumDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="forumSaving" @click="saveForums">保存</el-button>
      </template>
    </el-dialog>

    <!-- 检测进度对话框 -->
    <el-dialog
      v-model="checkDialogVisible"
      title="账号授权状态检测"
      width="600px"
      :close-on-click-modal="false"
    >
      <div class="check-progress">
        <el-progress :percentage="checkProgress.percentage" :status="checkProgress.status" />
        <p class="progress-text">
          正在检测: {{ checkProgress.current }} / {{ checkProgress.total }}
        </p>

        <div class="check-log">
          <div
            v-for="(log, index) in checkLogs"
            :key="index"
            class="log-item"
            :class="{ 'error': log.status === 'failed', 'warning': log.status === 'unknown' }"
          >
            <span class="log-platform">{{ getPlatformName(log.platform) }}</span>
            <el-tag :type="log.status === 'success' ? 'success' : log.status === 'failed' ? 'danger' : 'warning'" size="small">
              {{ log.status === 'success' ? '有效' : log.status === 'failed' ? '无效' : '无法确认' }}
            </el-tag>
          </div>
        </div>
      </div>

      <template #footer>
        <el-button :disabled="!checkCompleted" type="primary" @click="closeCheckDialog">
          确定
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { Plus, Loading, Refresh } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { accountApi } from '@/services/api' // 直接使用 API 避免 store 逻辑复杂化
import { getEnabledPlatforms, getPlatformConfig, isPublishPlatform } from '@/core/config/platform'
import RemoteAuthDialog from '@/components/common/RemoteAuthDialog.vue'

// 状态
const accounts = ref<any[]>([])
const filterPlatform = ref('')
const dialogVisible = ref(false)
const isEdit = ref(false)
const authStep = ref(false) // 是否处于授权等待阶段
const loading = ref(false)
const confirming = ref(false) // 是否正在确认授权
const authTaskId = ref('') // 当前授权任务ID
const authView = ref<'local' | 'remote'>('local')
const remoteAuthVisible = ref(false)
const remoteAuthUrl = ref('')
const pollTimer = ref<any>(null)
const filterStatus = ref<number | null>(null)

// 检测相关状态
const checking = ref(false)
const checkDialogVisible = ref(false)
const checkCompleted = ref(false)

// 贴吧目标吧配置
const forumDialogVisible = ref(false)
const forumSaving = ref(false)
const forumInput = ref('')
const forumList = ref<string[]>([])
const forumAccountId = ref<number | null>(null)
const checkProgress = ref({
  current: 0,
  total: 0,
  percentage: 0,
  status: '' as '' | 'success' | 'exception'
})
const checkLogs = ref<any[]>([])
let ws: WebSocket | null = null

// 平台选项
const platformOptions = computed(() => getEnabledPlatforms().map(p => ({ id: p.id, name: p.name })))

const formData = ref({
  id: null as number | null,
  platform: 'zhihu',
  account_name: '',
  remark: '',
})

// 计算属性
const filteredAccounts = computed(() => {
  let result = accounts.value
  if (filterPlatform.value) {
    result = result.filter(acc => acc.platform === filterPlatform.value)
  }
  if (filterStatus.value !== null) {
    result = result.filter(acc => acc.status === filterStatus.value)
  }
  return result
})

const dialogTitle = computed(() => {
  if (authStep.value) return '正在授权'
  return isEdit.value ? '编辑账号' : '添加账号'
})

const normalizeAccountList = (res: any): any[] => {
  if (Array.isArray(res)) return res
  if (Array.isArray(res?.items)) return res.items
  if (Array.isArray(res?.data?.items)) return res.data.items
  if (Array.isArray(res?.data)) return res.data
  return []
}

/**
 * 账号管理页面只展示"可发布"的发布平台账号，过滤掉 GEO 评测用的 AI 平台账号
 * （豆包 / 通义千问 / DeepSeek）。这些 AI 平台的登录态由 GEO 模块单独管理。
 */
const filterAccountsForDisplay = (list: any[]): any[] =>
  (list || []).filter((acc: any) => isPublishPlatform(acc.platform))

const getElectronServerBaseUrl = () => {
  const configured = import.meta.env.VITE_API_BASE_URL || ''
  if (!configured || configured.startsWith('/')) return undefined
  return configured.replace(/\/api\/?$/, '').replace(/\/+$/, '')
}

const canUseElectronLocalAuth = () => Boolean(window.electronAPI?.localAuth?.startAuth)

// 加载列表
const loadAccounts = async () => {
  try {
    const res: any = await accountApi.getList()
    accounts.value = filterAccountsForDisplay(normalizeAccountList(res))
  } catch (e) { console.error(e) }
}

// 打开添加
const showAddDialog = () => {
  // 网页端无法拉取浏览器，直接提示使用客户端
  if (!window.electronAPI?.localAuth?.startAuth) {
    ElMessageBox.alert(
      '添加账号需要启动本地浏览器进行授权，请在 AutoGEO 客户端中完成账号授权。',
      '需要桌面客户端',
      { type: 'info', confirmButtonText: '知道了' }
    )
    return
  }
  isEdit.value = false
  authStep.value = false
  formData.value = { id: null, platform: 'zhihu', account_name: '', remark: '' }
  dialogVisible.value = true
}

// 编辑信息
const editAccount = (acc: any) => {
  isEdit.value = true
  authStep.value = false
  formData.value = {
    id: acc.id,
    platform: acc.platform,
    account_name: acc.account_name,
    remark: acc.remark
  }
  dialogVisible.value = true
}

// 重新授权
const handleReAuth = (acc: any) => {
  if (!window.electronAPI?.localAuth?.startAuth) {
    ElMessageBox.alert(
      '账号授权需要启动本地浏览器，请在 AutoGEO 客户端中完成账号授权。',
      '需要桌面客户端',
      { type: 'info', confirmButtonText: '知道了' }
    )
    return
  }
  isEdit.value = false
  authStep.value = false
  formData.value = {
    id: acc.id,
    platform: acc.platform,
    account_name: acc.account_name,
    remark: acc.remark
  }
  dialogVisible.value = true
}

// 保存纯文本信息 (不涉及浏览器)
const saveAccountInfo = async () => {
  if (!formData.value.id) return
  try {
    await accountApi.update(formData.value.id, {
      account_name: formData.value.account_name,
      remark: formData.value.remark
    })
    ElMessage.success('更新成功')
    dialogVisible.value = false
    loadAccounts()
  } catch (e) { ElMessage.error('更新失败') }
}

// ---------- 贴吧目标吧配置 ----------
// 打开目标吧对话框（点卡片“目标吧”按钮，或贴吧绑定成功后自动弹出）
const openForumDialog = async (acc: any) => {
  forumAccountId.value = acc.id
  forumInput.value = ''
  forumList.value = []
  forumDialogVisible.value = true
  try {
    const res: any = await accountApi.getTiebaForums(acc.id)
    forumList.value = res?.data?.forums || []
  } catch (e) {
    // 读取失败不阻断，用户可重新配置
    console.warn('读取目标吧失败', e)
  }
}

const addForum = () => {
  const name = forumInput.value.trim().replace(/吧$/, '').trim()
  if (!name) return
  if (forumList.value.includes(name)) {
    ElMessage.warning('该吧已在列表中')
    forumInput.value = ''
    return
  }
  forumList.value.push(name)
  forumInput.value = ''
}

const removeForum = (index: number) => {
  forumList.value.splice(index, 1)
}

// 设为默认：移到列表第一位（发布用第一位）
const makeDefaultForum = (index: number) => {
  const [name] = forumList.value.splice(index, 1)
  forumList.value.unshift(name)
}

const saveForums = async () => {
  if (!forumAccountId.value) return
  forumSaving.value = true
  try {
    await accountApi.setTiebaForums(forumAccountId.value, forumList.value)
    ElMessage.success(forumList.value.length ? '目标吧已保存' : '已清空目标吧')
    forumDialogVisible.value = false
    loadAccounts()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '保存失败')
  } finally {
    forumSaving.value = false
  }
}

// 贴吧绑定成功后，提示配置目标吧（未配置就发不了帖）
const maybePromptTiebaForum = async (platform: string, accountId?: number | null) => {
  if (platform !== 'tieba' || !accountId) return
  try {
    await ElMessageBox.confirm(
      '贴吧账号已绑定成功。发帖前需要指定“目标吧”，现在配置吗？',
      '配置目标贴吧',
      { confirmButtonText: '去配置', cancelButtonText: '稍后', type: 'info' },
    )
    await openForumDialog({ id: accountId })
  } catch {
    // 用户选择“稍后”，可在账号卡片“目标吧”按钮再配
  }
}

// 生成默认账号名称：首个用「平台名+账号」，后续同名自动追加序号，避免顶替已有账号
const generateDefaultAccountName = (platform: string): string => {
  const base = `${getPlatformName(platform)}账号`
  const existingNames = new Set(
    accounts.value.filter(a => a.platform === platform).map(a => String(a.account_name).trim())
  )
  if (!existingNames.has(base)) return base
  let index = 2
  while (existingNames.has(`${base}${index}`)) {
    index += 1
  }
  return `${base}${index}`
}

// 启动授权流程 (核心逻辑)
const startAuthProcess = async () => {
  if (authStep.value) return // 防止重复点击

  if (!formData.value.account_name) {
    formData.value.account_name = generateDefaultAccountName(formData.value.platform)
  }

  loading.value = true
  try {
    if (canUseElectronLocalAuth()) {
      const token = localStorage.getItem('autogeo_token') || ''
      dialogVisible.value = false
      ElMessage.info(`正在打开${getPlatformName(formData.value.platform)}本机浏览器授权窗口`)

      const result = await window.electronAPI!.localAuth!.startAuth(
        formData.value.platform,
        token,
        getElectronServerBaseUrl(),
        formData.value.account_name,
        formData.value.id || undefined,
      )

      if (!result?.success) {
        ElMessage.error(result?.error || `${getPlatformName(formData.value.platform)}授权失败`)
        return
      }

      ElMessage.success(`${getPlatformName(formData.value.platform)}授权成功`)
      const boundPlatform = formData.value.platform
      await loadAccounts()
      // 贴吧：绑定成功后提示配置目标吧（新账号从列表回查其 id）
      if (boundPlatform === 'tieba') {
        const bound = accounts.value.find(
          (a: any) => a.platform === 'tieba' && (a.id === formData.value.id || a.account_name === formData.value.account_name)
        )
        await maybePromptTiebaForum('tieba', bound?.id ?? formData.value.id)
      }
      return
    }

    ElMessage.error('请在 AutoGEO 客户端中完成账号授权；本地测试请使用 npm run dev 打开的 Electron 窗口')
  } catch (e: any) {
    const msg = e?.response?.data?.detail || e?.message || '请求失败，请检查后端是否启动'
    ElMessage.error(msg)
  } finally {
    loading.value = false
  }
}

// 轮询检查状态
const startPolling = (taskId: string) => {
  if (pollTimer.value) clearInterval(pollTimer.value)
  
  pollTimer.value = setInterval(async () => {
    try {
      const res: any = await accountApi.getAuthStatus(taskId)
      
      if (res.status === 'success') {
        clearInterval(pollTimer.value)
        ElMessage.success('授权成功！')
        authStep.value = false
        authTaskId.value = ''
        remoteAuthVisible.value = false
        dialogVisible.value = false
        loadAccounts()
      } else if (res.status === 'failed' || res.status === 'timeout') {
        clearInterval(pollTimer.value)
        authStep.value = false
        authTaskId.value = ''
        remoteAuthVisible.value = false
        ElMessage.error(res.message || '授权失败')
      }
    } catch (error: any) {
      // 🌟 核心修复：如果后端返回 404 (任务丢失)，立即停止轮询
      if (error.response && error.response.status === 404) {
        console.warn('任务已失效，停止轮询')
        clearInterval(pollTimer.value)
        authStep.value = false
        authTaskId.value = ''
        remoteAuthVisible.value = false
        ElMessage.warning('授权会话已过期，请重试')
      }
    }
  }, 2000)
}

// 手动确认授权：用户登录后点击按钮，后端提取Cookie入库
const confirmAuth = async () => {
  if (!authTaskId.value) {
    ElMessage.error('授权任务已失效')
    return
  }
  confirming.value = true
  try {
    if (pollTimer.value) clearInterval(pollTimer.value)

    const res: any = await accountApi.confirmAuth(authTaskId.value)
    if (res.success) {
      ElMessage.success('授权成功！')
      const boundPlatform = formData.value.platform
      const boundAccountId = res.data?.account_id ?? formData.value.id
      authStep.value = false
      authTaskId.value = ''
      remoteAuthVisible.value = false
      dialogVisible.value = false
      loadAccounts()
      // 贴吧：绑定成功后提示配置目标吧
      await maybePromptTiebaForum(boundPlatform, boundAccountId)
    } else {
      ElMessage.warning(res.message || '授权还未完成，请先登录平台')
      // 恢复轮询
      startPolling(authTaskId.value)
    }
  } catch (e: any) {
    const msg = e.response?.data?.detail || '确认授权失败'
    ElMessage.error(msg)
    // 恢复轮询
    startPolling(authTaskId.value)
  } finally {
    confirming.value = false
  }
}

// 修改 deleteAccount 函数
const deleteAccount = async (acc: any) => {
  try {
    // 1. 弹出确认框
    await ElMessageBox.confirm(
      `确定要删除账号 "${acc.account_name}" 吗？\n删除后相关的发布记录也会被清除！`, 
      '高风险操作', 
      {
        confirmButtonText: '确定删除',
        cancelButtonText: '取消',
        type: 'warning',
      }
    )

    // 2. 发送请求
    console.log(`正在请求删除账号 ID: ${acc.id}...`)
    const res: any = await accountApi.delete(acc.id)

    // 3. 判断结果
    if (res.success) {
      ElMessage.success('账号已成功删除')
      await loadAccounts() // 重新加载列表
    } else {
      ElMessage.error(res.message || '删除失败，服务端拒绝')
    }

  } catch (e: any) {
    // 4. 区分是“用户取消”还是“报错”
    if (e === 'cancel') {
      console.log('用户取消删除')
    } else {
      console.error('删除接口报错:', e)
      // 获取更详细的错误信息
      const errorMsg = e.response?.data?.detail || e.message || '未知错误'
      ElMessage.error(`删除失败: ${errorMsg}`)
    }
  }
}

const resetForm = async () => {
  if (pollTimer.value) clearInterval(pollTimer.value)
  pollTimer.value = null

  // 如果处于授权阶段且有任务ID，清理后端授权任务
  if (authStep.value && authTaskId.value) {
    try {
      await accountApi.cancelAuth(authTaskId.value)
    } catch (e) {
      console.warn('取消授权任务失败（可能已超时）:', e)
    }
  }

  authStep.value = false
  confirming.value = false
  authTaskId.value = ''
  authView.value = 'local'
  remoteAuthVisible.value = false
  remoteAuthUrl.value = ''
  loading.value = false
}

// 检测相关方法
const handleCheckAll = async () => {
  try {
    await ElMessageBox.confirm(
      '将逐一用本地浏览器验证所有「已授权」账号的真实登录状态（无头浏览器，不打扰你）。\n' +
      '确认登出的账号会被标记为「授权过期」；网络/风控等无法确认的情况不会改动状态。是否开始？',
      '批量检测确认',
      {
        confirmButtonText: '开始检测',
        cancelButtonText: '取消',
        type: 'warning',
      }
    )
  } catch {
    return
  }

  checkLogs.value = []
  checkCompleted.value = false
  checkProgress.value = { current: 0, total: 0, percentage: 0, status: '' }
  checkDialogVisible.value = true
  checking.value = true

  try {
    const allAccounts = filterAccountsForDisplay(normalizeAccountList(await accountApi.getList()))
    const authorizedAccounts = allAccounts.filter((acc: any) => acc.status === 1)
    checkProgress.value.total = authorizedAccounts.length

    if (authorizedAccounts.length === 0) {
      ElMessage.warning('没有需要检测的账号')
      checkDialogVisible.value = false
      checking.value = false
      return
    }

    // 桌面端（Electron）：本地真实浏览器验证 + 回写（真相引擎）
    if (window.electronAPI?.localAuth?.verifySession) {
      await runLocalVerification(authorizedAccounts)
    } else {
      // Web / 非桌面端：走服务端轻量检测（仅查 DB cookie 是否存在）+ WS 进度
      setupWsListener()
      await accountApi.checkAll()
    }
  } catch (error: any) {
    console.error('检测失败:', error)
    ElMessage.error('检测过程中发生错误')
    checking.value = false
  }
}

/**
 * 本地真相引擎验证：逐个用本地会话在真实无头浏览器访问平台首页，
 * 判定登录态并回写服务端（铁律：ok→status=1, logged_out→status=-1, unknown→不动）。
 */
const runLocalVerification = async (accounts: any[]) => {
  let okCount = 0
  let expiredCount = 0
  let unknownCount = 0

  for (let i = 0; i < accounts.length; i++) {
    const acc = accounts[i]
    checkProgress.value.current = i + 1
    checkProgress.value.percentage = Math.round(((i + 1) / accounts.length) * 100)

    const result: any = await window.electronAPI!.localAuth!.verifySession!(acc.platform, acc.id).catch((e: any) => ({
      success: false,
      auth_status: 'unknown' as const,
      error: e?.message || '调用本地验证失败',
    }))

    const authStatus: string = result?.auth_status || 'unknown'

    // 回写服务端（按铁律处理 status / last_check_time）
    try {
      await accountApi.reportCheckResult(acc.id, authStatus)
    } catch (e: any) {
      console.warn(`[CheckAll] 回写账号 ${acc.id} 检测结果失败:`, e?.message)
    }

    if (authStatus === 'ok') {
      okCount++
      checkLogs.value.push({
        ...acc,
        status: 'success',
        message: result?.nickname ? `登录正常（${result.nickname}）` : '登录正常',
      })
    } else if (authStatus === 'logged_out') {
      expiredCount++
      checkLogs.value.push({ ...acc, status: 'failed', message: '会话已过期，需要重新授权' })
    } else {
      unknownCount++
      checkLogs.value.push({ ...acc, status: 'unknown', message: result?.error || '无法确认（网络/风控/未适配）' })
    }
  }

  checkCompleted.value = true
  checkProgress.value.status = expiredCount > 0 ? 'exception' : 'success'
  checking.value = false

  ElMessage.success(
    `本地检测完成：共 ${accounts.length} 个，有效 ${okCount} 个，失效 ${expiredCount} 个，无法确认 ${unknownCount} 个`
  )

  await loadAccounts()
}

const setupWsListener = () => {
  const configuredWsUrl = import.meta.env.VITE_WS_URL

  // 判断是否在 Electron 打包环境中
  const isElectronApp = typeof window !== 'undefined' &&
    (window.navigator.userAgent.includes('Electron') ||
     window.__ELECTRON_ENV__ === 'production')

  // 判断是否是有效的本机 WebSocket 地址
  const isLocalhostWsUrl = /^wss?:\/\/(?:localhost|127\.0\.0\.1)(?::\d+)?\/ws\/?$/i.test(configuredWsUrl || '')

  // 在 Electron 打包环境中使用绝对地址；开发环境用相对路径走 Vite 代理
  let wsUrl: string
  if (isLocalhostWsUrl && isElectronApp) {
    wsUrl = configuredWsUrl
  } else if (isLocalhostWsUrl) {
    wsUrl = `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}/ws`
  } else {
    wsUrl = configuredWsUrl || `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}/ws`
  }

  ws = new WebSocket(wsUrl)

  ws.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data)

      if (data.type === 'account_check_progress') {
        checkProgress.value.current = data.current
        checkProgress.value.percentage = data.progress || 0
        const result = data.result || {}
        if (!result.status && 'is_valid' in result) {
          result.status = result.is_valid ? 'success' : 'failed'
        }
        checkLogs.value.push(result)
      } else if (data.type === 'account_check_complete') {
        checkCompleted.value = true
        checking.value = false
        checkProgress.value.status = data.summary.failed > 0 ? 'exception' : 'success'

        ElMessage.success(
          `检测完成: 共 ${data.summary.total} 个账号, ` +
          `成功 ${data.summary.success} 个, ` +
          `失败 ${data.summary.failed} 个`
        )

        loadAccounts()
      }
    } catch (error) {
      console.error('解析WebSocket消息失败:', error)
    }
  }
}

const closeCheckDialog = () => {
  checkDialogVisible.value = false
  if (ws) {
    ws.close()
    ws = null
  }
}

// 工具函数
const getPlatformName = (p: string) => {
  const config = getPlatformConfig(p)
  return config ? config.name : p
}

const getPlatformColor = (p: string) => {
  const config = getPlatformConfig(p)
  return config ? config.color : '#999'
}

onMounted(loadAccounts)
onUnmounted(() => {
  resetForm()
  if (ws) {
    ws.close()
    ws = null
  }
})
</script>

<style scoped lang="scss">
.account-list-page { padding: 20px; display: flex; flex-direction: column; gap: 20px; }
.toolbar { display: flex; justify-content: space-between; }

.accounts-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 20px; }

.account-card {
  background: var(--bg-secondary); border-radius: 12px; padding: 20px; position: relative; border: 1px solid var(--border);
  transition: transform 0.2s;
  &:hover { transform: translateY(-3px); box-shadow: 0 5px 15px rgba(0,0,0,0.2); }

  &.expired {
    border: 2px solid #f56c6c;
    background: linear-gradient(135deg, rgba(245, 108, 108, 0.05), var(--bg-secondary));
  }
  
  &.add-card {
    display: flex; flex-direction: column; align-items: center; justify-content: center;
    border: 2px dashed var(--border); cursor: pointer; color: var(--text-secondary);
    &:hover { border-color: var(--primary); color: var(--primary); }
    .add-icon { font-size: 32px; margin-bottom: 10px; }
  }
}

.account-header {
  display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px;
  .platform-icon {
    width: 40px; height: 40px; border-radius: 8px; display: flex; align-items: center; justify-content: center;
    color: white; font-weight: bold; font-size: 18px;
  }
  .status-dot {
    width: 10px; height: 10px; border-radius: 50%;
    cursor: help;
    &.online { background: #67C23A; box-shadow: 0 0 5px #67C23A; }
    &.offline { background: #909399; }
    &.expired { background: #F56C6C; box-shadow: 0 0 5px #F56C6C; }
  }
}

.account-name { margin: 0 0 5px 0; font-size: 16px; color: var(--text-primary); }
.account-username { font-size: 13px; color: var(--text-secondary); margin-bottom: 5px; }
.account-platform { font-size: 12px; color: var(--text-tertiary); margin-bottom: 15px; }

.account-actions {
  display: flex; justify-content: flex-end; gap: 8px; border-top: 1px solid var(--border); padding-top: 10px;
}

.auth-step {
  text-align: center; padding: 30px 0;
  h3 { margin: 20px 0 10px; color: var(--text-primary); }
  .sub-text { color: var(--text-secondary); font-size: 12px; }
}

.check-progress {
  .progress-text {
    text-align: center;
    margin: 15px 0;
    color: var(--text-secondary);
  }

  .check-log {
    max-height: 300px;
    overflow-y: auto;
    margin-top: 15px;
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 10px;

    .log-item {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      padding: 8px 12px;
      border-bottom: 1px solid var(--border);

      &:last-child {
        border-bottom: none;
      }

      &.error {
        background: rgba(245, 108, 108, 0.05);
      }

      &.warning {
        background: rgba(230, 162, 60, 0.05);
      }

      .log-platform {
        font-weight: 500;
        color: var(--text-primary);
      }
    }
  }
}

.forum-dialog {
  .forum-tip {
    font-size: 13px;
    color: var(--text-secondary);
    line-height: 1.6;
    margin: 0 0 16px;
  }
  .forum-add-row {
    display: flex;
    gap: 8px;
    margin-bottom: 14px;
  }
  .forum-list {
    display: flex;
    flex-direction: column;
    gap: 8px;
    max-height: 260px;
    overflow-y: auto;
  }
  .forum-item {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 8px 12px;
    border: 1px solid var(--border);
    border-radius: 8px;
    &.is-default {
      border-color: var(--primary);
      background: rgba(196, 116, 28, 0.06);
    }
    .forum-name {
      display: flex;
      align-items: center;
      gap: 8px;
      color: var(--text-primary);
    }
  }
}
</style>
