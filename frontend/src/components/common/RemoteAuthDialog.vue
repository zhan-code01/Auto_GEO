<template>
  <el-dialog
    :model-value="modelValue"
    :title="dialogTitle"
    width="min(1180px, 96vw)"
    top="4vh"
    class="remote-auth-dialog"
    append-to-body
    :close-on-click-modal="false"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <div class="remote-auth-shell">
      <div class="remote-auth-bar">
        <div class="remote-auth-meta">
          <div class="remote-auth-subtitle">
            请在下方窗口内完成平台登录，授权信息会自动加密保存到当前账号。
          </div>
        </div>
        <div class="remote-auth-actions">
          <el-tag
            v-if="statusMeta"
            :type="statusMeta.type"
            effect="light"
            round
            size="small"
            class="remote-auth-status"
          >
            <el-icon
              :class="['remote-auth-status-icon', { spinning: statusMeta.spinning }]"
            >
              <component :is="statusMeta.icon" />
            </el-icon>
            <span>{{ statusMeta.text }}</span>
          </el-tag>
          <el-button :icon="Refresh" size="small" plain @click="reloadFrame">刷新</el-button>
          <el-button :icon="Link" size="small" plain @click="openStandalone">新窗口</el-button>
        </div>
      </div>

      <div v-if="showFrame" class="remote-auth-frame-wrap">
        <iframe
          :key="frameKey"
          class="remote-auth-frame"
          :src="remoteAuthUrl"
          :title="`${platformName || '平台'} 授权窗口`"
          allow="clipboard-read; clipboard-write"
        />
      </div>
      <div v-else class="remote-auth-browser-hint">
        <el-icon
          :class="['remote-auth-browser-icon', { spinning: displayStatus === 'authenticating' || displayStatus === 'checking' }]"
        >
          <component :is="statusMeta?.icon || Loading" />
        </el-icon>
        <div class="remote-auth-browser-title">{{ platformName || '平台' }} 授权进行中</div>
        <div class="remote-auth-browser-text">请在弹出的浏览器窗口完成登录，检测通过后会自动保存授权。</div>
      </div>

      <div v-if="showConfirm" class="remote-auth-footer">
        <div class="remote-auth-hint">完成登录后，点击右侧按钮保存授权。</div>
        <el-button type="primary" :loading="confirmLoading" @click="emit('confirm')">
          {{ confirmLoading ? '正在保存授权...' : '已完成登录并保存' }}
        </el-button>
      </div>
    </div>
  </el-dialog>
</template>

<script setup lang="ts">
import { computed, ref, type Component } from 'vue'
import {
  Link,
  Refresh,
  Loading,
  CircleCheckFilled,
  CircleCloseFilled,
} from '@element-plus/icons-vue'

type AuthStatus = 'idle' | 'authenticating' | 'checking' | 'success' | 'failed'

const props = withDefaults(
  defineProps<{
    modelValue: boolean
    platformName?: string
    /** 显式 noVNC 地址；不传则按 VITE_NOVNC_URL / 默认地址兜底 */
    url?: string
    /** 是否展示底部「已完成登录并保存」按钮（账号管理流程用） */
    showConfirm?: boolean
    showFrame?: boolean
    confirmLoading?: boolean
    /** 外部驱动的授权状态；未传时由 showConfirm/confirmLoading 推导，保持向后兼容 */
    status?: AuthStatus
  }>(),
  {
    platformName: '',
    url: '',
    showConfirm: false,
    showFrame: true,
    confirmLoading: false,
    status: 'idle',
  },
)

const emit = defineEmits<{
  (event: 'update:modelValue', value: boolean): void
  (event: 'confirm'): void
}>()

// show_dot=0 关闭 noVNC 拖拽圆点、reconnect=1 断线自动重连，减少远程桌面痕迹。
const DEFAULT_NOVNC_URL =
  '/novnc/vnc.html?resize=scale&autoconnect=1&reconnect=1&show_dot=0&path=novnc/websockify'

