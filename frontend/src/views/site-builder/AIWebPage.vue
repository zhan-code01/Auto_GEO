<template>
  <div class="page-container">
    <!-- 左侧：控制台 -->
    <div class="sidebar">
      <div class="sidebar-header">
        <div class="logo-box"><el-icon :size="20" color="#fff"><MagicStick /></el-icon></div>
        <div class="header-text">
          <h2>AI 网页生成</h2>
          <p>知识库驱动 · 一键生成</p>
        </div>
      </div>

      <div class="form-scroll-area">
        <!-- 选公司 + 一键生成 -->
        <div class="generate-section">
          <label class="config-label">选择公司</label>
          <el-select v-model="selectedClientId" placeholder="请选择公司" filterable class="company-select">
            <el-option v-for="c in clientList" :key="c.id" :label="c.company_name || c.name" :value="c.id" />
          </el-select>

          <div class="generate-buttons">
            <el-button type="primary" size="large" class="btn-generate" :loading="generating"
              :disabled="!selectedClientId" @click="handleGenerate">
              <el-icon v-if="!generating"><MagicStick /></el-icon>
              {{ generating ? 'AI 生成中…' : '一键生成' }}
            </el-button>

            <el-button size="large" class="btn-refine"
              :disabled="!hasResult || generating"
              :title="!hasResult ? '请先生成网页' : '对结果不满意？点击告诉我们'" @click="openRefineDialog">
              <el-icon><EditPen /></el-icon>
              不满意？优化
            </el-button>
          </div>
        </div>

        <!-- 生成信息 -->
        <div v-if="lastResult" class="result-info">
          <div class="info-row">
            <el-icon class="info-icon"><CircleCheckFilled /></el-icon>
            <span class="info-text">已为「{{ lastResult.company_name }}」生成网页</span>
          </div>
          <div v-if="lastResult.chunks_retrieved" class="info-detail">
            从知识库检索到 {{ lastResult.chunks_retrieved }} 个文档片段
          </div>
          <div v-if="refineHistory.length" class="info-detail">
            已优化 {{ refineHistory.length }} 次
          </div>
        </div>
      </div>

      <div class="sidebar-footer">
        <el-button @click="refreshPreview" :loading="refreshing" size="large" class="btn-refresh"
          :disabled="!hasResult">
          <el-icon><Refresh /></el-icon> 刷新
        </el-button>
        <el-button type="primary" size="large" class="btn-deploy" @click="openDeployDialog"
          :disabled="!siteId">
          <el-icon><Promotion /></el-icon> 立即部署
        </el-button>
      </div>
    </div>

    <!-- 右侧：预览 -->
    <div class="preview-area">
      <div class="preview-container">
        <div class="browser-header">
          <div class="dots">
            <span class="dot red"></span><span class="dot yellow"></span><span class="dot green"></span>
          </div>
          <div class="address-bar">
            <el-icon><Lock /></el-icon>
            <span>{{ previewError ? '生成失败' : (previewUrl || '等待生成…') }}</span>
          </div>
          <el-icon class="refresh-icon" @click="refreshPreview"><RefreshRight /></el-icon>
        </div>
        <div class="iframe-box">
          <iframe v-if="previewUrl" :src="previewUrl"></iframe>
          <div v-if="generating" class="loading-mask">
            <div class="loading-content">
              <el-icon class="is-loading" :size="36"><Loading /></el-icon>
              <p class="loading-title">AI 正在从知识库提取企业信息并生成网页…</p>
              <p class="loading-sub">通常需要 10-30 秒</p>
            </div>
          </div>
          <div v-if="!previewUrl && !generating && previewError" class="error-state">
            <el-icon :size="46" color="#d24a3c"><WarningFilled /></el-icon>
            <p>{{ previewError }}</p>
          </div>
          <div v-if="!previewUrl && !generating && !previewError" class="empty-state">
            <el-icon :size="50"><MagicStick /></el-icon>
            <p>选择公司，点击一键生成</p>
            <p class="sub-hint">系统自动从知识库提取企业信息，生成精美官网页面</p>
          </div>
        </div>
      </div>
    </div>

    <!-- 优化弹窗 -->
    <el-dialog v-model="showRefineDialog" title="优化网页" width="480px">
      <p class="refine-tip">告诉 AI 你不满意的地方，它会基于你的反馈重新生成：</p>
      <el-input v-model="refineInput" type="textarea" :rows="4"
        placeholder="例如：公司简介太简短了，多写一些发展历程；主色调换成蓝色；去掉案例展示部分…" />
      <template #footer>
        <el-button @click="showRefineDialog = false">取消</el-button>
        <el-button type="primary" :loading="generating" @click="handleRefine">重新生成</el-button>
      </template>
    </el-dialog>

    <!-- 部署弹窗 -->
    <el-dialog v-model="showDeployDialog" title="发布上线" width="500px">
      <el-tabs v-model="deployMethod" class="deploy-tabs">
        <el-tab-pane label="远程服务器 (SFTP)" name="sftp">
          <el-form label-position="left" label-width="110px">
            <el-form-item label="主机 IP"><el-input v-model="deployConfig.sftp_host" /></el-form-item>
            <el-form-item label="SSH 端口"><el-input v-model="deployConfig.sftp_port" placeholder="22" /></el-form-item>
            <el-form-item label="用户名"><el-input v-model="deployConfig.sftp_user" /></el-form-item>
            <el-form-item label="认证方式">
              <el-radio-group v-model="deployConfig.sftp_auth_type">
                <el-radio-button label="password" value="password">密码</el-radio-button>
                <el-radio-button label="private_key" value="private_key">PEM 私钥</el-radio-button>
              </el-radio-group>
            </el-form-item>
            <el-form-item v-if="deployConfig.sftp_auth_type === 'password'" label="密码">
              <el-input v-model="deployConfig.sftp_pass" type="password" show-password />
            </el-form-item>
            <template v-else>
              <el-form-item label="PEM 私钥">
                <el-input v-model="deployConfig.sftp_private_key" type="textarea" :rows="4" placeholder="粘贴 PEM 私钥内容" />
              </el-form-item>
              <el-form-item label="私钥口令">
                <el-input v-model="deployConfig.sftp_key_passphrase" type="password" show-password placeholder="可选" />
              </el-form-item>
            </template>
            <el-form-item label="上传路径"><el-input v-model="deployConfig.sftp_path" placeholder="/var/www/html" /></el-form-item>
            <el-form-item label="访问域名">
              <el-input v-model="deployConfig.public_base_url" placeholder="https://www.example.com" />
            </el-form-item>
          </el-form>
        </el-tab-pane>
        <el-tab-pane label="OSS / S3" name="s3">
          <el-form label-position="left" label-width="110px">
            <el-form-item label="Endpoint"><el-input v-model="deployConfig.s3_endpoint" placeholder="https://oss-cn-hangzhou.aliyuncs.com" /></el-form-item>
            <el-form-item label="Bucket"><el-input v-model="deployConfig.s3_bucket" /></el-form-item>
            <el-form-item label="AccessKey"><el-input v-model="deployConfig.s3_access_key" /></el-form-item>
            <el-form-item label="SecretKey"><el-input v-model="deployConfig.s3_secret_key" type="password" show-password /></el-form-item>
            <el-form-item label="访问域名">
              <el-input v-model="deployConfig.public_base_url" placeholder="https://cdn.example.com" />
            </el-form-item>
          </el-form>
        </el-tab-pane>
      </el-tabs>
      <template #footer>
        <el-button @click="showDeployDialog = false">取消</el-button>
        <el-button type="primary" :loading="deployLoading" @click="handleDeploy">立即发布</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { siteApi, clientApi } from '@/services/api'
