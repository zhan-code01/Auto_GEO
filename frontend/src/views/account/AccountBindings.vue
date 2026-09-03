<template>
  <div class="account-bindings-page">
    <div class="page-header">
      <div>
        <h1>账号绑定</h1>
        <p>绑定外部平台账号后，可以在对应平台向 GEO 发送生成和发布指令。</p>
      </div>
      <el-button :icon="Refresh" @click="refreshFeishuStatus" :loading="statusLoading">
        刷新状态
      </el-button>
    </div>

    <el-row :gutter="16" class="platform-grid">
      <el-col :xs="24" :md="12">
        <section class="platform-panel active">
          <div class="platform-header">
            <div class="platform-icon feishu">
              <el-icon><ChatDotRound /></el-icon>
            </div>
            <div>
              <h2>飞书</h2>
              <el-tag :type="feishuBound ? 'success' : 'warning'" size="small">
                {{ feishuBound ? '已绑定' : '未绑定' }}
              </el-tag>
            </div>
          </div>

          <el-alert
            v-if="feishuBound"
            type="success"
            :closable="false"
            show-icon
            class="status-alert"
          >
            <template #title>
              飞书账号已绑定到 {{ feishuStatus?.binding?.username || userStore.displayName }}
            </template>
          </el-alert>

          <div v-else class="binding-flow">
            <div class="code-box" :class="{ empty: !bindingCode }">
              <span>{{ bindingCode || '------' }}</span>
              <el-button
                v-if="bindingCode"
                text
                :icon="CopyDocument"
                @click="copyBindCommand"
              />
            </div>
            <div class="code-meta">
              <span v-if="expiresAt">有效期至 {{ expiresAt }}</span>
              <span v-else>绑定码 30 分钟内有效</span>
            </div>
            <div class="actions">
              <el-button type="primary" :loading="codeLoading" @click="generateFeishuCode">
                生成绑定码
              </el-button>
              <el-button :loading="statusLoading" @click="refreshFeishuStatus">
                检查状态
              </el-button>
            </div>
            <el-alert type="info" :closable="false" class="command-alert">
              <template #title>
                在飞书中发送：{{ bindCommand }}
              </template>
            </el-alert>
          </div>
        </section>
      </el-col>

      <el-col :xs="24" :md="12">
        <section class="platform-panel disabled">
          <div class="platform-header">
            <div class="platform-icon wechat">
              <el-icon><Link /></el-icon>
            </div>
            <div>
              <h2>微信</h2>
              <el-tag type="info" size="small">待接入</el-tag>
            </div>
          </div>
          <div class="placeholder">
            <el-empty description="微信绑定通道尚未启用" :image-size="86" />
          </div>
        </section>
      </el-col>
    </el-row>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { ChatDotRound, CopyDocument, Link, Refresh } from '@element-plus/icons-vue'
import { get, post } from '@/services/api'
import { useUserStore } from '@/stores/modules/user'

const userStore = useUserStore()

const codeLoading = ref(false)
const statusLoading = ref(false)
const bindingCode = ref('')
const expiresAt = ref('')
const feishuStatus = ref<any>(null)

const currentUserId = computed(() => userStore.user?.id)
const feishuBound = computed(() => Boolean(feishuStatus.value?.is_bound))
const bindCommand = computed(() => bindingCode.value ? `绑定 ${bindingCode.value}` : '绑定 <绑定码>')

function formatTime(value?: string) {
  if (!value) return ''
  try {
    return new Date(value).toLocaleString('zh-CN')
  } catch {
    return value
  }
}

async function generateFeishuCode() {
  if (!currentUserId.value) {
    ElMessage.warning('请先登录后再生成绑定码')
    return
  }
  codeLoading.value = true
  try {
    const resp: any = await post(`/feishu/bindings/generate-code/${currentUserId.value}`)
    const data = resp?.data || {}
    bindingCode.value = data.code || ''
    expiresAt.value = formatTime(data.expires_at)
    ElMessage.success(data.message || '绑定码已生成')
    await refreshFeishuStatus()
  } finally {
    codeLoading.value = false
  }
}

async function refreshFeishuStatus() {
  if (!currentUserId.value) return
  statusLoading.value = true
  try {
    const resp: any = await get(`/feishu/bindings/my-status/${currentUserId.value}`)
    feishuStatus.value = resp?.data || null
    const activeCode = feishuStatus.value?.active_code
    if (activeCode && !bindingCode.value) {
      bindingCode.value = activeCode.code || ''
      expiresAt.value = formatTime(activeCode.expires_at)
    }
  } finally {
    statusLoading.value = false
  }
}

async function copyBindCommand() {
  if (!bindingCode.value) return
  await navigator.clipboard.writeText(bindCommand.value)
  ElMessage.success('绑定命令已复制')
}

onMounted(() => {
  refreshFeishuStatus()
})
</script>

<style scoped lang="scss">
.account-bindings-page {
  padding: 24px;
}

.page-header {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  align-items: flex-start;
  margin-bottom: 18px;

  h1 {
    margin: 0;
    font-size: 24px;
    color: var(--el-text-color-primary);
  }

  p {
    margin: 6px 0 0;
    color: var(--el-text-color-secondary);
    font-size: 14px;
  }
}

.platform-grid {
  max-width: 1120px;
}

.platform-panel {
  min-height: 330px;
  padding: 20px;
  border: 1px solid var(--el-border-color-light);
  border-radius: 8px;
  background: var(--el-bg-color);
}

.platform-panel.disabled {
  opacity: 0.82;
}

.platform-header {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 18px;

  h2 {
    margin: 0 0 6px;
    font-size: 18px;
    color: var(--el-text-color-primary);
  }
}

.platform-icon {
  width: 44px;
  height: 44px;
  display: grid;
  place-items: center;
  border-radius: 8px;
  color: #fff;
  font-size: 22px;
}

.platform-icon.feishu {
  background: #3370ff;
}

.platform-icon.wechat {
  background: #07c160;
}

.status-alert,
.command-alert {
  margin-top: 14px;
}

.binding-flow {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.code-box {
  height: 86px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  border: 1px dashed #3370ff;
  border-radius: 8px;
  background: #f3f7ff;

  span {
    font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
    font-size: 30px;
    font-weight: 700;
    letter-spacing: 6px;
    color: #1f4fbf;
  }
}

.code-box.empty {
  border-color: var(--el-border-color);
  background: var(--el-fill-color-lighter);

  span {
    color: var(--el-text-color-placeholder);
  }
}

.code-meta {
  min-height: 20px;
  color: var(--el-text-color-secondary);
  font-size: 13px;
}

.actions {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}

.placeholder {
  display: grid;
  place-items: center;
  min-height: 220px;
}
</style>
