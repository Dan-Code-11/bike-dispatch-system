<template>
  <div class="spatial">
    <!-- 图层切换 -->
    <div class="layerTabs">
      <button
        v-for="t in layerTabs"
        :key="t.value"
        class="layerTab"
        :class="{ active: layer === t.value }"
        @click="switchLayer(t.value)"
      >{{ t.label }}</button>
    </div>

    <div class="body">
      <div class="topRow">
      <!-- 左侧控制栏 -->
      <aside class="rail">
        <!-- ============ 时间回放 ============ -->
        <template v-if="layer === 'timeline'">
          <div class="card">
            <div class="cardTitle">时间回放</div>
            <div class="rowGrid">
              <div>
                <label for="f_tlTime">开始时间</label>
                <select id="f_tlTime" v-model="tlTime" class="sel">
                  <option value="00:00">00:00 午夜</option>
                  <option value="06:00">06:00 晨间</option>
                  <option value="07:30">07:30 早高峰起点</option>
                  <option value="12:00">12:00 午间</option>
                  <option value="17:00">17:00 晚高峰起点</option>
                </select>
              </div>
              <div>
                <label for="f_tlMode">展示模式</label>
                <select id="f_tlMode" v-model="tlMode" class="sel">
                  <option value="need">Need（短缺度）</option>
                  <option value="ratio">容量占比 (%)</option>
                  <option value="vehicle">车辆数</option>
                </select>
              </div>
              <div>
                <label for="f_tlInterval">粒度（分钟）</label>
                <select id="f_tlInterval" v-model.number="tlInterval" class="sel">
                  <option :value="15">15 分钟</option>
                  <option :value="10">10 分钟</option>
                  <option :value="30">30 分钟</option>
                </select>
              </div>
              <div>
                <label>样本日</label>
                <select id="f_tlDay" v-model.number="tlDay" class="sel">
                  <option :value="2">典型工作日</option>
                  <option :value="3">典型周末</option>
                </select>
              </div>
            </div>
            <button class="btn primary full" :disabled="tlLoading" @click="loadTimeline">
              {{ tlLoading ? '加载中...' : '加载时间序列' }}
            </button>
            <div class="dataNote">数据为 2025 年 1-5 月真实 Citi Bike 历史回放，共 151 天</div>
            <div v-if="tlData" class="frameStats">
              <div class="frameLabel">
                <span class="tLabel">{{ currentFrameLabel }}</span>
                <span class="tLabelDim">→ {{ lastFrameLabel }}</span>
              </div>
              <div class="stat3">
                <div class="s3Box shortage"><span class="v">{{ nShortage }}</span><span class="l">短缺</span></div>
                <div class="s3Box healthy"><span class="v">{{ nHealthy }}</span><span class="l">健康</span></div>
                <div class="s3Box surplus"><span class="v">{{ nSurplus }}</span><span class="l">盈余</span></div>
              </div>
            </div>
          </div>
          <div class="card" v-if="tlData">
            <div class="cardTitle">回放控制</div>
            <div class="sliderRow">
              <span class="tLabel">{{ currentFrameLabel }}</span>
              <input
                class="slider" type="range"
                :min="0" :max="Math.max(0, (tlData.times?.length || 1) - 1)" step="1"
                v-model.number="tlFrame"
              />
              <span class="tLabel">{{ lastFrameLabel }}</span>
            </div>
            <div class="ctlRow">
              <button class="btn sm" @click="prevFrame">⏮</button>
              <button class="btn sm primary" @click="togglePlay">{{ playing ? '⏸ 暂停' : '▶ 播放' }}</button>
              <button class="btn sm" @click="nextFrame">⏭</button>
              <span class="spacer"></span>
              <select id="f_speedMs" v-model.number="speedMs" class="sel sm">
                <option :value="1200">0.8x</option>
                <option :value="600">1.6x</option>
                <option :value="300">3.2x</option>
                <option :value="120">8x</option>
              </select>
            </div>
          </div>
        </template>

        <!-- ============ OD 潮汐流线 ============ -->
        <template v-if="layer === 'od'">
          <div class="card">
            <div class="cardTitle">OD 潮汐流线</div>
            <div class="rowGrid">
              <div>
                <label for="f_odTime">发车时段</label>
                <select id="f_odTime" v-model="odTime" class="sel">
                  <option value="07:30">早高峰 07:30</option>
                  <option value="08:30">早高峰 08:30</option>
                  <option value="12:00">午间 12:00</option>
                  <option value="17:00">晚高峰 17:00</option>
                  <option value="18:00">晚高峰 18:00</option>
                </select>
              </div>
              <div>
                <label for="f_odWindow">窗口（分钟）</label>
                <select id="f_odWindow" v-model.number="odWindow" class="sel">
                  <option :value="30">30 min</option>
                  <option :value="60">60 min</option>
                  <option :value="120">120 min</option>
                </select>
              </div>
              <div>
                <label>Top-K 站</label>
                <select id="f_odTopK" v-model.number="odTopK" class="sel">
                  <option :value="20">Top 20</option>
                  <option :value="40">Top 40</option>
                  <option :value="60">Top 60</option>
                </select>
              </div>
              <div>
                <label>样本日</label>
                <select id="f_odDay" v-model.number="odDay" class="sel">
                  <option :value="2">典型工作日</option>
                  <option :value="3">典型周末</option>
                </select>
              </div>
            </div>
            <button class="btn primary full" :disabled="odLoading" @click="loadODFlows">
              {{ odLoading ? '加载中...' : '计算 OD 流线' }}
            </button>
            <div v-if="odError" class="errText">{{ odError }}</div>
            <div v-if="odData" class="odMeta">
              <div class="rowFlex"><span>来源:</span><b :class="odData.source === 'real_od' ? 'good' : ''">{{ odData.source }}</b></div>
              <div class="rowFlex"><span>总流量</span><b>{{ odData.total_flow_estimate }}</b></div>
              <div class="rowFlex"><span>Top-K 站</span><b>{{ odData.edges.length }}</b></div>
            </div>
          </div>
          <div class="card" v-if="odData">
            <div class="rankTitle">净流入 Top 站点</div>
            <div class="rankList">
              <div v-for="(s, i) in odData.inflow_top.slice(0, 5)" :key="'in' + i" class="rankRow">
                <span class="rkIdx">{{ i + 1 }}</span>
                <span class="rkName" :title="s.name">{{ s.name }}</span>
                <span class="rkNet good">+{{ s.net }}</span>
              </div>
            </div>
            <div class="rankTitle" style="margin-top:10px">净流出 Top 站点</div>
            <div class="rankList">
              <div v-for="(s, i) in odData.outflow_top.slice(0, 5)" :key="'out' + i" class="rankRow">
                <span class="rkIdx">{{ i + 1 }}</span>
                <span class="rkName" :title="s.name">{{ s.name }}</span>
                <span class="rkNet bad">{{ s.net }}</span>
              </div>
            </div>
          </div>
        </template>

        <!-- ============ Moran / LISA ============ -->
        <template v-if="layer === 'lisa'">
          <div class="card">
            <div class="cardTitle">Moran / LISA</div>
            <div class="rowGrid">
              <div>
                <label for="f_lisaTime">时间</label>
                <select id="f_lisaTime" v-model="lisaTime" class="sel">
                  <option value="07:30">早高峰 07:30</option>
                  <option value="08:30">早高峰 08:30</option>
                  <option value="12:00">午间 12:00</option>
                  <option value="17:00">晚高峰 17:00</option>
                  <option value="18:00">晚高峰 18:00</option>
                </select>
              </div>
              <div>
                <label for="f_lisaAttr">属性</label>
                <select id="f_lisaAttr" v-model="lisaAttr" class="sel">
                  <option value="need">Need（短缺度）</option>
                  <option value="ratio">容量占比</option>
                  <option value="vehicles">车辆数</option>
                </select>
              </div>
              <div>
                <label for="f_lisaWeight">权重</label>
                <select id="f_lisaWeight" v-model="lisaWeight" class="sel">
                  <option value="knn">KNN</option>
                  <option value="distance_band">Distance Band</option>
                </select>
              </div>
              <div>
                <label for="f_lisaK">{{ lisaWeight === 'knn' ? 'K 值' : '阈值(米)' }}</label>
                <select id="f_lisaK" v-model.number="lisaK" class="sel">
                  <template v-if="lisaWeight === 'knn'">
                    <option :value="3">k=3</option>
                    <option :value="5">k=5</option>
                    <option :value="7">k=7</option>
                  </template>
                  <template v-else>
                    <option :value="500">500 m</option>
                    <option :value="800">800 m</option>
                    <option :value="1200">1200 m</option>
                  </template>
                </select>
              </div>
            </div>
            <button class="btn primary full" :disabled="lisaLoading" @click="loadLISA">
              {{ lisaLoading ? '计算中...' : '计算 Moran\'s I + LISA' }}
            </button>
            <div v-if="lisaError" class="errText">{{ lisaError }}</div>
            <div v-if="lisaData" class="moranBox">
              <div class="gMoran">
                <div class="gLabel">全局 Moran's I</div>
                <div class="gVal">{{ fmtNum(lisaData.global?.I, 3) }}</div>
                <div class="gSub">E[I] = {{ fmtNum(lisaData.global?.expected, 3) }} · Z = {{ fmtNum(lisaData.global?.z_score, 2) }}</div>
                <div class="gInterp">{{ lisaData.global?.interpretation }}</div>
              </div>
              <div class="clusterCounts">
                <div class="cc hh"><b>{{ lisaData.cluster_count?.HH || 0 }}</b><span>HH</span></div>
                <div class="cc ll"><b>{{ lisaData.cluster_count?.LL || 0 }}</b><span>LL</span></div>
                <div class="cc hl"><b>{{ lisaData.cluster_count?.HL || 0 }}</b><span>HL</span></div>
                <div class="cc lh"><b>{{ lisaData.cluster_count?.LH || 0 }}</b><span>LH</span></div>
                <div class="cc ns"><b>{{ lisaData.cluster_count?.NS || 0 }}</b><span>NS</span></div>
              </div>
            </div>
          </div>
        </template>

        <!-- ============ 典型日对比 ============ -->
        <template v-if="layer === 'typical'">
          <div class="card">
            <div class="cardTitle">典型日对比</div>
            <div class="rowGrid">
              <div>
                <label for="f_typInterval">聚合粒度</label>
                <select id="f_typInterval" v-model.number="typInterval" class="sel">
                  <option :value="15">15 min</option>
                  <option :value="30">30 min</option>
                  <option :value="60">60 min</option>
                </select>
              </div>
              <div>
                <label for="f_typSeries">展示对象</label>
                <select id="f_typSeries" v-model="typSeries" class="sel">
                  <option value="avg_vs_avg">工作日 vs 周末</option>
                  <option value="top5_stations">Top 5 高频站</option>
                  <option value="all_zone_avg">所有站（均值±σ）</option>
                </select>
              </div>
            </div>
            <button class="btn primary full" :disabled="typLoading" @click="loadTypicalDay">
              {{ typLoading ? '加载中...' : '计算典型日曲线' }}
            </button>
            <div v-if="typError" class="errText">{{ typError }}</div>
            <div v-if="typData" class="typMeta">
              <div class="rowFlex"><span>样本:</span><b>工作日 {{ typData.n_weekday }} · 周末 {{ typData.n_weekend }}</b></div>
              <div class="rowFlex"><span>粒度:</span><b>{{ typData.interval_minutes }} min</b></div>
              <div class="typHighlights">
                <div><b>工作日峰值</b> {{ typMeta.wd_peak_time }} · {{ typMeta.wd_peak_value.toFixed(1) }}</div>
                <div><b>周末峰值</b> {{ typMeta.we_peak_time }} · {{ typMeta.we_peak_value.toFixed(1) }}</div>
                <div><b>Δ偏移</b> {{ typMeta.peak_shift_min }} min · 潮汐 {{ typMeta.tidal_ratio.toFixed(2) }}x</div>
              </div>
            </div>
          </div>
        </template>
      </aside>

        <div class="card mapCard">
          <MapView
            :zones="[]"
            :activeLayer="layer"
            :timelineFrameValues="currentFrameValues"
            :timelineMode="tlMode"
            :timelineThresholds="{ shortage: 3, surplus: 3 }"
            :timelineLabel="currentFrameLabel"
            :playing="playing"
            :odEdges="odEdges"
            :odMeta="odData"
            :lisaLocal="lisaLocal"
            :lisaMeta="lisaData"
            @zone-selected="onZoneSelected"
          />
        </div>
      </div>

      <div class="card chartCard" :class="{ fullscreen: chartFullscreen }">
          <div class="chartHead">
            <div class="chartTitle">{{ chartTitle }}</div>
            <div class="chartHeadBtns">
              <button v-if="layer === 'timeline' && tlData" class="btn sm toggleZones" @click="toggleTlAllZones">
                {{ tlAllZones ? '仅 Top/Bottom' : '全部 30 站' }}
              </button>
              <button v-if="layer === 'timeline' && tlData" class="btn sm fsBtn" @click="toggleFullscreen">
                {{ chartFullscreen ? '✕ 退出全屏' : '⛶ 全屏' }}
              </button>
            </div>
          </div>
          <div v-if="layer === 'timeline'" class="tlWrap">
            <div ref="tlChartEl" class="chart"></div>
            <div v-show="tlData && markerVisible" class="tlMarker" :style="{ left: markerLeft + 'px' }">
              <span class="tlMarkerLabel">{{ currentFrameLabel }}</span>
            </div>
          </div>
          <div v-if="layer === 'od'" ref="odChartEl" class="chart"></div>
          <div v-if="layer === 'lisa'" ref="moranChartEl" class="chart"></div>
          <div v-if="layer === 'typical'" ref="typChartEl" class="chart"></div>
          <div v-if="noDataHint" class="empty">{{ noDataHint }}</div>
        </div>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts'
