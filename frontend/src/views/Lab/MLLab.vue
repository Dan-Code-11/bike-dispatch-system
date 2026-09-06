<template>
  <div class="wrap">
    <div class="head">
      <div>
        <div class="title">预测模型实验室</div>
        <div class="sub">查看模型状态、手动触发训练（演示用同步训练）、单站预测曲线与基线对比。</div>
      </div>
      <div class="actions">
        <button class="btn" @click="reload" :disabled="loading">{{ loading ? '刷新中…' : '刷新状态' }}</button>
        <button class="btn primary" @click="train" :disabled="training">{{ training ? '训练中…' : '触发训练' }}</button>
      </div>
    </div>

    <div class="grid">
      <div class="card">
        <div class="cardTitle">训练参数</div>
        <div class="form">
          <div class="field">
            <div class="label">num_days</div>
            <input class="input" v-model.number="p_numDays" type="number" min="1" max="30" step="1" />
          </div>
          <div class="field">
            <div class="label">epochs</div>
            <input class="input" v-model.number="p_epochs" type="number" min="1" max="50" step="1" />
          </div>
          <div class="field">
            <div class="label">hidden_size</div>
            <input class="input" v-model.number="p_hidden" type="number" min="8" max="512" step="8" />
          </div>
          <div class="field">
            <div class="label">batch_size</div>
            <input class="input" v-model.number="p_batch" type="number" min="8" max="512" step="8" />
          </div>
          <div class="field">
            <div class="label">lr</div>
            <input class="input" v-model.number="p_lr" type="number" min="0.000001" max="1" step="0.0001" />
          </div>
          <div class="field">
            <div class="label">train_ratio</div>
            <input class="input" v-model.number="p_ratio" type="number" min="0.21" max="0.98" step="0.01" />
          </div>
          <div class="tip">训练会覆盖权重文件，并刷新服务端缓存模型；用于快速对比不同参数表现。</div>
        </div>
      </div>

      <div class="card">
        <div class="cardTitle">模型状态</div>
        <div class="kv">
          <div class="row"><span class="k">时间</span><span class="v">{{ status?.time || '-' }}</span></div>
          <div class="row"><span class="k">Torch</span><span class="v">{{ status?.torch_available ? '可用' : '不可用' }}</span></div>
          <div class="row"><span class="k">区域数</span><span class="v">{{ status?.zones_count ?? '-' }}</span></div>
          <div class="row"><span class="k">权重文件</span><span class="v mono">{{ status?.weights_exists ? '存在' : '不存在' }}</span></div>
          <div class="row"><span class="k">权重路径</span><span class="v mono">{{ status?.weights_path || '-' }}</span></div>
        </div>
      </div>

      <div class="card">
        <div class="cardTitle">运行统计</div>
        <div class="kv">
          <div class="row"><span class="k">调度次数</span><span class="v">{{ status?.dispatch_count ?? 0 }}</span></div>
          <div class="row"><span class="k">最近调度</span><span class="v">{{ status?.last_dispatch_time || '-' }}</span></div>
        </div>
        <div class="tip">提示：调度次数来自后端运行态统计；后续可接入任务队列与持久化。</div>
      </div>
    </div>

    <!-- 预测实验室：单站预测曲线 + LSTM vs Persistent 基线对比 -->
    <div class="labSection">
      <div class="labHead">
        <div>
          <div class="labTitle">预测实验室</div>
          <div class="labSub">单站历史与未来 3h 预测曲线 · LSTM 与 Persistent 基线对比</div>
        </div>
        <div class="labCtrls">
          <select class="input sel" v-model="labZoneId">
            <option value="" disabled>选择站点</option>
            <option v-for="z in labZones" :key="z.zone_id" :value="z.zone_id">{{ z.name }}</option>
          </select>
          <input class="input time" type="time" v-model="labTime" />
          <button class="btn primary" @click="runLabPredict" :disabled="labLoading || !labZoneId">{{ labLoading ? '预测中…' : '运行预测' }}</button>
        </div>
      </div>

      <div class="labGrid">
        <div class="card curveCard">
          <div class="cardTitle">预测曲线 · {{ labZoneName }}</div>
          <PredictionChart
            :zone-id="labZoneId"
            :zone-name="labZoneName"
            :current-vehicles="labZoneInfo?.current_count"
            :capacity="labZoneInfo?.capacity"
            :history-times="labSeries?.history_times || []"
            :history-series="labSeries?.history_vehicles || []"
            :curve-times="labSeries?.curve_times || []"
            :curve-series-lstm="labSeries?.curve_vehicles_lstm || []"
            :curve-series-persistent="labSeries?.curve_vehicles_persistent || []"
            :anchors="labZoneInfo?.forecast_anchors || []"
            :worst-horizon="labZoneInfo?.worst_horizon"
          />
        </div>

        <div class="colRight">
          <div class="card">
            <div class="cardTitle">LSTM vs Persistent 基线</div>
            <div class="evRows" v-if="labEvidenceRows.length">
              <div class="evRow" v-for="row in labEvidenceRows" :key="row.label">
                <div class="evL">{{ row.label }}</div>
                <div class="evTrack">
                  <div class="evFill" :style="{ width: row.width + '%', background: row.color }"></div>
                </div>
                <div class="evV" :style="{ color: row.color }">{{ row.text }}</div>
              </div>
            </div>
            <div class="evEmpty" v-else>运行预测后展示模型测试集相对 Persistent 基线的 MAE 改进</div>
            <div class="tip" v-if="labAgg">平均 {{ fmtPct(labAgg.avg_improvement_pct_mae) }} MAE（LSTM {{ num2(labAgg.lstm_avg_key_mae) }} vs 基线 {{ num2(labAgg.pers_avg_key_mae) }}）</div>
          </div>

          <div class="card" v-if="labAnchors.length">
            <div class="cardTitle">当前站锚点预测</div>
            <div class="anchors" v-for="(a, i) in labAnchors" :key="i">
              <div class="aRow">
                <span class="aH">{{ a.time }}</span>
                <span class="aLstm">LSTM {{ num1(a.vehicles) }}</span>
                <span class="aPers">基线 {{ num1(a.baseline_persistent) }}</span>
                <span class="aDelta" :class="a.delta_vs_now >= 0 ? 'up' : 'down'">{{ a.delta_vs_now >= 0 ? '+' : '' }}{{ num1(a.delta_vs_now) }}</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { showToast } from 'vant'
