<template>
  <div class="project-manager">
    <!-- 头部 -->
    <div class="manager-header">
      <div class="header-left">
        <div class="header-icon">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M3 3h18v18H3zM9 3v18M15 3v18M3 9h18M3 15h18"/>
          </svg>
        </div>
        <div>
          <h3 class="header-title">GEO 项目</h3>
          <span class="header-count">{{ projects.length }} 个项目</span>
        </div>
      </div>
      <el-button
        type="primary"
        size="small"
        :icon="PlusIcon"
        @click="showCreateDialog = true"
      >
        新建
      </el-button>
    </div>

    <!-- 项目列表 -->
    <div class="project-list">
      <div
        v-for="project in projects"
        :key="project.id"
        class="project-card"
        :class="{ active: modelValue === project.id, loading: project.loading }"
        @click="selectProject(project)"
      >
        <!-- 顶部：徽标 + 名称 + 操作 -->
        <div class="card-top">
          <div class="project-avatar" :style="{ background: getAvatarColor(project.name) }">
            {{ getProjectInitial(project.name) }}
          </div>
          <div class="project-main">
            <h4 class="project-name">{{ project.name }}</h4>
            <span v-if="project.company_name && !isNumericId(project.company_name)" class="project-company">
              <svg viewBox="0 0 16 16" fill="currentColor" width="11"><path d="M8 1a4 4 0 00-4 4v2H2v2h2v6a2 2 0 002 2h4a2 2 0 002-2V9h2V7h-2V5a4 4 0 00-4-4zm0 2a2 2 0 012 2v2H6V5a2 2 0 012-2z"/></svg>
              {{ project.company_name }}
            </span>
          </div>
          <el-dropdown trigger="click" @click.stop>
            <div class="more-btn">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
                <circle cx="12" cy="12" r="1"/><circle cx="12" cy="5" r="1"/><circle cx="12" cy="19" r="1"/>
              </svg>
            </div>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item @click.stop="editProject(project)">
                  <el-icon><Edit /></el-icon> 编辑
                </el-dropdown-item>
                <el-dropdown-item divided @click.stop="deleteProject(project)">
                  <el-icon><Delete /></el-icon> 删除
                </el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>

        <!-- 领域关键词 -->
        <div v-if="project.domain_keyword" class="card-keyword-row">
          <svg viewBox="0 0 16 16" fill="currentColor" width="12"><path d="M8 2L2 8l6 6 6-6-6-6zm0 2.83L11.17 8 8 11.17 4.83 8 8 4.83z"/></svg>
          <span class="keyword-text">{{ project.domain_keyword }}</span>
        </div>

        <!-- 底部：统计 + 当前指示 -->
        <div class="card-bottom">
          <div class="meta-tags">
            <span class="meta-tag">
              <svg viewBox="0 0 16 16" fill="currentColor" width="11"><path d="M8 2a6 6 0 100 12A6 6 0 008 2zm0 10a4 4 0 110-8 4 4 0 010 8z"/></svg>
              {{ getKeywordCount(project.id) }} 个关键词
            </span>
            <span v-if="project.industry" class="meta-tag industry">{{ project.industry }}</span>
          </div>
          <div v-if="modelValue === project.id" class="active-pill">
            <span class="active-dot"></span>当前
          </div>
        </div>
      </div>

      <!-- 空状态 -->
      <div v-if="!loading && projects.length === 0" class="empty-state">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
          <path d="M9 17h6M9 13h6M9 9h6M5 21h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v14a2 2 0 002 2z"/>
        </svg>
        <p>还没有项目</p>
        <el-button size="small" @click="showCreateDialog = true">创建第一个项目</el-button>
      </div>

      <!-- 加载状态 -->
      <div v-if="loading && projects.length === 0" class="loading-state">
        <div v-for="i in 3" :key="i" class="skeleton-card">
          <div class="skeleton-header">
            <div class="skeleton-badge"></div>
            <div class="skeleton-text"></div>
          </div>
          <div class="skeleton-keyword"></div>
        </div>
      </div>
    </div>

    <!-- 创建/编辑项目对话框 -->
    <el-dialog
      v-model="showCreateDialog"
      :title="editingProject ? '编辑GEO项目' : '创建GEO项目'"
      width="480px"
      :close-on-click-modal="false"
      class="project-dialog"
    >
      <el-form :model="projectForm" label-position="top" @submit.prevent="saveProject">
        <el-form-item label="项目名称" required>
          <el-input
            v-model="projectForm.name"
            placeholder="如：绿阳环保无人机清洗"
            clearable
            size="large"
          >
            <template #prefix>
              <svg viewBox="0 0 16 16" fill="currentColor" width="16">
                <path d="M4 2h8a2 2 0 012 2v8a2 2 0 01-2 2H4a2 2 0 01-2-2V4a2 2 0 012-2z"/>
              </svg>
            </template>
          </el-input>
        </el-form-item>

        <el-form-item label="公司名称" required>
          <el-select
            v-model="projectForm.client_id"
            placeholder="请选择已创建的公司"
            filterable
            clearable
            style="width: 100%"
            size="large"
          >
            <template #prefix>
              <svg viewBox="0 0 16 16" fill="currentColor" width="16">
                <path d="M8 1a4 4 0 00-4 4v2H2v2h2v6a2 2 0 002 2h4a2 2 0 002-2V9h2V7h-2V5a4 4 0 00-4-4zm0 2a2 2 0 012 2v2H6V5a2 2 0 012-2z"/>
              </svg>
            </template>
            <el-option
              v-for="client in clients"
              :key="client.id"
              :label="client.company_name"
              :value="client.id"
            />
          </el-select>
        </el-form-item>

        <el-form-item label="领域关键词" required>
          <el-input
            v-model="projectForm.domain_keyword"
            placeholder="如：无人机清洗"
            clearable
            size="large"
          >
            <template #prefix>
              <svg viewBox="0 0 16 16" fill="currentColor" width="16">
                <path d="M6.5 2a.5.5 0 01.5.5v1a.5.5 0 01-.5.5h-1a.5.5 0 01-.5-.5v-1a.5.5 0 01.5-.5h1zm3 0a.5.5 0 01.5.5v1a.5.5 0 01-.5.5h-1a.5.5 0 01-.5-.5v-1a.5.5 0 01.5-.5h1zM3 5.5A.5.5 0 013.5 5h9a.5.5 0 010 1h-9a.5.5 0 01-.5-.5zM6.5 7a.5.5 0 01.5.5v1a.5.5 0 01-.5.5h-1a.5.5 0 01-.5-.5v-1a.5.5 0 01.5-.5h1zm3 0a.5.5 0 01.5.5v1a.5.5 0 01-.5.5h-1a.5.5 0 01-.5-.5v-1a.5.5 0 01.5-.5h1z"/>
              </svg>
            </template>
          </el-input>
          <div class="form-tip">此关键词将用于AI蒸馏生成提问句</div>
        </el-form-item>

        <el-form-item label="所属行业">
          <el-select
            v-model="projectForm.industry"
            placeholder="选择行业"
            allow-create
            filterable
            style="width: 100%"
            size="large"
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
            :rows="2"
            placeholder="简要描述项目背景和目标（可选）"
          />
        </el-form-item>
      </el-form>

      <template #footer>
        <el-button @click="showCreateDialog = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveProject">
          {{ editingProject ? '保存修改' : '创建项目' }}
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Edit, Delete, Plus as PlusIcon } from '@element-plus/icons-vue'
import { geoKeywordApi, clientApi } from '@/services/api'

