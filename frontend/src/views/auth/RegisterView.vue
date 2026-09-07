<template>
  <div class="register-page">
    <div class="register-container">
      <!-- 左侧装饰区 -->
      <div class="register-decoration">
        <div class="decoration-content">
          <div class="logo-large">
            <span class="logo-icon">🚀</span>
            <span class="logo-text">AutoGeo</span>
          </div>
          <p class="slogan">智能多平台文章发布助手</p>
          <div class="features">
            <div class="feature-item">
              <el-icon><Check /></el-icon>
              <span>智能 GEO 文章生成</span>
            </div>
            <div class="feature-item">
              <el-icon><Check /></el-icon>
              <span>多平台一键发布</span>
            </div>
            <div class="feature-item">
              <el-icon><Check /></el-icon>
              <span>收录状态实时监控</span>
            </div>
            <div class="feature-item">
              <el-icon><Check /></el-icon>
              <span>定时任务自动执行</span>
            </div>
          </div>
        </div>
      </div>

      <!-- 右侧注册表单 -->
      <div class="register-form-wrapper">
        <div class="register-form-container">
          <h2 class="form-title">创建账号</h2>
          <p class="form-subtitle">填写以下信息完成注册</p>

          <el-form
            ref="formRef"
            :model="formData"
            :rules="formRules"
            class="register-form"
            @keyup.enter="handleRegister"
          >
            <el-form-item prop="username">
              <el-input
                v-model="formData.username"
                placeholder="请输入用户名（3-20个字符）"
                size="large"
                :prefix-icon="User"
                clearable
              />
            </el-form-item>

            <el-form-item prop="nickname">
              <el-input
                v-model="formData.nickname"
                placeholder="请输入昵称（可选）"
                size="large"
                :prefix-icon="UserFilled"
                clearable
              />
            </el-form-item>

            <el-form-item prop="password">
              <el-input
                v-model="formData.password"
                type="password"
                placeholder="请输入密码（6-20个字符）"
                size="large"
                :prefix-icon="Lock"
                show-password
                clearable
              />
            </el-form-item>

            <el-form-item prop="confirmPassword">
              <el-input
                v-model="formData.confirmPassword"
                type="password"
                placeholder="请再次输入密码"
                size="large"
                :prefix-icon="Lock"
                show-password
                clearable
              />
            </el-form-item>

            <el-form-item prop="email">
              <el-input
                v-model="formData.email"
                placeholder="请输入邮箱（可选）"
                size="large"
                :prefix-icon="Message"
                clearable
              />
            </el-form-item>

            <el-form-item>
              <el-button
                type="primary"
                size="large"
                class="register-button"
                :loading="loading"
                @click="handleRegister"
              >
                {{ loading ? '注册中...' : '立即注册' }}
              </el-button>
            </el-form-item>
          </el-form>

          <div class="form-footer">
            <span class="has-account">已有账号？</span>
            <el-button type="primary" link @click="router.push('/login')">
              立即登录
            </el-button>
          </div>

          <div class="version-info">
            <span>Version 1.0.0</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import type { FormInstance, FormRules } from 'element-plus'
import { User, Lock, UserFilled, Message, Check } from '@element-plus/icons-vue'
import { register } from '@/services/userApi'

const router = useRouter()

// 表单引用
const formRef = ref<FormInstance>()

// 加载状态
const loading = ref(false)

// 表单数据
const formData = reactive({
  username: '',
  nickname: '',
  password: '',
  confirmPassword: '',
  email: '',
})

// 自定义验证：确认密码
const validateConfirmPassword = (_rule: unknown, value: string, callback: (error?: Error) => void) => {
  if (value !== formData.password) {
    callback(new Error('两次输入的密码不一致'))
  } else {
    callback()
  }
}

// 表单验证规则
const formRules: FormRules = {
  username: [
    { required: true, message: '请输入用户名', trigger: 'blur' },
    { min: 3, max: 20, message: '用户名长度应为 3-20 个字符', trigger: 'blur' },
  ],
  password: [
    { required: true, message: '请输入密码', trigger: 'blur' },
    { min: 6, max: 20, message: '密码长度应为 6-20 个字符', trigger: 'blur' },
  ],
  confirmPassword: [
    { required: true, message: '请再次输入密码', trigger: 'blur' },
    { validator: validateConfirmPassword, trigger: 'blur' },
  ],
  email: [
    { type: 'email', message: '请输入有效的邮箱地址', trigger: 'blur' },
  ],
}

/**
 * 处理注册
 */
async function handleRegister() {
  if (!formRef.value) return

  await formRef.value.validate(async (valid) => {
    if (!valid) return

    loading.value = true

    try {
      const result = await register({
        username: formData.username,
        password: formData.password,
        nickname: formData.nickname || undefined,
        email: formData.email || undefined,
      })

      if (result.success) {
        ElMessage.success('注册成功！请登录')
        router.push('/login')
      } else {
        ElMessage.error(result.message || '注册失败')
      }
    } catch (error: unknown) {
      const message = error instanceof Error ? error.message : '注册失败，请稍后重试'
      ElMessage.error(message)
    } finally {
      loading.value = false
    }
  })
}
</script>

