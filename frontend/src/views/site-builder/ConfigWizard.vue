<template>
  <div class="page-container">
    
    <!-- 左侧：控制台 -->
    <div class="sidebar">
      <div class="sidebar-header">
        <div class="logo-box"><el-icon :size="20" color="#fff"><Platform /></el-icon></div>
        <div class="header-text"><h2>全能建站工坊</h2><p>AI 驱动 · 即时渲染</p></div>
      </div>

      <div class="form-scroll-area">
        <el-form :model="formData" label-position="top" class="dark-form">
          <!-- 默认展开前两项：0=模版选择, 1=品牌视觉 -->
          <el-collapse v-model="activeNames" class="minimal-collapse">
            
            <!-- [核心新增] 0. 模版选择 -->
            <el-collapse-item name="0">
              <template #title><div class="section-title"><span class="bar"></span><h3>选择模版 (Templates)</h3></div></template>
              <div class="form-section-content">
                <div class="template-grid">
                  <!-- 模版 A: 商务 -->
                  <div 
                    class="template-card" 
                    :class="{ active: formData.template_id === 'corporate' }"
                    @click="formData.template_id = 'corporate'"
                  >
                    <div class="preview-box bg-[#0f172a]">
                      <div class="mini-nav"></div>
                      <div class="mini-hero text-white">Corp</div>
                    </div>
                    <div class="template-info">
                      <span class="name">商务旗舰版</span>
                      <span class="tag">稳重</span>
                    </div>
                    <div class="check-mark" v-if="formData.template_id === 'corporate'"><el-icon><Check /></el-icon></div>
                  </div>

                  <!-- 模版 B: Cowboy -->
                  <div 
                    class="template-card" 
                    :class="{ active: formData.template_id === 'cowboy' }"
                    @click="formData.template_id = 'cowboy'"
                  >
                    <div class="preview-box bg-[#fdfbf7] border border-gray-600">
                      <div class="mini-nav-light"></div>
                      <div class="mini-hero text-black">Modern</div>
                    </div>
                    <div class="template-info">
                      <span class="name">现代生活版</span>
                      <span class="tag">极简</span>
                    </div>
                    <div class="check-mark" v-if="formData.template_id === 'cowboy'"><el-icon><Check /></el-icon></div>
                  </div>
                </div>
              </div>
            </el-collapse-item>

            <!-- 1. 品牌与配色 -->
            <el-collapse-item name="1">
              <template #title><div class="section-title"><span class="bar"></span><h3>品牌视觉</h3></div></template>
              <div class="form-section-content">
                <el-form-item label="公司全称"><el-input v-model="formData.company_name" /></el-form-item>
                <el-form-item label="品牌主色"><el-color-picker v-model="formData.theme_color_primary" show-alpha /></el-form-item>
                <el-form-item label="强调色"><el-color-picker v-model="formData.theme_color_accent" show-alpha /></el-form-item>
              </div>
            </el-collapse-item>

            <!-- 2. 首屏 -->
            <el-collapse-item name="2">
              <template #title><div class="section-title"><span class="bar"></span><h3>首屏 (Hero)</h3></div></template>
              <div class="form-section-content">
                <el-form-item label="标签"><el-input v-model="formData.hero_badge_text" /></el-form-item>
                <el-form-item label="标语"><el-input v-model="formData.company_slogan_hero" type="textarea" :rows="2" /></el-form-item>
                <el-form-item label="描述"><el-input v-model="formData.company_description_hero" type="textarea" :rows="3" /></el-form-item>
                <el-form-item label="背景图"><FileUpload :imageUrl="formData.image_hero_bg" @success="(url)=>formData.image_hero_bg=url" tip="1920x1080"/></el-form-item>
              </div>
            </el-collapse-item>

            <!-- 3. 数据 -->
            <el-collapse-item name="3">
              <template #title><div class="section-title"><span class="bar"></span><h3>数据 (Stats)</h3></div></template>
              <div class="form-section-content">
                <div v-for="(s,i) in formData.stats" :key="i" class="list-item-card">
                  <div class="flex-row gap-2"><el-input v-model="s.value" style="width:80px"/><el-input v-model="s.unit" style="width:60px"/><el-input v-model="s.label"/></div>
                  <el-icon class="delete-icon" @click="formData.stats.splice(i,1)"><Delete/></el-icon>
                </div>
                <el-button class="w-full mt-2 btn-dashed" size="small" @click="addStat" icon="Plus">添加指标</el-button>
              </div>
            </el-collapse-item>

            <!-- 4. 服务 -->
            <el-collapse-item name="4">
              <template #title><div class="section-title"><span class="bar"></span><h3>服务 (Services)</h3></div></template>
              <div class="form-section-content">
                <div v-for="(s,i) in formData.services" :key="i" class="list-item-card">
                  <div class="flex-col w-full">
                    <div class="flex-row gap-2 mb-2"><el-input v-model="s.icon" style="width:120px"><template #prefix>fa-</template></el-input><el-input v-model="s.title"/></div>
                    <el-input v-model="s.desc" type="textarea" :rows="2"/>
                  </div>
                  <el-icon class="delete-icon" @click="formData.services.splice(i,1)"><Delete/></el-icon>
                </div>
                <el-button class="w-full mt-2 btn-dashed" size="small" @click="addService" icon="Plus">添加服务</el-button>
              </div>
            </el-collapse-item>

            <!-- 5. 关于 -->
            <el-collapse-item name="5">
              <template #title><div class="section-title"><span class="bar"></span><h3>关于 (About)</h3></div></template>
              <div class="form-section-content">
                <el-form-item label="标题"><el-input v-model="formData.company_about_title"/></el-form-item>
                <el-form-item label="简介"><el-input v-model="formData.company_about_intro" type="textarea" :rows="4"/></el-form-item>
                <el-form-item label="核心优势列表">
                  <div v-for="(feat, i) in formData.company_features" :key="i" class="list-item-card">
                    <el-input v-model="formData.company_features[i]" />
                    <el-icon class="delete-icon ml-2" @click="formData.company_features.splice(i,1)"><Delete/></el-icon>
                  </div>
                  <el-button class="w-full mt-2 btn-dashed" size="small" @click="addFeature" icon="Plus">添加优势</el-button>
                </el-form-item>
                <el-form-item label="配图"><FileUpload :imageUrl="formData.image_about_team" @success="(url)=>formData.image_about_team=url" tip="竖向图片"/></el-form-item>
              </div>
            </el-collapse-item>

            <!-- 6. 资质 -->
            <el-collapse-item name="8">
              <template #title><div class="section-title"><span class="bar"></span><h3>资质 (Quals)</h3></div></template>
              <div class="form-section-content">
                <div v-for="(q,i) in formData.qualifications" :key="i" class="list-item-card">
                  <div class="flex-col w-full"><el-input v-model="q.title" class="mb-2 font-bold"/><el-input v-model="q.desc" size="small"/></div>
                  <el-icon class="delete-icon" @click="formData.qualifications.splice(i,1)"><Delete/></el-icon>
                </div>
                <el-button class="w-full mt-2 btn-dashed" size="small" @click="addQual" icon="Plus">添加资质</el-button>
              </div>
            </el-collapse-item>

            <!-- 7. 案例 -->
            <el-collapse-item name="6">
              <template #title><div class="section-title"><span class="bar"></span><h3>案例 (Cases)</h3></div></template>
              <div class="form-section-content">
                <div v-for="(c,i) in formData.cases" :key="i" class="list-item-card column-layout">
                  <div class="card-header"><span class="badge">#{{i+1}}</span><el-icon class="delete-icon-static" @click="formData.cases.splice(i,1)"><Delete/></el-icon></div>
                  <el-form-item label="封面"><FileUpload :imageUrl="c.image" @success="(url)=>c.image=url" height="100px"/></el-form-item>
                  <div class="flex-row gap-2 mb-2"><el-input v-model="c.tag" style="width:40%"/><el-input v-model="c.title" style="width:60%"/></div>
                  <el-input v-model="c.desc" type="textarea" :rows="2"/>
                </div>
                <el-button class="w-full mt-2 btn-dashed" size="small" @click="addCase" icon="Plus">添加案例</el-button>
              </div>
            </el-collapse-item>

            <!-- 8. 联系 -->
            <el-collapse-item name="7">
              <template #title><div class="section-title"><span class="bar"></span><h3>联系 (Contact)</h3></div></template>
              <div class="form-section-content">
                <el-form-item label="地址"><el-input v-model="formData.contact_address" prefix-icon="Location"/></el-form-item>
                <el-form-item label="电话"><el-input v-model="formData.contact_phone" prefix-icon="Phone"/></el-form-item>
                <el-form-item label="邮箱"><el-input v-model="formData.contact_email" prefix-icon="Message"/></el-form-item>
              </div>
            </el-collapse-item>

          </el-collapse>
        </el-form>
      </div>
      <div class="sidebar-footer">
        <el-button class="btn-refresh" size="large" @click="refresh" :icon="Refresh">刷新</el-button>
        <el-button class="btn-deploy" type="primary" size="large" @click="openDeployDialog">立即部署</el-button>
      </div>
    </div>

    <!-- 右侧：预览 -->
    <div class="preview-area">
      <div class="preview-container">
        <div class="browser-header">
          <div class="dots"><span class="dot red"></span><span class="dot yellow"></span><span class="dot green"></span></div>
          <div class="address-bar"><el-icon><Lock /></el-icon><span>{{ previewError ? '生成失败' : (url || 'Ready...') }}</span></div>
          <el-icon class="refresh-icon" @click="refresh"><RefreshRight /></el-icon>
        </div>
        <div class="iframe-box">
          <iframe v-if="url" :src="url"></iframe>
          <div v-if="loading" class="loading-mask"><el-icon class="is-loading" size="30"><Loading /></el-icon></div>
          <div v-if="!url && !loading && previewError" class="error-state"><el-icon size="46" color="#d24a3c"><WarningFilled /></el-icon><p>{{ previewError }}</p></div>
          <div v-if="!url && !loading && !previewError" class="empty-state"><el-icon size="50"><Platform /></el-icon><p>AI 引擎已就绪</p></div>
        </div>
      </div>
    </div>

    <!-- 部署弹窗 -->
    <el-dialog v-model="showDeployDialog" title="发布上线配置" width="500px" custom-class="deploy-dialog">
      <el-tabs v-model="deployMethod" class="deploy-tabs">
        <el-tab-pane label="远程服务器 (SFTP)" name="sftp">
          <div class="p-2">
            <el-alert title="上传路径需对应 Nginx/Apache 的 Web 根目录" type="info" :closable="false" show-icon class="mb-4"/>
            <el-form label-position="left" label-width="110px">
              <el-form-item label="主机 IP"><el-input v-model="deployConfig.sftp_host"/></el-form-item>
              <el-form-item label="SSH 端口"><el-input v-model="deployConfig.sftp_port" placeholder="22"/></el-form-item>
              <el-form-item label="用户名"><el-input v-model="deployConfig.sftp_user"/></el-form-item>
              <el-form-item label="认证方式">
                <el-radio-group v-model="deployConfig.sftp_auth_type">
                  <el-radio-button label="password" value="password">密码</el-radio-button>
                  <el-radio-button label="private_key" value="private_key">PEM 私钥</el-radio-button>
                </el-radio-group>
              </el-form-item>
              <el-form-item v-if="deployConfig.sftp_auth_type === 'password'" label="密码">
                <el-input v-model="deployConfig.sftp_pass" type="password" show-password/>
              </el-form-item>
              <template v-else>
                <el-form-item label="PEM 私钥">
                  <el-input
                    v-model="deployConfig.sftp_private_key"
                    type="textarea"
                    :rows="5"
                    placeholder="粘贴 .pem 文件完整内容，包含 BEGIN/END 行"
                  />
                </el-form-item>
                <el-form-item label="私钥口令">
                  <el-input v-model="deployConfig.sftp_key_passphrase" type="password" show-password placeholder="无口令可留空"/>
                </el-form-item>
              </template>
              <el-form-item label="上传路径"><el-input v-model="deployConfig.sftp_path" placeholder="/var/www/html"/></el-form-item>
              <el-form-item label="访问域名">
                <el-input v-model="deployConfig.public_base_url" placeholder="https://www.example.com">
                   <template #append><el-tooltip content="浏览器实际访问的域名，与上传路径的 Web 根对应" placement="top"><el-icon><InfoFilled /></el-icon></el-tooltip></template>
                </el-input>
              </el-form-item>
              <el-form-item label="站点目录名">
                <el-input v-model="deployConfig.publish_slug" placeholder="留空自动生成">
                   <template #append><el-tooltip content="自定义发布子目录名，留空则自动用 项目名-site编号" placement="top"><el-icon><InfoFilled /></el-icon></el-tooltip></template>
                </el-input>
              </el-form-item>
            </el-form>
          </div>
        </el-tab-pane>
        <el-tab-pane label="云对象存储 (OSS/S3)" name="s3">
          <div class="p-2">
            <el-form label-position="left" label-width="100px">
              <el-form-item label="Endpoint"><el-input v-model="deployConfig.s3_endpoint" placeholder="https://oss-cn-shenzhen.aliyuncs.com"/></el-form-item>
              <el-form-item label="Bucket"><el-input v-model="deployConfig.s3_bucket"/></el-form-item>
              <el-form-item label="AccessKey"><el-input v-model="deployConfig.s3_access_key"/></el-form-item>
              <el-form-item label="SecretKey"><el-input v-model="deployConfig.s3_secret_key" type="password" show-password/></el-form-item>
            </el-form>
          </div>
        </el-tab-pane>
      </el-tabs>
      <template #footer>
        <span class="dialog-footer">
          <el-button @click="showDeployDialog = false">取消</el-button>
          <el-button type="primary" @click="handleDeploy" :loading="deployLoading">确认发布</el-button>
        </span>
      </template>
    </el-dialog>

  </div>
