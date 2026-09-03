// AutoGEO Cookie Sync - Background Service Worker
// 负责：Cookie 读取、localStorage 收集、token 鉴权同步

const DEBUG = false;
function log(msg, ...a) { if (DEBUG) console.log(`[AutoGEO] ${msg}`, ...a); }

const PLATFORM_CONFIG = {
  doubao:   { domains: ['doubao.com','bytedance.com'],        loginCookies: ['sessionid','uid_tt','odin_tt','sid_guard','multi_sids'] },
  deepseek: { domains: ['deepseek.com'],                       loginCookies: [] },
  qianwen:  { domains: ['qianwen.com','tongyi.aliyun.com'],   loginCookies: ['tongyi_sso_ticket','tongyi_sso_ticket_hash','login_aliyunid'] },
};

// ==================== Storage ====================
async function getBackendUrl() {
  const r = await chrome.storage.local.get(['backendUrl']);
  return r.backendUrl || '';
}

async function getExtensionToken() {
  const r = await chrome.storage.local.get(['extensionToken']);
  return r.extensionToken || '';
}

// ==================== Cookie 获取 ====================
async function getAllCookies(platformId) {
  const cfg = PLATFORM_CONFIG[platformId];
  if (!cfg) return [];
  const all = []; const seen = new Set();
  for (const d of cfg.domains) {
    for (const p of ['.'+d, d]) {
      try {
        for (const c of await chrome.cookies.getAll({domain:p})) {
          const k = c.name+'|'+c.domain;
          if (!seen.has(k)) { seen.add(k); all.push(c); }
        }
      } catch(e) {}
    }
  }
  return all.map(c=>({name:c.name,value:c.value,domain:c.domain,path:c.path,expires:c.expirationDate,httpOnly:c.httpOnly,secure:c.secure,sameSite:c.sameSite}));
}

// ==================== 指纹 ====================
function fingerprint() {
  let s={w:1920,h:1080}; try{s.w=self.screen?.width||1920;s.h=self.screen?.height||1080}catch(e){}
  let p='Win32'; try{p=navigator.platform||'Win32'}catch(e){}
  let l=['zh-CN','en']; try{l=navigator.languages||['zh-CN']}catch(e){}
  return {user_agent:navigator.userAgent,platform:p,language:navigator.language||'zh-CN',languages:l,hardware_concurrency:navigator.hardwareConcurrency||8,timezone:Intl.DateTimeFormat().resolvedOptions().timeZone,screen:s,viewport:s};
}

// ==================== 同步（使用 extension_token 鉴权）====================
async function syncPlatform(platformId, localStorageData) {
  const url = await getBackendUrl();
  const token = await getExtensionToken();

  if (!url || !token) {
    log('未配置后端地址或未绑定账号');
    return { success: false, error: '插件未绑定 AutoGeo 账号，请先输入绑定码' };
  }

  const cookies = await getAllCookies(platformId);
  if (!cookies.length) {
    log(platformId + ': 无cookie');
    return { success: false, error: '当前浏览器未登录 ' + platformId };
  }

  const unique=[]; const seen=new Set();
  for(const c of cookies){const k=c.name+'|'+c.domain;if(!seen.has(k)){seen.add(k);unique.push(c);}}

  const ctrl=new AbortController(); const t=setTimeout(()=>ctrl.abort(),15000);
  try {
    const r=await fetch(`${url}/api/auth/sync-cookies`,{
      method:'POST',
      headers:{
        'Content-Type':'application/json',
        'Authorization': `Bearer ${token}`
      },
      body:JSON.stringify({
        platform:platformId,
        cookies:unique,
        local_storage: localStorageData || {},
        fingerprint:fingerprint()
      }),
      signal:ctrl.signal
    });
    clearTimeout(t);
    const data=await r.json();
    log('sync result:', data);
    return data;
  }catch(e){
    clearTimeout(t);
    log('sync fail: '+e.message);
    return { success: false, error: 'AutoGeo 后端连接失败: ' + e.message };
  }
}

// ==================== 消息处理 ====================
chrome.runtime.onMessage.addListener((msg,sender,sendResponse)=>{
  // 来自 popup 或 content script
  if (msg.action === 'syncCookies') {
    // localStorageData 可由 content script 传入
    syncPlatform(msg.platform, msg.localStorage).then(r=>sendResponse(r));
    return true;
  }
  if (msg.action === 'getAllCookies') {
    getAllCookies(msg.platform).then(r=>sendResponse(r));
    return true;
  }
  // 来自 popup 的绑定码
  if (msg.action === 'saveToken') {
    chrome.storage.local.set({ extensionToken: msg.token, backendUrl: msg.backendUrl }, () => {
      sendResponse({ success: true });
    });
    return true;
  }
  if (msg.action === 'getStatus') {
    Promise.all([
      getExtensionToken(),
      getBackendUrl(),
    ]).then(([token, backendUrl]) => {
      sendResponse({ token: !!token, backendUrl });
    });
    return true;
  }
  // 来自 content script 请求 localStorage
  if (msg.action === 'requestLocalStorage') {
    // 找出发送消息的 tab，回复 localStorage
    chrome.tabs.query({ active: true, currentWindow: true }).then(tabs => {
      if (tabs[0]) {
        chrome.tabs.sendMessage(tabs[0].id, { action: 'provideLocalStorage' }, result => {
          sendResponse(result || {});
        });
      } else {
        sendResponse({});
      }
    });
    return true;
  }
});

// ==================== 注册扩展 ID ====================
async function registerId(){
  const url=await getBackendUrl();
  if (!url) return;
  try{await fetch(`${url}/api/auth/register-extension`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({extension_id:chrome.runtime.id})});}catch(e){}
}

log('SW启动, ID:'+chrome.runtime.id);
getBackendUrl().then(u=>{if(u){log('后端:'+u);registerId();}});
chrome.runtime.onStartup?.addListener?.(registerId);