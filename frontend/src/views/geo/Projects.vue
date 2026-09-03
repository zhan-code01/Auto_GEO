<template>
  <div class="projects-page">
    <!-- 头部 -->
    <header class="page-header">
      <div class="header-content">
        <div class="header-icon">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M9 17V7m0 10a2 2 0 01-2 2H5a2 2 0 01-2-2V7a2 2 0 012-2h2a2 2 0 012 2m0 10a2 2 0 002 2h2a2 2 0 002-2M9 7a2 2 0 012-2h2a2 2 0 012 2m0 10V7m0 10a2 2 0 002 2h2a2 2 0 002-2V7a2 2 0 00-2-2h-2a2 2 0 00-2 2"/>
          </svg>
        </div>
        <div class="header-text">
          <h1 class="page-title">GEO 项目管理</h1>
          <p class="page-desc">智能获客项目全生命周期管理</p>
        </div>
      </div>
      <el-button type="primary" size="large" @click="showCreateDialog = true">
        <svg viewBox="0 0 16 16" fill="currentColor" width="16">
          <path d="M8 4a.5.5 0 01.5.5v3h3a.5.5 0 010 1h-3v3a.5.5 0 01-1 0v-3h-3a.5.5 0 010-1h3v-3A.5.5 0 018 4z"/>
        </svg>
        创建项目
      </el-button>
    </header>

    <!-- 项目网格 -->
    <section class="projects-section">
      <div class="section-header">
        <h2 class="section-title">项目列表</h2>
        <span class="section-count">{{ projects.length }} 个项目</span>
      </div>
      <div v-loading="loading" class="projects-grid">
        <div
          v-for="project in projects"
          :key="project.id"
          class="project-card"
          @click="viewProject(project)"
        >
          <!-- 顶部：头像 + 名称 + 操作 -->
          <div class="card-top">
            <div class="project-avatar" :style="{ background: getAvatarColor(project.name) }">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
                <path d="M3 9l9-7 9 7v11a2 2 0 01-2 2H5a2 2 0 01-2-2z"/>
                <polyline points="9,22 9,12 15,12 15,22"/>
              </svg>
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
                    <el-icon><Edit /></el-icon> 编辑项目
                  </el-dropdown-item>
                  <el-dropdown-item divided @click.stop="deleteProject(project)">
                    <el-icon><Delete /></el-icon> 删除项目
                  </el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </div>

          <!-- 项目名 + 标签 -->
          <div class="project-name-row">
            <span class="label-tag project-label">项目</span>
            <h3 class="project-name">{{ project.name }}</h3>
          </div>

          <!-- 公司名称 + 标签（隐藏纯数字 ID） -->
          <div v-if="project.company_name && !isNumericId(project.company_name)" class="project-company-row">
            <span class="label-tag company-label">客户</span>
            <div class="project-company">
              {{ project.company_name }}
            </div>
          </div>

          <!-- 底部统计栏 -->
          <div class="card-footer">
            <div class="footer-stats">
              <span class="footer-stat">
                <svg viewBox="0 0 16 16" fill="currentColor" width="12"><path d="M3 2h10a1 1 0 011 1v11a1 1 0 01-1 1H3a1 1 0 01-1-1V3a1 1 0 011-1zm1 3v2h8V5H4zm0 4v2h8V9H4z"/></svg>
                {{ getArticleCount(project.id) }} 篇文章
              </span>
              <span class="footer-stat">
                <svg viewBox="0 0 16 16" fill="currentColor" width="12"><path d="M8 13a5 5 0 110-10 5 5 0 010 10zm0-2c-1.7 0-3-1.3-3-3h1.5A1.5 1.5 0 008 9.5V11zm0-4.5a1.5 1.5 0 00-1.5 1.5H9A1.5 1.5 0 008 6.5z"/></svg>
                {{ getQuestionCount(project.id) }} 个用户问题
              </span>
            </div>
            <span v-if="project.industry" class="industry-chip">{{ project.industry }}</span>
          </div>
        </div>

        <!-- 空状态 -->
        <div v-if="!loading && projects.length === 0" class="empty-state">
          <div class="empty-icon">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
              <path d="M9 13h6m-3-3v6m-9 1V7a2 2 0 012-2h6l2 3h6a2 2 0 012 2v8a2 2 0 01-2 2H5a2 2 0 01-2-2z"/>
            </svg>
          </div>
          <h3>还没有GEO项目</h3>
          <p>创建第一个项目开始您的获客之旅</p>
          <el-button type="primary" @click="showCreateDialog = true">创建项目</el-button>
        </div>
      </div>
    </section>

    <!-- 创建/编辑项目对话框 -->
    <el-dialog
      v-model="showCreateDialog"
      :title="editingProject ? '编辑GEO项目' : '创建GEO项目'"
      width="520px"
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
          />
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
          />
          <div class="form-tip">此关键词将用于AI蒸馏生成用户提问句</div>
        </el-form-item>

        <el-form-item label="所属行业">
          <el-select
            v-model="projectForm.industry"
            placeholder="选择或输入自定义行业"
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
          <div class="form-tip">支持自定义输入行业名称</div>
        </el-form-item>

        <el-form-item label="项目描述">
          <el-input
            v-model="projectForm.description"
            type="textarea"
            :rows="3"
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
import { ref, onMounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Edit, Delete, Key } from '@element-plus/icons-vue'
import { geoKeywordApi, clientApi } from '@/services/api'
import { smartArticleApi } from '@/services/smartArticleApi'

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
  created_at: string
}