import { fetchModelStatus, trainModel, fetchHistory, predictMulti3Hour } from '../../api'
import PredictionChart from '../../components/PredictionChart.vue'

const loading = ref(false)
const training = ref(false)
const status = ref(null)

const p_numDays = ref(7)
const p_epochs = ref(8)
const p_hidden = ref(64)
const p_batch = ref(64)
const p_lr = ref(0.001)
const p_ratio = ref(0.8)

async function reload() {
  loading.value = true
  try {
    status.value = await fetchModelStatus()
  } catch (e) {
    console.error(e)
    showToast({ type: 'fail', message: e?.message || String(e) })
  } finally {
    loading.value = false
  }
}

async function train() {
  training.value = true
  try {
    await trainModel({
      num_days: p_numDays.value,
      epochs: p_epochs.value,
      hidden_size: p_hidden.value,
      batch_size: p_batch.value,
      lr: p_lr.value,
      train_ratio: p_ratio.value,
    })
    showToast({ type: 'success', message: '训练完成' })
    await reload()
  } catch (e) {
    console.error(e)
    showToast({ type: 'fail', message: e?.message || String(e) })
  } finally {
    training.value = false
  }
}

// ====== 预测实验室 ======
const labZones = ref([])
const labZoneId = ref('')
const labTime = ref('12:30')
const labLoading = ref(false)
const labPrediction = ref(null)

const labSeries = computed(() => labPrediction.value?.series_by_zone?.[labZoneId.value] || null)
const labZoneInfo = computed(() => labPrediction.value?.zones?.find((z) => z.zone_id === labZoneId.value) || null)
const labZoneName = computed(() => labZoneInfo.value?.name || labZoneId.value || '—')

const labAnchors = computed(() => {
  const times = labSeries.value?.anchors_times || []
  const lstm = labSeries.value?.anchors_vehicles_lstm || []
  const pers = labSeries.value?.anchors_vehicles_persistent || []
  const cur = labZoneInfo.value?.current_count ?? null
  return times.map((t, i) => ({
    time: t,
    vehicles: lstm[i] ?? null,
    baseline_persistent: pers[i] ?? null,
    delta_vs_now: lstm[i] != null && cur != null ? lstm[i] - cur : null,
  }))
})

const labEvidence = computed(() => labPrediction.value?.baseline_evidence || null)
const labAgg = computed(() => labEvidence.value?.aggregate || null)
const labEvidenceRows = computed(() => {
  const ph = labEvidence.value?.per_horizon
  if (!ph) return []
  let maxAbs = 1
  const vals = Object.values(ph).map((v) => Math.abs(v.improvement_pct_mae ?? 0))
  if (vals.length) maxAbs = Math.max(...vals, 1)
  return Object.entries(ph).map(([label, v]) => {
    const imp = v.improvement_pct_mae ?? 0
    const width = Math.max(4, Math.round((Math.abs(imp) / maxAbs) * 100))
    return {
      label,
      imp,
      text: `${imp >= 0 ? '+' : ''}${imp.toFixed(1)}%`,
      width,
      color: imp >= 0 ? '#06C167' : '#F04438',
    }
  })
})

