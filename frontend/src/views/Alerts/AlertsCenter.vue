<template>
  <div class="wrap">
    <div class="head">
      <div>
        <div class="title">消息与预警中心</div>
        <div class="sub">规则配置、告警历史与一键检查（写入数据库）。</div>
      </div>
      <div class="actions">
        <button class="btn" @click="reloadAll" :disabled="loading">{{ loading ? '刷新中…' : '刷新' }}</button>
        <button class="btn primary" @click="doCheck" :disabled="checking">{{ checking ? '检查中…' : '执行检查' }}</button>
      </div>
    </div>

    <div class="grid">
      <div class="card">
        <div class="cardTitle">新增规则</div>
        <div class="form">
          <div class="field">
            <div class="label">名称</div>
            <input class="input" v-model="newName" placeholder="例如：高饱和度预警" />
          </div>
          <div class="field">
            <div class="label">类型</div>
            <select class="input" v-model="newType">
              <option value="zone_saturation_high">区域饱和度过高</option>
              <option value="zone_shortage_high">区域车辆不足</option>
            </select>
          </div>
          <div class="field" v-if="newType === 'zone_saturation_high'">
            <div class="label">threshold（0~1）</div>
            <input class="input" v-model.number="newThreshold" type="number" step="0.01" min="0" max="1" />
          </div>
          <div class="field" v-else>
            <div class="label">min_bikes</div>
            <input class="input" v-model.number="newMinBikes" type="number" step="1" min="0" />
          </div>
          <div class="row">
            <label class="chk"><input type="checkbox" v-model="newEnabled" /> 启用</label>
            <button class="btn primary" @click="addRule" :disabled="creating || !newName.trim()">
              {{ creating ? '创建中…' : '创建规则' }}
            </button>
          </div>
        </div>
      </div>

      <div class="card">
        <div class="cardTitle">规则列表</div>
        <div class="list" v-if="rules.length">
          <div class="item" v-for="r in rules" :key="r.id">
            <div class="meta">
              <div class="rName">{{ r.name }}</div>
              <div class="rSub">
                <span class="pill">{{ r.rule_type }}</span>
                <span class="pill">{{ r.enabled ? 'enabled' : 'disabled' }}</span>
              </div>
            </div>
            <div class="ops">
              <button class="btn small" @click="toggleRule(r)" :disabled="savingRuleId === r.id">
                {{ savingRuleId === r.id ? '…' : r.enabled ? '停用' : '启用' }}
              </button>
              <button class="btn small danger" @click="removeRule(r)" :disabled="deletingRuleId === r.id">
                {{ deletingRuleId === r.id ? '…' : '删除' }}
              </button>
            </div>
          </div>
        </div>
        <div class="empty" v-else>暂无规则，先在左侧创建一条。</div>
      </div>

      <div class="card span2">
        <div class="cardTitle">告警历史</div>
        <div class="toolbar">
          <div class="hint">最近 {{ historyLimit }} 条</div>
          <button class="btn small" @click="loadHistory" :disabled="loadingHistory">刷新历史</button>
        </div>
        <div class="history" v-if="events.length">
          <div class="ev" v-for="e in events" :key="e.id">
            <div class="badge" :class="e.level">{{ e.level }}</div>
            <div class="evBody">
              <div class="evTitle">{{ e.title }}</div>
              <div class="evMsg">{{ e.message }}</div>
              <div class="evMeta">#{{ e.id }} · rule {{ e.rule_id ?? '-' }} · {{ e.created_at }}</div>
            </div>
          </div>
        </div>
        <div class="empty" v-else>暂无告警记录。点击右上角“执行检查”可生成记录。</div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { showConfirmDialog, showToast } from 'vant'

import {
  checkAlerts,
  createAlertRule,
  deleteAlertRule,
  listAlertHistory,
  listAlertRules,
  updateAlertRule,
} from '../../api'

const loading = ref(false)
const checking = ref(false)

const rules = ref([])
const events = ref([])
const historyLimit = 100

const newName = ref('')
const newType = ref('zone_saturation_high')
const newEnabled = ref(true)
const newThreshold = ref(0.85)
const newMinBikes = ref(5)

const creating = ref(false)
const savingRuleId = ref(null)
const deletingRuleId = ref(null)
const loadingHistory = ref(false)

async function loadRules() {
  rules.value = await listAlertRules()
}

async function loadHistory() {
  loadingHistory.value = true
  try {
    events.value = await listAlertHistory({ limit: historyLimit })
  } finally {
    loadingHistory.value = false
  }
}

async function reloadAll() {
  loading.value = true
  try {
    await loadRules()
    await loadHistory()
  } finally {
    loading.value = false
  }
}

async function addRule() {
  creating.value = true
  try {
    const params = newType.value === 'zone_saturation_high' ? { threshold: newThreshold.value } : { min_bikes: newMinBikes.value }
    await createAlertRule({ name: newName.value.trim(), enabled: newEnabled.value, rule_type: newType.value, params })
    newName.value = ''
    await loadRules()
    showToast({ type: 'success', message: '规则已创建' })
  } catch (e) {
    console.error(e)
    showToast({ type: 'fail', message: `创建失败：${e?.message || e}` })
  } finally {
    creating.value = false
  }
}

