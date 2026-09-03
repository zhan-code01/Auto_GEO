<template>
  <div class="project-sidebar" :class="{ collapsed: isCollapsed }">
    <!-- 折叠按钮 -->
    <div class="collapse-btn" @click="toggleCollapse">
      <el-icon :size="16">
        <component :is="isCollapsed ? 'ArrowRight' : 'ArrowLeft'" />
      </el-icon>
    </div>

    <!-- 头部 -->
    <div v-if="!isCollapsed" class="sidebar-header">
      <div class="header-title">
        <el-icon><FolderOpened /></el-icon>
        <span>项目管理</span>
      </div>
      <el-button
        type="primary"
        size="small"
        :icon="Plus"
        @click="showCreateDialog = true"
      >
        新建项目
      </el-button>
    </div>

    <!-- 项目列表 -->
    <div v-if="!isCollapsed" class="project-list">
      <div
        v-for="project in projects"
        :key="project.id"
        class="project-item"
        :class="{ active: modelValue === project.id }"
        @click="selectProject(project.id)"
      >
        <div class="project-info">
          <div class="project-name">{{ project.name }}</div>
          <div class="project-meta">
            <span class="company-name">{{ project.company_name }}</span>
            <el-tag v-if="project.industry" size="small" type="info">
              {{ project.industry }}
            </el-tag>
          </div>
        </div>
        <el-dropdown trigger="click" @command="(cmd) => handleCommand(cmd, project)">
          <el-icon class="more-btn"><MoreFilled /></el-icon>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="edit">编辑</el-dropdown-item>
              <el-dropdown-item command="delete" divided>删除</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </div>

      <!-- 空状态 -->
      <div v-if="!loading && projects.length === 0" class="empty-state">
        <el-empty description="暂无项目" :image-size="80" />
      </div>

      <!-- 加载状态 -->
      <div v-if="loading" class="loading-state">
        <el-icon class="is-loading"><Loading /></el-icon>
        <span>加载中...</span>
      </div>
    </div>

    <!-- 折叠状态 -->
    <div v-else class="collapsed-view">
      <el-tooltip
        v-for="project in projects.slice(0, 5)"
        :key="project.id"
        :content="`${project.name} - ${project.company_name}`"
        placement="right"
      >
        <div
          class="collapsed-item"
          :class="{ active: modelValue === project.id }"
          @click="selectProject(project.id)"
        >
          <span class="project-initial">{{ getInitial(project.name) }}</span>
        </div>
      </el-tooltip>
      <el-button
        class="add-project-btn"
        type="primary"
        :icon="Plus"
        circle
        size="small"
        @click="showCreateDialog = true"
      />
    </div>

    <!-- 创建项目对话框 -->
    <el-dialog
      v-model="showCreateDialog"
      :title="editingProject ? '编辑项目' : '创建项目'"
      width="500px"
      :close-on-click-modal="false"
    >
      <el-form :model="projectForm" label-width="90px" @submit.prevent="saveProject">
        <el-form-item label="项目名称" required>
          <el-input
            v-model="projectForm.name"
            placeholder="如：绿阳环保获客项目"
            clearable
          />
        </el-form-item>
        <el-form-item label="公司名称" required>
          <el-input
            v-model="projectForm.company_name"
            placeholder="如：绿阳环保科技有限公司"
            clearable
          />
        </el-form-item>
        <el-form-item label="所属行业">
          <el-select
            v-model="projectForm.industry"
            placeholder="选择行业"
            allow-create
            filterable
            style="width: 100%"
          >
            <el-option
              v-for="ind in industries"
              :key="ind"
              :label="ind"
              :value="ind"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="项目描述">
          <el-input
            v-model="projectForm.description"
            type="textarea"
            :rows="3"
            placeholder="简要描述项目背景和目标"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showCreateDialog = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveProject">
          {{ editingProject ? '保存' : '创建' }}
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  FolderOpened,
  Plus,
  ArrowLeft,
  ArrowRight,
  MoreFilled,
  Loading,
} from '@element-plus/icons-vue'
import { geoKeywordApi } from '@/services/api'

// 行业列表
const industries = [
  'SaaS软件',
  '电商',
  '教育',
  '金融',
  '医疗',
  '制造业',
  '房地产',
  '餐饮',
  '旅游',
  '物流',
  '环保',
  '新能源',
  '化工',
  '建筑',
  '其他',
]

// ==================== 类型定义 ====================
interface Project {
  id: number
  name: string
  company_name: string
  description?: string
  industry?: string
  status: number
  created_at: string
}

// ==================== Props ====================
const modelValue = defineModel<number | null>()

// ==================== 状态 ====================
const projects = ref<Project[]>([])
const loading = ref(false)
const saving = ref(false)
const isCollapsed = ref(false)
const showCreateDialog = ref(false)
const editingProject = ref<Project | null>(null)

const projectForm = ref({
  name: '',
  company_name: '',
  industry: '',
  description: '',
})

// ==================== 方法 ====================

// 加载项目列表
const loadProjects = async () => {
  loading.value = true
  try {
    const result = await geoKeywordApi.getProjects()
    projects.value = result || []
    // 如果有项目且没有选中，默认选中第一个
    if (projects.value.length > 0 && !modelValue.value) {
      modelValue.value = projects.value[0].id
    }
  } catch (error) {
    console.error('加载项目失败:', error)
    ElMessage.error('加载项目失败')
  } finally {
    loading.value = false
  }
}

// 选择项目
const selectProject = (projectId: number) => {
  modelValue.value = projectId
}

// 折叠/展开
const toggleCollapse = () => {
  isCollapsed.value = !isCollapsed.value
}