const frameKey = ref(0)

const dialogTitle = computed(() => (props.platformName ? `${props.platformName} 授权` : '平台授权'))

const remoteAuthUrl = computed(() => props.url || import.meta.env.VITE_NOVNC_URL || DEFAULT_NOVNC_URL)

// 推导展示状态：优先外部 status，否则按确认按钮态推导（兼容旧调用方）。
const displayStatus = computed<AuthStatus>(() => {
  if (props.status && props.status !== 'idle') return props.status
  if (props.confirmLoading) return 'checking'
  return props.showConfirm ? 'authenticating' : 'idle'
})

interface StatusMeta {
  text: string
  type: 'primary' | 'warning' | 'success' | 'danger'
  icon: Component
  spinning: boolean
}

const STATUS_MAP: Record<Exclude<AuthStatus, 'idle'>, StatusMeta> = {
  authenticating: { text: '等待登录', type: 'primary', icon: Loading, spinning: true },
  checking: { text: '检测登录状态中', type: 'warning', icon: Loading, spinning: true },
  success: { text: '授权成功', type: 'success', icon: CircleCheckFilled, spinning: false },
  failed: { text: '授权失败，请重试', type: 'danger', icon: CircleCloseFilled, spinning: false },
}

const statusMeta = computed<StatusMeta | null>(() =>
  displayStatus.value === 'idle' ? null : STATUS_MAP[displayStatus.value],
)

const reloadFrame = () => {
  frameKey.value += 1
}

const openStandalone = () => {
  window.open(remoteAuthUrl.value, '_blank', 'noopener,noreferrer')
}
</script>

<style scoped>
.remote-auth-shell {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.remote-auth-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}

.remote-auth-subtitle {
  font-size: 13px;
  color: var(--text-secondary, #756b60);
  line-height: 1.5;
}

.remote-auth-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

.remote-auth-status {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.remote-auth-status-icon {
  font-size: 14px;
}

.remote-auth-status-icon.spinning {
  animation: remote-auth-spin 1s linear infinite;
}

@keyframes remote-auth-spin {
  from {
    transform: rotate(0deg);
  }
  to {
    transform: rotate(360deg);
  }
}

.remote-auth-frame-wrap {
  height: min(72vh, 760px);
  min-height: 620px;
  overflow: hidden;
  border: 1px solid var(--border, #ded8cf);
  border-radius: 8px;
  background: #fff;
}

.remote-auth-frame {
  width: 100%;
  height: 100%;
  border: 0;
  background: #fff;
  display: block;
}

.remote-auth-browser-hint {
  min-height: 220px;
  border: 1px solid var(--border, #ded8cf);
  border-radius: 8px;
  background: #fffaf2;
  display: grid;
  place-items: center;
  align-content: center;
  gap: 10px;
  padding: 32px;
  text-align: center;
}

.remote-auth-browser-icon {
  font-size: 30px;
  color: var(--primary, #d88418);
}

.remote-auth-browser-icon.spinning {
  animation: remote-auth-spin 1s linear infinite;
}

.remote-auth-browser-title {
  font-size: 16px;
  font-weight: 700;
  color: var(--text-primary, #2d2419);
}

.remote-auth-browser-text {
  max-width: 360px;
  font-size: 13px;
  line-height: 1.6;
  color: var(--text-secondary, #756b60);
}

.remote-auth-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding-top: 2px;
}

.remote-auth-hint {
  font-size: 13px;
  color: var(--text-secondary, #756b60);
}

@media (max-width: 768px) {
  .remote-auth-bar {
    align-items: flex-start;
    flex-direction: column;
  }

  .remote-auth-frame-wrap {
    height: 64vh;
    min-height: 380px;
  }

  .remote-auth-footer {
    align-items: stretch;
    flex-direction: column;
  }
}
</style>