async function toggleRule(r) {
  savingRuleId.value = r.id
  try {
    await updateAlertRule(r.id, { enabled: !r.enabled })
    await loadRules()
    showToast({ type: 'success', message: '已更新' })
  } catch (e) {
    console.error(e)
    showToast({ type: 'fail', message: `更新失败：${e?.message || e}` })
  } finally {
    savingRuleId.value = null
  }
}

async function removeRule(r) {
  try {
    await showConfirmDialog({ title: '确认删除', message: `确认删除规则：${r.name}？` })
  } catch {
    return
  }
  deletingRuleId.value = r.id
  try {
    await deleteAlertRule(r.id)
    await loadRules()
    showToast({ type: 'success', message: '已删除' })
  } catch (e) {
    console.error(e)
    showToast({ type: 'fail', message: `删除失败：${e?.message || e}` })
  } finally {
    deletingRuleId.value = null
  }
}

async function doCheck() {
  checking.value = true
  try {
    await checkAlerts({})
    await loadHistory()
    showToast({ type: 'success', message: '检查完成' })
  } catch (e) {
    console.error(e)
    showToast({ type: 'fail', message: `检查失败：${e?.message || e}` })
  } finally {
    checking.value = false
  }
}

onMounted(() => {
  reloadAll().catch((e) => console.error(e))
})
</script>

<style scoped>
.wrap {
  color: #c9c9c9;
}
.head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
  padding: 14px 14px 12px;
  border: 1px solid #1f1f1f;
  background: #141414;
  border-radius: 8px;
  
}
.title {
  font-weight: 800;
  letter-spacing: 0.2px;
}
.sub {
  margin-top: 6px;
  font-size: 12px;
  color: #8b8b8b;
}
.actions {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
  justify-content: flex-end;
}
.btn {
  border: 1px solid #262626;
  background: #1a1a1a;
  color: #e6e6e6;
  border-radius: 8px;
  padding: 9px 12px;
  cursor: pointer;
  transition: transform 0.12s ease, box-shadow 0.12s ease, background 0.12s ease;
}
.btn:hover {
  background: #222222;
}
.btn:disabled {
  opacity: 0.55;
  cursor: not-allowed;
  transform: none;
  box-shadow: none;
}
.btn.primary {
  border-color: rgba(6, 193, 103, 0.35);
  background: rgba(6, 193, 103, 0.12);
}
.btn.small {
  padding: 7px 10px;
  border-radius: 8px;
  font-size: 12px;
}
.btn.danger {
  border-color: rgba(240, 68, 56, 0.35);
  background: rgba(240, 68, 56, 0.12);
}
.grid {
  margin-top: 14px;
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 14px;
}
.card {
  border: 1px solid #1f1f1f;
  background: #141414;
  border-radius: 8px;
  
  padding: 12px;
}
.span2 {
  grid-column: 1 / -1;
  display: flex;
  flex-direction: column;
  max-height: calc(100vh - 240px);
  min-height: 380px;
  overflow: hidden;
}
.cardTitle {
  font-weight: 800;
  margin-bottom: 10px;
}
.form {
  display: grid;
  gap: 10px;
}
.field {
  display: grid;
  gap: 6px;
}
.label {
  font-size: 12px;
  color: #8b8b8b;
  font-weight: 900;
}
.input {
  border: 1px solid #262626;
  background: #1a1a1a;
  color: #ffffff;
  border-radius: 8px;
  padding: 10px 10px;
  outline: none;
}
.row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}
.chk {
  font-size: 12px;
  color: #b9b9b9;
}
.list {
  display: grid;
  gap: 10px;
}
.item {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  border: 1px solid #1f1f1f;
  background: #1a1a1a;
  border-radius: 8px;
  padding: 10px 10px;
}
.rName {
  font-weight: 900;
}
.rSub {
  margin-top: 4px;
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.pill {
  font-size: 12px;
  border: 1px solid #262626;
  background: #141414;
  padding: 3px 8px;
  border-radius: 999px;
  color: #b9b9b9;
}
.ops {
  display: flex;
  gap: 8px;
  align-items: center;
}
.toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 10px;
}
.hint {
  font-size: 12px;
  color: #8b8b8b;
}
.history {
  display: grid;
  gap: 10px;
  overflow: auto;
  padding-right: 2px;
  flex: 1;
  align-content: start;
}
.ev {
  display: grid;
  grid-template-columns: 78px 1fr;
  gap: 10px;
  border: 1px solid #1f1f1f;
  background: #1a1a1a;
  border-radius: 8px;
  padding: 10px 10px;
}
.badge {
  height: fit-content;
  border-radius: 999px;
  padding: 5px 10px;
  font-size: 12px;
  font-weight: 800;
  border: 1px solid #262626;
  background: #1a1a1a;
  text-align: center;
}
.badge.critical {
  border-color: rgba(240, 68, 56, 0.40);
  background: rgba(240, 68, 56, 0.16);
}
.badge.warning {
  border-color: rgba(255, 178, 36, 0.40);
  background: rgba(255, 178, 36, 0.16);
}
.evTitle {
  font-weight: 800;
}
.evMsg {
  margin-top: 4px;
  color: #c9c9c9;
  font-size: 13px;
}
.evMeta {
  margin-top: 6px;
  font-size: 12px;
  color: #8b8b8b;
}
.empty {
  font-size: 13px;
  color: #8b8b8b;
  padding: 10px 2px;
}
@media (max-width: 1100px) {
  .grid {
    grid-template-columns: 1fr;
  }
  .span2 {
    grid-column: auto;
  }
}
</style>

