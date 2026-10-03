<script setup lang="ts">
import PageHeader from '../components/PageHeader.vue'
import { useBreakpoint } from '../composables/useBreakpoint'

const { isMobile } = useBreakpoint()
import { ref, h, onMounted } from 'vue'
import {
  NCard, NDataTable, NButton, NModal, NForm, NFormItem, NInput, NInputNumber,
  NSelect, NSpace, NPopconfirm, NText, useMessage,
} from 'naive-ui'
import type { DataTableColumns } from 'naive-ui'
import * as api from '../api/connections'
import type { Connection } from '../api/connections'

const msg = useMessage()
const data = ref<Connection[]>([])
const loading = ref(false)
const show = ref(false)
const editing = ref<Connection | null>(null)
const form = ref<any>({})

const dbOptions = ref<{ label: string; value: string }[]>([])
const loadingDbs = ref(false)

async function fetchDbs() {
  loadingDbs.value = true
  try {
    let resp
    if (editing.value && !form.value.password) {
      // 编辑态且密码未改:用已存密码
      resp = await api.listDatabasesForConnection(editing.value.id)
    } else {
      resp = await api.listDatabases({
        type: form.value.type, host: form.value.host, port: form.value.port,
        username: form.value.username, password: form.value.password, db_name: form.value.db_name,
      })
    }
    const list = resp.data.databases || []
    dbOptions.value = list.map((d: string) => ({ label: d, value: d }))
    // 权限检测语义:列举结果即该账号有备份权限的库,默认全选
    form.value.db_names = [...list]
    if (!list.length) {
      msg.warning('该账号没有可备份的数据库(权限不足,或服务器上没有业务库)')
    } else {
      msg.success(`检测通过:该账号可备份 ${list.length} 个数据库,已默认全选`)
    }
    return list.length > 0
  } catch (e: any) {
    msg.error(e.response?.data?.detail || '权限检测失败,请检查主机/账号/密码')
    return false
  } finally {
    loadingDbs.value = false
  }
}

const typeOptions = [
  { label: 'PostgreSQL', value: 'pg' },
  { label: 'MySQL', value: 'mysql' },
  { label: 'MongoDB', value: 'mongo' },
  { label: 'Redis', value: 'redis' },
  { label: 'SQLite', value: 'sqlite' },
]

let detectTimer: number | undefined

function tryAutoDetect() {
  const f = form.value
  if (!['pg', 'mysql', 'mongo'].includes(f.type)) return
  if (!f.host || !f.username || (!f.password && !editing.value)) return
  if (detectTimer) window.clearTimeout(detectTimer)
  detectTimer = window.setTimeout(() => { fetchDbs() }, 800)
}

async function load() {
  loading.value = true
  try { data.value = (await api.listConnections()).data }
  catch (e: any) { msg.error('加载连接列表失败') }
  finally { loading.value = false }
}

function openAdd() {
  editing.value = null
  form.value = { type: 'pg', port: 5432, db_names: [] }
  dbOptions.value = []
  show.value = true
}

function openEdit(row: Connection) {
  editing.value = row
  const names = row.db_names ? [...row.db_names] : []
  form.value = {
    name: row.name, type: row.type, host: row.host, port: row.port,
    db_name: row.db_name, db_names: names, username: row.username, password: '',
  }
  dbOptions.value = names.map(d => ({ label: d, value: d }))
  show.value = true
}

async function save() {
  try {
    if (editing.value) await api.updateConnection(editing.value.id, form.value)
    else await api.createConnection(form.value)
    msg.success('已保存')
    show.value = false
    await load()
  } catch (e: any) {
    msg.error(e.response?.data?.detail || '保存失败')
  }
}

async function remove(id: number) {
  try {
    await api.deleteConnection(id)
    msg.success('已删除')
    await load()
  } catch (e: any) { msg.error(e.response?.data?.detail || '删除失败') }
}

const columns: DataTableColumns<Connection> = [
  { title: '名称', key: 'name' },
  { title: '类型', key: 'type' },
  { title: '主机', key: 'host' },
  { title: '端口', key: 'port' },
  { title: '数据库', key: 'db_names', render: row => (row.db_names && row.db_names.length) ? row.db_names.join(', ') : (row.db_name || (row.type === 'mysql' ? '全部' : '—')) },
  { title: '用户', key: 'username' },
  {
    title: '操作', key: 'actions',
    render(row) {
      return h(NSpace, null, {
        default: () => [
          h(NButton, { size: 'small', onClick: () => openEdit(row) }, { default: () => '编辑' }),
          h(NPopconfirm, { onPositiveClick: () => remove(row.id) }, {
            trigger: () => h(NButton, { size: 'small', type: 'error', ghost: true }, { default: () => '删除' }),
            default: () => '确认删除该连接?',
          }),
        ],
      })
    },
  },
]

