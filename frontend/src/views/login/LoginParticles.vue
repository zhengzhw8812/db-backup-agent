<script setup lang="ts">
import { NForm, NFormItem, NInput, NButton } from 'naive-ui'
import { useLogin } from '../../composables/useLogin'

defineEmits<{ (e: 'toggle'): void }>()
const { username, password, loading, submit } = useLogin()

// 粒子配置:深色基调 + 连线 + 鼠标 grab
const options = {
  background: { color: { value: '#0f172a' } },
  fpsLimit: 60,
  particles: {
    color: { value: ['#60a5fa', '#a78bfa', '#f472b6'] },
    links: { enable: true, color: '#64748b', distance: 140, opacity: 0.4, width: 1 },
    move: { enable: true, speed: 1.1, outModes: 'out' as const },
    number: { value: 70, density: { enable: true } },
    opacity: { value: 0.6 },
    shape: { type: 'circle' },
    size: { value: { min: 1, max: 3 } },
  },
  interactivity: {
    events: { onHover: { enable: true, mode: 'grab' } },
    modes: { grab: { distance: 160, links: { opacity: 0.7 } } },
  },
  detectRetina: true,
}
</script>

<template>
  <div class="login-particles">
    <VueParticles id="tsparticles" :options="options" class="bg" />
    <button class="switch-btn" type="button" @click="$emit('toggle')">看分屏版 →</button>
    <div class="card">
      <div class="logo">▦</div>
      <h1>数据库备份管理器</h1>
      <p class="en">Database Backup Agent</p>
      <n-form @submit.prevent="submit" label-placement="top">
        <n-form-item label="用户名">
          <n-input v-model:value="username" placeholder="admin" />
        </n-form-item>
        <n-form-item label="密码">
          <n-input v-model:value="password" type="password" show-password-on="click"
                   placeholder="请输入密码" @keyup.enter="submit" />
        </n-form-item>
        <n-button type="primary" block :loading="loading" @click="submit">登 录</n-button>
      </n-form>
    </div>
  </div>
</template>

<style scoped>
.login-particles { position:relative; min-height:100vh; display:flex; align-items:center; justify-content:center; }
.bg { position:fixed; inset:0; z-index:0; }
.switch-btn {
  position:fixed; top:20px; right:24px; z-index:2;
  border:1px solid rgba(255,255,255,.3); background:rgba(255,255,255,.08);
  color:#e2e8f0; padding:6px 12px; border-radius:999px; font-size:13px; cursor:pointer;
  backdrop-filter: blur(6px);
}
.switch-btn:hover { background:rgba(255,255,255,.16); }
.card {
  position:relative; z-index:1; width:100%; max-width:380px; margin:24px;
  padding:40px 36px; border-radius:18px; color:#fff;
  background:rgba(15,23,42,.45); border:1px solid rgba(255,255,255,.18);
  backdrop-filter: blur(14px); box-shadow:0 12px 40px rgba(0,0,0,.35);
}
.logo { font-size:40px; opacity:.9; }
.card h1 { margin:8px 0 2px; font-size:22px; font-weight:700; }
.card .en { margin:0 0 24px; opacity:.7; font-size:13px; letter-spacing:2px; }
</style>