// 行业列表
const industries = [
  'SaaS软件',
  '环保工程',
  '工业清洗',
  '无人机服务',
  '电商',
  '教育培训',
  '金融服务',
  '医疗健康',
  '制造业',
  '房地产',
  '餐饮美食',
  '旅游出行',
  '物流运输',
  '新能源',
  '化工行业',
  '建筑工程',
  '其他',
]

// ==================== 类型定义 ====================
interface Client {
  id: number
  name: string
  company_name: string
}

interface Project {
  id: number
  client_id?: number
  name: string
  company_name: string
  domain_keyword?: string
  description?: string
  industry?: string
  status: number
  loading?: boolean
  created_at: string
}

// ==================== Props ====================
const modelValue = defineModel<number | null>()

// ==================== 状态 ====================
const projects = ref<Project[]>([])
const loading = ref(false)
const saving = ref(false)
const showCreateDialog = ref(false)
const editingProject = ref<Project | null>(null)

const clients = ref<Client[]>([])

const projectForm = ref({
  name: '',
  client_id: undefined as number | undefined,
  company_name: '',
  domain_keyword: '',
  industry: '',
  description: '',
})

// ==================== 方法 ====================

// 加载客户列表（用于公司名称下拉选择）
const loadClients = async () => {
  try {
    const result: any = await clientApi.getList({ limit: 100 })
    const list = result?.items || []
    clients.value = list.map((c: any) => ({
      id: c.id,
      name: c.name || c.company_name,
      company_name: c.company_name || c.name,
    }))
  } catch (error) {
    console.error('加载客户列表失败:', error)
    clients.value = []
  }
}

