<template>
  <div class="progress-card" :class="`status-${task.status}`">
    <div class="progress-header">
      <div class="task-info">
        <span class="article-title">{{ task.articleTitle }}</span>
        <el-icon class="arrow"><Right /></el-icon>
        <PlatformIcon :platform="task.platform" :size="24" />
        <span class="account-name">{{ task.accountName }}</span>
      </div>
      <div class="task-status">
        <el-icon v-if="task.status === 0" class="is-loading spin"><Loading /></el-icon>
        <el-icon v-else-if="task.status === 2" class="success-icon"><CircleCheck /></el-icon>
        <el-icon v-else-if="task.status === 3" class="error-icon"><CircleClose /></el-icon>
      </div>
    </div>

    <div v-if="task.status === 0" class="progress-bar">
      <el-progress :percentage="100" :show-text="false" :indeterminate="true" />
    </div>

    <div v-if="task.errorMsg" class="error-message">
      <el-icon><Warning /></el-icon>
      <span>{{ task.errorMsg }}</span>
    </div>

    <div v-if="task.platformUrl" class="success-link">
      <el-link type="primary" :href="task.platformUrl" target="_blank">
        查看文章 <el-icon><TopRight /></el-icon>
      </el-link>
    </div>
  </div>
</template>

<script setup lang="ts">
import { Right, Loading, CircleCheck, CircleClose, Warning, TopRight } from '@element-plus/icons-vue'
import PlatformIcon from '@/components/business/account/PlatformIcon.vue'
import type { PublishTask } from '@/types'

interface Props {
  task: PublishTask
}

defineProps<Props>()
</script>

<style scoped lang="scss">
.progress-card {
  background: var(--bg-secondary);
  border: 2px solid transparent;
  border-radius: 12px;
  padding: 16px;
  margin-bottom: 12px;
  transition: all 0.3s;

  &.status-0 {
    border-left: 3px solid var(--warning);
  }

  &.status-1 {
    border-left: 3px solid var(--primary);
  }

  &.status-2 {
    border-left: 3px solid var(--success);
    background: rgba(76, 175, 80, 0.05);
  }

  &.status-3 {
    border-left: 3px solid var(--danger);
    background: rgba(229, 57, 53, 0.05);
  }

  .progress-header {
    display: flex;
    justify-content: space-between;
    align-items: center;

    .task-info {
      display: flex;
      align-items: center;
      gap: 8px;
      flex: 1;
      min-width: 0;

      .article-title {
        font-weight: 500;
        color: var(--text-primary);
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
      }

      .arrow {
        color: var(--text-secondary);
        flex-shrink: 0;
      }

      .account-name {
        font-size: 14px;
        color: var(--text-secondary);
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
      }
    }

    .task-status {
      .el-icon {
        font-size: 20px;

        &.spin {
          animation: spin 1s linear infinite;
        }

        &.success-icon {
          color: var(--success);
        }

        &.error-icon {
          color: var(--danger);
        }
      }
    }
  }

  .progress-bar {
    margin-top: 12px;
  }

  .error-message {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-top: 12px;
    padding: 8px 12px;
    background: rgba(229, 57, 53, 0.1);
    border-radius: 6px;
    color: var(--danger);
    font-size: 14px;

    .el-icon {
      flex-shrink: 0;
    }
  }

  .success-link {
    margin-top: 12px;
  }
}

@keyframes spin {
  from {
    transform: rotate(0deg);
  }
  to {
    transform: rotate(360deg);
  }
}
</style>
