<script setup lang="ts">
import { NForm, NFormItem, NInput, NButton } from 'naive-ui'
import { useLogin } from '../../composables/useLogin'

defineEmits<{ (e: 'toggle'): void }>()
const { username, password, loading, submit } = useLogin()
</script>

<template>
  <div class="login-shell">
    <!-- 左:品牌区 -->
    <div class="brand">
      <div class="brand-inner">
        <div class="logo">▦</div>
        <h1>数据库备份管理器</h1>
        <p class="en">Database Backup Agent</p>
        <p class="desc">多数据库 · 自动调度 · 加密云同步 · 一键恢复<br />专注、可靠、可视化的备份运维平台。</p>
        <div class="dots"><span /><span /><span /></div>
      </div>
    </div>

    <!-- 右:表单区 -->
    <div class="form-side">
      <button class="switch-btn" type="button" @click="$emit('toggle')">看粒子版 →</button>
      <div class="card">
        <h2>欢迎回来</h2>
        <p class="sub">登录以继续</p>
        <n-form @submit.prevent="submit" label-placement="top">
          <n-form-item label="用户名">
            <n-input v-model:value="username" placeholder="admin" size="large" />
          </n-form-item>
          <n-form-item label="密码">
            <n-input v-model:value="password" type="password" show-password-on="click"
                     placeholder="请输入密码" size="large" @keyup.enter="submit" />
          </n-form-item>
          <n-button type="primary" block size="large" :loading="loading" @click="submit">登 录</n-button>
        </n-form>
      </div>
    </div>
  </div>
</template>

<style scoped>
.login-shell { display:flex; min-height:100vh; }
.brand {
  flex: 1.2; color:#fff; padding:64px 56px; display:flex; align-items:center;
  background: linear-gradient(135deg, #1e3a8a 0%, #4f46e5 45%, #7c3aed 100%);
  position: relative; overflow:hidden;
}
.brand::after {
  content:''; position:absolute; right:-120px; top:-120px; width:360px; height:360px;
  border-radius:50%; background:rgba(255,255,255,.08);
}
.brand-inner { position:relative; z-index:1; }
.logo { font-size:48px; line-height:1; margin-bottom:18px; opacity:.9; }
.brand h1 { font-size:34px; margin:0 0 6px; font-weight:700; letter-spacing:1px; }
.brand .en { margin:0 0 28px; opacity:.75; font-size:14px; letter-spacing:2px; }
.brand .desc { line-height:1.9; opacity:.85; font-size:14px; max-width:340px; }
.dots { margin-top:36px; display:flex; gap:10px; }
.dots span { width:28px; height:6px; border-radius:3px; background:rgba(255,255,255,.5); }
.dots span:first-child { background:#fbbf24; }

.form-side {
  flex: 1; display:flex; align-items:center; justify-content:center;
  background:#f8fafc; position:relative; padding:48px 24px;
}
.switch-btn {
  position:absolute; top:20px; right:24px; border:1px solid #e2e8f0; background:#fff;
  color:#475569; padding:6px 12px; border-radius:999px; font-size:13px; cursor:pointer;
}
.switch-btn:hover { background:#f1f5f9; }
.card { width:100%; max-width:360px; }
.card h2 { margin:0 0 4px; font-size:24px; color:#0f172a; }
.card .sub { margin:0 0 28px; color:#94a3b8; font-size:14px; }

@media (max-width: 768px) {
  .login-shell { flex-direction:column; }
  .brand { flex:none; padding:36px 28px; }
  .brand h1 { font-size:24px; }
  .brand .desc, .dots { display:none; }
  .form-side { flex:1; }
}
</style>
