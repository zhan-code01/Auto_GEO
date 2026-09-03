// AutoGEO Cookie Sync - Popup Script
const PLATFORMS = ['doubao', 'deepseek', 'qianwen'];
let syncInProgress = false;

document.addEventListener('DOMContentLoaded', () => {
  loadSettings();
  restoreButtonStates();
  bindEvents();
  checkBindingStatus();
});

function bindEvents() {
  // 同步按钮
  document.querySelectorAll('.sync-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      if (syncInProgress) return;
      syncPlatform(btn.dataset.platform);
    });
  });

  // 后端地址变化
  document.getElementById('backendUrl').addEventListener('change', (e) => {
    const url = e.target.value.trim().replace(/\/$/, '');
    chrome.storage.local.set({ backendUrl: url });
    // 地址变了需要重新检查绑定状态
    checkBindingStatus();
  });

  // 绑定按钮
  document.getElementById('bindBtn').addEventListener('click', handleBind);

  // 解绑按钮
  document.getElementById('unbindBtn').addEventListener('click', handleUnbind);

  // 回车提交绑定码
  document.getElementById('pairCodeInput').addEventListener('keyup', (e) => {
    if (e.key === 'Enter') handleBind();
  });
}

async function checkBindingStatus() {
  const [{ extensionToken, backendUrl }] = await chrome.storage.local.get(['extensionToken', 'backendUrl']);

  const bindDot = document.getElementById('bindDot');
  const bindCard = document.getElementById('bindCard');
  const bindTitle = document.getElementById('bindTitle');
  const bindSub = document.getElementById('bindSub');
  const pairCodeSection = document.getElementById('pairCodeSection');
  const unbindBtn = document.getElementById('unbindBtn');
  const bindBtn = document.getElementById('bindBtn');

  if (extensionToken && backendUrl) {
    // 已绑定
    bindDot.className = 'bind-status-dot bound';
    bindCard.className = 'bind-card';
    bindTitle.textContent = '已绑定 AutoGEO';
    bindSub.textContent = backendUrl.replace('https://', '').replace('http://', '');
    pairCodeSection.classList.remove('show');
    unbindBtn.style.display = '';

    // 设置同步按钮可用
    document.querySelectorAll('.sync-btn').forEach(btn => {
      btn.classList.remove('disabled');
    });
  } else {
    // 未绑定
    bindDot.className = 'bind-status-dot unbound';
    bindCard.className = 'bind-card unbound';
    bindTitle.textContent = '未绑定 AutoGEO 账号';
    bindSub.textContent = '请输入绑定码完成配置';
    pairCodeSection.classList.add('show');
    unbindBtn.style.display = 'none';

    // 禁用同步按钮
    document.querySelectorAll('.sync-btn').forEach(btn => {
      btn.classList.add('disabled');
    });
  }
}

async function handleBind() {
  const pairCode = document.getElementById('pairCodeInput').value.trim().toUpperCase();
  const [{ backendUrl }] = await chrome.storage.local.get(['backendUrl']);

  if (!pairCode) {
    showMsg('请输入绑定码', 'warn');
    return;
  }
  if (!backendUrl) {
    showMsg('请先填写后端地址', 'warn');
    return;
  }

  const btn = document.getElementById('bindBtn');
  btn.disabled = true;
  btn.textContent = '绑定中...';

  try {
    const cleanUrl = backendUrl.replace(/\/$/, '');
    const resp = await fetch(`${cleanUrl}/api/auth/extension/bind`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        pair_code: pairCode,
        extension_id: chrome.runtime.id,
        device_name: navigator.userAgent.includes('Windows') ? 'Chrome on Windows' :
                     navigator.userAgent.includes('Mac') ? 'Chrome on Mac' : 'Chrome',
      }),
    });
    const data = await resp.json();

    if (data.success && data.extension_token) {
      // 保存 token 和后端地址
      await chrome.storage.local.set({
        extensionToken: data.extension_token,
        backendUrl: cleanUrl,
      });
      document.getElementById('pairCodeInput').value = '';
      showMsg('绑定成功！', 'success');
      checkBindingStatus();
    } else {
      showMsg(data.detail || '绑定失败', 'error');
    }
  } catch (e) {
    showMsg('绑定失败: ' + e.message, 'error');
  } finally {
    btn.disabled = false;
    btn.textContent = '绑定';
  }
}