</template>

<script setup>
import { ref, reactive, watch, onMounted, defineComponent, h } from 'vue';
import { debounce } from 'lodash';
import { ElMessage, ElUpload, ElIcon, ElMessageBox } from 'element-plus';
import { siteApi } from '@/services/api';
import { Platform, RefreshRight, Lock, Picture, Delete, Refresh, Loading, Location, Phone, Message, Plus, Promotion, Check, InfoFilled, WarningFilled } from '@element-plus/icons-vue';

const apiBase = import.meta.env.VITE_API_BASE_URL || '/api';
const backendBase = apiBase.endsWith('/api') ? apiBase.slice(0, -4) || '' : apiBase;

const FileUpload = defineComponent({
  props: ['imageUrl', 'tip', 'height'], emits: ['success'],
  setup(props, { emit }) {
    return () => h(ElUpload, {
      class: 'simple-uploader', action: `${apiBase}/upload`, showFileList: false,
      // ElUpload 用自带 XHR，不走统一 axios 拦截器，必须显式带 JWT
      headers: { Authorization: 'Bearer ' + (localStorage.getItem('autogeo_token') || '') },
      onSuccess: (res) => { if(res.url) emit('success', res.url); },
      onError: () => { ElMessage.error('图片上传失败，请重新登录后重试'); }
    }, { default: () => [
      props.imageUrl 
        ? h('img', { src: props.imageUrl.startsWith('http') ? props.imageUrl : `${backendBase}${props.imageUrl}`, class: 'uploaded-img', style: { height: props.height||'120px' } })
        : h('div', { class: 'uploader-placeholder', style: { height: props.height||'120px' } }, [h(ElIcon, { size: 24 }, () => h(Picture)), h('span', null, props.tip||'点击上传')])
    ]});
  }
});

