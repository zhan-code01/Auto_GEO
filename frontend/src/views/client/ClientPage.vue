<template>
  <div class="client-page">
    <!-- 顶部统计卡片 -->
    <div class="stats-cards">
      <div class="stat-card">
        <div class="stat-icon" style="background: #6366f1">
          <el-icon><OfficeBuilding /></el-icon>
        </div>
        <div class="stat-content">
          <div class="stat-label">总客户</div>
          <div class="stat-value">{{ stats.total }}</div>
        </div>
      </div>
      <div class="stat-card">
        <div class="stat-icon" style="background: #22c55e">
          <el-icon><CircleCheck /></el-icon>
        </div>
        <div class="stat-content">
          <div class="stat-label">活跃客户</div>
          <div class="stat-value">{{ stats.active }}</div>
        </div>
      </div>
      <div class="stat-card">
        <div class="stat-icon" style="background: #f59e0b">
          <el-icon><Warning /></el-icon>
        </div>
        <div class="stat-content">
          <div class="stat-label">停用客户</div>
          <div class="stat-value">{{ stats.inactive }}</div>
        </div>
      </div>
      <div class="stat-card">
        <div class="stat-icon" style="background: #8b5cf6">
          <el-icon><TrendCharts /></el-icon>
        </div>
        <div class="stat-content">
          <div class="stat-label">行业数</div>
          <div class="stat-value">{{ Object.keys(stats.industry_distribution || {}).length }}</div>
        </div>
      </div>
    </div>

    <!-- 工具栏 -->
    <div class="toolbar">
      <div class="toolbar-left">
        <el-input
          v-model="searchKeyword"
          placeholder="搜索公司名称"
          clearable
          style="width: 200px"
          @change="loadClients"
        >
          <template #prefix>
            <el-icon><Search /></el-icon>
          </template>
        </el-input>

        <el-select v-model="filterStatus" placeholder="状态" clearable style="width: 120px" @change="loadClients">
          <el-option label="活跃" :value="1" />
          <el-option label="停用" :value="0" />
        </el-select>

        <el-select v-model="filterIndustry" placeholder="行业" clearable style="width: 150px" @change="loadClients">
          <el-option v-for="ind in industries" :key="ind" :label="ind" :value="ind" />
        </el-select>
      </div>
      <div class="toolbar-right">
        <el-button type="primary" @click="showCreateDialog">
          <el-icon><Plus /></el-icon>
          新建客户
        </el-button>
      </div>
    </div>

    <!-- 客户表格 -->
    <div class="table-container" v-loading="loading">
      <el-table :data="clients" style="width: 100%">
        <el-table-column label="公司名称" min-width="220">
          <template #default="{ row }">
            <div class="company-cell">
              <div class="company-avatar">{{ (row.company_name || '?').charAt(0) }}</div>
              <span class="company-text" :title="row.company_name">{{ truncateName(row.company_name) }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="联系人" min-width="140" align="center">
          <template #default="{ row }">
            <span class="cell-muted">{{ row.contact_person || '-' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="联系方式" min-width="180" align="center">
          <template #default="{ row }">
            <span class="cell-muted">{{ row.phone || '-' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="300" fixed="right" align="center">
          <template #default="{ row }">
            <div class="op-cell">
              <el-button size="small" plain @click="viewProjects(row)">
                <el-icon><View /></el-icon> 查看项目
              </el-button>
              <el-button size="small" type="primary" plain @click="uploadKnowledge(row)">
                <el-icon><Upload /></el-icon> 上传资料
              </el-button>
              <el-tooltip content="编辑" placement="top">
                <el-button size="small" text :icon="Edit" @click="editClient(row)" />
              </el-tooltip>
              <el-tooltip content="删除" placement="top">
                <el-button size="small" text type="danger" :icon="Delete" @click="deleteClient(row.id)" />
              </el-tooltip>
            </div>
          </template>
        </el-table-column>
      </el-table>

      <el-empty v-if="clients.length === 0 && !loading" description="暂无客户" />

      <!-- 分页 -->
      <div class="pagination">
        <el-pagination
          v-model:current-page="pagination.page"
          v-model:page-size="pagination.limit"
          :total="pagination.total"
          :page-sizes="[10, 20, 50, 100]"
          layout="total, sizes, prev, pager, next, jumper"
          @size-change="loadClients"
          @current-change="loadClients"
        />
      </div>
    </div>

    <!-- 创建/编辑对话框 -->
    <el-dialog
      v-model="dialogVisible"
      :title="isEdit ? '编辑客户' : '新建客户'"
      width="600px"
    >
      <el-form :model="clientForm" label-width="100px">
        <el-form-item label="公司名称" required>
          <el-input v-model="clientForm.company_name" placeholder="请输入公司名称" />
        </el-form-item>
        <el-form-item label="所属行业" required>
          <el-select
            v-model="clientForm.industry"
            placeholder="请选择或输入细分行业"
            allow-create
            filterable
            style="width: 100%"
          >
            <el-option v-for="ind in clientIndustryOptions" :key="ind" :label="ind" :value="ind" />
          </el-select>
        </el-form-item>
        <el-form-item label="所在地" required>
          <el-input v-model="clientForm.location" placeholder="请输入公司所在地，例如：广州" />
        </el-form-item>
        <el-form-item label="公司官网" required>
          <el-input v-model="clientForm.website" placeholder="请输入公司官网，例如：https://www.example.com" />
        </el-form-item>
        <el-form-item label="联系人">
          <el-input v-model="clientForm.contact_person" placeholder="请输入联系人姓名" />
        </el-form-item>
        <el-form-item label="联系电话">
          <el-input v-model="clientForm.phone" placeholder="请输入联系电话" />
        </el-form-item>
        <el-form-item label="邮箱">
          <el-input v-model="clientForm.email" placeholder="请输入邮箱地址" />
        </el-form-item>
        <el-form-item label="状态">
          <el-radio-group v-model="clientForm.status">
            <el-radio :value="1">活跃</el-radio>
            <el-radio :value="0">停用</el-radio>
          </el-radio-group>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="saveClient">确定</el-button>
      </template>
    </el-dialog>

    <!-- 项目列表对话框 -->
    <el-dialog
      v-model="projectsDialogVisible"
      title="客户项目"
      width="900px"
    >
      <div class="projects-header">
        <h4>{{ currentClient?.company_name || currentClient?.name }} 的项目列表</h4>
        <el-button type="primary" size="small" @click="showProjectForm(null)">
          <el-icon><Plus /></el-icon>
          新建项目
        </el-button>
      </div>
      <el-table :data="clientProjects" v-loading="loadingProjects" stripe>
        <el-table-column prop="id" label="ID" width="60" />
        <el-table-column prop="name" label="项目名称" min-width="120" />
        <el-table-column prop="company_name" label="公司名称" min-width="120" />
        <el-table-column prop="domain_keyword" label="领域关键词" min-width="120" />
        <el-table-column prop="description" label="描述" min-width="150" show-overflow-tooltip />
        <el-table-column label="状态" width="80">
          <template #default="{ row }">
            <el-tag :type="row.status === 1 ? 'success' : 'info'" size="small">
              {{ row.status === 1 ? '活跃' : '停用' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="150" fixed="right">
          <template #default="{ row }">
            <el-button type="primary" size="small" link @click="showProjectForm(row)">编辑</el-button>
            <el-button type="danger" size="small" link @click="deleteProjectItem(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
      <el-empty v-if="!loadingProjects && clientProjects.length === 0" description="暂无项目" />
    </el-dialog>

    <!-- 项目新建/编辑对话框 -->
    <el-dialog
      v-model="projectFormVisible"
      :title="editingProject ? '编辑项目' : '新建项目'"
      width="520px"
      append-to-body
    >
      <el-form :model="projectForm" label-width="100px">
        <el-form-item label="项目名称" required>
          <el-input v-model="projectForm.name" placeholder="请输入项目名称" />
        </el-form-item>
        <el-form-item label="公司名称" required>
          <el-input v-model="projectForm.company_name" placeholder="请输入公司名称" />
        </el-form-item>
        <el-form-item label="领域关键词" required>
          <el-input v-model="projectForm.domain_keyword" placeholder="用于AI蒸馏生成用户提问句" />
        </el-form-item>
        <el-form-item label="所属行业">
          <el-select v-model="projectForm.industry" placeholder="选择行业" allow-create filterable style="width: 100%">
            <el-option v-for="ind in projectIndustries" :key="ind" :label="ind" :value="ind" />
          </el-select>
        </el-form-item>
        <el-form-item label="项目描述">
          <el-input v-model="projectForm.description" type="textarea" :rows="3" placeholder="简要描述项目（可选）" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="projectFormVisible = false">取消</el-button>
        <el-button type="primary" :loading="savingProject" @click="saveProjectItem">
          {{ editingProject ? '保存修改' : '创建项目' }}
        </el-button>
      </template>
    </el-dialog>

    <!-- 知识库上传对话框 -->
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
            <el-input :value="currentClient?.company_name || currentClient?.name" disabled />
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
              ref="uploadRef"
              :auto-upload="false"
              :limit="5"
              :on-change="handleFileChange"
              :on-exceed="handleExceed"
              :file-list="fileList"
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
        <el-button type="primary" :loading="uploading" @click="confirmUpload">
          <el-icon><Upload /></el-icon>
          确认上传
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import {
  OfficeBuilding, CircleCheck, Warning, TrendCharts, Search, Plus,
  Upload, UploadFilled, View, Edit, Delete
} from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { UploadFile, UploadInstance, UploadUserFile } from 'element-plus'
import { clientApi, geoKeywordApi } from '@/services/api'

// 状态
const loading = ref(false)
const loadingProjects = ref(false)
const clients = ref<any[]>([])
const clientProjects = ref<any[]>([])
const industries = ref<string[]>([])

// 筛选
const searchKeyword = ref('')
const filterStatus = ref<number | null>(null)
const filterIndustry = ref<string | null>(null)

// 分页
const pagination = ref({
  page: 1,
  limit: 20,
  total: 0
})

// 统计
const stats = ref({
  total: 0,
  active: 0,
  inactive: 0,
  industry_distribution: {}
})

// 对话框
const dialogVisible = ref(false)
const projectsDialogVisible = ref(false)
const uploadDialogVisible = ref(false)
const isEdit = ref(false)
const currentClient = ref<any>(null)

// 知识库上传
const uploadRef = ref<UploadInstance>()
const uploading = ref(false)
const fileList = ref<UploadUserFile[]>([])
const uploadForm = ref({
  category: '',
  description: ''
})
const clientForm = ref({
  id: null as number | null,
  name: '',
  company_name: '',
  contact_person: '',
  phone: '',
  email: '',
  industry: '',
  location: '',
  website: '',
  status: 1
})

// 项目管理
const projectFormVisible = ref(false)
const editingProject = ref<any>(null)
const savingProject = ref(false)
const projectForm = ref({
  name: '',
  company_name: '',
  domain_keyword: '',
  industry: '',
  description: '',
})
const projectIndustries = [
  '食品', '餐饮', '食品供应链', '预制菜', '生鲜食材', '餐饮食材供应',
  '酒水饮料', '农产品', '冷链物流', '零售', '电商', '本地生活',
  'SaaS软件', '企业服务', 'AI服务', '数字营销', '教育培训', '金融服务',
  '医疗健康', '制造业', '工业设备', '环保工程', '工业清洗', '无人机服务',
  '房地产', '建筑工程', '旅游出行', '物流运输', '新能源', '化工行业',
]
const clientIndustryOptions = projectIndustries

// 加载客户列表
const loadClients = async () => {
  loading.value = true
  try {
    const data = await clientApi.getList({
      page: pagination.value.page,
      limit: pagination.value.limit,
      status: filterStatus.value ?? undefined,
      keyword: searchKeyword.value || undefined,
      industry: filterIndustry.value || undefined
    })

    clients.value = data.items || []
    pagination.value.total = data.total || 0
  } catch (e: any) {
    ElMessage.error('加载失败: ' + e.message)
  } finally {
    loading.value = false
  }
}

// 加载统计数据
const loadStats = async () => {
  try {
    const data = await clientApi.getStats()
    stats.value = data.data || { total: 0, active: 0, inactive: 0, industry_distribution: {} }
  } catch (e) {
    console.error('加载统计失败', e)
  }
}

// 加载行业列表
const loadIndustries = async () => {
  try {
    const data = await clientApi.getIndustries()
    industries.value = data.data || []
  } catch (e) {
    console.error('加载行业列表失败', e)
  }
}

// 显示创建对话框
const showCreateDialog = () => {
  isEdit.value = false
  clientForm.value = {
    id: null,
    name: '',
    company_name: '',
    contact_person: '',
    phone: '',
    email: '',
    industry: '',
    location: '',
    website: '',
    status: 1
  }
  dialogVisible.value = true
}

// 编辑客户
const editClient = (client: any) => {
  isEdit.value = true
  const companyName = client.company_name || client.name || ''
  clientForm.value = {
    id: client.id,
    name: companyName,
    company_name: companyName,
    contact_person: client.contact_person || '',
    phone: client.phone || '',
    email: client.email || '',
    industry: client.industry || '',
    location: client.location || '',
    website: client.website || '',
    status: client.status
  }
  dialogVisible.value = true
}

// 保存客户
const saveClient = async () => {
  const companyName = clientForm.value.company_name?.trim()
  if (!companyName) {
    ElMessage.warning('请输入公司名称')
    return
  }
  const location = clientForm.value.location?.trim()
  if (!location) {
    ElMessage.warning('请输入公司所在地')
    return
  }
  const industry = clientForm.value.industry?.trim()
  if (!industry) {
    ElMessage.warning('请选择或输入所属行业')
    return
  }
  const website = clientForm.value.website?.trim()
  if (!website) {
    ElMessage.warning('请输入公司官网')
    return
  }

  try {
    const payload = {
      name: companyName,
      company_name: companyName,
      contact_person: clientForm.value.contact_person,
      phone: clientForm.value.phone,
      email: clientForm.value.email,
      industry,
      location,
      website,
      status: clientForm.value.status
    }

    if (isEdit.value) {
      await clientApi.update(clientForm.value.id!, payload)
      const index = clients.value.findIndex((item: any) => item.id === clientForm.value.id)
      if (index !== -1) {
        clients.value[index] = { ...clients.value[index], ...payload }
      }
      ElMessage.success('更新成功')
    } else {
      await clientApi.create(payload)
      ElMessage.success('创建成功')
    }

    dialogVisible.value = false
    await loadClients()
    await loadStats()
    await loadIndustries()
  } catch (e: any) {
    ElMessage.error('操作失败: ' + e.message)
  }
}

// 删除客户
const deleteClient = async (id: number) => {
  try {
    await clientApi.delete(id)
    ElMessage.success('删除成功')
    loadClients()
    loadStats()
  } catch (e: any) {
    ElMessage.error('删除失败: ' + e.message)
  }
}

// 公司名称截断（最多 15 字）
const truncateName = (name: string) => {
  if (!name) return '-'
  return name.length > 15 ? name.slice(0, 15) + '…' : name
}

// 查看项目
const viewProjects = async (client: any) => {
  currentClient.value = client
  loadingProjects.value = true
  projectsDialogVisible.value = true

  try {
    const data = await clientApi.getProjects(client.id)
    clientProjects.value = data.data || []
  } catch (e: any) {
    ElMessage.error('加载项目失败: ' + e.message)
  } finally {
    loadingProjects.value = false
  }
}

// 显示项目表单（新建或编辑）
const showProjectForm = (project: any) => {
  if (project) {
    editingProject.value = project
    projectForm.value = {
      name: project.name || '',
      company_name: project.company_name || '',
      domain_keyword: project.domain_keyword || '',
      industry: project.industry || '',
      description: project.description || '',
    }
  } else {
    editingProject.value = null
    projectForm.value = {
      name: '',
      company_name: currentClient.value?.company_name || currentClient.value?.name || '',
      domain_keyword: '',
      industry: currentClient.value?.industry || '',
      description: '',
    }
  }
  projectFormVisible.value = true
}

// 保存项目（新建或编辑）
const saveProjectItem = async () => {
  if (!projectForm.value.name?.trim()) {
    ElMessage.warning('请输入项目名称')
    return
  }
  if (!projectForm.value.company_name?.trim()) {
    ElMessage.warning('请输入公司名称')
    return
  }
  if (!projectForm.value.domain_keyword?.trim()) {
    ElMessage.warning('请输入领域关键词')
    return
  }

  savingProject.value = true
  try {
    if (editingProject.value) {
      await geoKeywordApi.updateProject(editingProject.value.id, {
        client_id: currentClient.value?.id,
        ...projectForm.value,
      })
      ElMessage.success('项目已更新')
    } else {
      await geoKeywordApi.createProject({
        client_id: currentClient.value?.id,
        ...projectForm.value,
      })
      ElMessage.success('项目创建成功')
    }
    projectFormVisible.value = false
    // 刷新项目列表
    if (currentClient.value) {
      viewProjects(currentClient.value)
    }
    loadClients()
  } catch (e: any) {
    ElMessage.error('操作失败: ' + (e.message || '未知错误'))
  } finally {
    savingProject.value = false
  }
}

// 删除项目
const deleteProjectItem = async (project: any) => {
  try {
    await ElMessageBox.confirm(
      `确定要删除项目"${project.name}"吗？`,
      '确认删除',
      { type: 'warning', confirmButtonText: '确定删除', cancelButtonText: '取消' }
    )
    await geoKeywordApi.deleteProject(project.id)
    ElMessage.success('项目已删除')
    if (currentClient.value) {
      viewProjects(currentClient.value)
    }
    loadClients()
  } catch (e: any) {
    if (e !== 'cancel') {
      ElMessage.error('删除失败')
    }
  }
}

// ==================== 知识库上传相关方法 ====================

// 打开知识库上传对话框
const uploadKnowledge = (client: any) => {
  currentClient.value = client
  uploadForm.value = {
    category: '',
    description: ''
  }
  fileList.value = []
  uploadDialogVisible.value = true
}

// 处理文件选择
const handleFileChange = (file: UploadFile, uploadFiles: UploadUserFile[]) => {
  // 验证文件类型
  const allowedTypes = ['pdf', 'doc', 'docx', 'txt', 'md']
  const ext = file.name.split('.').pop()?.toLowerCase()
  if (!ext || !allowedTypes.includes(ext)) {
    ElMessage.error('不支持的文件格式，请上传 PDF、Word、TXT 或 Markdown 文件')
    fileList.value = uploadFiles.filter(item => item.uid !== file.uid)
    return false
  }

  // 验证文件大小 (10MB)
  if ((file.size || 0) > 10 * 1024 * 1024) {
    ElMessage.error('文件大小不能超过 10MB')
    fileList.value = uploadFiles.filter(item => item.uid !== file.uid)
    return false
  }

  fileList.value = uploadFiles
  return true
}

// 处理文件超出限制
const handleExceed = () => {
  ElMessage.warning('最多只能上传 5 个文件')
}

// 确认上传
const confirmUpload = async () => {
  if (!currentClient.value) return

  if (fileList.value.length === 0) {
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
    formData.append('client_id', String(currentClient.value.id))
    formData.append('category', uploadForm.value.category)
    formData.append('description', uploadForm.value.description)

    // 添加所有文件
    fileList.value.forEach((file: any) => {
      formData.append('files', file.raw)
    })

    const response = await clientApi.uploadFiles(formData)
    const result = response.data || {}

    if (response.success) {
      const successCount = result.success_count ?? result.uploaded?.length ?? fileList.value.length
      const failedCount = result.failed_count ?? result.failed?.length ?? 0
      if (failedCount > 0) {
        ElMessage.warning(`上传完成：成功 ${successCount} 个，失败 ${failedCount} 个`)
        if (Array.isArray(result.failed) && result.failed.length > 0) {
          const failedText = result.failed
            .map((item: any) => `${item.name || '未知文件'}：${item.error || '未知错误'}`)
            .join('\n')
          ElMessageBox.alert(failedText, '上传失败详情', {
            confirmButtonText: '知道了',
            type: 'warning'
          })
        }
      } else {
        ElMessage.success(`成功上传 ${successCount} 个文件`)
      }

      if (successCount === 0) {
        return
      }

      uploadDialogVisible.value = false
      fileList.value = []
      uploadRef.value?.clearFiles()
      uploadForm.value = { category: '', description: '' }

      const appliedFields = {
        ...(result.applied_client_fields || {}),
        ...(result.applied_profile_fields || {})
      }
      if (Object.keys(appliedFields).length > 0) {
        await loadClients()
        await loadStats()
        await loadIndustries()
        currentClient.value = currentClient.value
          ? { ...currentClient.value, ...appliedFields }
          : currentClient.value
        ElMessage.success(`已自动回填客户信息：${Object.keys(appliedFields).join('、')}`)
      } else if (result.extracted_info && Object.keys(result.extracted_info).length > 0) {
        // 未自动写入时保留人工确认入口，避免覆盖已有客户资料
        const info = result.extracted_info
        const companyName = info.company_name || currentClient.value.company_name || currentClient.value.name || ''
        clientForm.value = {
          id: currentClient.value.id,
          name: companyName,
          company_name: companyName,
          contact_person: info.contact_person || currentClient.value.contact_person || '',
          phone: info.phone || currentClient.value.phone || '',
          email: info.email || currentClient.value.email || '',
          industry: info.industry || currentClient.value.industry || '',
          location: info.location || currentClient.value.location || '',
          website: info.website || currentClient.value.website || '',
          status: currentClient.value.status ?? 1
        }
        isEdit.value = true
        dialogVisible.value = true
        ElMessage.info('已从文档中提取客户信息，请确认并保存')
      } else {
        await loadClients()
      }
    } else {
      ElMessage.error(response.message || '上传失败')
    }
  } catch (e: any) {
    ElMessage.error('上传失败: ' + e.message)
  } finally {
    uploading.value = false
  }
}

onMounted(() => {
  loadClients()
  loadStats()
  loadIndustries()
})
</script>

<style scoped lang="scss">
.client-page {
  display: flex;
  flex-direction: column;
  gap: 20px;
  padding: 20px;
}

.stats-cards {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;

  .stat-card {
    display: flex;
    align-items: center;
    gap: 16px;
    padding: 20px;
    background: var(--bg-secondary);
    border-radius: 12px;

    .stat-icon {
      width: 48px;
      height: 48px;
      border-radius: 12px;
      display: flex;
      align-items: center;
      justify-content: center;
      color: white;
      font-size: 24px;
    }

    .stat-content {
      .stat-label {
        font-size: 12px;
        color: var(--text-secondary);
        margin-bottom: 4px;
      }

      .stat-value {
        font-size: 24px;
        font-weight: 600;
        color: var(--text-primary);
      }
    }
  }
}

.toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;

  .toolbar-left {
    display: flex;
    gap: 12px;
  }
}

.table-container {
  background: var(--bg-secondary);
  border-radius: 12px;
  padding: 4px 16px 16px;

  .company-cell {
    display: flex;
    align-items: center;
    gap: 12px;

    .company-avatar {
      width: 36px;
      height: 36px;
      flex-shrink: 0;
      border-radius: 50%;
      background: var(--el-color-primary-light-9, #ecf0fe);
      color: var(--el-color-primary, #409eff);
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 15px;
      font-weight: 600;
    }

    .company-text {
      font-size: 15px;
      font-weight: 600;
      color: var(--text-primary);
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
  }

  .cell-muted {
    color: var(--text-secondary);
    font-size: 14px;
  }

  .count-pill {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    min-width: 24px;
    height: 24px;
    padding: 0 8px;
    border-radius: 12px;
    background: var(--el-color-primary-light-9, #ecf0fe);
    color: var(--el-color-primary, #409eff);
    font-size: 13px;
    font-weight: 600;
  }

  .op-cell {
    display: flex;
    justify-content: center;
    gap: 4px;
  }

  .pagination {
    margin-top: 16px;
    display: flex;
    justify-content: flex-end;
  }
}

.delete-item {
  color: #f56c6c;
}

.projects-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;

  h4 {
    margin: 0;
    font-size: 16px;
    font-weight: 500;
  }
}

</style>