import {
  MagicStick, Loading, Refresh, RefreshRight, Lock, EditPen,
  Promotion, CircleCheckFilled, WarningFilled
} from '@element-plus/icons-vue'

const apiBase = import.meta.env.VITE_API_BASE_URL || '/api'
const backendBase = apiBase.endsWith('/api') ? apiBase.slice(0, -4) || '' : apiBase

// ===== 状态 =====
const selectedClientId = ref(null)
const clientList = ref([])
const generating = ref(false)
const refreshing = ref(false)
const siteId = ref('')
const structuredData = ref(null)
const lastResult = ref(null)
const previewUrl = ref('')
const previewError = ref('')
const refineHistory = ref([])

const hasResult = computed(() => !!previewUrl.value && !previewError.value)

// 优化弹窗
const showRefineDialog = ref(false)
const refineInput = ref('')

// 部署
const showDeployDialog = ref(false)
const deployLoading = ref(false)
const deployMethod = ref('sftp')
const deployConfig = reactive({
  sftp_host: '', sftp_port: '22', sftp_user: 'root', sftp_auth_type: 'password',
  sftp_pass: '', sftp_private_key: '', sftp_key_passphrase: '', sftp_path: '/var/www/html',
  public_base_url: '',
  s3_endpoint: '', s3_bucket: '', s3_access_key: '', s3_secret_key: ''
})