const activeNames = ref(['0','1','2']);
const loading = ref(false);
const dLoading = ref(false);
const url = ref("");
const previewError = ref("");
const showDeployDialog = ref(false);
const deployLoading = ref(false);
const deployMethod = ref("sftp");
const currentSiteId = ref("");

const deployConfig = reactive({
  sftp_host: "", sftp_port: "22", sftp_user: "root", sftp_auth_type: "password",
  sftp_pass: "", sftp_private_key: "", sftp_key_passphrase: "", sftp_path: "/var/www/html",
  public_base_url: "", publish_slug: "",
  s3_endpoint: "", s3_bucket: "", s3_access_key: "", s3_secret_key: ""
});

const formData = reactive({
  template_id: "corporate", // 默认为商务风
  meta_title: "极速物流", company_name: "Turbo Logistics", theme_color_primary: "#0f172a", theme_color_accent: "#ef4444",
  hero_badge_text: "Global Leader", company_slogan_hero: "连接全球<br>极速送达", company_description_hero: "提供比传统物流快 30% 的服务。",
  image_hero_bg: "https://images.unsplash.com/photo-1586528116311-ad8dd3c8310d",
  stats: [{ value: "15", unit: "+", label: "年经验" }, { value: "200", unit: "个", label: "覆盖国家" }],
  services: [{ icon: "robot", title: "自动化", desc: "无人化操作" }, { icon: "plane", title: "航空速运", desc: "全球次日达" }],
  qualifications: [{ title: "ISO 9001", desc: "质量认证" }],
  company_about_title: "为什么选择我们？", company_about_intro: "拥有超过50名高级工程师...", image_about_team: "https://images.unsplash.com/photo-1556761175-5973dc0f32e7",
  company_features: ["行业领先的技术解决方案", "7x24小时 全球化支持"],
  cases: [{ title: "黑五保障", tag: "电商", desc: "0 爆仓", image: "https://images.unsplash.com/photo-1566576912321-d58ddd7a6088" }],
  contact_address: "上海市浦东新区", contact_phone: "400-888-6666", contact_email: "support@turbo.com"
});

