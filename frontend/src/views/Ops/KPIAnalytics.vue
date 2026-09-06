<template>
  <div class="wrap">
    <div class="head">
      <div>
        <div class="title">运营分析</div>
        <div class="sub">按时间片查看区域车辆分布与饱和度，多维可视化洞察供需状态</div>
      </div>
      <div class="actions">
        <div class="timeBox">
          <span class="tLabel">时间</span>
          <span class="curTime" :class="{ live: realtime }">{{ nowLabel }}</span>
        </div>
        <div class="timeBox" :class="{ dim: realtime }">
          <span class="tLabel">固定</span>
          <input class="time" type="time" v-model="timeStr" :disabled="realtime" />
        </div>
        <button class="btn" @click="toggleRealtime">{{ realtime ? '切换到固定' : '回到实时' }}</button>
        <button class="btn" @click="reload(null, false)" :disabled="loading">{{ loading ? '加载中…' : '刷新' }}</button>
      </div>
    </div>

    <div class="kpiPane">
      <!-- KPI 概览 -->
      <div class="kpiRow">
        <div class="kpi">
          <div class="kpiLabel">在库车辆</div>
          <div class="kpiVal">{{ kpi.totalVehicles }}</div>
        </div>
        <div class="kpi">
          <div class="kpiLabel">平均饱和度</div>
          <div class="kpiVal">{{ kpi.avgSaturation }}%</div>
        </div>
        <div class="kpi">
          <div class="kpiLabel">短缺站</div>
          <div class="kpiVal shortage">{{ kpi.shortage }}</div>
        </div>
        <div class="kpi">
          <div class="kpiLabel">盈余站</div>
          <div class="kpiVal surplus">{{ kpi.surplus }}</div>
        </div>
        <div class="kpi">
          <div class="kpiLabel">健康站</div>
          <div class="kpiVal neutral">{{ kpi.healthy }}</div>
        </div>
      </div>

      <div class="grid">
        <div class="card">
          <div class="cardTitle">Top 区域 · 车辆数</div>
          <div ref="vehChartEl" class="chart"></div>
        </div>

        <div class="card">
          <div class="cardTitle">Top 区域 · 饱和度</div>
          <div ref="satChartEl" class="chart"></div>
        </div>

        <div class="card">
          <div class="cardTitle">供需状态分布</div>
          <div ref="donutEl" class="chart"></div>
        </div>

        <div class="card">
          <div class="cardTitle">车辆数 × 饱和度</div>
          <div ref="scatterEl" class="chart"></div>
        </div>

        <div class="card span2">
          <div class="cardTitle">全量明细</div>
          <div class="table">
            <div class="tr headRow">
              <div>区域</div>
              <div>车辆</div>
              <div>饱和度</div>
              <div>状态</div>
            </div>
            <div class="tr" v-for="z in zones" :key="z.zone_id">
              <div class="td name">{{ z.name }}</div>
              <div class="td">{{ z.vehicles }}</div>
              <div class="td">{{ (z.saturation_ratio * 100).toFixed(0) }}%</div>
              <div class="td"><span class="statusTag" :class="statusClass(z)">{{ statusLabel(z) }}</span></div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts'
import { showToast } from 'vant'

const timeStr = ref('12:30')
const realtime = ref(true) // 实时模式：每 5 秒按当前时刻自动刷新；固定模式：按所选时间
const nowLabel = ref('')
let tickTimer = null
const loading = ref(false)
const zones = ref([])

const vehChartEl = ref(null)
const satChartEl = ref(null)
const donutEl = ref(null)
const scatterEl = ref(null)
let vehChart = null
let satChart = null
let donut = null
let scatter = null

function ratioOf(z) { return Math.round((z.saturation_ratio || 0) * 100) }
function statusOf(z) {
  const r = ratioOf(z)
  if (r < 20) return 'shortage'
  if (r > 150) return 'surplus'
  return 'healthy'
}
function statusLabel(z) {
  const s = statusOf(z)
  return s === 'shortage' ? '短缺' : s === 'surplus' ? '盈余' : '健康'
}
function statusClass(z) { return statusOf(z) }

