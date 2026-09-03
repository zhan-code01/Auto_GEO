<template>
  <div
    class="account-card"
    :class="{
      selected: modelValue,
      disabled: account.status !== 1
    }"
    @click="handleClick"
  >
    <div class="card-header">
      <div class="platform-icon" :style="{ background: platformColor }">
        {{ platformCode }}
      </div>
      <div class="status-indicator" :class="statusClass"></div>
    </div>

    <div class="card-body">
      <h3 class="account-name">{{ account.account_name }}</h3>
      <p class="account-username">@{{ account.username || '未授权' }}</p>
      <p class="account-platform">{{ platformName }}</p>
      <p v-if="account.last_auth_time" class="auth-time">
        授权于 {{ formatDate(account.last_auth_time) }}
      </p>
    </div>

    <div class="card-actions" @click.stop>
      <el-button
        v-if="account.status !== 1"
        type="primary"
        size="small"
        @click="$emit('auth', account)"
      >
        去授权
      </el-button>
      <el-dropdown v-else @command="handleCommand">
        <el-button size="small">
          操作 <el-icon><ArrowDown /></el-icon>
        </el-button>
        <template #dropdown>
          <el-dropdown-menu>
            <el-dropdown-item command="edit">编辑</el-dropdown-item>
            <el-dropdown-item command="reauth">重新授权</el-dropdown-item>
            <el-dropdown-item command="delete" divided>删除</el-dropdown-item>
          </el-dropdown-menu>
        </template>
      </el-dropdown>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { ArrowDown } from '@element-plus/icons-vue'
import { PLATFORMS } from '@/core/config/platform'
import type { Account } from '@/types'

interface Props {
  account: Account
  modelValue?: boolean
}

interface Emits {
  (e: 'update:modelValue', value: boolean): void
  (e: 'auth', account: Account): void
  (e: 'edit', account: Account): void
  (e: 'delete', account: Account): void
  (e: 'reauth', account: Account): void
}

const props = defineProps<Props>()
const emit = defineEmits<Emits>()

const platformConfig = computed(() => PLATFORMS[props.account.platform])
const platformName = computed(() => platformConfig.value?.name || props.account.platform)
const platformCode = computed(() => platformConfig.value?.code || '?')
const platformColor = computed(() => platformConfig.value?.color || '#666')

const statusClass = computed(() => {
  return {
    'status-active': props.account.status === 1,
    'status-inactive': props.account.status === 0,
    'status-expired': props.account.status === -1,
  }
})

const handleClick = () => {
  if (props.account.status === 1) {
    emit('update:modelValue', !props.modelValue)
  }
}

const handleCommand = (command: string) => {
  switch (command) {
    case 'edit':
      emit('edit', props.account)
      break
    case 'delete':
      emit('delete', props.account)
      break
    case 'reauth':
      emit('auth', props.account)
      break
  }
}

const formatDate = (dateStr: string) => {
  const date = new Date(dateStr)
  const now = new Date()
  const diff = now.getTime() - date.getTime()
  const days = Math.floor(diff / (1000 * 60 * 60 * 24))

  if (days === 0) return '今天'
  if (days === 1) return '昨天'
  if (days < 7) return `${days} 天前`
  return date.toLocaleDateString('zh-CN')
}
</script>

<style scoped lang="scss">
.account-card {
  background: var(--bg-secondary);
  border: 2px solid transparent;
  border-radius: 16px;
  padding: 20px;
  cursor: pointer;
  transition: all 0.2s ease;
  position: relative;

  &:hover:not(.disabled) {
    transform: translateY(-4px);
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.3);
  }

  &.selected {
    border-color: var(--primary);
    box-shadow: 0 0 0 2px rgba(74, 144, 226, 0.2);
  }

  &.disabled {
    opacity: 0.6;
    cursor: not-allowed;
  }

  .card-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 16px;

    .platform-icon {
      width: 48px;
      height: 48px;
      border-radius: 12px;
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 16px;
      font-weight: 700;
      color: white;
      text-shadow: 0 1px 2px rgba(0, 0, 0, 0.2);
    }

    .status-indicator {
      width: 12px;
      height: 12px;
      border-radius: 50%;

      &.status-active {
        background: #4caf50;
        box-shadow: 0 0 8px #4caf50;
      }

      &.status-inactive {
        background: #9e9e9e;
      }

      &.status-expired {
        background: #f44336;
      }
    }
  }

  .card-body {
    margin-bottom: 16px;

    .account-name {
      margin: 0 0 4px 0;
      font-size: 16px;
      font-weight: 600;
      color: var(--text-primary);
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .account-username {
      margin: 0 0 4px 0;
      font-size: 14px;
      color: var(--text-secondary);
    }

    .account-platform {
      margin: 0 0 8px 0;
      font-size: 12px;
      color: var(--text-secondary);
    }

    .auth-time {
      margin: 0;
      font-size: 11px;
      color: var(--text-secondary);
    }
  }

  .card-actions {
    display: flex;
    gap: 8px;
  }
}
</style>