function fmtPct(v) { return v == null ? '—' : `${v >= 0 ? '+' : ''}${Number(v).toFixed(1)}%` }
function num1(v) { return v == null ? '—' : Number(v).toFixed(1) }
function num2(v) { return v == null ? '—' : Number(v).toFixed(2) }

async function loadLabZones() {
  try {
    const res = await fetch('/api/monitor/stats')
    if (!res.ok) return
    const data = await res.json()
    labZones.value = data.zones || []
    if (!labZoneId.value && labZones.value.length) labZoneId.value = labZones.value[0].zone_id
  } catch (e) {
    console.error('loadLabZones', e)
  }
}

async function runLabPredict() {
  if (!labZoneId.value) return
  labLoading.value = true
  try {
    const t = labTime.value
    const histRes = await fetchHistory(t, 24)
    const predRes = await predictMulti3Hour({ time: t, history: histRes.history, zone_order: histRes.zone_order })
    labPrediction.value = predRes
  } catch (e) {
    console.error(e)
    showToast({ type: 'fail', message: e?.message || String(e) })
  } finally {
    labLoading.value = false
  }
}

onMounted(() => {
  reload().catch(() => {})
  loadLabZones().catch(() => {})
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
.btn.primary {
  border-color: rgba(6, 193, 103, 0.35);
  background: rgba(6, 193, 103, 0.12);
}
.grid {
  margin-top: 14px;
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 14px;
}
.form {
  display: grid;
  grid-template-columns: 1fr 1fr;
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
.card {
  border: 1px solid #1f1f1f;
  background: #141414;
  border-radius: 8px;
  padding: 12px;
}
.cardTitle {
  font-weight: 800;
  margin-bottom: 10px;
  color: #fff;
}
.kv {
  display: grid;
  gap: 8px;
  font-size: 13px;
}
.row {
  display: flex;
  justify-content: space-between;
  gap: 12px;
}
.k {
  color: #8b8b8b;
  font-weight: 900;
}
.mono {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
  font-size: 12px;
}
.tip {
  margin-top: 10px;
  font-size: 12px;
  color: #8b8b8b;
}

/* 预测实验室 */
.labSection {
  margin-top: 14px;
  border: 1px solid #1f1f1f;
  background: #111;
  border-radius: 12px;
  padding: 14px;
}
.labHead {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 12px;
}
.labTitle { font-weight: 800; color: #fff; }
.labSub { margin-top: 4px; font-size: 12px; color: #8b8b8b; }
.labCtrls { display: flex; gap: 10px; flex-wrap: wrap; }
.sel { min-width: 220px; }
.time { width: 120px; }
.labGrid {
  display: grid;
  grid-template-columns: 1.6fr 1fr;
  gap: 14px;
}
.curveCard { min-width: 0; }
.curveCard :deep(.chart) { height: 300px; }
.colRight { display: grid; gap: 14px; align-content: start; }

.evRows { display: grid; gap: 10px; }
.evRow { display: flex; align-items: center; gap: 10px; }
.evL { width: 30px; font-weight: 800; color: #fff; font-size: 13px; }
.evTrack { flex: 1; height: 10px; background: #1f1f1f; border-radius: 999px; overflow: hidden; }
.evFill { height: 100%; border-radius: 999px; }
.evV { width: 56px; text-align: right; font-weight: 800; font-size: 13px; font-variant-numeric: tabular-nums; }
.evEmpty { font-size: 12px; color: #5a5a5a; }

.anchors { display: grid; gap: 8px; }
.aRow {
  display: flex; align-items: center; gap: 10px;
  border: 1px solid #1f1f1f; background: #1a1a1a;
  border-radius: 8px; padding: 8px 10px; font-size: 13px;
}
.aH { width: 56px; font-weight: 800; color: #fff; }
.aLstm { color: #06C167; font-weight: 700; }
.aPers { color: #8b8b8b; }
.aDelta { margin-left: auto; font-weight: 800; font-variant-numeric: tabular-nums; }
.aDelta.up { color: #06C167; }
.aDelta.down { color: #F04438; }

@media (max-width: 1100px) {
  .grid {
    grid-template-columns: 1fr;
  }
  .form {
    grid-template-columns: 1fr;
  }
  .labGrid {
    grid-template-columns: 1fr;
  }
}
</style>