import MapView from './MapView.vue'
import { fetchTimeline, fetchODFlows, fetchSpatialStats, fetchTypicalDay, fetchZones } from '../api/index'

// 请求超时保护：后端一旦长时间无响应，20s 内强制抛错让按钮恢复，
// 避免“计算中”卡死需刷新页面的问题
function withTimeout(promise, ms = 20000) {
  return Promise.race([
    promise,
    new Promise((_, reject) => setTimeout(() => reject(new Error('请求超时，请重试')), ms)),
  ])
}

// ===================== 图层 =====================
const layerTabs = [
  { value: 'timeline', label: '时间回放' },
  { value: 'od', label: 'OD 潮汐流线' },
  { value: 'lisa', label: 'Moran / LISA' },
  { value: 'typical', label: '典型日对比' },
]
const layer = ref('timeline')
const selectedZoneId = ref(null)
// 站点元数据：zone_id → 可读站名，用于图表 tooltip 显示（避免显示数字 id）
const zones = ref([])
const zoneNameMap = computed(() => {
  const m = {}
  for (const z of zones.value) m[z.zone_id] = z.name
  return m
})
function onZoneSelected(zid) {
  selectedZoneId.value = selectedZoneId.value === zid ? null : zid
}

// v-if 切换后销毁旧 ECharts 实例，保证下次拿到全新干净 DOM
function disposeChartByKey(key) {
  try {
    if (key === 'tl' && tlChart) { tlChart.dispose(); tlChart = null }
    else if (key === 'od' && odChart) { odChart.dispose(); odChart = null }
    else if (key === 'moran' && moranChart) { moranChart.dispose(); moranChart = null }
    else if (key === 'typ' && typChart) { typChart.dispose(); typChart = null }
  } catch (e) { console.warn('[disposeChart]', e) }
}