// ===== 加载客户列表 =====
onMounted(async () => {
  try {
    const res = await clientApi.getList({ limit: 100 })
    // 后端直接返回 {success, total, items}，不是 {code, data}
    clientList.value = res.items || res.data?.items || res.data || []
  } catch (e) {
    console.error('加载客户列表失败', e)
  }
})

// ===== 一键生成 =====
const handleGenerate = async () => {
  if (!selectedClientId.value) return ElMessage.warning('请先选择公司')
  await doGenerate('')
}

// ===== 生成核心方法 =====
const doGenerate = async (extraInstructions) => {
  generating.value = true
  previewError.value = ''
  try {
    const res = await siteApi.aiGenerate({
      client_id: selectedClientId.value,
      template_id: 'tech',
      extra_instructions: extraInstructions
    })
    if (res.code === 200) {
      siteId.value = res.data.site_id
      structuredData.value = res.data.structured_data
      lastResult.value = {
        company_name: res.data.structured_data?.company_name || '',
        chunks_retrieved: res.data.chunks_retrieved || 0
      }
      previewUrl.value = `${backendBase}${res.data.preview_url}?t=${Date.now()}`
      if (extraInstructions) {
        refineHistory.value.push(extraInstructions)
      }
      ElMessage.success(extraInstructions ? '已根据反馈重新生成' : '网页生成成功')
    }
  } catch (e) {
    const detail = e?.response?.data?.detail
    previewError.value = typeof detail === 'string' ? detail : (detail?.message || '生成失败，请检查该公司的知识库是否有资料')
    previewUrl.value = ''
  } finally {
    generating.value = false
  }
}

// ===== 优化弹窗 =====
const openRefineDialog = () => {
  refineInput.value = ''
  showRefineDialog.value = true
}

const handleRefine = async () => {
  const feedback = refineInput.value.trim()
  if (!feedback) return ElMessage.warning('请输入你不满意的地方')
  showRefineDialog.value = false
  await doGenerate(feedback)
}

// ===== 刷新预览（纯渲染，不调AI） =====
const refreshPreview = async () => {
  if (!siteId.value || !structuredData.value) return
  refreshing.value = true
  try {
    const res = await siteApi.aiRegenerate({
      site_id: siteId.value,
      structured_data: structuredData.value,
      template_id: 'tech'
    })
    if (res.code === 200) {
      previewUrl.value = `${backendBase}${res.data.preview_url}?t=${Date.now()}`
    }
  } catch (e) {
    ElMessage.error('刷新预览失败')
  } finally {
    refreshing.value = false
  }
}

// ===== 部署 =====
const openDeployDialog = () => {
  if (!siteId.value) return ElMessage.warning('请先生成网页')
  showDeployDialog.value = true
}

