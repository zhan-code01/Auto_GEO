<template>
  <div class="scheduler-page">
    <!-- 头部 -->
    <header class="page-header">
      <div class="header-left">
        <div class="header-icon">
          <el-icon><Timer /></el-icon>
        </div>
        <div class="header-text">
          <h1 class="page-title">定时任务调度中心</h1>
          <p class="page-desc">动态管理后台任务频率，无需重启服务即刻生效</p>
        </div>
      </div>
      <div class="header-actions">
        <el-button type="primary" @click="loadTasks" :loading="loading">
          <el-icon class="mr-1"><Refresh /></el-icon> 刷新状态
        </el-button>
      </div>
    </header>

    <!-- 任务卡片网格 -->
    <div class="tasks-section" v-loading="loading">
      <el-row :gutter="20">
        <el-col
          v-for="task in tasks"
          :key="task.id"
          :xs="24"
          :sm="12"
          :md="12"
          :lg="8"
          :xl="6"
        >
          <el-card class="task-card" shadow="hover">
            <!-- 卡片头部 -->
            <template #header>
              <div class="card-header">
                <div class="header-left">
                  <div class="task-icon" :class="{ active: task.is_active }">
                    <el-icon>
                      <component :is="getTaskIcon(task.task_key)" />
                    </el-icon>
                  </div>
                  <div>
                    <h3 class="task-name">{{ task.name }}</h3>
                    <div class="status-badge" :class="{ active: task.is_active }">
                      <span class="status-dot"></span>
                      <span class="status-text">{{ task.is_active ? '运行中' : '已暂停' }}</span>
                    </div>
                  </div>
                </div>
                <el-switch
                  v-model="task.is_active"
                  inline-prompt
                  active-text=""
                  inactive-text=""
                  style="--el-switch-on-color: #52c41a; --el-switch-off-color: #d9d9d9"
                  @change="handleStatusChange(task)"
                />
              </div>
            </template>

            <!-- 卡片内容 -->
            <div class="card-content">
              <p class="task-description">{{ task.description }}</p>

              <div class="schedule-info">
                <div class="schedule-icon">
                  <el-icon><Clock /></el-icon>
                </div>
                <div class="schedule-text">
                  <span class="schedule-label">执行频率</span>
                  <span class="schedule-value">{{ formatCronToText(task.cron_expression) }}</span>
                </div>
              </div>
            </div>

            <!-- 卡片底部操作按钮 -->
            <div class="card-footer">
              <el-button
                @click="openEdit(task)"
                class="action-btn"
              >
                <el-icon class="btn-icon"><Edit /></el-icon>
                修改频率
              </el-button>
              <el-divider direction="vertical" />
              <el-button
                @click="triggerTask(task)"
                class="action-btn"
              >
                <el-icon class="btn-icon"><VideoPlay /></el-icon>
                立即执行
              </el-button>
            </div>
          </el-card>
        </el-col>
      </el-row>

      <!-- 空状态 -->
      <el-empty
        v-if="!loading && tasks.length === 0"
        description="暂无定时任务"
        :image-size="120"
      />
    </div>

    <!-- 修改频率对话框 (人性化表单) -->
    <el-dialog
      v-model="showEditDialog"
      title="修改执行频率"
      width="480px"
      destroy-on-close
      :close-on-click-modal="false"
    >
      <el-form label-width="80px" class="edit-form">
        <el-form-item label="任务名称">
          <span class="task-name-display">{{ currentTask.name }}</span>
        </el-form-item>

        <el-form-item label="模式选择">
          <el-radio-group v-model="frequencyMode">
            <el-radio-button label="interval">按间隔</el-radio-button>
            <el-radio-button label="time">按时间</el-radio-button>
          </el-radio-group>
        </el-form-item>

        <!-- 按间隔模式 -->
        <el-form-item label="执行间隔" v-if="frequencyMode === 'interval'">
          <el-input-number
            v-model="intervalMinutes"
            :min="1"
            :max="1440"
            controls-position="right"
            class="interval-input"
          />
          <span class="interval-unit">分钟</span>
        </el-form-item>

        <!-- 按时间模式 -->
        <el-form-item label="执行时间" v-if="frequencyMode === 'time'">
          <el-time-picker
            v-model="executionTime"
            format="HH:mm"
            value-format="HH:mm"
            placeholder="选择执行时间"
            :clearable="false"
            class="time-picker"
          />
        </el-form-item>

        <!-- 预览 -->
        <el-form-item label="频率预览">
          <span class="preview-text">{{ frequencyPreview }}</span>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showEditDialog = false">取消</el-button>
        <el-button type="primary" @click="saveFrequency" :loading="saving">
          <el-icon class="mr-1"><Check /></el-icon> 保存并生效
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import {
  Timer, Refresh, Edit, VideoPlay, Check, Clock,
  Promotion, Search, RefreshLeft, Monitor, Setting
} from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { schedulerApi } from '@/services/api'