// 安全获取/初始化 echarts：DOM 必须有真实尺寸才初始化
function safeInitChart(el, existing) {
  if (!el) return null
  try {
    const rect = el.getBoundingClientRect?.() || { width: el.clientWidth, height: el.clientHeight }
    if ((rect.height || 0) < 20 || (rect.width || 0) < 20) return null
    if (existing) return existing
    return echarts.init(el)
  } catch (e) { console.warn('[safeInitChart]', e); return null }
}

// 等待浏览器布局完成后再初始化图表（v-if 刚挂载时 DOM 尺寸可能为 0）
function waitLayout(fn, maxWait = 8) {
  let tries = 0
  let stopped = false
  const tick = () => {
    if (stopped) return
    tries++
    try {
      if (fn()) { stopped = true; return }
    } catch (e) { console.warn('[waitLayout]', e) }
    if (tries >= maxWait) {
      stopped = true
      console.warn('[waitLayout] timeout, skip chart init')
      return
    }
    requestAnimationFrame(() => setTimeout(tick, 0))
  }
  nextTick(tick)
}

function chartKeyForLayer(l) {
  return l === 'timeline' ? 'tl'
    : l === 'od' ? 'od'
    : l === 'lisa' ? 'moran'
    : l === 'typical' ? 'typ' : ''
}

function switchLayer(v) {
  if (v === layer.value) return
  // 先销毁当前图层的 ECharts 实例（v-if 卸载后 ref 会变 null）
  disposeChartByKey(chartKeyForLayer(layer.value))
  layer.value = v
  // v-if 重新挂载新图层 DOM 后，等待布局完成再初始化图表
  nextTick(() => {
    if (v === 'timeline' && tlData.value) {
      waitLayout(() => { renderTlChart(); return !!tlChart })
    } else if (v === 'od' && odData.value) {
      waitLayout(() => { renderOdChart(); return !!odChart })
    } else if (v === 'lisa' && lisaData.value) {
      waitLayout(() => { renderMoranChart(); return !!moranChart })
    } else if (v === 'typical' && typData.value) {
      waitLayout(() => { renderTypChart(); return !!typChart })
    }
  })
}

const chartTitle = computed(() => {
  switch (layer.value) {
    case 'timeline': return tlAllZones.value ? '全天趋势（全部 30 站）' : '全天趋势（Top/Bottom 站点）'
    case 'od': return '净流入 / 净流出 Top 10'
    case 'lisa': return 'Moran 散点图（Zi × WZi）'
    default: return '工作日 vs 周末 典型日曲线'
  }
})
const noDataHint = computed(() => {
  if (layer.value === 'timeline' && !tlData.value) return '点击「加载时间序列」查看 24h 潮汐动画'
  if (layer.value === 'od' && !odData.value) return '点击「计算 OD 流线」查看站点流向'
  if (layer.value === 'lisa' && !lisaData.value) return '点击「计算 Moran\'s I + LISA」查看空间自相关'
  if (layer.value === 'typical' && !typData.value) return '点击「计算典型日曲线」查看工作日 vs 周末'
  return ''
})

// ===================== 图表实例 =====================
const tlChartEl = ref(null)
const odChartEl = ref(null)
const moranChartEl = ref(null)
const typChartEl = ref(null)
let tlChart = null, odChart = null, moranChart = null, typChart = null

// ===================== 时间回放 =====================
const tlTime = ref('00:00')
const tlMode = ref('need')
const tlInterval = ref(15)
const tlDay = ref(2)
const tlData = ref(null)
const tlLoading = ref(false)
const tlFrame = ref(0)
const playing = ref(false)
const speedMs = ref(600)
let timer = null

const times = computed(() => tlData.value?.times || [])
const zoneOrderTl = computed(() => tlData.value?.zone_order || [])
const tlValues = computed(() => tlData.value?.values || [])
const currentFrameLabel = computed(() => times.value[tlFrame.value] || '--:--')
const lastFrameLabel = computed(() => times.value[times.value.length - 1] || '--:--')
const currentFrameValues = computed(() => {
  if (!tlData.value || !tlValues.value.length) return {}
  const frame = tlValues.value[tlFrame.value] || []
  const m = {}
  for (let i = 0; i < zoneOrderTl.value.length; i++) m[zoneOrderTl.value[i]] = frame[i]
  return m
})
const nShortage = computed(() => Object.values(currentFrameValues.value).filter(v => (v ?? 0) >= 3).length)
const nSurplus = computed(() => Object.values(currentFrameValues.value).filter(v => (v ?? 0) <= -3).length)
const nHealthy = computed(() => Math.max(0, 30 - nShortage.value - nSurplus.value))

