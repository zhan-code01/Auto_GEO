<template>
  <el-dialog
    :model-value="modelValue"
    :title="`${platformName} — 本机浏览器授权`"
    width="520px"
    :close-on-click-modal="false"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <!-- 步骤指示器 -->
    <div class="step-indicator">
      <div v-for="(step, i) in steps" :key="i" :class="['step', { active: currentStep === i, done: currentStep > i }]">
        <div class="step-num">{{ currentStep > i ? '✓' : i + 1 }}</div>
        <div class="step-label">{{ step }}</div>
      </div>
    </div>

    <!-- Step 0: 检查插件安装状态 -->
    <div v-if="currentStep === 0" class="step-content">
      <div class="info-card">
        <div class="info-icon">🔌</div>
        <div class="info-text">
          <strong>安装 AutoGEO 浏览器插件</strong>
          <p>插件用于将您的浏览器登录态安全同步到 AutoGEO 服务器。</p>
        </div>
      </div>

      <div class="install-guide">
        <div class="guide-step">1. 下载插件压缩包（联系管理员获取）</div>
        <div class="guide-step">2. 打开 Chrome/Edge 扩展管理页面 <code>chrome://extensions</code></div>
        <div class="guide-step">3. 开启右上角「开发者模式」</div>
        <div class="guide-step">4. 拖入插件包或点击「加载已解压的扩展程序」</div>
        <div class="guide-step">5. 点击工具栏右侧的 AutoGEO 图标，确认已启用</div>
      </div>

      <el-input v-model="backendUrl" placeholder="AutoGEO 后端地址，如 https://autogeo.yourdomain.com" size="large" class="backend-url-input">
        <template #prepend>后端地址</template>
      </el-input>
    </div>

    <!-- Step 1: 输入绑定码 -->
    <div v-if="currentStep === 1" class="step-content">
      <div class="info-card">
        <div class="info-icon">🔗</div>
        <div class="info-text">
          <strong>绑定插件到您的账号</strong>
          <p>在插件弹窗中输入下方的绑定码完成身份关联。</p>
        </div>
      </div>

      <div class="pair-code-display">
        <div class="pair-code-label">绑定码</div>
        <div class="pair-code-value">{{ pairCode }}</div>
        <div class="pair-code-hint">有效期 5 分钟，请尽快完成绑定</div>
      </div>

      <div class="plugin-hint">
        <p>1. 点击浏览器工具栏右侧的 <strong>AutoGEO</strong> 图标</p>
        <p>2. 在插件弹窗中输入绑定码 <strong>{{ pairCode }}</strong></p>
        <p>3. 点击「绑定」按钮</p>
      </div>

      <el-button type="primary" :loading="pollingBind" @click="checkBindStatus" class="check-bind-btn">
        我已完成绑定，继续
      </el-button>
    </div>

    <!-- Step 2: 登录 AI 平台 -->
    <div v-if="currentStep === 2" class="step-content">
      <div class="info-card">
        <div class="info-icon">🌐</div>
        <div class="info-text">
          <strong>登录 {{ platformName }}</strong>
          <p>在自己电脑的浏览器中打开 {{ platformName }} 并完成登录。</p>
        </div>
      </div>

      <div class="open-platform-btns">
        <el-button type="primary" plain @click="openPlatform(platformUrls[platformId])">
          打开 {{ platformName }}
        </el-button>
      </div>

      <div class="sync-hint">
        <p>1. 在打开的 {{ platformName }} 页面中<strong>扫码</strong>或<strong>账号密码登录</strong></p>
        <p>2. 登录成功后，点击插件图标的<strong>「同步」</strong>按钮</p>
        <p>3. 等待插件显示「同步成功」后，点击下方按钮</p>
      </div>

      <el-button type="primary" :loading="syncing" @click="checkSyncStatus" class="check-sync-btn">
        我已完成同步，继续
      </el-button>
    </div>

    <!-- Step 3: 完成 -->
    <div v-if="currentStep === 3" class="step-content">
      <div class="success-card">
        <div class="success-icon">✅</div>
        <div class="success-text">
          <strong>{{ platformName }} 授权成功！</strong>
          <p>登录态已保存，服务器可以使用您的身份访问 {{ platformName }}。</p>
        </div>
      </div>
    </div>

    <!-- 错误提示 -->
    <el-alert v-if="errorMsg" :title="errorMsg" type="error" show-icon class="step-error" />

    <template #footer>
      <div class="dialog-footer">
        <el-button @click="emit('update:modelValue', false)">取消</el-button>
        <el-button v-if="currentStep === 0" type="primary" :disabled="!backendUrl" :loading="creatingCode" @click="createPairCode">
          生成绑定码
        </el-button>
        <el-button v-if="currentStep === 2" type="default" @click="currentStep = 1">
          上一步
        </el-button>
        <el-button v-if="currentStep === 3" type="primary" @click="handleDone">
          完成
        </el-button>
      </div>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { get, post } from '@/services/api'
import { useUserStore } from '@/stores/modules/user'

const props = defineProps<{
  modelValue: boolean
  platformId: string    // doubao / qianwen / deepseek
  platformName: string
}>()

const emit = defineEmits<{
  (event: 'update:modelValue', value: boolean): void
  (event: 'success'): void
}>()

const userStore = useUserStore()
const steps = ['安装插件', '绑定账号', '登录平台', '完成']
const currentStep = ref(0)
const pairCode = ref('')
const backendUrl = ref(window.location.origin)
const creatingCode = ref(false)
const pollingBind = ref(false)
const syncing = ref(false)
const errorMsg = ref('')

const platformUrls: Record<string, string> = {
  doubao:   'https://www.doubao.com',
  qianwen:  'https://qianwen.com',
  deepseek: 'https://chat.deepseek.com',
}