interface Task {
  id: number
  name: string
  task_key: string
  cron_expression: string
  is_active: boolean
  description: string
}

const tasks = ref<Task[]>([])
const loading = ref(false)
const saving = ref(false)
const showEditDialog = ref(false)
const currentTask = ref<any>({})

// 频率配置模式：interval=按间隔, time=按时间
const frequencyMode = ref<'interval' | 'time'>('interval')
const intervalMinutes = ref(5)
const executionTime = ref('02:00')

// 任务图标映射
const getTaskIcon = (taskKey: string) => {
  const iconMap: Record<string, any> = {
    'publish_task': Promotion,
    'monitor_task': Search,
    'ai_index_monitor_task': Monitor,
    'auto_publish_scheduler': Timer,
  }
  return iconMap[taskKey] || Setting
}

// Cron 转自然语言
const formatCronToText = (cron: string): string => {
  if (!cron) return '未配置'

  const parts = cron.trim().split(/\s+/)
  if (parts.length !== 5) return '自定义频率'

  const [minute, hour, day, month, weekday] = parts

  // 按间隔执行：*/N * * * *
  const intervalMatch = minute.match(/^\*\/(\d+)$/)
  if (intervalMatch && hour === '*' && day === '*' && month === '*' && weekday === '*') {
    const n = parseInt(intervalMatch[1])
    if (n === 1) return '每 1 分钟执行一次'
    return `每 ${n} 分钟执行一次`
  }

  // 按小时执行：0 * * * *
  if (minute === '0' && hour === '*' && day === '*' && month === '*' && weekday === '*') {
    return '每小时执行一次'
  }

  // 按时间执行：0 H * * *
  const hourMatch = hour.match(/^(\d+)$/)
  if (minute === '0' && hourMatch && day === '*' && month === '*' && weekday === '*') {
    const h = parseInt(hourMatch[1])
    return `每天 ${h.toString().padStart(2, '0')}:00 执行`
  }

  // 工作日特定时间：0 H * * 1-5
  const workdayMatch = weekday.match(/^1-5$/)
  if (minute === '0' && hourMatch && day === '*' && month === '*' && workdayMatch) {
    const h = parseInt(hourMatch[1])
    return `工作日 ${h.toString().padStart(2, '0')}:00 执行`
  }

  return '自定义频率'
}

// 根据配置生成 Cron
const generateCron = (): string => {
  if (frequencyMode.value === 'interval') {
    return `*/${intervalMinutes.value} * * * *`
  } else {
    const [h, m] = executionTime.value.split(':')
    return `${m} ${h} * * *`
  }
}

// 频率预览
const frequencyPreview = computed(() => {
  return formatCronToText(generateCron())
})

// 加载任务列表
const loadTasks = async () => {
  loading.value = true
  try {
    const res = await schedulerApi.getJobs()
    tasks.value = Array.isArray(res) ? res : []
  } catch (error) {
    ElMessage.error('无法连接到调度中心')
  } finally {
    loading.value = false
  }
}

// 切换开关状态
const handleStatusChange = async (row: Task) => {
  try {
    await updateTaskApi(row)
    ElMessage.success(row.is_active ? `任务 [${row.name}] 已启动` : `任务 [${row.name}] 已暂停`)
  } catch (error) {
    row.is_active = !row.is_active // 失败则回滚UI状态
    ElMessage.error('状态更新失败')
  }
}

// 打开编辑
const openEdit = (row: Task) => {
  currentTask.value = { ...row }

  // 解析现有 Cron，设置初始值
  const parts = row.cron_expression.trim().split(/\s+/)
  if (parts.length === 5) {
    const [minute, hour] = parts

    // 判断是否为间隔模式
    const intervalMatch = minute.match(/^\*\/(\d+)$/)
    if (intervalMatch && hour === '*') {
      frequencyMode.value = 'interval'
      intervalMinutes.value = parseInt(intervalMatch[1])
    } else {
      frequencyMode.value = 'time'
      // 解析时间
      if (minute === '0' && hour.match(/^\d+$/)) {
        const h = parseInt(hour).toString().padStart(2, '0')
        executionTime.value = `${h}:00`
      } else {
        // 尝试解析复杂的时间格式
        const hNum = parseInt(hour) || 0
        const mNum = parseInt(minute) || 0
        executionTime.value = `${hNum.toString().padStart(2, '0')}:${mNum.toString().padStart(2, '0')}`
      }
    }
  }

  showEditDialog.value = true
}