// —— 方案A：折线只在加载时画一次；当前时刻改为容器上的 HTML 覆盖竖线（纯 DOM 定位，零图表重绘）——
const tlAllZones = ref(false)
const chartFullscreen = ref(false)
function toggleFullscreen() {
  chartFullscreen.value = !chartFullscreen.value
  if (chartFullscreen.value) {
    document.body.style.overflow = 'hidden'
  } else {
    document.body.style.overflow = ''
  }
  nextTick(() => resizeAll())
}
const markerLeft = ref(-999)
const markerVisible = computed(() =>
  !!(tlData.value && times.value.length && tlFrame.value >= 0 && tlFrame.value < times.value.length))
function toggleTlAllZones() {
  tlAllZones.value = !tlAllZones.value
  waitLayout(() => { renderTlChart(); return !!tlChart }, 10)
}
function updateMarker() {
  const el = tlChartEl.value
  if (!el || !times.value.length) { markerLeft.value = -999; return }
  const n = times.value.length
  const w = el.clientWidth
  if (!w) { markerLeft.value = -999; return }
  // 与 renderTlChart 的 grid 配置保持一致：left=40, right=12
  // 类目轴数据点均匀分布在绘图区内，纯 DOM 计算定位（不依赖 ECharts API，稳定）
  const plotLeft = 44, plotRight = 16
  const plotW = Math.max(1, w - plotLeft - plotRight)
  const ratio = n > 1 ? tlFrame.value / (n - 1) : 0
  const x = plotLeft + ratio * plotW
  markerLeft.value = Math.round(x) - 1
}

async function loadTimeline() {
  tlLoading.value = true
  try {
    const steps = Math.min(288, Math.floor(1440 / tlInterval.value))
    const res = await withTimeout(fetchTimeline({
      time: tlTime.value, steps, interval: tlInterval.value,
      day_index: tlDay.value, mode: tlMode.value,
    }))
    tlData.value = res
    tlFrame.value = 0
    waitLayout(() => { renderTlChart(); return !!tlChart }, 10)
  } catch (e) {
    console.error(e)
  } finally {
    tlLoading.value = false
  }
}
function prevFrame() { tlFrame.value = Math.max(0, tlFrame.value - 1) }
function nextFrame() { tlFrame.value = Math.min(times.value.length - 1, tlFrame.value + 1) }
function togglePlay() {
  if (playing.value) {
    playing.value = false
    if (timer) { clearInterval(timer); timer = null }
  } else {
    if (!times.value.length) return
    playing.value = true
    timer = setInterval(() => {
      tlFrame.value += 1
      if (tlFrame.value >= times.value.length - 1) tlFrame.value = 0
    }, speedMs.value)
  }
}
watch(speedMs, () => {
  if (playing.value && timer) {
    clearInterval(timer)
    timer = setInterval(() => {
      tlFrame.value += 1
      if (tlFrame.value >= times.value.length - 1) tlFrame.value = 0
    }, speedMs.value)
  }
})
watch(tlFrame, updateMarker)
// 切换展示模式（need/ratio/vehicle）后重新加载数据，否则图表和地图还是旧模式的数据
watch(tlMode, () => { if (tlData.value) loadTimeline() })

const ZONE_PALETTE = ['#06C167', '#F04438', '#FFB224', '#3B82F6', '#B48CEA', '#00C2A8',
  '#F5668A', '#A3D5E8', '#E1B98F', '#94D8C3', '#C9A7E8', '#F4B393',
  '#8BC8EA', '#9EACEA', '#DEBEF8', '#F8E7B1']

function yAxisRange(mode, st) {
  // ratio 固定 0~100；vehicles 从 0 起、上限扩展 15% 后 nice 到 5 的倍数；
  // need 用函数形式在数据极值基础上两端各留 12~15% 空间，并 nice 到 5 的倍数，保证曲线顶部/底部不被裁剪且刻度整齐
  if (mode === 'ratio') return { min: 0, max: 100 }
  if (mode === 'vehicle') return { min: 0, max: (v) => Math.ceil(v.max * 1.15 / 5) * 5 }
  return {
    min: (v) => Math.floor((v.min - Math.max(1, Math.abs(v.min) * 0.12)) / 5) * 5,
    max: (v) => Math.ceil((v.max + Math.max(1, Math.abs(v.max) * 0.15)) / 5) * 5,
  }
}