// 加载项目列表
const loadProjects = async () => {
  loading.value = true
  try {
    const result = await geoKeywordApi.getProjects()
    projects.value = (result || []).map((p: Project) => ({ ...p, loading: false }))

    // 默认选中第一个项目
    if (projects.value.length > 0 && !modelValue.value) {
      modelValue.value = projects.value[0].id
    }
  } catch (error) {
    console.error('加载项目失败:', error)
  } finally {
    loading.value = false
  }
}

// 选择项目
const selectProject = (project: Project) => {
  modelValue.value = project.id
}

// 获取项目首字母
const getProjectInitial = (name: string) => {
  return name.charAt(0).toUpperCase()
}

// 根据项目名生成渐变色（固定色板，保证同一名字颜色一致）
const avatarColors = [
  'linear-gradient(135deg, #6366f1, #8b5cf6)',
  'linear-gradient(135deg, #3b82f6, #06b6d4)',
  'linear-gradient(135deg, #ec4899, #f43f5e)',
  'linear-gradient(135deg, #f59e0b, #ef4444)',
  'linear-gradient(135deg, #10b981, #14b8a6)',
  'linear-gradient(135deg, #8b5cf6, #ec4899)',
  'linear-gradient(135deg, #0ea5e9, #6366f1)',
  'linear-gradient(135deg, #f97316, #eab308)',
]
const getAvatarColor = (name: string) => {
  let hash = 0
  for (let i = 0; i < name.length; i++) hash = name.charCodeAt(i) + ((hash << 5) - hash)
  return avatarColors[Math.abs(hash) % avatarColors.length]
}

// 判断 company_name 是否为纯数字 ID（如 "662146436"）
const isNumericId = (val: string) => {
  return /^\d{6,}$/.test(val.trim())
}

// 获取项目关键词数量（从父组件传递的数据中获取）
const getKeywordCount = (projectId: number) => {
  // 这里需要从父组件或store中获取
  return 0
}