// 立即执行任务
const triggerTask = async (task: Task) => {
  try {
    await ElMessageBox.confirm(
      `确定要立即执行任务 "${task.name}" 吗？`,
      '立即执行',
      {
        confirmButtonText: '执行',
        cancelButtonText: '取消',
        type: 'info',
      }
    )
    loading.value = true
    // 使用 task_key 而不是 id，因为 APScheduler 的 Job ID 是 task_key (字符串)
    await schedulerApi.runJob(task.task_key)
    ElMessage.success('任务已触发执行')
  } catch (error: any) {
    if (error !== 'cancel') {
      ElMessage.error('触发执行失败')
    }
  } finally {
    loading.value = false
  }
}

// 保存频率修改
const saveFrequency = async () => {
  saving.value = true
  try {
    const newCron = generateCron()
    const task = {
      ...currentTask.value,
      cron_expression: newCron
    }
    await updateTaskApi(task)
    ElMessage.success('执行频率已更新，下次执行将按新规则')
    showEditDialog.value = false
    loadTasks() // 刷新列表
  } catch (error) {
    ElMessage.error('更新失败')
  } finally {
    saving.value = false
  }
}

// 统一更新接口
const updateTaskApi = async (task: Task) => {
  const payload = {
    cron_expression: task.cron_expression,
    is_active: task.is_active
  }
  await schedulerApi.updateJob(task.id, payload)
}

onMounted(() => {
  loadTasks()
})
</script>

<style scoped lang="scss">
/* ================================================================
   Scheduler — Atelier Lumière Warm Theme
   融入全局暖色设计系统：象牙白底面 + 赭石琥珀主色 + 深青辅助色
   ================================================================ */

.scheduler-page {
  padding: 32px 36px;
  background: var(--surface-base);
  min-height: 100vh;
}

/* ---- Page Header ---- */
.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 26px 32px;
  background:
    linear-gradient(135deg, rgba(196, 116, 28, 0.05), rgba(31, 122, 146, 0.03) 60%, transparent),
    var(--surface-raised);
  border: 1px solid var(--border-thin);
  border-radius: var(--radius-lg);
  margin-bottom: 32px;
  box-shadow: var(--shadow-sm);

  .header-left {
    display: flex;
    align-items: center;
    gap: 18px;

    .header-icon {
      width: 50px;
      height: 50px;
      background: linear-gradient(135deg, #e0941f, var(--accent) 56%, #9c560e);
      border-radius: 14px;
      display: flex;
      align-items: center;
      justify-content: center;
      color: white;
      font-size: 24px;
      box-shadow: 0 4px 16px rgba(196, 116, 28, 0.28);
      flex-shrink: 0;
    }

    .page-title {
      margin: 0 0 4px 0;
      font-family: var(--font-display);
      font-size: 21px;
      font-weight: 700;
      color: var(--text-head);
      letter-spacing: 0.02em;
    }

    .page-desc {
      margin: 0;
      font-size: 13px;
      color: var(--text-muted);
      letter-spacing: 0.01em;
    }
  }

  .header-actions {
    .el-button {
      font-weight: 600;
      letter-spacing: 0.02em;
      border-radius: 10px;
    }
  }
}

/* ---- Task Cards Grid ---- */
.tasks-section {
  min-height: 300px;
}

.task-card {
  height: 100%;
  border: 1px solid var(--border-thin);
  border-radius: var(--radius-lg);
  background: var(--surface-raised);
  overflow: hidden;
  transition:
    transform var(--duration-normal) var(--ease-out),
    box-shadow var(--duration-normal) var(--ease-out),
    border-color var(--duration-fast) var(--ease-out);

  &:hover {
    transform: translateY(-4px);
    box-shadow: 0 12px 32px rgba(74, 53, 24, 0.10), 0 2px 6px rgba(74, 53, 24, 0.04);
    border-color: var(--border-soft);
  }

  :deep(.el-card__header) {
    padding: 20px 24px;
    border-bottom: 1px solid var(--border-thin);
    background: linear-gradient(180deg, rgba(196, 116, 28, 0.025), transparent);
  }

  :deep(.el-card__body) {
    padding: 22px 24px 24px;
  }
}

/* ---- Card Header ---- */
.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;

  .header-left {
    display: flex;
    align-items: center;
    gap: 14px;
    flex: 1;
    min-width: 0;
  }

  .task-icon {
    width: 44px;
    height: 44px;
    flex-shrink: 0;
    background: var(--surface-field);
    border-radius: 12px;
    display: flex;
    align-items: center;
    justify-content: center;
    color: var(--text-muted);
    font-size: 20px;
    transition: all 0.35s var(--ease-out);

    &.active {
      background: linear-gradient(135deg, #e0941f, var(--accent) 56%, #9c560e);
      color: white;
      box-shadow: 0 4px 14px rgba(196, 116, 28, 0.25);
    }
  }

  .task-name {
    margin: 0 0 5px 0;
    font-size: 15px;
    font-weight: 700;
    color: var(--text-head);
    line-height: 1.3;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    letter-spacing: 0.01em;
  }

  .status-badge {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    font-size: 11px;
    font-weight: 600;
    color: var(--text-disabled);
    padding: 3px 10px;
    background: var(--surface-field);
    border-radius: 20px;
    letter-spacing: 0.03em;
    transition: all 0.3s ease;

    &.active {
      color: var(--success);
      background: var(--success-soft);
    }

    .status-dot {
      width: 6px;
      height: 6px;
      border-radius: 50%;
      background: var(--text-disabled);
      transition: all 0.3s ease;

      .status-badge.active & {
        background: var(--success);
        box-shadow: 0 0 8px rgba(63, 138, 82, 0.45);
        animation: pulse-dot 2s ease-in-out infinite;
      }
    }
  }
}

