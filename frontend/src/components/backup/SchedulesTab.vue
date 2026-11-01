<script setup lang="ts">
// 备份计划 Tab(自 Schedules.vue 平移;Task 8 再接入立即执行/props)
import { useBreakpoint } from '../../composables/useBreakpoint'

const { isMobile } = useBreakpoint()
import { ref, h, onMounted } from 'vue'
import {
  NCard, NDataTable, NButton, NModal, NForm, NFormItem, NInput, NInputNumber,
  NSelect, NSpace, NPopconfirm, NSwitch, NTag, useMessage,
} from 'naive-ui'
import type { DataTableColumns } from 'naive-ui'
import * as schedApi from '../../api/schedules'
import type { Schedule } from '../../api/schedules'
import * as connApi from '../../api/connections'
import type { Connection } from '../../api/connections'

const msg = useMessage()
const data = ref<Schedule[]>([])
const conns = ref<Connection[]>([])
const loading = ref(false)
const show = ref(false)
const editing = ref<Schedule | null>(null)
const form = ref<any>({})

const connOptions = () => conns.value.map(c => ({
  label: `${c.name} (${c.type})`, value: c.id,
}))

function connLabel(id: number) {
  const c = conns.value.find(x => x.id === id); return c ? `${c.name}` : `#${id}`
}

async function load() {
  loading.value = true
  try {
    const [s, c] = await Promise.all([schedApi.listSchedules(), connApi.listConnections()])
    data.value = s.data; conns.value = c.data
  } catch (e: any) { msg.error('加载计划列表失败') }
  finally { loading.value = false }
}

function openAdd() { editing.value = null; form.value = { cron_expr: '0 2 * * *', enabled: true, retention_days: 7 }; show.value = true }
function openEdit(row: Schedule) {
  editing.value = row
  form.value = { connection_id: row.connection_id, cron_expr: row.cron_expr, enabled: row.enabled, retention_days: row.retention_days }
  show.value = true
}
async function save() {
  try {
    if (editing.value) await schedApi.updateSchedule(editing.value.id, form.value)
    else await schedApi.createSchedule(form.value)
    msg.success('已保存'); show.value = false; await load()
  } catch (e: any) { msg.error(e.response?.data?.detail || '保存失败') }
}
async function toggle(row: Schedule, val: boolean) {
  try { await schedApi.updateSchedule(row.id, { enabled: val }); row.enabled = val; await load() }
  catch (e: any) { msg.error('更新失败') }
}
async function remove(id: number) {
  try { await schedApi.deleteSchedule(id); msg.success('已删除'); await load() }
  catch (e: any) { msg.error(e.response?.data?.detail || '删除失败') }
}

const columns: DataTableColumns<Schedule> = [
  { title: '连接', key: 'connection_id', render: r => connLabel(r.connection_id) },
  { title: 'Cron 表达式', key: 'cron_expr', render: r => h(NTag, { size: 'small', bordered: false }, { default: () => r.cron_expr }) },
  { title: '保留(天)', key: 'retention_days' },
  { title: '下次运行', key: 'next_run_at', render: r => r.next_run_at ? h('span', { title: r.next_run_at }, new Date(r.next_run_at).toLocaleString()) : '—' },
  { title: '启用', key: 'enabled', render: r => h(NSwitch, { value: r.enabled, 'onUpdate:value': (v: boolean) => toggle(r, v) }) },
  { title: '操作', key: 'actions', render: r => h(NSpace, null, {
      default: () => [
        h(NButton, { size: 'small', onClick: () => openEdit(r) }, { default: () => '编辑' }),
        h(NPopconfirm, { onPositiveClick: () => remove(r.id) }, {
          trigger: () => h(NButton, { size: 'small', type: 'error', ghost: true }, { default: () => '删除' }),
          default: () => '确认删除该计划?',
        }),
      ],
    }) },
]

onMounted(load)
</script>

<template>
  <n-card title="备份计划" :bordered="false">
    <template #header-extra><n-button type="primary" @click="openAdd">+ 新增计划</n-button></template>
    <template v-if="!isMobile">
      <n-data-table v-if="data.length" :columns="columns" :data="data" :loading="loading" :bordered="false" size="small" striped />
        <div v-else-if="!loading" style="padding:24px;text-align:center;opacity:.5">还没有备份计划</div>
      </template>
<template v-else>
        <n-card v-for="s in data" :key="s.id" class="mcard" :title="connLabel(s.connection_id)" size="small">
          <div class="mrow"><span class="mlabel">Cron</span><n-tag size="small" :bordered="false">{{ s.cron_expr }}</n-tag></div>
          <div class="mrow"><span class="mlabel">保留</span><span>{{ s.retention_days }} 天</span></div>
          <div class="mrow"><span class="mlabel">下次运行</span><span>{{ s.next_run_at ? new Date(s.next_run_at).toLocaleString() : '—' }}</span></div>
          <div class="mrow"><span class="mlabel">启用</span><n-switch :value="s.enabled" @update:value="(v: boolean) => toggle(s, v)" /></div>
          <div class="mactions">
            <n-button size="large" @click="openEdit(s)">编辑</n-button>
            <n-popconfirm @positive-click="remove(s.id)"><template #trigger><n-button size="large" type="error" ghost>删除</n-button></template>确认删除?</n-popconfirm>
          </div>
        </n-card>
      </template>
  </n-card>

  <n-modal v-model:show="show" preset="card" :title="editing ? '编辑计划' : '新增计划'" style="width:480px">
    <n-form label-placement="top">
      <n-form-item label="数据库连接"><n-select v-model:value="form.connection_id" :options="connOptions()" placeholder="选择连接" filterable /></n-form-item>
      <n-form-item label="Cron 表达式(5 字段:分 时 日 月 周)">
        <n-input v-model:value="form.cron_expr" placeholder="例:0 2 * * * (每天 02:00)" />
      </n-form-item>
      <n-space>
        <n-form-item label="保留天数"><n-input-number v-model:value="form.retention_days" :min="1" /></n-form-item>
        <n-form-item label="启用"><n-switch v-model:value="form.enabled" /></n-form-item>
      </n-space>
      <n-space justify="end"><n-button @click="show=false">取消</n-button><n-button type="primary" @click="save">保存</n-button></n-space>
    </n-form>
  </n-modal>
</template>

<style scoped>
.mcard { margin-bottom: 12px }
.mrow { display: flex; justify-content: space-between; gap: 8px; padding: 3px 0; font-size: 13px }
.mlabel { opacity: .55; flex-shrink: 0 }
.mactions { margin-top: 8px; display: flex; gap: 8px; flex-wrap: wrap }
.mactions .n-button { flex: 1; min-height: 44px }
</style>