const validateDeploy = () => {
  if (deployMethod.value === 'sftp') {
    if (!deployConfig.sftp_host?.trim()) return '请填写主机 IP'
    if (!deployConfig.sftp_user?.trim()) return '请填写用户名'
    if (deployConfig.sftp_auth_type === 'password' && !deployConfig.sftp_pass?.trim()) return '请填写密码'
    if (deployConfig.sftp_auth_type === 'private_key' && !deployConfig.sftp_private_key?.trim()) return '请粘贴 PEM 私钥'
    if (!deployConfig.sftp_path?.trim()) return '请填写上传路径'
    if (!deployConfig.sftp_path.startsWith('/')) return '上传路径必须是绝对路径'
  } else {
    if (!deployConfig.s3_endpoint) return '请填写 Endpoint'
    if (!deployConfig.s3_bucket) return '请填写 Bucket'
    if (!deployConfig.s3_access_key) return '请填写 AccessKey'
    if (!deployConfig.s3_secret_key) return '请填写 SecretKey'
  }
  return ''
}

const handleDeploy = async () => {
  const err = validateDeploy()
  if (err) { ElMessage.warning(err); return }
  deployLoading.value = true
  try {
    const companyName = structuredData.value?.company_name || 'website'
    const payload = { site_id: siteId.value, method: deployMethod.value, project_name: companyName }
    if (deployMethod.value === 'sftp') {
      Object.assign(payload, {
        sftp_host: deployConfig.sftp_host.trim(),
        sftp_port: deployConfig.sftp_port,
        sftp_user: deployConfig.sftp_user.trim(),
        sftp_auth_type: deployConfig.sftp_auth_type,
        sftp_path: deployConfig.sftp_path.trim(),
        public_base_url: deployConfig.public_base_url?.trim() || ''
      })
      if (deployConfig.sftp_auth_type === 'password') {
        payload.sftp_pass = deployConfig.sftp_pass
      } else {
        payload.sftp_private_key = deployConfig.sftp_private_key?.trim() || ''
        payload.sftp_key_passphrase = deployConfig.sftp_key_passphrase || ''
      }
    } else {
      Object.assign(payload, {
        s3_endpoint: deployConfig.s3_endpoint,
        s3_bucket: deployConfig.s3_bucket,
        s3_access_key: deployConfig.s3_access_key,
        s3_secret_key: deployConfig.s3_secret_key,
        public_base_url: deployConfig.public_base_url?.trim() || ''
      })
    }
    const res = await siteApi.deploy(payload)
    if (res.code === 200) {
      ElMessage.success('发布成功')
      showDeployDialog.value = false
      if (res.data?.url) window.open(res.data.url, '_blank')
    }
  } catch (error) {
    const d = error?.response?.data?.detail
    const msg = (d && typeof d === 'object') ? d.message : (d || '发布失败')
    const suggestion = (d && typeof d === 'object') ? d.suggestion : ''
    ElMessage.error(msg)
    if (suggestion) ElMessageBox.alert(suggestion, '修复建议', { type: 'info' })
  } finally {
    deployLoading.value = false
  }
}
</script>