function renderTlChart() {
  try {
    if (!tlChartEl.value || !tlData.value) return false
    const inst = safeInitChart(tlChartEl.value, tlChart)
    if (!inst) return false
    tlChart = inst
    const Z = times.value
    const st = tlValues.value
    if (!Z.length || !st.length) return false
    const zoneOrder = zoneOrderTl.value
    const avg = (arr) => arr.reduce((a, b) => a + b, 0) / Math.max(1, arr.length)
    // ratio 后端返回 0~1 小数，y 轴是 0~100 百分比，需乘 100 统一单位
    const isRatio = tlMode.value === 'ratio'
    const fmtVal = (v) => v != null ? Number((Number(v) * (isRatio ? 100 : 1)).toFixed(2)) : null
    const series = []
    if (tlAllZones.value) {
      // 全部 30 站：颜色循环
      zoneOrder.forEach((name, i) => {
        const color = ZONE_PALETTE[i % ZONE_PALETTE.length]
        series.push({
          name, type: 'line', showSymbol: false, smooth: true,
          data: st.map(f => fmtVal(f[i])),
          lineStyle: { width: 1.2, color },
          itemStyle: { color },
        })
      })
    } else {
      // Top/Bottom：均值最低 3 + 最高 3 + 中间补到 10 条
      const meanByZone = zoneOrder.map((_, i) => avg(st.map(f => isRatio ? Number(f[i] || 0) * 100 : Number(f[i] || 0))))
      const sorted = meanByZone.map((_, i) => i).sort((a, b) => meanByZone[a] - meanByZone[b])
      const picked = new Set()
      for (let i = 0; i < Math.min(3, sorted.length); i++) picked.add(sorted[i])
      for (let i = 0; i < Math.min(3, sorted.length); i++) picked.add(sorted[sorted.length - 1 - i])
      let mid = Math.floor(sorted.length / 2) - 2
      while (picked.size < 10 && mid < sorted.length) picked.add(sorted[mid++])
      zoneOrder.forEach((name, i) => {
        if (picked.has(i)) {
          series.push({
            name, type: 'line', showSymbol: false, smooth: true,
            data: st.map(f => fmtVal(f[i])),
            lineStyle: { width: 1.6 },
          })
        }
      })
    }
    const yr = yAxisRange(tlMode.value, st)
    // 只在这里全量画一次；播放时不再触碰 series（当前帧标记由 HTML 覆盖层负责）
    tlChart.setOption({
      grid: { left: 44, right: 16, top: 36, bottom: 44 },
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'cross' },
        confine: true,
        formatter: (ps) => {
          if (!ps || !ps.length) return ''
          const MAX = chartFullscreen.value ? 30 : (tlAllZones.value ? 15 : 10)
          // 按值从大到小排序，最大值在最上面
          const sorted = [...ps].sort((a, b) => Number(b.value) - Number(a.value))
          let html = `<b>${sorted[0].axisValue}</b><br/>`
          for (const p of sorted.slice(0, MAX)) {
            const name = zoneNameMap.value[p.seriesName] || p.seriesName
            html += `${p.marker}${name}: ${p.value}<br/>`
          }
          if (sorted.length > MAX) {
            html += `<span style="color:#8B8B8B;font-size:11px">...还有 ${sorted.length - MAX} 个站点</span>`
          }
          return html
        },
        extraCssText: 'max-height: 88vh; overflow-y: auto; line-height: 1.45; font-size: 11px; box-shadow: 0 4px 16px rgba(0,0,0,0.4);',
      },
      xAxis: { type: 'category', data: Z, axisLabel: { interval: Math.floor(Z.length / 8) } },
      yAxis: { type: 'value', name: tlMode.value.toUpperCase(), min: yr.min, max: yr.max, scale: true },
      legend: { show: false },
      series,
    }, true)
    updateMarker()
    return true
  } catch (e) {
    console.warn('[renderTlChart]', e)
    return false
  }
}

// ===================== OD 潮汐流线 =====================
const odTime = ref('07:30')
const odWindow = ref(60)
const odTopK = ref(40)
const odDay = ref(2)
const odData = ref(null)
const odLoading = ref(false)
const odError = ref('')
const odEdges = computed(() => odData.value?.edges || [])

async function loadODFlows() {
  odLoading.value = true
  odError.value = ''
  try {
    const res = await withTimeout(fetchODFlows({
      time: odTime.value, window_minutes: odWindow.value,
      top_k: odTopK.value, day_index: odDay.value,
    }))
    odData.value = res
    waitLayout(() => { renderOdChart(); return !!odChart }, 10)
  } catch (e) {
    console.error(e)
    odError.value = e?.message || String(e)
  } finally {
    odLoading.value = false
  }
}
function renderOdChart() {
  try {
    if (!odChartEl.value || !odData.value) return false
    const inst = safeInitChart(odChartEl.value, odChart)
    if (!inst) return false
    odChart = inst
    const inflow = (odData.value.inflow_top || []).slice(0, 10).reverse()
    const outflow = (odData.value.outflow_top || []).slice(0, 10).reverse()
    odChart.setOption({
      grid: { left: 10, right: 10, top: 10, bottom: 30, containLabel: true },
      tooltip: {
        trigger: 'axis', axisPointer: { type: 'shadow' },
        formatter: (ps) => { const p = ps[0]; return `<b>${p.name}</b><br/>净流动 ${p.data.value}` },
      },
      xAxis: { type: 'value' },
      yAxis: {
        type: 'category',
        data: inflow.map(s => s.name).concat(outflow.map(s => s.name)),
        axisLabel: { width: 120, overflow: 'truncate', fontSize: 10 },
      },
      series: [{
        type: 'bar',
        data: inflow.map(s => ({ value: s.net, itemStyle: { color: '#06C167' } }))
          .concat(outflow.map(s => ({ value: s.net, itemStyle: { color: '#F04438' } }))),
        barWidth: 14,
        label: { show: true, position: 'right', fontSize: 10, formatter: p => p.value > 0 ? `+${p.value}` : p.value },
      }],
      dataZoom: [{ type: 'inside', orient: 'vertical' }],
    }, true)
    return true
  } catch (e) {
    console.warn('[renderOdChart]', e)
    return false
  }
}

// ===================== Moran / LISA =====================
const lisaTime = ref('07:30')
const lisaAttr = ref('need')
const lisaWeight = ref('knn')
const lisaK = ref(5)
const lisaData = ref(null)
const lisaLoading = ref(false)
const lisaError = ref('')
const lisaLocal = computed(() => lisaData.value?.local || [])

async function loadLISA() {
  lisaLoading.value = true
  lisaError.value = ''
  try {
    const weightParams = lisaWeight.value === 'knn' ? { k: lisaK.value } : { band_m: lisaK.value }
    const res = await withTimeout(fetchSpatialStats({
      time: lisaTime.value, attr: lisaAttr.value, weight: lisaWeight.value, ...weightParams,
    }))
    lisaData.value = res
    waitLayout(() => { renderMoranChart(); return !!moranChart }, 10)
  } catch (e) {
    console.error(e)
    lisaError.value = e?.message || String(e)
  } finally {
    lisaLoading.value = false
  }
}
function lisaColor(cluster) {
  switch (cluster) {
    case 'HH': return '#F04438'
    case 'LL': return '#06C167'
    case 'HL': return '#FFB224'
    case 'LH': return '#3B82F6'
    default: return '#8B8B8B'
  }
}
function renderMoranChart() {
  try {
    if (!moranChartEl.value || !lisaData.value) return false
    const inst = safeInitChart(moranChartEl.value, moranChart)
    if (!inst) return false
    moranChart = inst
    const safeNum = (v) => { const n = Number(v); return Number.isFinite(n) ? n : 0 }
    const pts = lisaLocal.value.map(t => ({
      value: [safeNum(t.z_x), safeNum(t.lag_z)],
      cluster: t.cluster, name: t.name,
    }))
    const scatter = pts.map(t => ({ value: t.value, itemStyle: { color: lisaColor(t.cluster) }, name: t.name }))
    const I = safeNum(lisaData.value?.global?.I)
    const z = 3.2
    const regLine = [[-z, -z * I], [z, z * I]]
    moranChart.setOption({
      grid: { left: 50, right: 20, top: 30, bottom: 50 },
      tooltip: {
        formatter: p => p.seriesType === 'scatter'
          ? `<b>${p.data?.name || ''}</b><br/>Zi=${safeNum(p.data?.value?.[0]).toFixed(2)}<br/>WZi=${safeNum(p.data?.value?.[1]).toFixed(2)}`
          : `Moran 回归线（I=${I.toFixed(3)}）`,
      },
      xAxis: { type: 'value', name: 'Zi', min: -z, max: z, splitLine: { lineStyle: { type: 'dashed' } } },
      yAxis: { type: 'value', name: 'WZi', min: -z, max: z, splitLine: { lineStyle: { type: 'dashed' } } },
      series: [
        {
          type: 'scatter', data: scatter, symbolSize: 10,
          markLine: {
            symbol: 'none', silent: true, lineStyle: { type: 'solid' },
            data: [
              { xAxis: 0, lineStyle: { color: '#333', width: 1 } },
              { yAxis: 0, lineStyle: { color: '#333', width: 1 } },
            ],
          },
        },
        { type: 'line', data: regLine, smooth: false, lineStyle: { color: '#555', width: 2 }, symbol: 'none', name: 'slope=I' },
      ],
      animation: false,
    }, true)
    return true
  } catch (e) {
    console.warn('[renderMoranChart]', e)
    return false
  }
}