// 编辑项目
const editProject = (project: Project) => {
  editingProject.value = project
  const clientId =
    project.client_id ??
    clients.value.find((c) => c.company_name === project.company_name)?.id
  projectForm.value = {
    name: project.name,
    client_id: clientId,
    company_name: project.company_name,
    domain_keyword: project.domain_keyword || '',
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
  // 根据选中的客户推导公司名称
  const selectedClient = clients.value.find(
    (c) => c.id === projectForm.value.client_id
  )
  const companyName = selectedClient
    ? selectedClient.company_name
    : projectForm.value.company_name

  // 验证表单
  if (!projectForm.value.name?.trim()) {
    ElMessage.warning('请输入项目名称')
    return
  }
  if (!companyName?.trim()) {
    ElMessage.warning('请选择公司名称')
    return
  }
  if (!projectForm.value.domain_keyword?.trim()) {
    ElMessage.warning('请输入领域关键词')
    return
  }

  saving.value = true
  try {
    if (editingProject.value) {
      // 更新项目
      await geoKeywordApi.updateProject(editingProject.value.id, {
        client_id: projectForm.value.client_id,
        name: projectForm.value.name,
        company_name: companyName,
        domain_keyword: projectForm.value.domain_keyword,
        industry: projectForm.value.industry,
        description: projectForm.value.description,
      })
      const index = projects.value.findIndex(p => p.id === editingProject.value!.id)
      if (index !== -1) {
        projects.value[index] = {
          ...projects.value[index],
          client_id: projectForm.value.client_id,
          name: projectForm.value.name,
          company_name: companyName,
          domain_keyword: projectForm.value.domain_keyword,
          industry: projectForm.value.industry,
          description: projectForm.value.description,
        }
      }
      ElMessage.success('项目已更新')
    } else {
      // 创建项目
      const result = await geoKeywordApi.createProject({
        client_id: projectForm.value.client_id,
        name: projectForm.value.name,
        company_name: companyName,
        domain_keyword: projectForm.value.domain_keyword,
        industry: projectForm.value.industry,
        description: projectForm.value.description,
      })
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
    client_id: undefined,
    company_name: '',
    domain_keyword: '',
    industry: '',
    description: '',
  }
}

// 刷新项目列表
const refresh = () => {
  loadProjects()
}

// 暴露方法给父组件
defineExpose({ refresh, projects })

// 对话框打开时刷新客户列表
watch(showCreateDialog, (visible) => {
  if (visible) {
    loadClients()
  }
})

// ==================== 生命周期 ====================
onMounted(() => {
  loadProjects()
  loadClients()
})
</script>

<style scoped lang="scss">
/* ================================================================
   Project Manager — Modern Card Design
   ================================================================ */

.project-manager {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: var(--surface-base, #f5f6fa);
}

/* ── Header ── */
.manager-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 18px 20px;
  background: var(--surface-raised, #fff);
  border-bottom: 1px solid var(--border-thin, rgba(0,0,0,0.06));

  .header-left {
    display: flex;
    align-items: center;
    gap: 12px;

    .header-icon {
      width: 38px;
      height: 38px;
      border-radius: 10px;
      background: linear-gradient(135deg, #4f46e5, #7c3aed);
      display: flex;
      align-items: center;
      justify-content: center;
      color: #fff;
      svg { width: 19px; height: 19px; }
    }

    .header-title {
      margin: 0;
      font-size: 15px;
      font-weight: 650;
      color: var(--text-head, #111827);
      letter-spacing: -0.01em;
    }
    .header-count {
      font-size: 11.5px;
      color: var(--text-muted, #9ca3af);
      margin-top: 1px;
    }
  }
}

/* ── List Container ── */
.project-list {
  flex: 1;
  overflow-y: auto;
  padding: 14px;
  display: flex;
  flex-direction: column;
  gap: 10px;

  &::-webkit-scrollbar { width: 4px; }
  &::-webkit-scrollbar-track { background: transparent; }
  &::-webkit-scrollbar-thumb {
    background: rgba(0,0,0,0.12);
    border-radius: 3px;
    &:hover { background: rgba(0,0,0,0.2); }
  }
}

/* ── Project Card ── */
.project-card {
  position: relative;
  background: var(--surface-raised, #fff);
  border-radius: 14px;
  padding: 16px 18px;
  cursor: pointer;
  transition: all 0.22s cubic-bezier(.4,0,.2,1);
  border: 1.5px solid transparent;
  box-shadow:
    0 1px 2px rgba(0,0,0,0.04),
    0 4px 12px rgba(0,0,0,0.03);

  &:hover {
    border-color: rgba(99,102,241,0.25);
    box-shadow:
      0 4px 12px rgba(99,102,241,0.1),
      0 1px 3px rgba(0,0,0,0.05);
    transform: translateY(-1.5px);
  }

  &.active {
    border-color: rgba(99,102,241,0.45);
    background: linear-gradient(135deg, rgba(99,102,241,0.04) 0%, rgba(139,92,246,0.02) 100%);
    box-shadow:
      0 0 0 1px rgba(99,102,241,0.12),
      0 4px 16px rgba(99,102,241,0.08);

    .project-avatar {
      box-shadow: 0 4px 12px rgba(99,102,241,0.35);
    }
  }
}

/* ── Card Top Row ── */
.card-top {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
}

.project-avatar {
  width: 42px;
  height: 42px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 700;
  font-size: 17px;
  color: #fff;
  flex-shrink: 0;
  transition: box-shadow 0.25s ease;
  letter-spacing: -0.02em;
}

.project-main {
  flex: 1;
  min-width: 0;

  .project-name {
    margin: 0 0 3px 0;
    font-size: 14.5px;
    font-weight: 600;
    color: var(--text-head, #111827);
    letter-spacing: -0.01em;
    line-height: 1.3;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .project-company {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    font-size: 11.5px;
    color: var(--text-muted, #9ca3af);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    max-width: 200px;

    svg { flex-shrink: 0; opacity: 0.65; }
  }
}

.more-btn {
  width: 28px;
  height: 28px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--text-muted, #9ca3af);
  cursor: pointer;
  transition: all 0.18s;
  flex-shrink: 0;

  &:hover {
    background: rgba(0,0,0,0.05);
    color: #6366f1;
  }
  svg { width: 15px; height: 15px; }
}

/* ── Keyword Row ── */
.card-keyword-row {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 5px 11px;
  background: linear-gradient(135deg, rgba(99,102,241,0.07), rgba(139,92,246,0.04));
  border: 1px solid rgba(99,102,241,0.09);
  border-radius: 8px;
  margin-bottom: 12px;
  max-width: 100%;

  svg { flex-shrink: 0; color: #6366f1; opacity: 0.7; }

  .keyword-text {
    font-size: 12px;
    font-weight: 500;
    color: #4338ca;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
}

/* ── Card Bottom ── */
.card-bottom {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding-top: 10px;
  border-top: 1px solid rgba(0,0,0,0.04);
}

.meta-tags {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.meta-tag {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 11px;
  color: var(--text-muted, #9ca3af);
  padding: 3px 8px;
  background: rgba(0,0,0,0.03);
  border-radius: 6px;
  line-height: 1.4;

  svg { flex-shrink: 0; opacity: 0.55; }

  &.industry {
    background: linear-gradient(135deg, rgba(245,158,11,0.08), rgba(245,158,11,0.03));
    color: #b45309;
    font-weight: 500;
  }
}

.active-pill {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 11px;
  font-weight: 600;
  color: #4f46e5;
  padding: 3px 10px;
  background: rgba(79,70,229,0.08);
  border-radius: 20px;
  white-space: nowrap;
}

.active-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #4f46e5;
  animation: pulse-dot 2s infinite;
}

/* ── Empty State ── */
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 48px 20px;
  text-align: center;

  svg {
    width: 52px;
    height: 52px;
    color: #d1d5db;
    margin-bottom: 14px;
    opacity: 0.7;
  }
  p {
    margin: 0 0 18px 0;
    font-size: 14px;
    color: #9ca3af;
    font-weight: 500;
  }
}

/* ── Skeleton Loading ── */
.loading-state {
  display: flex;
  flex-direction: column;
  gap: 10px;

  .skeleton-card {
    background: var(--surface-raised, #fff);
    border-radius: 14px;
    padding: 16px 18px;

    .skeleton-header {
      display: flex;
      align-items: center;
      gap: 12px;
      margin-bottom: 12px;

      .skeleton-badge {
        width: 42px;
        height: 42px;
        border-radius: 12px;
        background: linear-gradient(90deg, #eef0f4 25%, #e2e5eb 50%, #eef0f4 75%);
        background-size: 200% 100%;
        animation: shimmer 1.6s infinite;
      }
      .skeleton-text {
        flex: 1;
        height: 14px;
        border-radius: 5px;
        background: linear-gradient(90deg, #eef0f4 25%, #e2e5eb 50%, #eef0f4 75%);
        background-size: 200% 100%;
        animation: shimmer 1.6s infinite;
      }
    }
    .skeleton-keyword {
      width: 55%;
      height: 26px;
      border-radius: 8px;
      background: linear-gradient(90deg, #eef0f4 25%, #e2e5eb 50%, #eef0f4 75%);
      background-size: 200% 100%;
      animation: shimmer 1.6s infinite;
    }
  }
}

/* ── Dialog ── */
.form-tip {
  margin-top: 6px;
  font-size: 11.5px;
  color: var(--text-muted, #9ca3af);
  line-height: 1.5;
}

:deep(.project-dialog) {
  .el-dialog__header {
    padding: 20px 22px 12px;
    .el-dialog__title {
      font-size: 16px;
      font-weight: 650;
      color: var(--text-head, #111827);
    }
  }
  .el-dialog__body { padding: 18px 22px; }
  .el-dialog__footer {
    padding: 14px 22px 20px;
    border-top: 1px solid var(--border-thin, rgba(0,0,0,0.06));
  }
  .el-form-item__label {
    font-weight: 600;
    font-size: 13px;
    color: var(--text-body, #374151);
  }
  .el-input__wrapper,
  .el-textarea__inner {
    border-radius: 10px;
    transition: all 0.2s;
    &:hover { box-shadow: 0 0 0 1px #6366f1 inset; }
    &.is-focus { box-shadow: 0 0 0 1px #6366f1 inset; }
  }
}

/* ── Animations ── */
@keyframes pulse-dot {
  0%, 100% { opacity: 1; transform: scale(1); }
  50% { opacity: 0.4; transform: scale(0.85); }
}
@keyframes shimmer {
  0% { background-position: -200% 0; }
  100% { background-position: 200% 0; }
}
</style>
