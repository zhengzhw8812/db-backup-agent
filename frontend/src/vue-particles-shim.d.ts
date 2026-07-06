import type { DefineComponent } from 'vue'

// @tsparticles/vue3 在 app.use 时注册全局组件 <VueParticles>;此处补全局类型,
// 让 vue-tsc 在模板里识别它(包本身未导出可供直接 import 的组件类型)。
declare module 'vue' {
  interface GlobalComponents {
    VueParticles: DefineComponent<Record<string, unknown>, Record<string, unknown>, unknown>
  }
}