// ===================== 典型日对比 =====================
const typInterval = ref(30)
const typSeries = ref('avg_vs_avg')
const typData = ref(null)
const typLoading = ref(false)
const typError = ref('')

const typMeta = computed(() => {
  if (!typData.value) return { wd_peak_time: '--:--', wd_peak_value: 0, we_peak_time: '--:--', we_peak_value: 0, peak_shift_min: 0, tidal_ratio: 1 }
  const wd = typData.value.weekday
  const we = typData.value.weekend
  if (!wd?.times?.length || !we?.times?.length) return { wd_peak_time: '--:--', wd_peak_value: 0, we_peak_time: '--:--', we_peak_value: 0, peak_shift_min: 0, tidal_ratio: 1 }
  const wdAvg = wd.times.map((_, t) => wd.values_by_zone.reduce((s, z) => s + (z[t] || 0), 0) / wd.values_by_zone.length)
  const weAvg = we.times.map((_, t) => we.values_by_zone.reduce((s, z) => s + (z[t] || 0), 0) / we.values_by_zone.length)
  let wdIdx = 0, weIdx = 0
  wdAvg.forEach((v, i) => { if (v > wdAvg[wdIdx]) wdIdx = i })
  weAvg.forEach((v, i) => { if (v > weAvg[weIdx]) weIdx = i })
  const fmtT = (m) => `${String(Math.floor(m / 60)).padStart(2, '0')}:${String(m % 60).padStart(2, '0')}`
  const wdPeakMin = wdIdx * typInterval.value
  const wePeakMin = weIdx * typInterval.value
  const rangeOf = (a) => Math.max(...a) - Math.min(...a)
  const tidal = rangeOf(weAvg) > 0.01 ? rangeOf(wdAvg) / rangeOf(weAvg) : 1
  return {
    wd_peak_time: fmtT(wdPeakMin), wd_peak_value: wdAvg[wdIdx],
    we_peak_time: fmtT(wePeakMin), we_peak_value: weAvg[weIdx],
    peak_shift_min: Math.abs(wePeakMin - wdPeakMin),
    tidal_ratio: tidal,
  }
})

async function loadTypicalDay() {
  typLoading.value = true
  typError.value = ''
  try {
    const res = await withTimeout(fetchTypicalDay({ interval_minutes: typInterval.value }))
    typData.value = res
    waitLayout(() => { renderTypChart(); return !!typChart }, 10)
  } catch (e) {
    console.error(e)
    typError.value = e?.message || String(e)
  } finally {
    typLoading.value = false
  }
}
watch(typSeries, () => { if (typData.value) renderTypChart() })

function renderTypChart() {
  try {
    if (!typChartEl.value || !typData.value) return false
    const inst = safeInitChart(typChartEl.value, typChart)
    if (!inst) return false
    typChart = inst
    const wd = typData.value.weekday
    const we = typData.value.weekend
    const times = wd.times || []
    const nZones = (wd.values_by_zone || []).length
    if (!times.length || !nZones) return false
    const mode = typSeries.value
    const safeNum = (v) => Number.isFinite(v) ? +Number(v).toFixed(2) : 0
    const series = []
    if (mode === 'avg_vs_avg') {
      const wdAvg = times.map((_, t) => wd.values_by_zone.reduce((s, z) => s + safeNum(z[t] || 0), 0) / nZones)
      const weAvg = times.map((_, t) => we.values_by_zone.reduce((s, z) => s + safeNum(z[t] || 0), 0) / nZones)
      series.push({ name: '工作日 均值', type: 'line', data: wdAvg.map(safeNum), smooth: true, lineStyle: { width: 3, color: '#06C167' }, itemStyle: { color: '#06C167' }, showSymbol: false })
      series.push({ name: '周末 均值', type: 'line', data: weAvg.map(safeNum), smooth: true, lineStyle: { width: 3, color: '#FFB224' }, itemStyle: { color: '#FFB224' }, showSymbol: false })
    } else if (mode === 'top5_stations') {
      const ranked = wd.values_by_zone.map((z, i) => ({ i, range: Math.max(...z.map(safeNum)) - Math.min(...z.map(safeNum)) }))
        .sort((a, b) => b.range - a.range).slice(0, 5)
      const order = typData.value.zone_order || []
      const palette = ['#F04438', '#FFB224', '#3B82F6', '#3B82F6', '#06C167']
      ranked.forEach((r, k) => {
        const color = palette[k % palette.length]
        const name = order[r.i] || `Zone-${r.i}`
        series.push({ name: `工作日 · ${name}`, type: 'line', data: wd.values_by_zone[r.i].map(safeNum), smooth: true, showSymbol: false, lineStyle: { width: 2, color } })
        series.push({ name: `周末 · ${name}`, type: 'line', data: we.values_by_zone[r.i].map(safeNum), smooth: true, showSymbol: false, lineStyle: { width: 2, color, type: 'dashed' } })
      })
    } else {
      const pushBand = (avgArr, upper, lower, color, label) => {
        series.push({ name: `${label} · ±1σ`, type: 'line', data: upper.map(safeNum), lineStyle: { opacity: 0 }, stack: `conf_${label}`, symbol: 'none' })
        series.push({ name: `${label} · 下限`, type: 'line', data: lower.map(safeNum), lineStyle: { opacity: 0 }, stack: `conf_${label}`, symbol: 'none', areaStyle: { color: color + '55' } })
      }
      const n = times.length
      const wdAvg = new Array(n).fill(0)
      const weAvg = new Array(n).fill(0)
      const wdStd = new Array(n).fill(0)
      const weStd = new Array(n).fill(0)
      for (let t = 0; t < n; t++) {
        const wdCol = wd.values_by_zone.map(z => safeNum(z[t] || 0))
        const weCol = we.values_by_zone.map(z => safeNum(z[t] || 0))
        wdAvg[t] = wdCol.reduce((s, v) => s + v, 0) / nZones
        weAvg[t] = weCol.reduce((s, v) => s + v, 0) / nZones
        wdStd[t] = Math.sqrt(wdCol.reduce((s, v) => s + (v - wdAvg[t]) ** 2, 0) / Math.max(1, nZones - 1))
        weStd[t] = Math.sqrt(weCol.reduce((s, v) => s + (v - weAvg[t]) ** 2, 0) / Math.max(1, nZones - 1))
      }
      pushBand(wdAvg, wdAvg.map((v, t) => v + wdStd[t]), wdAvg.map((v, t) => v - wdStd[t]), '#06C167', '工作日')
      pushBand(weAvg, weAvg.map((v, t) => v + weStd[t]), weAvg.map((v, t) => v - weStd[t]), '#FFB224', '周末')
      series.push({ name: '工作日 均值', type: 'line', data: wdAvg.map(safeNum), smooth: true, lineStyle: { width: 2.5, color: '#06C167' }, itemStyle: { color: '#06C167' }, showSymbol: false })
      series.push({ name: '周末 均值', type: 'line', data: weAvg.map(safeNum), smooth: true, lineStyle: { width: 2.5, color: '#FFB224' }, itemStyle: { color: '#FFB224' }, showSymbol: false })
    }
    typChart.setOption({
      grid: { left: 50, right: 20, top: 40, bottom: 40 },
      tooltip: { trigger: 'axis', axisPointer: { type: 'cross' } },
      legend: { show: true, top: 0, textStyle: { color: '#8B8B8B', fontSize: 11 }, data: series.map(s => s.name) },
      xAxis: { type: 'category', data: times, axisLabel: { interval: Math.floor(times.length / 8), color: '#8B8B8B' } },
      yAxis: { type: 'value', name: '车辆数/站', axisLabel: { color: '#8B8B8B' }, splitLine: { lineStyle: { color: 'rgba(255,255,255,0.06)' } } },
      series,
      animation: false,
    }, true)
    return true
  } catch (e) {
    console.warn('[renderTypChart]', e)
    return false
  }
}