const kpi = computed(() => {
  const zs = zones.value
  const totalVehicles = zs.reduce((s, z) => s + (z.vehicles || 0), 0)
  const avg = zs.length ? zs.reduce((s, z) => s + (z.saturation_ratio || 0), 0) / zs.length : 0
  const shortage = zs.filter((z) => statusOf(z) === 'shortage').length
  const surplus = zs.filter((z) => statusOf(z) === 'surplus').length
  return {
    totalVehicles,
    avgSaturation: Math.round(avg * 100),
    shortage,
    surplus,
    healthy: Math.max(0, zs.length - shortage - surplus),
  }
})

function renderCharts() {
  if (!zones.value.length) return
  const zs = zones.value

  // 1. 车辆数 Top 10 横向条形
  const topVeh = zs.slice().sort((a, b) => (b.vehicles || 0) - (a.vehicles || 0)).slice(0, 10)
  if (vehChart) {
    vehChart.setOption({
      grid: { left: 8, right: 30, top: 8, bottom: 8, containLabel: true },
      xAxis: { type: 'value', splitLine: { lineStyle: { color: '#1F1F1F' } }, axisLabel: { color: '#5A5A5A', fontSize: 10 } },
      yAxis: {
        type: 'category', inverse: true,
        data: topVeh.map((z) => z.name),
        axisLabel: { color: '#8B8B8B', fontSize: 11 },
        axisLine: { show: false }, axisTick: { show: false },
      },
      tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' }, backgroundColor: '#1A1A1A', borderColor: '#2A2A2A', textStyle: { color: '#fff', fontSize: 12 } },
      series: [{
        type: 'bar', data: topVeh.map((z) => z.vehicles), barWidth: 12,
        itemStyle: { color: '#06C167', borderRadius: [0, 6, 6, 0] },
        label: { show: true, position: 'right', color: '#FFFFFF', fontSize: 10, fontWeight: 700 },
      }],
    }, true)
  }

  // 2. 饱和度 Top 10 横向条形（颜色区分状态）
  const topSat = zs.slice().sort((a, b) => (b.saturation_ratio || 0) - (a.saturation_ratio || 0)).slice(0, 10)
  if (satChart) {
    satChart.setOption({
      grid: { left: 8, right: 30, top: 8, bottom: 8, containLabel: true },
      xAxis: { type: 'value', max: 200, splitLine: { lineStyle: { color: '#1F1F1F' } }, axisLabel: { color: '#5A5A5A', fontSize: 10 } },
      yAxis: {
        type: 'category', inverse: true,
        data: topSat.map((z) => z.name),
        axisLabel: { color: '#8B8B8B', fontSize: 11 },
        axisLine: { show: false }, axisTick: { show: false },
      },
      tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' }, backgroundColor: '#1A1A1A', borderColor: '#2A2A2A', textStyle: { color: '#fff', fontSize: 12 } },
      series: [{
        type: 'bar', data: topSat.map((z) => ratioOf(z)), barWidth: 12,
        itemStyle: {
          borderRadius: [0, 6, 6, 0],
          color: (p) => p.value < 20 ? '#F04438' : p.value > 150 ? '#06C167' : '#8B8B8B',
        },
        label: { show: true, position: 'right', color: '#FFFFFF', fontSize: 10, fontWeight: 700, formatter: (p) => `${p.value}%` },
      }],
    }, true)
  }

  // 3. 供需状态分布 环形图
  if (donut) {
    const k = kpi.value
    donut.setOption({
      tooltip: { trigger: 'item', backgroundColor: '#1A1A1A', borderColor: '#2A2A2A', textStyle: { color: '#fff', fontSize: 12 } },
      legend: { bottom: 0, left: 'center', textStyle: { color: '#8B8B8B', fontSize: 11 }, itemWidth: 12, itemHeight: 12 },
      series: [{
        type: 'pie', radius: ['52%', '76%'], center: ['50%', '44%'],
        avoidLabelOverlap: true,
        itemStyle: { borderColor: '#0A0A0A', borderWidth: 2 },
        label: { show: true, formatter: '{b}\n{c}', color: '#FFFFFF', fontSize: 11 },
        data: [
          { name: '短缺', value: k.shortage, itemStyle: { color: '#F04438' } },
          { name: '健康', value: k.healthy, itemStyle: { color: '#6B6B6B' } },
          { name: '盈余', value: k.surplus, itemStyle: { color: '#06C167' } },
        ],
      }],
    }, true)
  }

  // 4. 车辆数 × 饱和度 散点
  if (scatter) {
    scatter.setOption({
      grid: { left: 8, right: 14, top: 20, bottom: 26, containLabel: true },
      tooltip: {
        trigger: 'item',
        backgroundColor: '#1A1A1A', borderColor: '#2A2A2A', textStyle: { color: '#fff', fontSize: 12 },
        formatter: (p) => `${p.data.name}<br/>车辆: ${p.data.vehicles}<br/>饱和度: ${p.data.sat}%`,
      },
      xAxis: {
        type: 'value', name: '车辆数', nameTextStyle: { color: '#5A5A5A', fontSize: 10 },
        axisLabel: { color: '#5A5A5A', fontSize: 10 }, splitLine: { lineStyle: { color: '#1F1F1F' } },
      },
      yAxis: {
        type: 'value', name: '饱和度 %', max: 200, nameTextStyle: { color: '#5A5A5A', fontSize: 10 },
        axisLabel: { color: '#5A5A5A', fontSize: 10 }, splitLine: { lineStyle: { color: '#1F1F1F' } },
      },
      series: [{
        type: 'scatter',
        symbolSize: 11,
        data: zs.map((z) => ({
          value: [z.vehicles || 0, ratioOf(z)],
          name: z.name,
          vehicles: z.vehicles || 0,
          sat: ratioOf(z),
          itemStyle: { color: statusOf(z) === 'shortage' ? '#F04438' : statusOf(z) === 'surplus' ? '#06C167' : '#6B6B6B' },
        })),
        itemStyle: { opacity: 0.9 },
      }],
    }, true)
  }
}