async function handleUnbind() {
  const [{ backendUrl }] = await chrome.storage.local.get(['backendUrl']);
  if (!backendUrl) return;

  try {
    const cleanUrl = backendUrl.replace(/\/$/, '');
    // 撤销前先获取设备列表找到自己的 binding_id
    // 直接清除本地 token 即可（后端 token 保留用于追溯）
    await chrome.storage.local.remove(['extensionToken']);
    showMsg('已解绑', 'warn');
    checkBindingStatus();
  } catch (e) {
    showMsg('解绑失败: ' + e.message, 'error');
  }
}

function loadSettings() {
  chrome.storage.local.get(['backendUrl'], (result) => {
    if (result.backendUrl) {
      document.getElementById('backendUrl').value = result.backendUrl;
    }
  });
}

function restoreButtonStates() {
  chrome.storage.local.get(['syncStates'], (result) => {
    const states = result.syncStates || {};
    for (const platform of PLATFORMS) {
      const state = states[platform];
      if (state) updateButton(platform, state.status, state.cookieCount);
    }
  });
}

function updateButton(platform, status, cookieCount) {
  const btn = document.getElementById(`btn-${platform}`);
  const statusEl = document.getElementById(`status-${platform}`);
  if (!btn) return;
  btn.className = 'sync-btn ' + status;
  switch (status) {
    case 'syncing': btn.textContent = '同步中...'; btn.disabled = true; break;
    case 'done': btn.textContent = `✓ ${cookieCount || ''}`; btn.disabled = false; if (statusEl) statusEl.textContent = '已同步'; break;
    case 'error': btn.textContent = '重试'; btn.disabled = false; if (statusEl) statusEl.textContent = '同步失败'; break;
    default: btn.textContent = '同步'; btn.disabled = false;
  }
  saveButtonState(platform, status, cookieCount);
}

function saveButtonState(platform, status, cookieCount) {
  chrome.storage.local.get(['syncStates'], (result) => {
    const states = result.syncStates || {};
    states[platform] = { status, cookieCount, time: Date.now() };
    chrome.storage.local.set({ syncStates: states });
  });
}

function showMsg(msg, type) {
  const el = document.getElementById('result');
  el.textContent = msg;
  el.className = 'result-msg ' + (type || '');
  if (msg) setTimeout(() => { el.className = 'result-msg'; el.textContent = ''; }, 5000);
}

async function syncPlatform(platform) {
  // 先检查是否已绑定
  const [{ extensionToken, backendUrl }] = await chrome.storage.local.get(['extensionToken', 'backendUrl']);
  if (!extensionToken || !backendUrl) {
    showMsg('插件未绑定 AutoGEO 账号', 'warn');
    return;
  }

  syncInProgress = true;
  updateButton(platform, 'syncing');
  showMsg(`正在同步 ${platform}...`, '');

  try {
    // 先从 content script 获取当前页面的 localStorage
    const localStorageData = await new Promise((resolve) => {
      chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
        if (tabs[0]) {
          chrome.tabs.sendMessage(tabs[0].id, { action: 'provideLocalStorage' }, (result) => {
            resolve(result || {});
          });
        } else {
          resolve({});
        }
      });
    });

    const response = await chrome.runtime.sendMessage({
      action: 'syncCookies',
      platform: platform,
      localStorage: localStorageData,
    });

    if (!response) {
      updateButton(platform, 'error');
      showMsg('扩展 Service Worker 无响应，请刷新扩展', 'error');
      return;
    }

    if (response.success) {
      updateButton(platform, 'done', response.cookie_count || '?');
      showMsg(`${platform} 同步成功！${response.cookie_count || 0} 个 cookie 已传至后端`, 'success');
    } else {
      updateButton(platform, 'error');
      showMsg(`${platform}: ${response.error || '同步失败'}`, 'error');
    }
  } catch (e) {
    updateButton(platform, 'error');
    showMsg(`通信失败: ${e.message}。请检查后端地址是否正确。`, 'error');
  } finally {
    syncInProgress = false;
  }
}