<style scoped>
.page-container { display: flex; height: 100vh; background: #efeae0; font-family: sans-serif; overflow: hidden; }
.sidebar { width: 420px; min-width: 420px; background: #fbf8f2; border-right: 1px solid #f2ebde; display: flex; flex-direction: column; z-index: 10; box-shadow: 4px 0 20px rgba(74,53,24,.10); }
.sidebar-header { padding: 20px; border-bottom: 1px solid #f2ebde; display: flex; gap: 12px; align-items: center; }
.logo-box { width: 36px; height: 36px; background: #6366f1; border-radius: 8px; display: flex; align-items: center; justify-content: center; }
.header-text h2 { margin: 0; font-size: 16px; color: #211a10; font-weight: 700; }
.header-text p { margin: 0; font-size: 12px; color: #8a7d68; }
.form-scroll-area { flex: 1; overflow-y: auto; padding: 24px 20px; }

/* 生成区 */
.generate-section { display: flex; flex-direction: column; gap: 16px; }
.config-label { font-size: 13px; font-weight: 600; color: #43392a; }
.company-select { width: 100%; }
.generate-buttons { display: flex; gap: 10px; }
.btn-generate { flex: 2; background: #6366f1; border: none; font-weight: 600; }
.btn-refine { flex: 1; border: 1px solid #d8cfbe; color: #8a7d68; background: transparent; }
.btn-refine:not(:disabled):hover { border-color: #6366f1; color: #6366f1; }
.btn-refine:disabled { opacity: .4; cursor: not-allowed; }

/* 结果信息 */
.result-info { margin-top: 28px; padding: 16px; background: #f2ebde; border-radius: 8px; border: 1px solid #d8cfbe; }
.info-row { display: flex; align-items: center; gap: 8px; }
.info-icon { color: #16a34a; font-size: 18px; }
.info-text { font-size: 14px; color: #211a10; font-weight: 500; }
.info-detail { font-size: 12px; color: #8a7d68; margin-top: 8px; padding-left: 26px; }

/* 底部 */
.sidebar-footer { padding: 16px 20px; border-top: 1px solid #f2ebde; display: flex; gap: 12px; }
.btn-refresh { flex: 1; border-color: #d8cfbe; color: #43392a; background: #f2ebde; }
.btn-refresh:disabled { opacity: .4; }
.btn-deploy { flex: 2; background: #6366f1; border: none; font-weight: 600; }
.btn-deploy:disabled { opacity: .4; }

/* 预览区 */
.preview-area { flex: 1; background: #efeae0; display: flex; align-items: center; justify-content: center; padding: 40px; }
.preview-container { width: 100%; height: 100%; max-width: 1400px; background: #fff; border-radius: 8px; box-shadow: 0 0 30px rgba(74,53,24,.14); display: flex; flex-direction: column; border: 1px solid #d8cfbe; overflow: hidden; }
.browser-header { height: 42px; background: #f2ebde; border-bottom: 1px solid #fbf8f2; display: flex; align-items: center; gap: 12px; padding: 0 16px; }
.dots { display: flex; gap: 6px; }
.dot { width: 10px; height: 10px; border-radius: 50%; }
.dot.red { background: #ff5f57; } .dot.yellow { background: #febc2e; } .dot.green { background: #28c840; }
.address-bar { flex: 1; height: 28px; background: #fbf8f2; border: 1px solid #d8cfbe; border-radius: 4px; display: flex; align-items: center; padding: 0 10px; font-size: 12px; color: #8a7d68; gap: 8px; }
.refresh-icon { cursor: pointer; color: #8a7d68; } .refresh-icon:hover { color: #43392a; }
.iframe-box { flex: 1; position: relative; }
iframe { width: 100%; height: 100%; border: none; }
.loading-mask { position: absolute; inset: 0; background: rgba(251,248,242,.95); display: flex; justify-content: center; align-items: center; z-index: 20; }
.loading-content { text-align: center; color: #43392a; }
.loading-title { font-size: 15px; margin: 16px 0 6px; }
.loading-sub { font-size: 13px; color: #8a7d68; }
.empty-state { height: 100%; display: flex; flex-direction: column; align-items: center; justify-content: center; color: #8a7d68; gap: 8px; background: #efeae0; }
.empty-state p { margin: 0; font-size: 15px; }
.empty-state .sub-hint { font-size: 13px; color: #a8a29e; }
.error-state { height: 100%; display: flex; flex-direction: column; align-items: center; justify-content: center; color: #b5432f; gap: 12px; background: #efeae0; padding: 0 40px; text-align: center; }
.error-state p { margin: 0; font-size: 14px; line-height: 1.6; max-width: 420px; }

/* 优化弹窗 */
.refine-tip { font-size: 14px; color: #43392a; margin-bottom: 12px; }

/* Element Plus 覆盖 */
:deep(.el-select .el-input__wrapper) { background-color: #f2ebde !important; box-shadow: 0 0 0 1px #d8cfbe inset !important; }
:deep(.el-input__wrapper), :deep(.el-textarea__inner) { background-color: #f2ebde !important; box-shadow: 0 0 0 1px #d8cfbe inset !important; color: #43392a !important; }
:deep(.el-form-item__label) { color: #8a7d68 !important; font-size: 13px; }
</style>