// 获取项目首字母
const getInitial = (name: string) => {
  return name.charAt(0).toUpperCase()
}

// 处理下拉菜单命令
const handleCommand = (command: string, project: Project) => {
  if (command === 'edit') {
    editProject(project)
  } else if (command === 'delete') {
    deleteProject(project)
  }
}

// 编辑项目
const editProject = (project: Project) => {
  editingProject.value = project
  projectForm.value = {
    name: project.name,
    company_name: project.company_name,
    industry: project.industry || '',
    description: project.description || '',
  }
  showCreateDialog.value = true
}

// 删除项目
const deleteProject = async (project: Project) => {
  try {
    await ElMessageBox.confirm(
      `确定要删除项目"${project.name}"吗？删除后关联的关键词和文章也将被删除！`,
      '确认删除',
      { type: 'warning', confirmButtonText: '确定删除', cancelButtonText: '取消' }
    )

    await geoKeywordApi.deleteProject(project.id)
    projects.value = projects.value.filter(p => p.id !== project.id)

    // 如果删除的是当前选中的项目，选中第一个
    if (modelValue.value === project.id && projects.value.length > 0) {
      modelValue.value = projects.value[0].id
    } else if (projects.value.length === 0) {
      modelValue.value = null
    }

    ElMessage.success('项目已删除')
  } catch (error) {
    if (error !== 'cancel') {
      console.error('删除项目失败:', error)
      ElMessage.error('删除项目失败')
    }
  }
}

// 保存项目
const saveProject = async () => {
  // 验证表单
  if (!projectForm.value.name?.trim()) {
    ElMessage.warning('请输入项目名称')
    return
  }
  if (!projectForm.value.company_name?.trim()) {
    ElMessage.warning('请输入公司名称')
    return
  }

  saving.value = true
  try {
    if (editingProject.value) {
      // 更新项目
      await geoKeywordApi.updateProject(editingProject.value.id, projectForm.value)
      const index = projects.value.findIndex(p => p.id === editingProject.value!.id)
      if (index !== -1) {
        projects.value[index] = { ...projects.value[index], ...projectForm.value }
      }
      ElMessage.success('项目已更新')
    } else {
      // 创建项目
      const result = await geoKeywordApi.createProject(projectForm.value)
      projects.value.unshift(result)
      modelValue.value = result.id
      ElMessage.success('项目创建成功')
    }

    showCreateDialog.value = false
    resetForm()
  } catch (error) {
    console.error('保存项目失败:', error)
    ElMessage.error('保存项目失败')
  } finally {
    saving.value = false
  }
}

// 重置表单
const resetForm = () => {
  editingProject.value = null
  projectForm.value = {
    name: '',
    company_name: '',
    industry: '',
    description: '',
  }
}

// 刷新项目列表
const refresh = () => {
  loadProjects()
}

// 暴露方法供父组件调用
defineExpose({
  refresh,
})

// ==================== 生命周期 ====================
onMounted(() => {
  loadProjects()
})
</script>

<style scoped lang="scss">
.project-sidebar {
  position: relative;
  width: 280px;
  height: 100%;
  background: var(--bg-secondary);
  border-right: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  transition: width 0.3s;

  &.collapsed {
    width: 60px;
  }
}

.collapse-btn {
  position: absolute;
  top: 12px;
  right: -12px;
  width: 24px;
  height: 24px;
  background: var(--color-primary);
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  z-index: 10;
  color: white;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.15);

  &:hover {
    transform: scale(1.1);
  }
}

.sidebar-header {
  padding: 16px;
  border-bottom: 1px solid var(--border);

  .header-title {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 12px;
    font-size: 15px;
    font-weight: 500;
    color: var(--text-primary);
  }
}

.project-list {
  flex: 1;
  overflow-y: auto;
  padding: 8px;
}

.project-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px;
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.2s;
  margin-bottom: 4px;

  &:hover {
    background: var(--bg-tertiary);
  }

  &.active {
    background: rgba(64, 158, 255, 0.15);
    border-left: 3px solid var(--color-primary);

    .project-name {
      color: var(--color-primary);
      font-weight: 500;
    }
  }

  .project-info {
    flex: 1;
    min-width: 0;
  }

  .project-name {
    font-size: 14px;
    color: var(--text-primary);
    margin-bottom: 4px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .project-meta {
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 12px;

    .company-name {
      color: var(--text-muted);
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
  }

  .more-btn {
    color: var(--text-muted);
    padding: 4px;
    border-radius: 4px;

    &:hover {
      background: var(--bg-tertiary);
      color: var(--text-secondary);
    }
  }
}

.empty-state,
.loading-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 40px 20px;
  color: var(--text-muted);

  .el-icon {
    font-size: 24px;
    margin-bottom: 8px;
  }
}

.collapsed-view {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 50px 8px 8px;
  gap: 8px;

  .collapsed-item {
    width: 40px;
    height: 40px;
    border-radius: 8px;
    display: flex;
    align-items: center;
    justify-content: center;
    background: var(--bg-tertiary);
    cursor: pointer;
    transition: all 0.2s;

    &:hover {
      background: rgba(64, 158, 255, 0.1);
    }

    &.active {
      background: var(--color-primary);
      color: white;
    }

    .project-initial {
      font-size: 16px;
      font-weight: 500;
    }
  }

  .add-project-btn {
    margin-top: 8px;
  }
}

// 滚动条样式
.project-list::-webkit-scrollbar {
  width: 4px;
}

.project-list::-webkit-scrollbar-track {
  background: transparent;
}

.project-list::-webkit-scrollbar-thumb {
  background: var(--border);
  border-radius: 2px;

  &:hover {
    background: var(--text-muted);
  }
}
</style>
