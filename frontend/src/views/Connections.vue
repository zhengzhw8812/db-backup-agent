<script setup lang="ts">
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
    msg.success(`拉取到 ${list.length} 个数据库`)
  } catch (e: any) {
    msg.error(e.response?.data?.detail || '拉取数据库列表失败')
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
  <n-card title="数据库连接" :bordered="false">
    <template #header-extra>
      <n-button type="primary" @click="openAdd">+ 新增连接</n-button>
    </template>
    <n-data-table :columns="columns" :data="data" :loading="loading" :bordered="false" />
  </n-card>

  <n-modal v-model:show="show" preset="card" :title="editing ? '编辑连接' : '新增连接'" style="width: 480px">
    <n-form label-placement="top">
      <n-form-item label="名称"><n-input v-model:value="form.name" placeholder="例如:生产库" /></n-form-item>
      <n-form-item label="类型"><n-select v-model:value="form.type" :options="typeOptions" /></n-form-item>
      <n-space>
        <n-form-item label="主机"><n-input v-model:value="form.host" placeholder="127.0.0.1" /></n-form-item>
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
                placeholder="点击右侧按钮拉取库列表后多选"
                style="width: 260px"
              />
              <n-button :loading="loadingDbs" @click="fetchDbs">拉取数据库列表</n-button>
            </n-space>
          </template>
          <template v-else-if="form.type === 'mysql'">
            <n-text depth="3">MySQL 默认备份全部数据库</n-text>
          </template>
          <template v-else>
            <n-input v-model:value="form.db_name" />
          </template>
        </n-form-item>
      <n-form-item label="用户名"><n-input v-model:value="form.username" /></n-form-item>
      <n-form-item :label="editing ? '密码(留空表示不修改)' : '密码'">
        <n-input v-model:value="form.password" type="password" show-password-on="click" placeholder="留空不改" />
      </n-form-item>
      <n-space justify="end">
        <n-button @click="show = false">取消</n-button>
        <n-button type="primary" @click="save">保存</n-button>
      </n-space>
    </n-form>
  </n-modal>
</template>