const addStat = () => formData.stats.push({ value: "0", unit: "", label: "新指标" });
const addService = () => formData.services.push({ icon: "star", title: "新服务", desc: "描述" });
const addQual = () => formData.qualifications.push({ title: "证书", desc: "描述" });
const addCase = () => formData.cases.push({ title: "案例", tag: "行业", desc: "描述", image: "" });
const addFeature = () => formData.company_features.push("新优势特性");

const generate = debounce(async () => {
  loading.value = true;
  try {
    // 统一走 siteApi（自动带 JWT），返回体已是 { code, data }
    const res = await siteApi.build({
      name: formData.company_name,
      config: formData,
      template_id: formData.template_id
    });
    if (res.code === 200) {
      currentSiteId.value = res.data.site_id;
      url.value = `${backendBase}${res.data.preview_url}?t=${Date.now()}`;
      previewError.value = '';
    }
  } catch(e) {
    const status = e?.response?.status;
    const detail = e?.response?.data?.detail;
    if (status === 401) {
      previewError.value = '登录已过期，请重新登录后生成预览';
    } else if (status === 403) {
      previewError.value = '当前账号无权限使用智能建站';
    } else {
      previewError.value = (typeof detail === 'string' ? detail : (detail && detail.message)) || '预览生成失败，请稍后重试';
    }
    url.value = ''; // 清空 url，使右侧显示错误态而非一直 Ready
    console.error('预览生成失败:', e);
  } finally { setTimeout(() => loading.value = false, 500); }
}, 800);