watch(() => props.modelValue, (val) => {
  if (val) {
    currentStep.value = 0
    pairCode.value = ''
    errorMsg.value = ''
    syncing.value = false
    pollingBind.value = false
  }
})

async function createPairCode() {
  creatingCode.value = true
  errorMsg.value = ''
  try {
    const res: any = await post('/auth/extension/pair-code', {
      platform: props.platformId,
      scene: 'account_auth',
    })
    if (res.success) {
      pairCode.value = res.pair_code
      currentStep.value = 1
    } else {
      errorMsg.value = res.detail || '生成绑定码失败'
    }
  } catch (e: any) {
    errorMsg.value = e?.response?.data?.detail || e?.message || '生成绑定码失败'
  } finally {
    creatingCode.value = false
  }
}

async function checkBindStatus() {
  pollingBind.value = true
  errorMsg.value = ''
  // 前端不知道插件侧是否绑定成功，只能提示用户确认
  // 这里直接进入下一步，让用户自己操作插件
  await new Promise(r => setTimeout(r, 1000))
  pollingBind.value = false
  currentStep.value = 2
}

async function checkSyncStatus() {
  syncing.value = true
  errorMsg.value = ''
  try {
    // 轮询 session 状态，最多等 60 秒
    for (let i = 0; i < 30; i++) {
      await new Promise(r => setTimeout(r, 2000))
      try {
        // 暂时用 fast 检查，如果文件存在就认为成功
        const userId = userStore.user?.id
        if (!userId) {
          errorMsg.value = '未登录，请重新登录后再试'
          syncing.value = false
          return
        }
        const res: any = await get('/auth/session/status', { user_id: userId, platform: props.platformId, fast: true })
        if (res?.success && res?.data?.exists) {
          currentStep.value = 3
          syncing.value = false
          return
        }
      } catch {}
    }
    errorMsg.value = '检测超时，请在插件中确认同步状态后再试'
  } catch (e: any) {
    errorMsg.value = e?.message || '检测失败'
  } finally {
    syncing.value = false
  }
}

function openPlatform(url: string) {
  window.open(url, '_blank')
}

function handleDone() {
  emit('update:modelValue', false)
  emit('success')
}
</script>

<style scoped>
.step-indicator {
  display: flex;
  justify-content: center;
  gap: 0;
  margin-bottom: 24px;
  position: relative;
}
.step {
  display: flex;
  flex-direction: column;
  align-items: center;
  flex: 1;
  position: relative;
  z-index: 1;
}
.step:not(:last-child)::after {
  content: '';
  position: absolute;
  top: 14px;
  left: 50%;
  width: 100%;
  height: 2px;
  background: #e0e0e0;
  z-index: 0;
}
.step.done:not(:last-child)::after {
  background: #0066FF;
}
.step-num {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  background: #e0e0e0;
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 13px;
  font-weight: 600;
  position: relative;
  z-index: 2;
}
.step.active .step-num { background: #0066FF; }
.step.done .step-num { background: #28a745; }
.step-label { font-size: 12px; color: #888; margin-top: 4px; text-align: center; }
.step.active .step-label { color: #0066FF; font-weight: 500; }

.step-content { min-height: 200px; }

.info-card {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 14px;
  background: #f5f7ff;
  border-radius: 8px;
  margin-bottom: 16px;
  border: 1px solid #dde3ff;
}
.info-icon { font-size: 22px; flex-shrink: 0; }
.info-text strong { display: block; margin-bottom: 4px; font-size: 14px; }
.info-text p { font-size: 12px; color: #666; margin: 0; }

.install-guide { margin-bottom: 16px; }
.guide-step {
  font-size: 13px;
  color: #555;
  padding: 6px 0;
  border-bottom: 1px solid #f0f0f0;
}
.guide-step:last-child { border-bottom: none; }
.guide-step code {
  background: #f0f0f0;
  padding: 1px 5px;
  border-radius: 3px;
  font-size: 12px;
  color: #d63384;
}

.backend-url-input { margin-bottom: 8px; }

.pair-code-display {
  text-align: center;
  padding: 20px;
  background: #f0f7ff;
  border-radius: 8px;
  margin-bottom: 16px;
  border: 1px solid #cce0ff;
}
.pair-code-label { font-size: 12px; color: #888; margin-bottom: 6px; }
.pair-code-value {
  font-size: 36px;
  font-weight: 700;
  letter-spacing: 8px;
  color: #0066FF;
  font-family: monospace;
}
.pair-code-hint { font-size: 11px; color: #f56c6c; margin-top: 6px; }

.plugin-hint {
  font-size: 13px;
  color: #555;
  background: #fafafa;
  border-radius: 6px;
  padding: 12px 14px;
  margin-bottom: 14px;
  border: 1px solid #eee;
}
.plugin-hint p { margin: 4px 0; }

.open-platform-btns { text-align: center; margin-bottom: 16px; }

.sync-hint {
  font-size: 13px;
  color: #555;
  background: #fafafa;
  border-radius: 6px;
  padding: 12px 14px;
  margin-bottom: 14px;
  border: 1px solid #eee;
}
.sync-hint p { margin: 4px 0; }

.check-bind-btn,
.check-sync-btn { width: 100%; margin-top: 4px; }

.success-card {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 20px;
  background: #edfaed;
  border-radius: 8px;
  border: 1px solid #b8e6b8;
  margin-bottom: 16px;
}
.success-icon { font-size: 32px; }
.success-text strong { display: block; font-size: 16px; color: #155724; margin-bottom: 4px; }
.success-text p { font-size: 13px; color: #666; margin: 0; }

.step-error { margin-top: 12px; }

.dialog-footer { display: flex; justify-content: flex-end; gap: 8px; }
</style>