@keyframes pulse-dot {
  0%, 100% { opacity: 1; transform: scale(1); }
  50% { opacity: 0.55; transform: scale(0.85); }
}

/* ---- Card Content ---- */
.card-content {
  .task-description {
    margin: 0 0 18px 0;
    font-size: 13px;
    color: var(--text-muted);
    line-height: 1.7;
    min-height: 44px;
  }

  .schedule-info {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 12px 14px;
    background: var(--surface-field);
    border-radius: var(--radius-md);
    border-left: 3px solid var(--accent);

    .schedule-icon {
      width: 34px;
      height: 34px;
      flex-shrink: 0;
      background: linear-gradient(135deg, var(--accent), #a8620f);
      border-radius: 9px;
      display: flex;
      align-items: center;
      justify-content: center;
      color: white;
      font-size: 16px;
      box-shadow: 0 2px 8px rgba(196, 116, 28, 0.18);
    }

    .schedule-text {
      flex: 1;
      display: flex;
      flex-direction: column;
      gap: 2px;
      min-width: 0;

      .schedule-label {
        font-size: 11px;
        color: var(--text-muted);
        letter-spacing: 0.04em;
        text-transform: uppercase;
      }
      .schedule-value {
        font-size: 14px;
        font-weight: 600;
        color: var(--text-head);
      }
    }
  }
}

/* ---- Card Footer (Action Buttons) ---- */
.card-footer {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  margin-top: 20px;
  padding-top: 18px;
  border-top: 1px solid var(--border-thin);

  .action-btn {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 8px 22px;
    font-size: 13px;
    font-weight: 600;
    letter-spacing: 0.03em;
    border-radius: 10px;
    transition: all var(--duration-fast) var(--ease-out);

    /* 主要按钮 - 立即执行 */
    &:last-child {
      background: linear-gradient(135deg, #e0941f, var(--accent) 56%, #9c560e) !important;
      color: #fff !important;
      border: none !important;
      box-shadow: 0 3px 12px rgba(196, 116, 28, 0.22);

      &:hover {
        box-shadow: 0 6px 20px rgba(196, 116, 28, 0.32);
        transform: translateY(-2px);
        filter: brightness(1.06);
      }

      &:active {
        transform: translateY(0);
        box-shadow: 0 2px 6px rgba(196, 116, 28, 0.18);
        filter: brightness(0.97);
      }
    }

    /* 次要按钮 - 修改频率 */
    &:first-child {
      background: var(--surface-raised) !important;
      color: var(--text-body) !important;
      border: 1px solid var(--border-soft) !important;
      box-shadow: 0 1px 4px rgba(74, 53, 24, 0.05);

      &:hover {
        border-color: var(--accent) !important;
        color: var(--accent) !important;
        background: var(--accent-soft) !important;
        transform: translateY(-1px);
        box-shadow: 0 4px 12px rgba(196, 116, 28, 0.12);
      }

      &:active {
        transform: translateY(0);
        box-shadow: 0 1px 2px rgba(0, 0, 0, 0.06);
      }
    }

    .btn-icon {
      font-size: 14px;
      transition: transform var(--duration-fast) var(--ease-out);
    }

    &:hover .btn-icon {
      transform: scale(1.1);
    }
  }

  :deep(.el-divider--vertical) {
    height: 16px;
    margin: 0;
    border-color: var(--border-thin);
    opacity: 0.5;
  }
}

/* ---- Edit Dialog Form ---- */
.edit-form {
  .task-name-display {
    font-size: 15px;
    font-weight: 600;
    color: var(--text-head);
    font-family: var(--font-display);
  }
  .interval-input { width: 140px; }
  .interval-unit { margin-left: 8px; color: var(--text-muted); }
  .time-picker { width: 100%; }

  .preview-text {
    font-size: 14px;
    font-weight: 600;
    color: var(--accent);
    padding: 8px 14px;
    background: var(--accent-soft);
    border: 1px solid var(--border-accent);
    border-radius: var(--radius-sm);
    display: inline-block;
  }
}

.mr-1 { margin-right: 4px; }
</style>