// ===================== 工具 =====================
function fmtNum(v, d = 3) {
  if (v == null || Number.isNaN(v)) return '--'
  return Number(v).toFixed(d)
}
function resizeAll() {
  try { tlChart?.resize() } catch (e) { console.warn('[resize tlChart]', e) }
  try { odChart?.resize() } catch (e) { console.warn('[resize odChart]', e) }
  try { moranChart?.resize() } catch (e) { console.warn('[resize moranChart]', e) }
  try { typChart?.resize() } catch (e) { console.warn('[resize typChart]', e) }
  updateMarker()  // 容器尺寸变化后 convertToPixel 现算，保证竖线仍对齐绘图区
}

let resizeHandler = null
onMounted(async () => {
  try {
    const raw = await fetchZones()
    // /api/zones 返回 GeoJSON FeatureCollection，展平为 {zone_id, name}
    zones.value = (raw?.features || []).map(f => ({
      zone_id: f.properties?.zone_id,
      name: f.properties?.name || f.properties?.zone_id,
    }))
  } catch (e) { console.warn('[zones]', e) }
  loadTimeline()
  resizeHandler = () => resizeAll()
  window.addEventListener?.('resize', resizeHandler)
  window.addEventListener?.('keydown', (e) => { if (e.key === 'Escape' && chartFullscreen.value) toggleFullscreen() })
})
onBeforeUnmount(() => {
  if (timer) clearInterval(timer)
  tlChart?.dispose(); tlChart = null
  odChart?.dispose(); odChart = null
  moranChart?.dispose(); moranChart = null
  typChart?.dispose(); typChart = null
  if (resizeHandler) window.removeEventListener?.('resize', resizeHandler)
  document.body.style.overflow = ''
})
</script>

<style scoped>
* { box-sizing: border-box; }
.spatial {
  height: 100%;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
  color: #FFFFFF;
  font-family: -apple-system, 'Segoe UI', "PingFang SC", "Microsoft YaHei", sans-serif;
}