onMounted(load)
</script>

<template>
  
  <PageHeader title="数据库连接" description="管理要备份的数据库连接" /><n-card title="数据库连接" :bordered="false">
    <template #header-extra>
      <n-button type="primary" @click="openAdd">+ 新增连接</n-button>
    </template>
    <template v-if="!isMobile">
      <n-data-table :columns="columns" :data="data" :loading="loading" :bordered="false" />
      </template>
<template v-else>
        <n-card v-for="c in data" :key="c.id" class="mcard" :title="c.name" size="small">
          <div class="mrow"><span class="mlabel">类型</span><span>{{ c.type }}</span></div>
          <div class="mrow"><span class="mlabel">主机</span><span>{{ c.host || '—' }}{{ c.port ? ':' + c.port : '' }}</span></div>
          <div class="mrow"><span class="mlabel">数据库</span><span>{{ (c.db_names && c.db_names.length) ? c.db_names.join(', ') : (c.db_name || (c.type === 'mysql' ? '全部' : '—')) }}</span></div>
          <div class="mrow"><span class="mlabel">用户</span><span>{{ c.username || '—' }}</span></div>
          <div class="mactions">
            <n-button size="large" @click="openEdit(c)">编辑</n-button>
            <n-popconfirm @positive-click="remove(c.id)"><template #trigger><n-button size="large" type="error" ghost>删除</n-button></template>确认删除?</n-popconfirm>
          </div>
        </n-card>
      </template>
  </n-card>

  <n-modal v-model:show="show" preset="card" :title="editing ? '编辑连接' : '新增连接'" style="width: 480px">
    <n-form label-placement="top">
      <n-form-item label="名称"><n-input v-model:value="form.name" placeholder="例如:生产库" /></n-form-item>
      <n-form-item label="类型"><n-select v-model:value="form.type" :options="typeOptions" /></n-form-item>
      <n-space>
        <n-form-item label="主机"><n-input v-model:value="form.host" placeholder="127.0.0.1" @blur="tryAutoDetect" /></n-form-item>
        <n-form-item label="端口"><n-input-number v-model:value="form.port" /></n-form-item>
      </n-space>
      <n-form-item label="数据库">
          <template v-if="form.type === 'pg'">
            <n-space align="center" style="width: 100%">
              <n-select
                v-model:value="form.db_names"
                multiple
                filterable
                :options="dbOptions"
                :loading="loadingDbs"
                placeholder="填完账号后自动检测权限并列出库"
                style="width: 260px"
              />
              <n-button :loading="loadingDbs" @click="fetchDbs">重新检测</n-button>
            </n-space>
          </template>
          <template v-else-if="form.type === 'mysql'">
            <n-space align="center" style="width: 100%">
              <n-select
                v-model:value="form.db_names"
                multiple
                filterable
                :options="dbOptions"
                :loading="loadingDbs"
                placeholder="填完账号后自动检测权限并列出库"
                style="width: 260px"
              />
              <n-button :loading="loadingDbs" @click="fetchDbs">重新检测</n-button>
            </n-space>
          </template>
          <template v-else-if="form.type === 'mongo'">
            <n-space align="center" style="width: 100%">
              <n-select
                v-model:value="form.db_names"
                multiple
                filterable
                :options="dbOptions"
                :loading="loadingDbs"
                placeholder="填完账号后自动检测权限并列出库"
                style="width: 260px"
              />
              <n-button :loading="loadingDbs" @click="fetchDbs">重新检测</n-button>
            </n-space>
          </template>
          <template v-else>
            <n-input v-model:value="form.db_name" placeholder="SQLite 填库文件路径;Redis 留空即整实例" />
          </template>
        </n-form-item>
      <n-form-item label="用户名"><n-input v-model:value="form.username" @blur="tryAutoDetect" /></n-form-item>
      <n-form-item :label="editing ? '密码(留空表示不修改)' : '密码'">
        <n-input v-model:value="form.password" type="password" show-password-on="click" placeholder="留空不改" @blur="tryAutoDetect" />
      </n-form-item>
      <n-space justify="end">
        <n-button @click="show = false">取消</n-button>
        <n-button type="primary" @click="save">保存</n-button>
      </n-space>
    </n-form>
  </n-modal>
</template>