watch(formData, () => generate(), { deep: true });
onMounted(() => generate());
const refresh = generate;
const openDeployDialog = () => { if(!currentSiteId.value) return ElMessage.warning('请先等待预览生成'); showDeployDialog.value = true; }

// 前端按 tab 校验，提前拦截错误配置，减少无谓的后端往返
const validateDeploy = () => {
  if (!currentSiteId.value) return '请先等待预览生成';
  if (deployMethod.value === 'sftp') {
    const authType = deployConfig.sftp_auth_type;
    if (!String(deployConfig.sftp_host || '').trim()) return '请填写主机 IP';
    if (!String(deployConfig.sftp_user || '').trim()) return '请填写用户名';
    if (authType === 'password' && !String(deployConfig.sftp_pass || '').trim()) return '请填写密码';
    if (authType === 'private_key' && !String(deployConfig.sftp_private_key || '').trim()) return '请粘贴 PEM 私钥内容，不是私钥口令';
    if (!String(deployConfig.sftp_path || '').trim()) return '请填写上传路径';
    if (!deployConfig.sftp_path.startsWith('/')) return '上传路径必须是绝对路径，例如 /var/www/html';
    if (deployConfig.public_base_url && !/^https?:\/\//i.test(deployConfig.public_base_url)) return '访问域名必须以 http:// 或 https:// 开头';
  } else if (deployMethod.value === 's3') {
    if (!deployConfig.s3_endpoint) return '请填写 Endpoint';
    if (!deployConfig.s3_bucket) return '请填写 Bucket';
    if (!deployConfig.s3_access_key) return '请填写 AccessKey';
    if (!deployConfig.s3_secret_key) return '请填写 SecretKey';
  }
  return '';
};

const handleDeploy = async () => {
  const err = validateDeploy();
  if (err) { ElMessage.warning(err); return; }
  deployLoading.value = true;
  try {
    // 按 tab 组装 payload：把前端字段映射到后端 public_base_url
    const payload = { site_id: currentSiteId.value, method: deployMethod.value, project_name: formData.company_name };
    if (deployMethod.value === 'sftp') {
      const authType = deployConfig.sftp_auth_type;
      Object.assign(payload, {
        sftp_host: String(deployConfig.sftp_host || '').trim(),
        sftp_port: deployConfig.sftp_port,
        sftp_user: String(deployConfig.sftp_user || '').trim(),
        sftp_auth_type: authType,
        sftp_path: String(deployConfig.sftp_path || '').trim(),
        public_base_url: String(deployConfig.public_base_url || '').trim(),
        publish_slug: String(deployConfig.publish_slug || '').trim()
      });
      if (authType === 'password') {
        Object.assign(payload, { sftp_pass: deployConfig.sftp_pass });
      } else {
        Object.assign(payload, {
          sftp_private_key: String(deployConfig.sftp_private_key || '').trim(),
          sftp_key_passphrase: deployConfig.sftp_key_passphrase || ''
        });
      }
    } else {
      Object.assign(payload, {
        s3_endpoint: deployConfig.s3_endpoint, s3_bucket: deployConfig.s3_bucket,
        s3_access_key: deployConfig.s3_access_key, s3_secret_key: deployConfig.s3_secret_key
      });
    }
    const res = await siteApi.deploy(payload);
    if (res.code === 200) {
      const data = res.data || {};
      ElMessage.success('🎉 发布成功，已生成可访问网页');
      showDeployDialog.value = false;
      if (data.url) {
        const win = window.open(data.url, '_blank');
        if (!win) ElMessage.warning('弹窗被浏览器拦截，请手动复制链接：' + data.url);
      }
    }
  } catch (error) {
    // 401/403 单独提示（拦截器已静默清 token，不弹通用 toast）
    const status = error?.response?.status;
    const d = error.response?.data?.detail;
    const code = (d && typeof d === 'object') ? d.code : '';
    if (code === 'SFTP_AUTH_FAILED') {
      ElMessage.error('SFTP 认证失败，请检查用户名、密码或私钥');
    } else if (status === 401) {
      ElMessage.error('登录已过期，请重新登录后再发布');
    } else if (status === 403) {
      ElMessage.error('无权发布该站点，只能发布自己生成的站点');
    } else {
      // 后端返回结构化 detail: { code, message, suggestion }
      const msg = (d && typeof d === 'object') ? d.message : (d || '发布失败');
      const suggestion = (d && typeof d === 'object') ? d.suggestion : '';
      ElMessage.error(msg);
      if (suggestion) ElMessageBox.alert(suggestion, '修复建议', { type: 'info' });
    }
  } finally { deployLoading.value = false; }
}
</script>

<style scoped>
/* 保持原有深色 CSS 样式 */
.page-container { display: flex; height: 100vh; background: #efeae0; font-family: sans-serif; overflow: hidden; }
.sidebar { width: 440px; min-width: 440px; background: #fbf8f2; border-right: 1px solid #f2ebde; display: flex; flex-direction: column; z-index: 10; box-shadow: 4px 0 20px rgba(74,53,24,0.10); }
.sidebar-header { padding: 20px; border-bottom: 1px solid #f2ebde; display: flex; gap: 12px; align-items: center; }
.logo-box { width: 36px; height: 36px; background: #c4741c; border-radius: 8px; display: flex; align-items: center; justify-content: center; }
.header-text h2 { margin: 0; font-size: 16px; color: #211a10; font-weight: 700; }
.header-text p { margin: 0; font-size: 12px; color: #8a7d68; }
.form-scroll-area { flex: 1; overflow-y: auto; padding: 0; background: #fbf8f2; }
.sidebar-footer { padding: 16px 20px; border-top: 1px solid #f2ebde; display: flex; gap: 12px; background: #fbf8f2; }
.btn-refresh { flex: 1; border-color: #d8cfbe; color: #43392a; background: #f2ebde; }
.btn-deploy { flex: 2; background: #c4741c; border: none; font-weight: 600; letter-spacing: 0.5px; }
.preview-area { flex: 1; background: #efeae0; display: flex; align-items: center; justify-content: center; padding: 40px; }
.preview-container { width: 100%; height: 100%; max-width: 1400px; background: #fff; border-radius: 8px; box-shadow: 0 0 30px rgba(74,53,24,0.14); display: flex; flex-direction: column; border: 1px solid #d8cfbe; overflow: hidden; }
.browser-header { height: 42px; background: #f2ebde; border-bottom: 1px solid #fbf8f2; display: flex; align-items: center; px: 16px; gap: 12px; padding: 0 16px; }
.dots { display: flex; gap: 6px; } .dot { width: 10px; height: 10px; border-radius: 50%; } .dot.red { background: #ff5f57; } .dot.yellow { background: #febc2e; } .dot.green { background: #28c840; }
.address-bar { flex: 1; height: 28px; background: #fbf8f2; border: 1px solid #d8cfbe; border-radius: 4px; display: flex; align-items: center; padding: 0 10px; font-size: 12px; color: #8a7d68; gap: 8px; }
.iframe-box { flex: 1; position: relative; }
iframe { width: 100%; height: 100%; border: none; }
.loading-mask { position: absolute; inset: 0; background: rgba(251, 248, 242, 0.92); display: flex; justify-content: center; align-items: center; z-index: 20; color: #43392a; }
.error-state { height: 100%; display: flex; flex-direction: column; align-items: center; justify-content: center; color: #b5432f; gap: 12px; background: #efeae0; padding: 0 40px; text-align: center; }
.error-state p { margin: 0; font-size: 14px; line-height: 1.6; max-width: 420px; }
.empty-state { height: 100%; display: flex; flex-direction: column; align-items: center; justify-content: center; color: #8a7d68; gap: 10px; background: #efeae0; }

/* 模版选择卡片 */
.template-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 12px; }
.template-card { border: 2px solid #d8cfbe; border-radius: 8px; cursor: pointer; transition: all 0.2s; position: relative; overflow: hidden; }
.template-card:hover { border-color: #8a7d68; }
.template-card.active { border-color: #c4741c; background: rgba(196, 116, 28, 0.08); }
.preview-box { height: 60px; position: relative; }
.mini-nav { height: 8px; background: rgba(74,53,24,0.1); margin-bottom: 4px; }
.mini-nav-light { height: 8px; background: rgba(0,0,0,0.1); margin-bottom: 4px; }
.mini-hero { display: flex; align-items: center; justify-content: center; height: 100%; font-size: 10px; font-weight: bold; }
.template-info { padding: 8px; display: flex; justify-content: space-between; align-items: center; }
.name { color: #211a10; font-size: 12px; font-weight: bold; }
.tag { font-size: 10px; color: #8a7d68; background: #f2ebde; padding: 2px 6px; border-radius: 4px; }
.check-mark { position: absolute; top: 4px; right: 4px; background: #c4741c; color: white; border-radius: 50%; width: 16px; height: 16px; display: flex; align-items: center; justify-content: center; font-size: 10px; }

/* 复用之前的样式... */
:deep(.el-collapse) { border: none; }
:deep(.el-collapse-item__header) { background-color: #fbf8f2; color: #211a10; border-bottom: 1px solid #f2ebde; padding-left: 20px; font-weight: 600; }
:deep(.el-collapse-item__content) { background-color: #efeae0; padding: 20px; color: #43392a; border-bottom: 1px solid #f2ebde; }
:deep(.el-input__wrapper), :deep(.el-textarea__inner) { background-color: #f2ebde !important; box-shadow: 0 0 0 1px #d8cfbe inset !important; color: #43392a !important; }
:deep(.el-form-item__label) { color: #8a7d68 !important; }
.section-title { display: flex; align-items: center; gap: 10px; } .section-title h3 { margin: 0; font-size: 14px; color: #211a10; } .bar { width: 4px; height: 14px; background-color: #c4741c; border-radius: 2px; }
.color-picker-row { display: flex; gap: 10px; align-items: center; } .color-dot { width: 24px; height: 24px; border-radius: 50%; cursor: pointer; border: 2px solid #d8cfbe; }
.list-item-card { background: #f2ebde; border: 1px solid #d8cfbe; padding: 12px; border-radius: 6px; display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
.list-item-card.column-layout { flex-direction: column; align-items: flex-start; }
.flex-row { display: flex; gap: 8px; width: 100%; } .flex-col { display: flex; flex-direction: column; width: 100%; }
.btn-dashed { border: 1px dashed #c4b9a3; color: #8a7d68; background: transparent; } .btn-dashed:hover { border-color: #d6882e; color: #d6882e; }
.delete-icon { cursor: pointer; color: #c4b9a3; } .delete-icon:hover { color: #d24a3c; }
.card-header { width: 100%; display: flex; justify-content: space-between; margin-bottom: 8px; border-bottom: 1px solid #d8cfbe; padding-bottom: 4px; }
.badge { font-size: 11px; background: #d8cfbe; padding: 2px 8px; border-radius: 10px; color: #8a7d68; }
:deep(.simple-uploader .el-upload) { width: 100%; border: 1px dashed #c4b9a3; border-radius: 6px; cursor: pointer; background: #f2ebde; overflow: hidden; }
.uploaded-img { width: 100%; object-fit: cover; display: block; }
.uploader-placeholder { display: flex; flex-direction: column; align-items: center; justify-content: center; color: #8a7d68; font-size: 12px; gap: 8px; height: 100%; }
</style>
