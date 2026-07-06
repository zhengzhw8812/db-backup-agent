import { createApp } from 'vue'
import { createPinia } from 'pinia'
import VueParticles from '@tsparticles/vue3'
import { loadSlim } from '@tsparticles/slim'
import App from './App.vue'
import router from './router'

createApp(App)
  .use(createPinia())
  .use(router)
  .use(VueParticles, { init: async (engine) => { await loadSlim(engine) } })
  .mount('#app')
