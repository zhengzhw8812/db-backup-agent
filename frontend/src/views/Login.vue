<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import LoginSoybean from './login/LoginSoybean.vue'
import LoginParticles from './login/LoginParticles.vue'

const route = useRoute()
const router = useRouter()
const style = computed<'soybean' | 'particles'>(() =>
  route.query.style === 'particles' ? 'particles' : 'soybean'
)
function toggle() {
  router.replace({ path: '/login', query: { style: style.value === 'soybean' ? 'particles' : 'soybean' } })
}
</script>

<template>
  <component :is="style === 'particles' ? LoginParticles : LoginSoybean" @toggle="toggle" />
</template>
