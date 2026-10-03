<template>
  <n-config-provider :theme="theme" :theme-overrides="overrides">
    <n-message-provider>
      <router-view v-slot="{ Component }">
        <transition name="page-fade" mode="out-in">
          <component :is="Component" />
        </transition>
      </router-view>
    </n-message-provider>
  </n-config-provider>
</template>
<script setup lang="ts">
import { NMessageProvider, NConfigProvider } from 'naive-ui'
import { useTheme } from './composables/useTheme'

// 主题提供者提升到根:确保 Login 等顶层路由(非 AppLayout 子级)也应用主题/品牌覆盖
const { theme, overrides } = useTheme()
</script>

<style>
.page-fade-enter-active, .page-fade-leave-active { transition: opacity .15s ease }
.page-fade-enter-from, .page-fade-leave-to { opacity: 0 }
</style>