<style scoped lang="scss">
.register-page {
  width: 100vw;
  height: 100vh;
  background: var(--surface-root);
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
}

.register-container {
  display: flex;
  width: 1000px;
  height: 650px;
  background: var(--surface-raised);
  border-radius: var(--radius-xl);
  overflow: hidden;
  box-shadow: var(--shadow-lg);
  border: 1px solid var(--border-thin);
}

// 左侧装饰区
.register-decoration {
  flex: 1;
  background:
    linear-gradient(135deg, rgba(196, 116, 28, 0.10) 0%, rgba(31, 122, 146, 0.08) 100%);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 40px;
  position: relative;
  overflow: hidden;

  &::before {
    content: '';
    position: absolute;
    top: -50%;
    left: -50%;
    width: 200%;
    height: 200%;
    background: radial-gradient(circle, rgba(31, 122, 146, 0.08) 0%, transparent 70%);
    animation: pulse 4s ease-in-out infinite;
  }

  @keyframes pulse {
    0%, 100% { transform: scale(1); opacity: 0.5; }
    50% { transform: scale(1.1); opacity: 0.8; }
  }
}

.decoration-content {
  position: relative;
  z-index: 1;
  text-align: center;
}

.logo-large {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 16px;
  margin-bottom: 16px;

  .logo-icon {
    font-size: 48px;
  }

  .logo-text {
    font-family: var(--font-display);
    font-size: 36px;
    font-weight: 700;
    letter-spacing: -0.02em;
    background: linear-gradient(135deg, var(--accent), var(--accent-blue));
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
  }
}

.slogan {
  font-size: 18px;
  color: var(--text-muted);
  margin-bottom: 40px;
}

.features {
  display: flex;
  flex-direction: column;
  gap: 16px;
  text-align: left;
}

.feature-item {
  display: flex;
  align-items: center;
  gap: 12px;
  color: var(--text-body);
  font-size: 14px;

  .el-icon {
    color: var(--success);
    font-size: 18px;
  }
}

// 右侧注册表单
.register-form-wrapper {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 40px;
}

.register-form-container {
  width: 100%;
  max-width: 360px;
}

.form-title {
  font-family: var(--font-display);
  font-size: 28px;
  font-weight: 700;
  color: var(--text-head);
  margin: 0 0 8px 0;
  text-align: center;
  letter-spacing: -0.01em;
}

.form-subtitle {
  font-size: 14px;
  color: var(--text-muted);
  margin: 0 0 32px 0;
  text-align: center;
}

.register-form {
  .el-input {
    :deep(.el-input__wrapper) {
      background: var(--surface-field) !important;
      border-radius: var(--radius-sm);
      box-shadow: none !important;
      border: 1px solid var(--border-soft) !important;
      padding: 4px 16px;
      height: 48px;
      transition: all var(--duration-fast) var(--ease-out);

      &:hover { border-color: var(--border-hover) !important; }

      &.is-focus {
        border-color: var(--accent) !important;
        box-shadow: 0 0 0 3px var(--accent-soft) !important;
      }
    }

    :deep(.el-input__inner) {
      color: var(--text-body);
      font-size: 15px;
    }

    :deep(.el-input__icon) {
      color: var(--text-muted);
    }
  }
}

.register-button {
  width: 100%;
  height: 48px;
  font-size: 16px;
  font-weight: 600;
  border-radius: var(--radius-sm);
  background:
    linear-gradient(135deg, #e0941f, var(--accent) 56%, #9c560e);
  border: none;
  color: var(--accent-ink);
  letter-spacing: 0.04em;
  transition: all var(--duration-normal) var(--ease-out);

  &:hover {
    background: linear-gradient(135deg, #e6a035, var(--accent-hover) 56%, #a86018);
    transform: translateY(-1px);
    box-shadow: var(--shadow-glow);
  }

  &:active {
    transform: translateY(0);
  }
}

.form-footer {
  margin-top: 16px;
  text-align: center;
  display: flex;
  justify-content: center;
  align-items: center;
  gap: 4px;

  .has-account {
    color: var(--text-muted);
    font-size: 14px;
  }
}

.version-info {
  margin-top: 24px;
  text-align: center;
  color: var(--text-disabled);
  font-size: 12px;
}

// 响应式设计
@media (max-width: 900px) {
  .register-container {
    width: 90%;
    height: auto;
    flex-direction: column;
  }

  .register-decoration {
    padding: 30px;
    min-height: 200px;
  }

  .logo-large {
    .logo-icon {
      font-size: 36px;
    }

    .logo-text {
      font-size: 28px;
    }
  }

  .slogan {
    font-size: 16px;
    margin-bottom: 24px;
  }

  .features {
    display: none;
  }

  .register-form-wrapper {
    padding: 30px;
  }
}

@media (max-width: 480px) {
  .register-decoration {
    padding: 20px;
    min-height: 150px;
  }

  .logo-large {
    .logo-icon {
      font-size: 28px;
    }

    .logo-text {
      font-size: 24px;
    }
  }

  .slogan {
    font-size: 14px;
    margin-bottom: 16px;
  }

  .register-form-wrapper {
    padding: 20px;
  }
}
</style>