/* LAYER TABS */
.layerTabs { display: flex; gap: 4px; flex-shrink: 0; }
.layerTab {
  padding: 7px 14px;
  border: 1px solid #262626;
  background: #141414;
  color: #8B8B8B;
  border-radius: 8px;
  cursor: pointer;
  font-size: 13px;
  font-weight: 600;
  font-family: inherit;
  transition: all 0.12s ease;
}
.layerTab:hover { color: #FFFFFF; background: #1A1A1A; }
.layerTab.active { background: #06C167; border-color: #06C167; color: #000000; }

/* BODY */
.body {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
/* 上半部分：左控制栏 + 地图等高对齐 */
.topRow {
  display: grid;
  grid-template-columns: 290px 1fr;
  gap: 4px;
  flex: 1;
  min-height: 0;
}

/* RAIL */
.rail {
  overflow: auto;
  display: flex;
  flex-direction: column;
  gap: 4px;
  overscroll-behavior: contain;
  min-width: 0;
}

/* CARD */
.card {
  background: #141414;
  border: 1px solid #222222;
  border-radius: 10px;
  padding: 12px;
  display: flex;
  flex-direction: column;
  flex-shrink: 0;
}
.cardTitle { font-weight: 700; margin-bottom: 8px; color: #FFFFFF; font-size: 13px; }
.mapCard { min-height: 0; padding: 4px; }
.mapCard :deep(.mapWrap) { height: 100%; min-height: 280px; border-radius: 8px; overflow: hidden; }
.chartCard { height: 280px; flex-shrink: 0; min-height: 0; position: relative; overflow: hidden; }
.chartCard.fullscreen {
  position: fixed !important;
  inset: 0 !important;
  z-index: 9999 !important;
  height: auto !important;
  width: auto !important;
  border-radius: 0 !important;
  padding: 20px !important;
  /* 不用 100vw/100vh，避免滚动条宽度导致左右两侧被裁剪；inset:0 + height:auto 已撑满视口 */
}
.chartHeadBtns { margin-left: auto; display: flex; gap: 6px; align-items: center; }
.fsBtn { white-space: nowrap; }
.chartHead { display: flex; align-items: center; gap: 8px; flex-shrink: 0; }
.chartTitle { font-weight: 700; font-size: 12px; color: #8B8B8B; }
.toggleZones { margin-left: auto; padding: 3px 8px; font-size: 11px; border: 1px solid #333; }
.chart { flex: 1; min-height: 0; width: 100%; }

/* 方案A：时间回放当前时刻覆盖竖线（纯 DOM 定位，不触发图表重绘） */
.tlWrap { position: relative; flex: 1; min-height: 0; }
.tlWrap .chart { position: absolute; inset: 0; width: 100%; height: 100%; flex: none; }
.tlMarker {
  position: absolute; top: 0; bottom: 0; width: 1.5px;
  background: rgba(6, 193, 103, 0.85);
  pointer-events: none; z-index: 2;
}
.tlMarkerLabel {
  position: absolute; top: 0; left: 4px;
  background: #06C167; color: #000000;
  font-size: 10px; font-weight: 700; padding: 2px 6px;
  border-radius: 0 0 6px 6px; white-space: nowrap;
  font-variant-numeric: tabular-nums;
}
.empty {
  position: absolute; inset: 0;
  display: flex; align-items: center; justify-content: center; text-align: center;
  color: #8B8B8B; font-size: 13px; padding: 10px;
}

/* FORM */
.rowGrid { display: grid; grid-template-columns: 1fr 1fr; gap: 6px 8px; margin-bottom: 10px; }
.rowGrid label { display: block; font-size: 11px; color: #8B8B8B; margin-bottom: 2px; }
.sel {
  background: #1A1A1A; border: 1px solid #333333; color: #FFFFFF;
  padding: 6px 8px; border-radius: 8px; font-size: 12px; width: 100%; font-family: inherit;
}
.sel option { background: #1A1A1A; color: #FFFFFF; }
.sel.sm { width: auto; padding: 5px 8px; font-size: 11px; }

/* BUTTON */
.btn {
  border: 1px solid #333333;
  background: #1A1A1A;
  color: #FFFFFF;
  border-radius: 8px;
  padding: 8px 12px;
  cursor: pointer;
  font-size: 13px;
  font-family: inherit;
}
.btn:disabled { opacity: 0.4; cursor: not-allowed; }
.btn.sm { padding: 6px 10px; font-size: 12px; }
.btn.primary { background: #1A1A1A; border: 1px solid #444444; color: #FFFFFF; }
.btn.full { width: 100%; }
.dataNote { margin-top: 8px; font-size: 10px; color: #666666; line-height: 1.4; }
.errText {
  margin-top: 8px; font-size: 12px; color: #F04438;
  background: rgba(240, 68, 56, 0.08); border: 1px solid rgba(240, 68, 56, 0.3);
  border-radius: 8px; padding: 8px; line-height: 1.5;
}

/* STAT3 */
.stat3 { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 4px; margin-top: 8px; }
.s3Box {
  padding: 8px 4px; text-align: center; border-radius: 8px;
  border: 1px solid #222222; background: #1A1A1A;
}
.s3Box .v { display: block; font-size: 18px; font-weight: 900; line-height: 1; }
.s3Box .l { display: block; font-size: 10px; color: #8B8B8B; margin-top: 2px; }
.s3Box.shortage .v { color: #F04438; }
.s3Box.healthy .v { color: #8B8B8B; }
.s3Box.surplus .v { color: #06C167; }

/* FRAME */
.frameStats { margin-top: 10px; }
.frameLabel { display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px; }
.tLabel { font-size: 13px; font-weight: 700; color: #FFFFFF; font-variant-numeric: tabular-nums; }
.tLabelDim { font-size: 11px; color: #8B8B8B; font-variant-numeric: tabular-nums; }

/* SLIDER */
.sliderRow { display: grid; grid-template-columns: 52px 1fr 52px; align-items: center; gap: 8px; }
.slider {
  -webkit-appearance: none; appearance: none; height: 3px; border-radius: 999px;
  background: #333333; outline: none;
}
.slider::-webkit-slider-thumb {
  -webkit-appearance: none; appearance: none;
  width: 14px; height: 14px; border-radius: 50%; background: #FFFFFF; border: 2px solid #06C167; cursor: pointer;
}
.slider::-moz-range-thumb {
  width: 14px; height: 14px; border-radius: 50%; background: #FFFFFF; border: 2px solid #06C167; cursor: pointer;
}
.ctlRow { display: flex; align-items: center; gap: 4px; margin-top: 10px; }
.ctlRow .spacer { flex: 1; }

/* OD META / RANK */
.odMeta { margin-top: 10px; display: flex; flex-direction: column; gap: 4px; font-size: 12px; }
.rowFlex { display: flex; justify-content: space-between; }
.good { color: #06C167; }
.bad { color: #F04438; }
.rankTitle { font-weight: 700; font-size: 11px; color: #8B8B8B; margin-bottom: 4px; }
.rankList { display: flex; flex-direction: column; gap: 2px; }
.rankRow { display: grid; grid-template-columns: 20px 1fr auto; align-items: center; gap: 4px; font-size: 12px; }
.rkIdx {
  width: 18px; height: 18px; border-radius: 50%;
  background: #1A1A1A; border: 1px solid #333333;
  display: inline-flex; align-items: center; justify-content: center;
  font-weight: 700; font-size: 10px; color: #FFFFFF;
}
.rkName { color: #FFFFFF; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.rkNet { font-weight: 700; font-variant-numeric: tabular-nums; }

/* MORAN */
.moranBox { display: flex; flex-direction: column; gap: 8px; margin-top: 10px; }
.gMoran {
  border: 1px solid #222222; border-radius: 8px; background: #1A1A1A; padding: 8px;
}
.gLabel { font-size: 11px; color: #8B8B8B; }
.gVal { font-size: 22px; font-weight: 900; color: #FFFFFF; margin-top: 2px; }
.gSub { font-size: 11px; color: #8B8B8B; margin-top: 2px; }
.gInterp { margin-top: 4px; font-size: 12px; font-weight: 600; color: #FFFFFF; }
.clusterCounts { display: grid; grid-template-columns: repeat(5, 1fr); gap: 4px; }
.cc { border-radius: 8px; padding: 6px 4px; text-align: center; border: 1px solid #222222; background: #1A1A1A; }
.cc b { display: block; font-size: 16px; font-weight: 900; }
.cc span { font-size: 10px; color: #8B8B8B; }
.cc.hh b { color: #F04438; }
.cc.ll b { color: #06C167; }
.cc.hl b { color: #FFB224; }
.cc.lh b { color: #3B82F6; }
.cc.ns b { color: #8B8B8B; }

/* TYPICAL */
.typMeta { margin-top: 10px; display: flex; flex-direction: column; gap: 4px; font-size: 12px; }
.typHighlights {
  margin-top: 6px; padding: 8px; border-radius: 8px;
  background: #1A1A1A; border: 1px solid #222222;
  display: flex; flex-direction: column; gap: 4px; font-size: 12px; line-height: 1.5;
}
</style>