function disposeCharts() {
  for (const c of [vehChart, satChart, donut, scatter]) if (c) c.dispose()
  vehChart = satChart = donut = scatter = null
}

function nowHHMM() {
  const d = new Date()
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

function toggleRealtime() {
  realtime.value = !realtime.value
  if (realtime.value) {
    nowLabel.value = nowHHMM()
    reload(null, true)
  } else {
    nowLabel.value = timeStr.value
    reload(timeStr.value, false)
  }
}

watch(timeStr, (v) => {
  if (!realtime.value) { nowLabel.value = v; reload(v, false) }
})

async function reload(time, quiet) {
  if (!quiet) loading.value = true
  try {
    const url = time ? `/api/monitor/stats?time=${encodeURIComponent(time)}` : '/api/monitor/stats'
    const res = await fetch(url)
    if (!res.ok) throw new Error(`monitor/stats failed: ${res.status}`)
    const data = await res.json()
    zones.value = (data.zones || []).slice().sort((a, b) => (b.vehicles || 0) - (a.vehicles || 0))
    await nextTick()
    renderCharts()
  } catch (e) {
    console.error(e)
    if (!quiet) showToast({ type: 'fail', message: e?.message || String(e) })
  } finally {
    if (!quiet) loading.value = false
  }
}

onMounted(() => {
  vehChart = echarts.init(vehChartEl.value)
  satChart = echarts.init(satChartEl.value)
  donut = echarts.init(donutEl.value)
  scatter = echarts.init(scatterEl.value)
  nowLabel.value = nowHHMM()
  reload(null, false).catch(() => {})
  // 实时模式：每 5 秒按当前时刻静默刷新，页面随时间变化
  tickTimer = setInterval(() => {
    if (realtime.value) {
      nowLabel.value = nowHHMM()
      reload(null, true)
    }
  }, 5000)
})

let _rt = null
function onResize() {
  if (_rt) clearTimeout(_rt)
  _rt = setTimeout(() => {
    for (const c of [vehChart, satChart, donut, scatter]) c?.resize()
  }, 120)
}
window.addEventListener?.('resize', onResize)

onBeforeUnmount(() => {
  window.removeEventListener?.('resize', onResize)
  if (tickTimer) clearInterval(tickTimer)
  disposeCharts()
})
</script>

<style scoped>
.wrap { color: #c9c9c9; }
.head {
  display:flex; justify-content:space-between; align-items:flex-start; gap:12px;
  padding:14px 14px 12px; border:1px solid #1f1f1f; background:#141414;
  border-radius:8px;
}
.title { font-weight:800; color:#fff; }
.sub { margin-top:6px; font-size:12px; color:#8b8b8b; }
.actions { display:flex; gap:10px; align-items:center; flex-wrap:wrap; justify-content:flex-end; }
.timeBox { display:flex; align-items:center; gap:8px; }
.timeBox.dim { opacity: 0.5; }
.tLabel { font-size: 12px; color: #8b8b8b; font-weight: 900; }
.curTime {
  font-size: 15px; font-weight: 800; color: #fff;
  font-variant-numeric: tabular-nums;
  padding: 6px 10px; border-radius: 8px; border: 1px solid #262626; background: #1a1a1a;
  min-width: 78px; text-align: center;
}
.curTime.live { color: #06C167; border-color: #0f5233; }
.time {
  width:140px; border:1px solid #262626; background:#1a1a1a;
  color:#ffffff; border-radius:8px; padding:8px 10px;
}
.btn {
  border:1px solid #262626; background:#1a1a1a; color:#e6e6e6;
  border-radius:8px; padding:9px 12px; cursor:pointer;
}
.btn:hover { background:#222222; }

.kpiPane { margin-top: 12px; }
.kpiRow { display: grid; grid-template-columns: repeat(5, 1fr); gap: 10px; }
.kpi {
  border:1px solid #1f1f1f; background:#141414; border-radius:8px;
  padding: 12px 14px;
}
.kpiLabel { font-size: 12px; color: #8b8b8b; }
.kpiVal { margin-top: 6px; font-size: 26px; font-weight: 800; color: #fff; font-variant-numeric: tabular-nums; }
.kpiVal.shortage { color: #F04438; }
.kpiVal.surplus { color: #06C167; }
.kpiVal.neutral { color: #8B8B8B; }

.grid { margin-top: 14px; display:grid; grid-template-columns: 1fr 1fr; gap: 14px; }
.card { border:1px solid #1f1f1f; background:#141414; border-radius:8px; padding:12px; }
.span2 { grid-column: 1 / -1; }
.cardTitle { font-weight:800; margin-bottom:10px; color:#fff; }
.chart { height: 240px; width: 100%; }

.table { display:grid; gap:6px; }
.tr { display:grid; grid-template-columns: 1fr 90px 90px 90px; gap:10px; align-items:center; padding:8px 10px; border-radius:8px; border:1px solid #1f1f1f; background:#1a1a1a; }
.headRow { background:#1a1a1a; font-weight:800; color:#8b8b8b; }
.td { color:#c9c9c9; }
.td.name { color:#fff; font-weight:700; }
.statusTag { display:inline-block; padding:2px 8px; border-radius:999px; font-size:11px; font-weight:700; }
.statusTag.shortage { background: rgba(240,68,56,0.15); color:#F04438; }
.statusTag.surplus { background: rgba(6,193,103,0.15); color:#06C167; }
.statusTag.healthy { background: rgba(255,255,255,0.06); color:#8b8b8b; }

@media (max-width: 1100px) {
  .kpiRow { grid-template-columns: repeat(2, 1fr); }
  .grid { grid-template-columns: 1fr; }
  .span2 { grid-column:auto; }
  .tr { grid-template-columns: 1fr 70px 70px 70px; }
}
</style>