// ==================== 状态 ====================
const router = useRouter()
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

// 加载客户列表（用于项目名称下拉选择）
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
    const result: any = await geoKeywordApi.getProjects()
    const list = Array.isArray(result) ? result : (result?.data || [])
    projects.value = list
    // 逐个项目加载文章数 + 用户问题数
    list.forEach((p: Project) => loadProjectStats(p.id))
  } catch (error) {
    console.error('加载项目失败:', error)
    projects.value = [] // 确保始终是数组
  } finally {
    loading.value = false
  }
}

// 根据项目名生成渐变色（固定色板，同一名字颜色一致）
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

// 判断 company_name 是否为无意义的纯数字 ID（如 "662146436"）
const isNumericId = (val: any): boolean => {
  if (!val) return true
  const str = String(val).trim()
  // 纯数字且长度>=6 视为自动生成的 ID，不是真实公司名
  return /^\d{6,}$/.test(str)
}

// 格式化公司名：如果是纯数字 ID 则返回占位文本
const formatCompanyName = (val: any): string => {
  if (!val) return ''
  const str = String(val).trim()
  if (/^\d{6,}$/.test(str)) return ''  // 隐藏
  return str
}

// 项目统计：文章数 + 用户问题数（按 project_id 缓存）
const projectStats = ref<Record<number, { articles: number; questions: number }>>({})

const loadProjectStats = async (projectId: number) => {
  try {
    const [qRes, aRes] = await Promise.all([
      smartArticleApi.getQuestions({ project_id: projectId, page: 1, limit: 1 }),
      smartArticleApi.getArticles({ project_id: projectId, page: 1, limit: 1 }),
    ])
    const extractTotal = (res: any) =>
      res?.total ?? res?.data?.total ?? (res?.items || res?.data?.items || []).length ?? 0
    projectStats.value[projectId] = {
      articles: extractTotal(aRes),
      questions: extractTotal(qRes),
    }
  } catch {
    projectStats.value[projectId] = { articles: 0, questions: 0 }
  }
}

const getArticleCount = (projectId: number) => projectStats.value[projectId]?.articles ?? 0
const getQuestionCount = (projectId: number) => projectStats.value[projectId]?.questions ?? 0

// 查看项目
const viewProject = (project: Project) => {
  goToKeywords(project)
}

