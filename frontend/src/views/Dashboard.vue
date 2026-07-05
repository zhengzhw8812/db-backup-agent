<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { NCard, NGrid, NGridItem, NStatistic, NSpin, useMessage } from 'naive-ui'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { BarChart, PieChart } from 'echarts/charts'
import { TooltipComponent, LegendComponent, GridComponent } from 'echarts/components'
import * as api from '../api/dashboard'
import type { DashboardStats, DashboardTrends } from '../api/dashboard'

use([CanvasRenderer, BarChart, PieChart, TooltipComponent, LegendComponent, GridComponent])

const stats = ref<DashboardStats | null>(null)
const trends = ref<DashboardTrends | null>(null)
const loading = ref(true)
const msg = useMessage()

function fmtBytes(n: number) {
  if (!n) return '0 B'
  const u = ['B', 'KB', 'MB', 'GB', 'TB']
  const i = Math.floor(Math.log(n) / Math.log(1024))
  return (n / Math.pow(1024, i)).toFixed(1) + ' ' + u[i]
}

const dailyOption = computed(() => ({
  tooltip: { trigger: 'axis' },
  legend: { data: ['成功', '失败'], top: 0 },
  grid: { left: 30, right: 16, top: 36, bottom: 24, containLabel: true },
  xAxis: { type: 'category', data: (trends.value?.daily ?? []).map((d) => d.date) },
  yAxis: { type: 'value', minInterval: 1 },
  series: [
    { name: '成功', type: 'bar', stack: 't', itemStyle: { color: '#10b981' }, data: (trends.value?.daily ?? []).map((d) => d.success) },
    { name: '失败', type: 'bar', stack: 't', itemStyle: { color: '#ef4444' }, data: (trends.value?.daily ?? []).map((d) => d.failed) },
  ],
}))

const pieOption = computed(() => ({
  tooltip: { trigger: 'item', formatter: (p: any) => `${p.name}: ${fmtBytes(p.value)}` },
  legend: { top: 0, type: 'scroll' },
  series: [
    {
      type: 'pie',
      radius: ['45%', '70%'],
      center: ['50%', '58%'],
      data: (trends.value?.by_type ?? []).map((t) => ({ name: t.type, value: t.storage_bytes })),
    },
  ],
}))

async function load() {
  loading.value = true
  try {
    const [s, t] = await Promise.all([api.getStats(), api.getTrends()])
    stats.value = s.data
    trends.value = t.data
  } catch (e: any) {
    msg.error('加载仪表盘数据失败')
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<template>
  <n-spin :show="loading">
    <n-grid :cols="4" :x-gap="16" :y-gap="16">
      <n-grid-item>
        <n-card :bordered="false">
          <n-statistic label="备份总数" :value="stats?.total ?? 0" />
        </n-card>
      </n-grid-item>
      <n-grid-item>
        <n-card :bordered="false">
          <n-statistic label="成功率" :value="((stats?.success_rate ?? 0) * 100).toFixed(1) + '%'" />
        </n-card>
      </n-grid-item>
      <n-grid-item>
        <n-card :bordered="false">
          <n-statistic label="存储占用" :value="fmtBytes(stats?.storage_bytes ?? 0)" />
        </n-card>
      </n-grid-item>
      <n-grid-item>
        <n-card :bordered="false">
          <n-statistic label="进行中" :value="stats?.running ?? 0" />
        </n-card>
      </n-grid-item>
    </n-grid>

    <n-grid :cols="3" :x-gap="16" :y-gap="16" style="margin-top:16px">
      <n-grid-item :span="2">
        <n-card title="近 30 天备份趋势" :bordered="false">
          <v-chart :option="dailyOption" autoresize style="height:300px" />
        </n-card>
      </n-grid-item>
      <n-grid-item>
        <n-card title="按数据库类型存储分布" :bordered="false">
          <v-chart :option="pieOption" autoresize style="height:300px" />
        </n-card>
      </n-grid-item>
    </n-grid>
  </n-spin>
</template>