// 跳转到关键词管理
const goToKeywords = (project: Project) => {
  router.push({
    name: 'GeoKeywords',
    query: { projectId: project.id }
  })
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
      // 更新项目 - 也要传递 domain_keyword
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
      // 创建项目 - 传递 domain_keyword
      const result = await geoKeywordApi.createProject({
        client_id: projectForm.value.client_id,
        name: projectForm.value.name,
        company_name: companyName,
        domain_keyword: projectForm.value.domain_keyword,
        industry: projectForm.value.industry,
        description: projectForm.value.description,
      })
      projects.value.unshift(result)
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
   Projects Page — Modern Card Design
   ================================================================ */

.projects-page {
  display: flex;
  flex-direction: column;
  gap: 24px;
  height: 100%;
  padding: 24px 28px;
  background: transparent;
}

/* ── Header ── */
.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 24px 28px;
  background:
    linear-gradient(135deg, rgba(99,102,241,0.06), transparent 60%),
    var(--surface-raised, #fff);
  border-radius: var(--radius-lg, 16px);
  border: 1px solid var(--border-thin, rgba(0,0,0,0.06));

  .header-content {
    display: flex;
    align-items: center;
    gap: 16px;

    .header-icon {
      width: 52px;
      height: 52px;
      border-radius: 14px;
      background: linear-gradient(135deg, #4f46e5, #7c3aed);
      display: flex;
      align-items: center;
      justify-content: center;
      color: #fff;
      svg { width: 26px; height: 26px; }
    }

    .page-title {
      margin: 0 0 4px 0;
      font-family: var(--font-display);
      font-size: 22px;
      font-weight: 650;
      color: var(--text-head, #111827);
      letter-spacing: -0.02em;
    }
    .page-desc { margin: 0; font-size: 13px; color: var(--text-muted, #9ca3af); }
  }
}

/* ── Section ── */
.projects-section {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  background: var(--surface-raised, #fff);
  border-radius: var(--radius-lg, 16px);
  border: 1px solid var(--border-thin, rgba(0,0,0,0.06));
  padding: 24px 28px;

  .section-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 20px;

    .section-title {
      margin: 0;
      font-size: 17px;
      font-weight: 650;
      color: var(--text-head, #111827);
      letter-spacing: -0.01em;
    }

    .section-count {
      font-size: 12px;
      color: var(--text-muted, #9ca3af);
      padding: 4px 13px;
      background: rgba(99,102,241,0.07);
      border-radius: 20px;
      font-weight: 500;
      color: #6366f1;
    }
  }
}

/* ── Grid ── */
.projects-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  grid-auto-rows: min-content;
  gap: 16px;
  flex: 1;
  overflow-y: auto;
  padding: 4px;

  &::-webkit-scrollbar { width: 5px; }
  &::-webkit-scrollbar-track { background: transparent; }
  &::-webkit-scrollbar-thumb {
    background: rgba(0,0,0,0.10); border-radius: 4px;
    &:hover { background: rgba(0,0,0,0.18); }
  }
}

/* ── Project Card ── */
.project-card {
  position: relative;
  background: var(--surface-field, #fafbfc);
  border-radius: 16px;
  padding: 20px 22px;
  min-height: 172px;
  border: 1.5px solid transparent;
  display: flex;
  flex-direction: column;
  cursor: pointer;
  transition: all 0.25s cubic-bezier(.4,0,.2,1);
  box-shadow:
    0 1px 2px rgba(0,0,0,0.03),
    0 4px 16px rgba(0,0,0,0.03);

  &:hover {
    border-color: rgba(99,102,241,0.22);
    box-shadow:
      0 6px 24px rgba(99,102,241,0.1),
      0 1px 3px rgba(0,0,0,0.04);
    transform: translateY(-2px);

    .project-avatar { box-shadow: 0 6px 20px rgba(99,102,241,0.25); }
  }

  &:active { transform: translateY(0); }
}

/* ── Card Top (Avatar + More) ── */
.card-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 14px;
}

.project-avatar {
  width: 48px;
  height: 48px;
  border-radius: 14px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  transition: box-shadow 0.25s ease;
  box-shadow: 0 2px 8px rgba(0,0,0,0.08);

  svg {
    width: 22px;
    height: 22px;
  }
}

.more-btn {
  width: 30px;
  height: 30px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--text-muted, #9ca3af);
  cursor: pointer;
  transition: all 0.18s;

  &:hover { background: rgba(0,0,0,0.05); color: #6366f1; }
  svg { width: 15px; height: 15px; }
}

/* ── Project Name + Label ── */
.project-name-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;

  .project-name {
    margin: 0;
    font-size: 15.5px;
    font-weight: 650;
    color: var(--text-head, #111827);
    letter-spacing: -0.01em;
    line-height: 1.35;
  }
}

.project-company-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;

  .project-company {
    font-size: 12px;
    color: var(--text-muted, #9ca3af);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    max-width: calc(100% - 36px);
  }
}

/* ── Label Tags ── */
.label-tag {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 1.5px 7px;
  border-radius: 5px;
  font-size: 10.5px;
  font-weight: 650;
  letter-spacing: 0.03em;
  flex-shrink: 0;
  line-height: 1.6;
}

.project-label {
  background: linear-gradient(135deg, rgba(99,102,241,0.12), rgba(99,102,241,0.06));
  color: #4338ca;
  border: 1px solid rgba(99,102,241,0.14);
}

.company-label {
  background: linear-gradient(135deg, rgba(16,185,129,0.10), rgba(16,185,129,0.05));
  color: #047857;
  border: 1px solid rgba(16,185,129,0.14);
}

/* ── Footer Stats ── */
.card-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding-top: 14px;
  margin-top: auto;
  border-top: 1px solid rgba(0,0,0,0.05);
  flex-wrap: wrap;
}

.footer-stats {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
}

.footer-stat {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 11.5px;
  color: var(--text-muted, #9ca3af);
  font-weight: 500;
  white-space: nowrap;

  svg { flex-shrink: 0; opacity: 0.55; }
}

.industry-chip {
  padding: 3px 10px;
  background: linear-gradient(135deg, rgba(245,158,11,0.09), rgba(245,158,11,0.04));
  border-radius: 20px;
  font-size: 11px;
  font-weight: 600;
  color: #b45309;
}

/* ── Empty State ── */
.empty-state {
  grid-column: 1 / -1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 60px 20px;

  .empty-icon {
    width: 72px;
    height: 72px;
    border-radius: 50%;
    background: linear-gradient(135deg, rgba(99,102,241,0.08), rgba(139,92,246,0.05));
    display: flex;
    align-items: center;
    justify-content: center;
    margin-bottom: 18px;

    svg { width: 32px; height: 32px; color: #6366f1; }
  }

  h3 { margin: 0 0 8px 0; font-size: 17px; font-weight: 650; color: var(--text-head, #111827); }
  p { margin: 0 0 22px 0; font-size: 13px; color: var(--text-muted, #9ca3af); }
}

/* ── Form Tip ── */
.form-tip { margin-top: 6px; font-size: 11.5px; color: var(--text-muted, #9ca3af); line-height: 1.5; }

/* ── Dialog ── */
:deep(.project-dialog) {
  .el-dialog__header {
    padding: 20px 24px 12px;
    .el-dialog__title { font-size: 17px; font-weight: 650; color: var(--text-head, #111827); }
  }
  .el-dialog__body { padding: 20px 24px; }
  .el-dialog__footer {
    padding: 14px 24px 20px;
    border-top: 1px solid var(--border-thin, rgba(0,0,0,0.06));
  }
  .el-form-item__label { font-weight: 600; font-size: 13px; color: var(--text-body, #374151); }
  .el-input__wrapper,
  .el-textarea__inner {
    border-radius: 10px;
    transition: all 0.2s;
    &:hover { box-shadow: 0 0 0 1px #6366f1 inset; }
    &.is-focus { box-shadow: 0 0 0 1px #6366f1 inset; }
  }
}
</style>
