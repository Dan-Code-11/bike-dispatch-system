<template>
  <div class="page">
    <!-- TOPBAR -->
    <div class="topbar">
      <div class="brand">BikeDispatch · 调度大屏</div>
      <div class="topbarRight">
        <span class="topbarTime">{{ stats?.time || '--:--' }}</span>
        <span class="topbarSep">|</span>
        <span class="topbarVehicles">{{ stats?.total_bikes ?? '--' }} 辆</span>
        <span class="wsDot" :class="{ ok: wsConnected }" :title="wsConnected ? 'WS 已连接' : 'WS 未连接'"></span>
        <button class="btn" @click="backHome">返回</button>
      </div>
    </div>

    <!-- LEFT CONTROLS + CENTER MAP -->
    <div class="shell">
      <!-- LEFT RAIL -->
      <aside class="left">
        <div class="leftScroll">
          <!-- 调度大屏只保留调度图层，无需图层切换 Tab -->

          <!-- ========== STATUS LAYER ========== -->
          <template v-if="activeLayer === 'status'">
            <div class="card">
              <div class="cardTitle">状态 / 调度</div>
              <div class="timePick">
                <label>时段</label>
                <select v-model="pickTime" class="sel" @change="onPickTimeChange">
                  <option v-for="t in presetTimes" :key="t.value" :value="t.value">{{ t.label }}</option>
                </select>
              </div>
              <div class="predInfo" v-if="prediction">
                <div class="predRow">预测时刻: {{ prediction.time }}</div>
                <div class="predRow">锚点: {{ keyHorizonLabels.join(' · ') }}</div>
              </div>
              <div class="btnGroup">
                <button class="btn primary" :disabled="predicting" @click="runPredict">
                  {{ predicting ? '预测中...' : '预测' }}
                </button>
                <button class="btn go" :disabled="dispatching || predicting || !prediction" @click="runDispatchWithPredict">
                  {{ dispatching ? '调度中...' : '一键调度' }}
                </button>
              </div>
              <div class="dispatchInfo" v-if="dispatchResult">
                {{ dispatchResult.plans.length }} 条方案 · {{ dispatchTotalQty }} 辆
                <span v-if="dispatchInfoExtra" class="extra"> · {{ dispatchInfoExtra }}</span>
              </div>
              <div class="emptyHint" v-if="dispatchResult && !dispatchResult.plans.length">
                供需平衡，暂无调度配对
              </div>
              <div class="error" v-if="errorMsg">{{ errorMsg }}</div>
            </div>

            <!-- 预测时域 + 态势 -->
            <div class="card">
              <div class="cardTitle">预测时域</div>
              <div class="horizonRow">
                <button
                  v-for="h in ['1h','2h','3h']"
                  :key="h"
                  class="horizonTab"
                  :class="{ active: activeHorizon === h }"
                  @click="selectHorizon(h)"
                >{{ h }}</button>
              </div>
              <div class="stat3">
                <div class="s3Box shortage"><span class="v">{{ horizonSummary.shortage }}</span><span class="l">短缺</span></div>
                <div class="s3Box healthy"><span class="v">{{ horizonSummary.healthy }}</span><span class="l">健康</span></div>
                <div class="s3Box surplus"><span class="v">{{ horizonSummary.surplus }}</span><span class="l">盈余</span></div>
              </div>
            </div>

            <!-- 调度方案 -->
            <div class="card" v-if="dispatchPlansData.length">
              <div class="cardTitle">调度方案 ({{ dispatchPlansData.length }})</div>
              <div class="plans">
                <div v-for="(p, i) in dispatchPlansData.slice(0, 9)" :key="i" class="planRow">
                  <span class="planFrom">{{ shortName(p.from_zone) }}</span>
                  <span class="planArrow">→</span>
                  <span class="planTo">{{ shortName(p.to_zone) }}</span>
                  <span class="planQty">{{ p.quantity }}辆</span>
                </div>
              </div>
              <div class="planHint">点击地图站点可只看该站调度</div>
            </div>
          </template>

          <!-- ========== TIMELINE LAYER ========== -->
          <template v-else-if="activeLayer === 'timeline'">
            <div class="card">
              <div class="cardTitle">时间回放</div>
              <div class="rowGrid">
                <div>
                  <label>开始时间</label>
                  <select v-model="tlStart" class="sel">
                    <option value="00:00">00:00 午夜</option>
                    <option value="06:00">06:00 晨间</option>
                    <option value="07:30">07:30 早高峰起点</option>
                    <option value="12:00">12:00 午间</option>
                    <option value="17:00">17:00 晚高峰起点</option>
                  </select>
                </div>
                <div>
                  <label>展示模式</label>
                  <select v-model="tlMode" class="sel">
                    <option value="need">Need（短缺度）</option>
                    <option value="ratio">容量占比 (%)</option>
                    <option value="vehicle">车辆数</option>
                  </select>
                </div>
                <div>
                  <label>粒度（分钟）</label>
                  <select v-model.number="tlInterval" class="sel">
                    <option :value="15">15 分钟</option>
                    <option :value="10">10 分钟</option>
                    <option :value="30">30 分钟</option>
                  </select>
                </div>
                <div>
                  <label>样本日</label>
                  <select v-model.number="tlDay" class="sel">
                    <option :value="2">典型工作日</option>
                    <option :value="3">典型周末</option>
                  </select>
                </div>
              </div>
              <button class="btn primary full" :disabled="loadingTimeline" @click="loadTimeline">
                {{ loadingTimeline ? '加载中...' : '加载时间序列' }}
              </button>
              <div class="error" v-if="errorMsg">{{ errorMsg }}</div>
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
                <select v-model.number="speedMs" class="sel sm">
                  <option :value="1200">0.8x</option>
                  <option :value="600">1.6x</option>
                  <option :value="300">3.2x</option>
                  <option :value="120">8x</option>
                </select>
              </div>
            </div>
          </template>

          <!-- ========== OD LAYER ========== -->
          <template v-else-if="activeLayer === 'od'">
            <div class="card">
              <div class="cardTitle">OD 潮汐流线</div>
              <div class="rowGrid">
                <div>
                  <label>发车时段</label>
                  <select v-model="odTime" class="sel">
                    <option value="07:30">早高峰 07:30</option>
                    <option value="08:30">早高峰 08:30</option>
                    <option value="12:00">午间 12:00</option>
                    <option value="17:00">晚高峰 17:00</option>
                    <option value="18:00">晚高峰 18:00</option>
                  </select>
                </div>
                <div>
                  <label>窗口（分钟）</label>
                  <select v-model.number="odWindow" class="sel">
                    <option :value="30">30 min</option>
                    <option :value="60">60 min</option>
                    <option :value="120">120 min</option>
                  </select>
                </div>
                <div>
                  <label>Top-K 站</label>
                  <select v-model.number="odTopK" class="sel">
                    <option :value="20">Top 20</option>
                    <option :value="40">Top 40</option>
                    <option :value="60">Top 60</option>
                  </select>
                </div>
                <div>
                  <label>样本日</label>
                  <select v-model.number="odDay" class="sel">
                    <option :value="2">工作日</option>
                    <option :value="5">周末</option>
                  </select>
                </div>
              </div>
              <button class="btn primary full" :disabled="loadingOD" @click="loadODFlows">
                {{ loadingOD ? '加载中...' : '计算 OD 流线' }}
              </button>
              <div class="error" v-if="errorMsg">{{ errorMsg }}</div>
              <div v-if="odData" class="odMeta">
                <div class="rowFlex"><span>来源:</span><b :class="odData.source === 'real_od' ? 'good' : ''">{{ odData.source }}</b></div>
                <div class="rowFlex"><span>总流量</span><b>{{ odData.total_flow_estimate }}</b></div>
                <div class="rowFlex"><span>Top-K 站</span><b>{{ odData.edges.length }}</b></div>
              </div>
            </div>
            <div class="card" v-if="odData">
              <div class="rankTitle">净流入 Top 站点</div>
              <div class="rankList">
                <div v-for="(s, i) in (odData.inflow_top || []).slice(0, 5)" :key="'in' + i" class="rankRow">
                  <span class="rkIdx">{{ i + 1 }}</span>
                  <span class="rkName" :title="s.name">{{ s.name }}</span>
                  <span class="rkNet good">+{{ s.net }}</span>
                </div>
              </div>
              <div class="rankTitle" style="margin-top:10px">净流出 Top 站点</div>
              <div class="rankList">
                <div v-for="(s, i) in (odData.outflow_top || []).slice(0, 5)" :key="'out' + i" class="rankRow">
                  <span class="rkIdx">{{ i + 1 }}</span>
                  <span class="rkName" :title="s.name">{{ s.name }}</span>
                  <span class="rkNet bad">{{ s.net }}</span>
                </div>
              </div>
            </div>
          </template>

          <!-- ========== LISA LAYER ========== -->
          <template v-else-if="activeLayer === 'lisa'">
            <div class="card">
              <div class="cardTitle">Moran / LISA</div>
              <div class="rowGrid">
                <div>
                  <label>时间</label>
                  <select v-model="lisaTime" class="sel">
                    <option value="07:30">早高峰 07:30</option>
                    <option value="08:30">早高峰 08:30</option>
                    <option value="12:00">午间 12:00</option>
                    <option value="17:00">晚高峰 17:00</option>
                    <option value="18:00">晚高峰 18:00</option>
                  </select>
                </div>
                <div>
                  <label>属性</label>
                  <select v-model="lisaAttr" class="sel">
                    <option value="need">Need（短缺度）</option>
                    <option value="ratio">容量占比</option>
                    <option value="vehicles">车辆数</option>
                  </select>
                </div>
                <div>
                  <label>权重</label>
                  <select v-model="lisaW" class="sel">
                    <option value="knn">KNN</option>
                    <option value="distance_band">Distance Band</option>
                  </select>
                </div>
                <div>
                  <label>{{ lisaW === 'knn' ? 'K 值' : '阈值(米)' }}</label>
                  <select v-model.number="lisaK" class="sel">
                    <template v-if="lisaW === 'knn'">
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
              <button class="btn primary full" :disabled="loadingLISA" @click="loadLISA">
                {{ loadingLISA ? '计算中...' : '计算 Moran\'s I + LISA' }}
              </button>
              <div class="error" v-if="errorMsg">{{ errorMsg }}</div>
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

          <!-- ========== TYPICAL DAY LAYER ========== -->
          <template v-else-if="activeLayer === 'typical'">
            <div class="card">
              <div class="cardTitle">典型日对比</div>
              <div class="rowGrid">
                <div>
                  <label>聚合粒度</label>
                  <select v-model.number="typInterval" class="sel">
                    <option :value="15">15 min</option>
                    <option :value="30">30 min</option>
                    <option :value="60">60 min</option>
                  </select>
                </div>
                <div>
                  <label>展示对象</label>
                  <select v-model="typSeries" class="sel">
                    <option value="avg_vs_avg">工作日 vs 周末</option>
                    <option value="top5_stations">Top 5 高频站</option>
                    <option value="all_zone_avg">所有站（均值±σ）</option>
                  </select>
                </div>
              </div>
              <button class="btn primary full" :disabled="loadingTypical" @click="loadTypicalDay">
                {{ loadingTypical ? '加载中...' : '计算典型日曲线' }}
              </button>
              <div class="error" v-if="errorMsg">{{ errorMsg }}</div>
              <div v-if="typData" class="typMeta">
                <div class="rowFlex"><span>样本:</span><b>工作日 {{ typData.n_weekday }} · 周末 {{ typData.n_weekend }}</b></div>
                <div class="rowFlex"><span>粒度:</span><b>{{ typData.interval_minutes }} min</b></div>
                <div class="typHighlights">
                  <div><b>工作日峰值</b> {{ typSummary.wd_peak_time }} · {{ typSummary.wd_peak_value.toFixed(1) }}</div>
                  <div><b>周末峰值</b> {{ typSummary.we_peak_time }} · {{ typSummary.we_peak_value.toFixed(1) }}</div>
                  <div><b>Δ偏移</b> {{ typSummary.peak_shift_min }} min · 潮汐 {{ typSummary.tidal_ratio.toFixed(2) }}x</div>
                </div>
              </div>
            </div>
          </template>
        </div>
      </aside>

      <!-- CENTER: MAP + DRAWER -->
      <main class="center">
        <!-- MAP CARD -->
        <div class="card mapCard">
          <MapView
            :zones="zonesForMap"
            :zonesVersion="zonesVersion"
            :baselineByZoneId="baselineByZoneId"
            :predictionByZoneId="horizonNeedByZone"
            :selectedZoneId="selectedZoneId"
            :dispatchPlans="dispatchPlansData"
            :activeLayer="activeLayer"
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

        <!-- 站点详情浮层 -->
        <aside v-if="selectedZoneId" class="detailDrawer">
          <div class="drawerHead">
            <div class="drawerTitleWrap">
              <span class="drawerTitle">{{ selectedZoneName || selectedZoneId }}</span>
              <div v-if="selectedZoneName" class="drawerSubId">{{ selectedZoneId }}</div>
            </div>
            <button class="drawerClose" @click="closeRightPanel">✕</button>
          </div>
          <div class="drawerBody">
            <div v-if="selectedZoneStory?.label" class="rpStatus">
              <span class="rpBadge" :class="selectedZoneStory.status || ''">{{ selectedZoneStory.label }}</span>
            </div>
            <div class="rpRow"><span class="rpLabel">当前车辆</span><span class="rpValue">{{ selectedZoneStory?.current ?? selectedZoneDetail.currentVehicles ?? '--' }}</span></div>
            <div class="rpRow"><span class="rpLabel">容量</span><span class="rpValue">{{ selectedZoneStory?.capacity ?? selectedZoneDetail.capacity ?? '--' }}</span></div>
            <template v-if="selectedZoneStory?.anchors?.length">
              <div class="rpSection">需求预测</div>
              <div class="rpAnchors">
                <div class="rpAnchorHead">
                  <span class="c1">锚点</span><span class="c2">车辆</span><span class="c3">Δvs现在</span><span class="c4">调度量</span>
                </div>
                <div v-for="(a, i) in selectedZoneStory.anchors" :key="a.horizon || a.label || i" class="rpAnchorRow">
                  <span class="c1">{{ a.label }}（{{ a.time }}）</span>
                  <span class="c2">{{ Math.round(a.vehicles) }}</span>
                  <span class="c3">{{ a.delta_vs_now != null ? (a.delta_vs_now >= 0 ? '+' : '') + Math.round(a.delta_vs_now) : '-' }}</span>
                  <span class="c4" :class="needClass(a.need)">{{ needText(a.need) }}</span>
                </div>
              </div>
              <div v-if="selectedZoneStory.worst?.label" class="rpWorst">
                最差锚点 {{ selectedZoneStory.worst.label }}（{{ selectedZoneStory.worst.time }}）:
                <b :class="needClass(selectedZoneStory.worst.need)">{{ needText(selectedZoneStory.worst.need) }}</b>
              </div>
            </template>
            <template v-if="selectedZoneStory?.advice">
              <div class="rpSection">调度建议</div>
              <div class="rpAdvice">{{ selectedZoneStory.advice }}</div>
            </template>
            <div v-if="selectedZoneDispatchPlans.length" class="rpSection">该站调度 ({{ selectedZoneDispatchPlans.length }})</div>
            <div v-if="selectedZoneDispatchPlans.length" class="rpPlans">
              <div v-for="(p, i) in selectedZoneDispatchPlans.slice(0, 8)" :key="i" class="rpPlan">
                <span class="rpPlanFrom">{{ p.from_zone }}</span>
                <span class="rpPlanArrow">→</span>
                <span class="rpPlanTo">{{ p.to_zone }}</span>
                <span class="rpPlanQty">{{ p.quantity }}辆</span>
              </div>
            </div>
            <div v-if="!selectedZoneStory?.anchors?.length && !selectedZoneStory?.advice" class="rpEmpty">运行「预测」后，点击站点查看调度详情</div>
          </div>
        </aside>
      </main>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import * as echarts from 'echarts'
import MapView from '../../components/MapView.vue'
import PredictionChart from '../../components/PredictionChart.vue'
import { fetchHistory, fetchTimeline, fetchODFlows, fetchSpatialStats, fetchTypicalDay, predictMulti3Hour, dispatchPlans } from '../../api/index'

const router = useRouter()
let ws = null

// 通用：WebSocket & 全局状态
const wsConnected = ref(false)
const stats = ref(null)
const selectedZoneId = ref(null)
const errorMsg = ref('')

// ====== Chart refs ======
const chartEl = ref(null)      // saturation chart
const tlChartEl = ref(null)    // timeline chart
const moranChartEl = ref(null) // moran scatter
const odChartEl = ref(null)    // od bar chart
const typChartEl = ref(null)   // typical day chart
let chart = null, tlChart = null, moranChart = null, odChart = null, typChart = null

// ====== Layer Tabs（调度大屏只保留调度功能；空间 4 图层已集成到空间可视化页 /ops/replay）======
const layerTabs = [
  { value: 'status', label: '📌 状态/调度' },
]
const activeLayer = ref('status')
// 在切换到其他echarts tab 前先 dispose 当前 tab 的旧实例（v-if 重新挂载后保证拿到全新干净 DOM）
function disposeChartByKey(key) {
  try {
    if (key === 'saturation' && chart) { chart.dispose(); chart = null }
    else if (key === 'tl' && tlChart) { tlChart.dispose(); tlChart = null }
    else if (key === 'od' && odChart) { odChart.dispose(); odChart = null }
    else if (key === 'moran' && moranChart) { moranChart.dispose(); moranChart = null }
    else if (key === 'typ' && typChart) { typChart.dispose(); typChart = null }
  } catch (e) { console.warn('[disposeChart]', e) }
}

// 安全获取/初始化 echarts：DOM 必须有真实尺寸才初始化；异常吞掉不抛到外层
function safeInitChart(el, existing) {
  if (!el) return null
  try {
    const rect = el.getBoundingClientRect?.() || { width: el.clientWidth, height: el.clientHeight }
    if ((rect.height || 0) < 20 || (rect.width || 0) < 20) return null
    if (existing) return existing
    return echarts.init(el)
  } catch (e) { console.warn('[safeInitChart]', e); return null }
}

// 等待下一次浏览器布局，确保容器有实际宽高（比 nextTick 更可靠，避免 Edge 下 echarts 尺寸为 0 死循环）
// 加超时保护：超过 maxWait 次后彻底放弃，避免 requestAnimationFrame 堆积导致事件循环阻塞
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

function selectLayer(l) {
  activeLayer.value = l
  // 切换图层时同步切底部图表，并先销毁旧 tab 的 echarts 实例
  const nextChartKey = (l === 'status') ? 'pred'
    : l === 'timeline' ? 'tl'
    : l === 'od' ? 'od'
    : l === 'lisa' ? 'moran'
    : l === 'typical' ? 'typ' : ''
  disposeChartByKey(activeChart.value)
  activeChart.value = nextChartKey
  nextTick(() => {
    if (l === 'timeline') {
      if (!tlData.value) loadTimeline()
      else waitLayout(() => { renderTlChart(); return !!tlChart })
    } else if (l === 'od') {
      if (!odData.value) loadODFlows()
      else waitLayout(() => { renderOdChart(); return !!odChart })
    } else if (l === 'lisa') {
      if (!lisaData.value) loadLISA()
      else waitLayout(() => { renderMoranChart(); return !!moranChart })
    } else if (l === 'typical') {
      if (!typData.value) loadTypicalDay()
      else waitLayout(() => { renderTypChart(); return !!typChart })
    } else if (l === 'status') {
      waitLayout(() => { renderSaturation(); return true })
    }
  })
}

// ====== Bottom Chart Tab Switcher（只保留调度相关图表；空间图表在空间可视化页）======
const chartTabs = [
  { value: 'pred', label: '预测曲线' },
  { value: 'saturation', label: '饱和度' },
]
const activeChart = ref('pred')
function selectChart(v) {
  disposeChartByKey(activeChart.value)
  activeChart.value = v
  const doRender = () => {
    if (v === 'saturation') return renderSaturation(), !!chart
    if (v === 'tl') return renderTlChart(), !!tlChart
    if (v === 'od') return renderOdChart(), !!odChart
    if (v === 'moran') return renderMoranChart(), !!moranChart
    if (v === 'typ') return renderTypChart(), !!typChart
    return true
  }
  if (v === 'pred') return
  waitLayout(doRender)
}
const noChartHint = computed(() => {
  if (activeChart.value === 'pred' && !prediction.value) return '运行「预测」后，点击站点查看曲线'
  if (activeChart.value === 'saturation' && !stats.value) return '等待实时数据接入...'
  if (activeChart.value === 'tl' && !tlData.value) return '点击「加载时间序列」查看 24h 潮汐动画'
  if (activeChart.value === 'od' && !odData.value) return '点击「计算 OD 流线」查看站点流向'
  if (activeChart.value === 'moran' && !lisaData.value) return '点击「计算 Moran\'s I + LISA」查看空间自相关'
  if (activeChart.value === 'typ' && !typData.value) return '点击「计算典型日曲线」查看工作日 vs 周末'
  return ''
})

// ====== 时域 ======
const activeHorizon = ref('1h')
function selectHorizon(h) { activeHorizon.value = h }
function closeRightPanel() { selectedZoneId.value = null }

// horizonNeedByZone: extract need values for the active horizon from prediction
const horizonNeedByZone = computed(() => {
  if (!prediction.value?.zones) return predictionByZoneId.value
  const horizonKey = activeHorizon.value
  const map = {}
  for (const z of prediction.value.zones) {
    const anchor = (z.forecast_anchors || []).find((a) => a.horizon === horizonKey)
    const horizonNeed = anchor?.need
    map[z.zone_id] = { ...z, need: horizonNeed != null ? horizonNeed : z.need }
  }
  return map
})

// horizonSummary: shortage/surplus/healthy counts for active horizon
const horizonSummary = computed(() => {
  if (!horizonNeedByZone.value || !Object.keys(horizonNeedByZone.value).length) {
    return predSummary.value
  }
  const zones = Object.values(horizonNeedByZone.value)
  const shortage = zones.filter((z) => (z.need ?? 0) >= 3).length
  const surplus = zones.filter((z) => (z.need ?? 0) <= -3).length
  return { shortage, surplus, healthy: Math.max(0, zones.length - shortage - surplus) }
})

// selectedZoneDetail
const selectedZoneDetail = computed(() => {
  const zid = selectedZoneId.value
  if (!zid) return { currentVehicles: null, capacity: null, needs: {}, advice: '' }
  const predZone = prediction.value?.zones?.find((z) => z.zone_id === zid)
  const statsZone = stats.value?.zones?.find((z) => z.zone_id === zid)
  const needs = {}
  if (predZone?.forecast_anchors) {
    for (const a of predZone.forecast_anchors) {
      if (a.horizon) needs[a.horizon] = a.need
    }
  } else if (predZone) {
    needs['1h'] = predZone.need
  }
  let advice = ''
  if (predZone) {
    const n = predZone.need ?? 0
    if (n >= 3) advice = `短缺 ${n.toFixed(1)}，需从盈余站调度入`
    else if (n <= -3) advice = `盈余 ${Math.abs(n).toFixed(1)}，可向短缺站调度出`
    else advice = '供需平衡，无需调度'
  }
  return {
    currentVehicles: predZone?.current_count ?? statsZone?.vehicles ?? null,
    capacity: predZone?.capacity ?? statsZone?.capacity ?? null,
    needs,
    advice,
  }
})

function needClass(v) {
  if (v == null) return ''
  if (v >= 3) return 'shortage'
  if (v <= -3) return 'surplus'
  return 'healthy'
}

function needText(n) {
  if (n == null || Number.isNaN(n)) return '平衡'
  const v = Math.round(n)
  if (v > 0) return `+${v} 调入`
  if (v < 0) return `${v} 调出`
  return '平衡'
}

// 与地图同源的站点详情：锚点/最差锚点/建议（右侧面板唯一展示，地图不再弹卡片）
const selectedZoneStory = computed(() => {
  const zid = selectedZoneId.value
  if (!zid) return null
  const info = horizonNeedByZone.value?.[zid]
  if (!info) return null
  const anchors = info.forecast_anchors || []
  const worst = info.worst_horizon || {}
  const status = info.status
  const need = info.need
  let label = '--', advice = ''
  if (status === 'shortage') {
    label = '短缺（需调入）'
    advice = `最差锚点 ${worst.label || ''}（${worst.time || ''}）需调入 ${Math.round(Math.abs(need ?? 0))} 辆`
  } else if (status === 'surplus') {
    label = '盈余（可调出）'
    advice = `最差锚点 ${worst.label || ''}（${worst.time || ''}）可调出 ${Math.round(Math.abs(need ?? 0))} 辆`
  } else if (status === 'healthy') {
    label = '容量水位健康'
    advice = '未来3h内水位在健康区间，暂无调度需求'
  } else if (need != null && !Number.isNaN(need)) {
    label = need >= 3 ? '短缺（需调入）' : need <= -3 ? '盈余（可调出）' : '容量水位健康'
    advice = `未来需调度 ${needText(need)}`
  }
  return {
    anchors, worst, need, status, label, advice,
    capacity: info.capacity ?? null,
    current: info.current_count ?? info.vehicles ?? null,
  }
})

const selectedZoneDispatchPlans = computed(() => {
  const zid = selectedZoneId.value
  if (!zid || !dispatchPlansData.value.length) return []
  return dispatchPlansData.value.filter((p) => p.from_zone === zid || p.to_zone === zid)
})

// ====== AI 预测 & 调度 ======
const prediction = ref(null)
const predictionByZoneId = ref({})
const dispatchPlansData = ref([])
const dispatchResult = ref(null)
const predicting = ref(false)
const dispatching = ref(false)
const pickTime = ref('12:00')
const presetTimes = [
  { value: '07:30', label: '早高峰 07:30' },
  { value: '08:30', label: '早高峰 08:30' },
  { value: '09:00', label: '上午 09:00' },
  { value: '12:00', label: '午间 12:00' },
  { value: '17:00', label: '晚高峰 17:00' },
  { value: '18:00', label: '晚高峰 18:00' },
]
const predSummary = ref({ shortage: 0, surplus: 0, healthy: 0 })
const keyHorizonLabels = computed(() => prediction.value?.key_horizon_labels || ['1h', '2h', '3h'])
function recomputeSummary() {
  if (!prediction.value?.zones) { predSummary.value = { shortage: 0, surplus: 0, healthy: 0 }; return }
  const shortage = prediction.value.zones.filter((z) => z.need >= 3).length
  const surplus = prediction.value.zones.filter((z) => z.need <= -3).length
  predSummary.value = { shortage, surplus, healthy: 30 - shortage - surplus }
}
const dispatchTotalQty = computed(() => (dispatchResult.value?.plans || []).reduce((s, p) => s + (p.quantity || 0), 0) || 0)
const dispatchInfoExtra = computed(() => {
  const plans = dispatchResult.value?.plans || []
  if (!plans.length) return ''
  const o = plans.filter((p) => p.route_source === 'osrm').length
  const s = plans.filter((p) => p.route_source === 'straight').length
  return `OSRM ${o} · 直线 ${s}`
})

// ====== Timeline ======
const tlStart = ref('00:00')
const tlMode = ref('need')
const tlInterval = ref(15)
const tlDay = ref(2)
const tlData = ref(null)
const loadingTimeline = ref(false)
const tlFrame = ref(0)
const playing = ref(false)
const speedMs = ref(600)
let playTimer = null

async function loadTimeline() {
  loadingTimeline.value = true; errorMsg.value = ''
  try {
    const steps = (24 * 60) / tlInterval.value
    const d = await fetchTimeline({
      time: tlStart.value,
      steps: Math.min(288, Math.floor(steps)),
      interval: tlInterval.value,
      day_index: tlDay.value,
      mode: tlMode.value,
    })
    tlData.value = d
    tlFrame.value = 0
    waitLayout(() => renderTlChart(), 10)
  } catch (e) {
    console.error(e); errorMsg.value = e?.message || String(e)
  } finally {
    loadingTimeline.value = false
  }
}
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
const nShortage = computed(() => Object.values(currentFrameValues.value).filter((v) => (v ?? 0) >= 3).length)
const nSurplus = computed(() => Object.values(currentFrameValues.value).filter((v) => (v ?? 0) <= -3).length)
const nHealthy = computed(() => Math.max(0, 30 - nShortage.value - nSurplus.value))

function prevFrame() { tlFrame.value = Math.max(0, tlFrame.value - 1) }
function nextFrame() { tlFrame.value = Math.min(times.value.length - 1, tlFrame.value + 1) }
function togglePlay() {
  if (playing.value) {
    playing.value = false
    if (playTimer) { clearInterval(playTimer); playTimer = null }
  } else {
    if (!times.value.length) return
    playing.value = true
    playTimer = setInterval(() => {
      tlFrame.value += 1
      if (tlFrame.value >= times.value.length - 1) tlFrame.value = 0
    }, speedMs.value)
  }
}
watch(speedMs, () => {
  if (playing.value && playTimer) {
    clearInterval(playTimer)
    playTimer = setInterval(() => {
      tlFrame.value += 1
      if (tlFrame.value >= times.value.length - 1) tlFrame.value = 0
    }, speedMs.value)
  }
})
watch(tlFrame, () => { if (activeChart.value === 'tl') renderTlChart() })

// ====== OD ======
const odTime = ref('08:30')
const odWindow = ref(60)
const odTopK = ref(40)
const odDay = ref(2)
const odData = ref(null)
const loadingOD = ref(false)
const odEdges = computed(() => odData.value?.edges || [])

async function loadODFlows() {
  loadingOD.value = true; errorMsg.value = ''
  try {
    const d = await fetchODFlows({
      time: odTime.value,
      window_minutes: odWindow.value,
      top_k: odTopK.value,
      day_index: odDay.value,
    })
    odData.value = d
    waitLayout(() => renderOdChart(), 10)
  } catch (e) {
    console.error(e); errorMsg.value = e?.message || String(e)
  } finally {
    loadingOD.value = false
  }
}

// ====== LISA ======
const lisaTime = ref('08:30')
const lisaAttr = ref('need')
const lisaW = ref('knn')
const lisaK = ref(5)
const lisaData = ref(null)
const loadingLISA = ref(false)
const lisaLocal = computed(() => lisaData.value?.local || [])

async function loadLISA() {
  loadingLISA.value = true; errorMsg.value = ''
  try {
    const kw = lisaW.value === 'knn' ? { k: lisaK.value } : { band_m: lisaK.value }
    const d = await fetchSpatialStats({
      time: lisaTime.value,
      attr: lisaAttr.value,
      weight: lisaW.value,
      ...kw,
    })
    lisaData.value = d
    waitLayout(() => renderMoranChart(), 10)
  } catch (e) {
    console.error(e); errorMsg.value = e?.message || String(e)
  } finally {
    loadingLISA.value = false
  }
}

// ====== Typical day ======
const typInterval = ref(30)
const typSeries = ref('avg_vs_avg')
const typData = ref(null)
const loadingTypical = ref(false)

const typSummary = computed(() => {
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
  loadingTypical.value = true; errorMsg.value = ''
  try {
    typData.value = await fetchTypicalDay({ interval_minutes: typInterval.value })
    waitLayout(() => renderTypChart(), 10)
  } catch (e) {
    console.error(e); errorMsg.value = e?.message || String(e)
  } finally {
    loadingTypical.value = false
  }
}
watch(typSeries, () => { if (typData.value && activeChart.value === 'typ') renderTypChart() })

// ====== Chart rendering ======
function ensureChart() {
  try {
    const c = safeInitChart(chartEl.value, chart)
    if (c) chart = c
  } catch (e) { console.warn('[ensureChart]', e) }
}

function renderSaturation() {
  try {
    if (!chartEl.value || !stats.value?.zones?.length) {
      try { chart?.clear?.() } catch {}
      return false
    }
    const inst = safeInitChart(chartEl.value, chart)
    if (!inst) return false
    chart = inst
    const zones = stats.value.zones
    const rows = zones.map((z) => {
      const cur = z.vehicles ?? 0
      const cap = z.capacity ?? 0
      const ratio = cap > 0 ? cur / cap : 0
      return { name: z.name || z.zone_id, cur, cap, ratio }
    }).sort((a, b) => a.ratio - b.ratio)
    const names = rows.map((r) => r.name)
    const colors = rows.map((r) => {
      if (r.ratio <= 0.2) return '#F04438'
      if (r.ratio >= 0.8) return '#06C167'
      return '#8B8B8B'
    })
    chart.setOption({
      grid: { left: 10, right: 16, top: 16, bottom: 30, containLabel: true },
      tooltip: {
        trigger: 'axis', axisPointer: { type: 'shadow' },
        formatter: (ps) => {
          const p = ps[0]
          const r = rows[p.dataIndex]
          if (!r) return ''
          return `<b>${r.name}</b><br/>车辆 ${r.cur} / 容量 ${r.cap}<br/>饱和度 ${(r.ratio * 100).toFixed(0)}%`
        },
      },
      xAxis: { type: 'category', data: names, axisLabel: { color: '#8B8B8B', fontSize: 10, interval: 0, rotate: 30 } },
      yAxis: {
        type: 'value', max: 1, axisLabel: { color: '#8B8B8B', formatter: (v) => `${Math.round(v * 100)}%` },
        splitLine: { lineStyle: { color: 'rgba(255,255,255,0.06)' } },
      },
      series: [{
        type: 'bar', data: rows.map((r, i) => ({ value: r.ratio, itemStyle: { color: colors[i] } })), barWidth: 14,
      }],
    }, true)
    return true
  } catch (e) {
    console.warn('[renderSaturation]', e)
    return false
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
    const meanByZone = zoneOrder.map((_, i) => avg(st.map((f) => f[i] || 0)))
    const sorted = meanByZone.map((_, i) => i).sort((a, b) => meanByZone[a] - meanByZone[b])
    const picked = new Set()
    for (let i = 0; i < Math.min(3, sorted.length); i++) picked.add(sorted[i])
    for (let i = 0; i < Math.min(3, sorted.length); i++) picked.add(sorted[sorted.length - 1 - i])
    let mid = Math.floor(sorted.length / 2) - 2
    while (picked.size < 10 && mid < sorted.length) picked.add(sorted[mid++])
    const series = []
    zoneOrder.forEach((name, i) => {
      if (picked.has(i)) {
        series.push({
          name, type: 'line', showSymbol: false, smooth: true,
          data: st.map((f) => (f[i] != null ? Number(f[i]).toFixed(2) - 0 : null)),
          lineStyle: { width: 1.6 },
        })
      }
    })
    const marker = currentFrameLabel.value
    tlChart.setOption({
      grid: { left: 40, right: 12, top: 20, bottom: 40 },
      tooltip: { trigger: 'axis', axisPointer: { type: 'cross' } },
      xAxis: { type: 'category', data: Z, axisLabel: { color: '#8B8B8B', interval: Math.floor(Z.length / 8) } },
      yAxis: { type: 'value', name: tlMode.value.toUpperCase(), axisLabel: { color: '#8B8B8B' }, splitLine: { lineStyle: { color: 'rgba(255,255,255,0.06)' } } },
      legend: { show: false },
      series,
    }, true)
    try {
      tlChart.setOption({
        series: [{
          name: '__marker__', type: 'line', data: [],
          markLine: {
            symbol: 'none', silent: true,
            data: [{ xAxis: marker, lineStyle: { color: '#06C167', width: 2, type: 'dashed' }, label: { formatter: marker, position: 'insideEndTop', fontWeight: 700 } }],
          },
        }],
      })
    } catch (e) { /* ignore */ }
    return true
  } catch (e) {
    console.warn('[renderTlChart]', e)
    return false
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
        formatter: (ps) => { const p = ps[0]; return p?.data ? `<b>${p.name}</b><br/>净流动 ${p.data.value}` : '' },
      },
      xAxis: { type: 'value', axisLabel: { color: '#8B8B8B' }, splitLine: { lineStyle: { color: 'rgba(255,255,255,0.06)' } } },
      yAxis: {
        type: 'category',
        data: inflow.map((s) => s.name).concat(outflow.map((s) => s.name)),
        axisLabel: { color: '#8B8B8B', width: 120, overflow: 'truncate', fontSize: 10 },
      },
      series: [{
        type: 'bar',
        data: inflow.map((s) => ({ value: s.net, itemStyle: { color: '#06C167' } }))
          .concat(outflow.map((s) => ({ value: s.net, itemStyle: { color: '#F04438' } }))),
        barWidth: 14,
        label: { show: true, position: 'right', fontSize: 10, color: '#FFFFFF', formatter: (p) => p.value > 0 ? `+${p.value}` : p.value },
      }],
      dataZoom: [{ type: 'inside', orient: 'vertical' }],
    }, true)
    return true
  } catch (e) {
    console.warn('[renderOdChart]', e)
    return false
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
    const safeNum = (v) => {
      const n = Number(v)
      return Number.isFinite(n) ? n : 0
    }
    const pts = lisaLocal.value.map((t) => ({
      value: [safeNum(t.z_x), safeNum(t.lag_z)],
      cluster: t.cluster, name: t.name,
    }))
    const scatter = pts.map((t) => ({ value: t.value, itemStyle: { color: lisaColor(t.cluster) }, name: t.name }))
    const I = safeNum(lisaData.value?.global?.I)
    const z = 3.2
    const regLine = [[-z, -z * I], [z, z * I]]
    moranChart.setOption({
      grid: { left: 50, right: 20, top: 30, bottom: 50 },
      tooltip: {
        formatter: (p) => p.seriesType === 'scatter'
          ? `<b>${p.data?.name || ''}</b><br/>Zi=${safeNum(p.data?.value?.[0]).toFixed(2)}<br/>WZi=${safeNum(p.data?.value?.[1]).toFixed(2)}`
          : `Moran 回归线（I=${I.toFixed(3)}）`,
      },
      xAxis: { type: 'value', name: 'Zi', min: -z, max: z, axisLabel: { color: '#8B8B8B' }, splitLine: { lineStyle: { type: 'dashed', color: 'rgba(255,255,255,0.08)' } } },
      yAxis: { type: 'value', name: 'WZi', min: -z, max: z, axisLabel: { color: '#8B8B8B' }, splitLine: { lineStyle: { type: 'dashed', color: 'rgba(255,255,255,0.08)' } } },
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

function renderTypChart() {
  try {
    if (!typChartEl.value || !typData.value) return false
    const inst = safeInitChart(typChartEl.value, typChart)
    if (!inst) return false
    typChart = inst
    const wd = typData.value.weekday
    const we = typData.value.weekend
    const tTimes = wd?.times || []
    const nZones = (wd?.values_by_zone || []).length
    if (!tTimes.length || !nZones) return false
    const mode = typSeries.value
    const safeNum = (v) => Number.isFinite(v) ? +Number(v).toFixed(2) : 0
    const series = []
    if (mode === 'avg_vs_avg') {
      const wdAvg = tTimes.map((_, t) => wd.values_by_zone.reduce((s, z) => s + safeNum(z[t] || 0), 0) / nZones)
      const weAvg = tTimes.map((_, t) => we.values_by_zone.reduce((s, z) => s + safeNum(z[t] || 0), 0) / nZones)
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
      const pushBand = (upper, lower, color, label) => {
        series.push({ name: `${label} · ±1σ`, type: 'line', data: upper.map(safeNum), lineStyle: { opacity: 0 }, stack: `conf_${label}`, symbol: 'none' })
        series.push({ name: `${label} · 下限`, type: 'line', data: lower.map(safeNum), lineStyle: { opacity: 0 }, stack: `conf_${label}`, symbol: 'none', areaStyle: { color: color + '55' } })
      }
      const n = tTimes.length
      const wdAvg = new Array(n).fill(0)
      const weAvg = new Array(n).fill(0)
      const wdStd = new Array(n).fill(0)
      const weStd = new Array(n).fill(0)
      for (let t = 0; t < n; t++) {
        const wdCol = wd.values_by_zone.map((z) => safeNum(z[t] || 0))
        const weCol = we.values_by_zone.map((z) => safeNum(z[t] || 0))
        wdAvg[t] = wdCol.reduce((s, v) => s + v, 0) / nZones
        weAvg[t] = weCol.reduce((s, v) => s + v, 0) / nZones
        wdStd[t] = Math.sqrt(wdCol.reduce((s, v) => s + (v - wdAvg[t]) ** 2, 0) / Math.max(1, nZones - 1))
        weStd[t] = Math.sqrt(weCol.reduce((s, v) => s + (v - weAvg[t]) ** 2, 0) / Math.max(1, nZones - 1))
      }
      pushBand(wdAvg.map((v, t) => v + wdStd[t]), wdAvg.map((v, t) => v - wdStd[t]), '#06C167', '工作日')
      pushBand(weAvg.map((v, t) => v + weStd[t]), weAvg.map((v, t) => v - weStd[t]), '#FFB224', '周末')
      series.push({ name: '工作日 均值', type: 'line', data: wdAvg.map(safeNum), smooth: true, lineStyle: { width: 2.5, color: '#06C167' }, itemStyle: { color: '#06C167' }, showSymbol: false })
      series.push({ name: '周末 均值', type: 'line', data: weAvg.map(safeNum), smooth: true, lineStyle: { width: 2.5, color: '#FFB224' }, itemStyle: { color: '#FFB224' }, showSymbol: false })
    }
    typChart.setOption({
      grid: { left: 50, right: 20, top: 40, bottom: 40 },
      tooltip: { trigger: 'axis', axisPointer: { type: 'cross' } },
      legend: { show: true, top: 0, textStyle: { color: '#8B8B8B', fontSize: 11 }, data: series.map((s) => s.name) },
      xAxis: { type: 'category', data: tTimes, axisLabel: { interval: Math.floor(tTimes.length / 8), color: '#8B8B8B' } },
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

// ====== 通用计算 ======
function fmt(v, d = 1) { if (v == null || Number.isNaN(v)) return '--'; return Number(v).toFixed(d) }
function fmtNum(v, d = 3) {
  if (v == null || Number.isNaN(v)) return '--'
  return Number(v).toFixed(d)
}
function shortName(zid) {
  if (!zid) return ''
  const z = stats.value?.zones?.find((x) => x.zone_id === zid)
  const name = z?.name || zid
  return name.length > 16 ? name.slice(0, 15) + '…' : name
}

// ====== WebSocket ======
function applyStats(s) {
  stats.value = s
  if (activeChart.value === 'saturation') renderSaturation()
}
function connectWS() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws'
  const url = new URL(location.href)
  const t = url.searchParams.get('t')
  const path = t ? `/api/ws/live/${encodeURIComponent(t)}` : '/api/ws/live'
  ws = new WebSocket(`${proto}://${location.host}${path}`)
  ws.onopen = () => (wsConnected.value = true)
  ws.onclose = () => (wsConnected.value = false)
  ws.onerror = () => (wsConnected.value = false)
  ws.onmessage = (ev) => { try { applyStats(JSON.parse(ev.data)) } catch (e) { /* ignore */ } }
}
function backHome() { router.push('/') }

// ====== AI 预测 / 调度 ======
async function runPredict() {
  predicting.value = true; errorMsg.value = ''
  try {
    const time = stats.value?.time || pickTime.value || new Date().toTimeString().slice(0, 5)
    const histRes = await fetchHistory(time, 24)
    const { history, zone_order } = histRes
    const predRes = await predictMulti3Hour({ time, history, zone_order })
    prediction.value = predRes
    const predMap = {}
    for (const z of predRes.zones) predMap[z.zone_id] = z
    predictionByZoneId.value = predMap
    dispatchPlansData.value = []
    dispatchResult.value = null
    recomputeSummary()
  } catch (e) { console.error(e); errorMsg.value = e?.message || String(e) }
  finally { predicting.value = false }
}
async function runDispatch() {
  if (!prediction.value) return
  dispatching.value = true; errorMsg.value = ''
  try {
    const predicted_need_by_zone = prediction.value.predicted_need_by_zone || {}
    const worst_minutes_by_zone = {}
    const wbz = prediction.value.worst_by_zone || {}
    for (const [zid, w] of Object.entries(wbz)) worst_minutes_by_zone[zid] = w?.horizon_minutes ?? null
    const dispatchRes = await dispatchPlans({ time: prediction.value.time, predicted_need_by_zone, worst_minutes_by_zone })
    dispatchResult.value = dispatchRes
    dispatchPlansData.value = dispatchRes.plans || []
  } catch (e) { console.error(e); errorMsg.value = e?.message || String(e) }
  finally { dispatching.value = false }
}
async function runDispatchWithPredict() {
  if (!prediction.value) { await runPredict(); if (!prediction.value) return }
  await runDispatch()
}

// ====== 切时段 ======
function onPickTimeChange() {
  const t = pickTime.value
  const proto = location.protocol === 'https:' ? 'wss' : 'ws'
  const wsNew = new WebSocket(`${proto}://${location.host}/api/ws/live/${encodeURIComponent(t)}`)
  wsNew.onopen = () => { if (ws) ws.close(); ws = wsNew; wsConnected.value = true }
  wsNew.onclose = () => { if (ws === wsNew) wsConnected.value = false }
  wsNew.onerror = () => { if (ws === wsNew) wsConnected.value = false }
  wsNew.onmessage = (ev) => { try { applyStats(JSON.parse(ev.data)) } catch (e) { /* ignore */ } }
  prediction.value = null
  predictionByZoneId.value = {}
  dispatchResult.value = null
  dispatchPlansData.value = []
  selectedZoneId.value = null
  recomputeSummary()
}

// ====== Map 联动 + PredictionChart 数据组装 ======
function onZoneSelected(zid) {
  // 点击同一站点再次点击 → 取消选择（恢复全部路线）
  selectedZoneId.value = selectedZoneId.value === zid ? null : zid
  // 选中站点后自动切到预测曲线图表（仅 status 层）
  if (selectedZoneId.value && activeLayer.value === 'status') activeChart.value = 'pred'
}
const selectedZoneName = computed(() => {
  if (!selectedZoneId.value) return ''
  const z = stats.value?.zones?.find((x) => x.zone_id === selectedZoneId.value)
  if (z?.name) return z.name
  const pz = prediction.value?.zones?.find((x) => x.zone_id === selectedZoneId.value)
  return pz?.name || selectedZoneId.value
})
const selectedCurrentVehicles = computed(() => {
  const z = prediction.value?.zones?.find((x) => x.zone_id === selectedZoneId.value)
  if (z?.current_count != null) return z.current_count
  const sz = stats.value?.zones?.find((x) => x.zone_id === selectedZoneId.value)
  return sz?.vehicles ?? null
})
const selectedCapacity = computed(() => {
  const z = prediction.value?.zones?.find((x) => x.zone_id === selectedZoneId.value)
  return z?.capacity ?? null
})
const selectedAnchors = computed(() => {
  const z = prediction.value?.zones?.find((x) => x.zone_id === selectedZoneId.value)
  return z?.forecast_anchors || []
})
const selectedWorstHorizon = computed(() => {
  const z = prediction.value?.zones?.find((x) => x.zone_id === selectedZoneId.value)
  if (!z) return null
  const wh = prediction.value?.worst_by_zone?.[z.zone_id]
  return z.worst_horizon || wh || null
})
const selectedSeries = computed(() => {
  if (!selectedZoneId.value) return null
  return prediction.value?.series_by_zone?.[selectedZoneId.value] || null
})
const selectedHistoryTimes = computed(() => selectedSeries.value?.history_times || [])
const selectedHistorySeries = computed(() => selectedSeries.value?.history_vehicles || [])
const selectedCurveTimes = computed(() => selectedSeries.value?.curve_times || [])
const selectedCurveLSTM = computed(() => selectedSeries.value?.curve_vehicles_lstm || [])
const selectedCurvePersistent = computed(() => selectedSeries.value?.curve_vehicles_persistent || [])

// ====== Map data ======
const zonesForMap = computed(() => stats.value?.zones || [])
const zonesVersion = computed(() => stats.value?.zones_version || 0)
const baselineByZoneId = computed(() => {
  const m = {}
  for (const z of stats.value?.zones || []) m[z.zone_id] = z.vehicles
  return m
})

// ====== 生命周期 ======
function resizeAll() {
  // 逐个 try/catch 包裹，避免 dispose/v-if 切换瞬间某实例异常导致后续全部跳过
  try { chart?.resize() } catch (e) { console.warn('[resize chart]', e) }
  try { tlChart?.resize() } catch (e) { console.warn('[resize tlChart]', e) }
  try { odChart?.resize() } catch (e) { console.warn('[resize odChart]', e) }
  try { moranChart?.resize() } catch (e) { console.warn('[resize moranChart]', e) }
  try { typChart?.resize() } catch (e) { console.warn('[resize typChart]', e) }
}
let resizeHandler = null
onMounted(async () => {
  ensureChart()
  connectWS()
  resizeHandler = () => resizeAll()
  window.addEventListener?.('resize', resizeHandler)
})
onBeforeUnmount(() => {
  if (ws) ws.close()
  if (playTimer) clearInterval(playTimer)
  chart?.dispose(); chart = null
  tlChart?.dispose(); tlChart = null
  odChart?.dispose(); odChart = null
  moranChart?.dispose(); moranChart = null
  typChart?.dispose(); typChart = null
  if (resizeHandler) window.removeEventListener?.('resize', resizeHandler)
})
</script>

<style scoped>
* { box-sizing: border-box; }

.page {
  height: calc(100vh - 32px);
  background: #0A0A0A;
  color: #FFFFFF;
  overflow: hidden;
  font-family: -apple-system, 'Segoe UI', "PingFang SC", "Microsoft YaHei", sans-serif;
  display: flex;
  flex-direction: column;
}

/* TOPBAR */
.topbar {
  height: 48px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 16px;
  background: #141414;
  border-bottom: 1px solid #222222;
}
.brand {
  font-weight: 700;
  font-size: 15px;
  letter-spacing: 0.3px;
  color: #FFFFFF;
}
.topbarRight {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: #8B8B8B;
}
.topbarTime { font-variant-numeric: tabular-nums; color: #FFFFFF; font-weight: 600; }
.topbarSep { color: #222222; }
.topbarVehicles { font-variant-numeric: tabular-nums; }
.wsDot { width: 8px; height: 8px; border-radius: 50%; background: #8B8B8B; margin-left: 4px; }
.wsDot.ok { background: #06C167; }

/* BUTTONS */
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
.btn.primary { background: #1A1A1A; border: 1px solid #444444; color: #FFFFFF; }
.btn.go {
  background: #06C167; border: none; color: #000000; font-weight: 700; border-radius: 8px;
}
.btn.full { width: 100%; }
.btn.sm { padding: 6px 10px; font-size: 12px; }

/* SELECT */
.sel {
  background: #1A1A1A; border: 1px solid #333333; color: #FFFFFF;
  padding: 6px 8px; border-radius: 8px; font-size: 13px; width: 100%; font-family: inherit;
}
.sel option { background: #1A1A1A; color: #FFFFFF; }
.sel.sm { width: auto; padding: 5px 8px; font-size: 11px; }

/* SHELL */
.shell {
  flex: 1;
  min-height: 0;
  display: grid;
  grid-template-columns: 360px 1fr;
  gap: 4px;
  padding: 4px;
  overflow: hidden;
  min-width: 0;
}

/* LEFT RAIL */
.left { height: 100%; overflow: hidden; min-width: 0; }
.leftScroll {
  height: 100%;
  overflow: auto;
  display: flex;
  flex-direction: column;
  gap: 4px;
  overscroll-behavior: contain;
  padding-right: 2px;
}

/* LAYER TABS */
.layerTabs {
  display: grid;
  grid-template-columns: 1fr;
  gap: 3px;
  flex-shrink: 0;
}
.layerTab {
  padding: 7px 4px;
  border: 1px solid #262626;
  background: #141414;
  color: #8B8B8B;
  border-radius: 8px;
  cursor: pointer;
  font-size: 11px;
  font-weight: 600;
  font-family: inherit;
  transition: all 0.12s ease;
  text-align: center;
  line-height: 1.3;
}
.layerTab:hover { color: #FFFFFF; background: #1A1A1A; }
.layerTab.active { background: #06C167; border-color: #06C167; color: #000000; }

/* CENTER (map + chart) */
.center {
  height: 100%;
  overflow: hidden;
  min-width: 0;
  position: relative;
  display: flex;
  flex-direction: column;
  gap: 4px;
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
.cardTitle {
  font-weight: 700;
  margin-bottom: 8px;
  color: #FFFFFF;
  font-size: 13px;
}

/* MAP CARD */
.mapCard { flex: 1; min-height: 0; padding: 4px; }
.mapCard :deep(.mapWrap) { height: 100%; min-height: 280px; border-radius: 8px; overflow: hidden; }

/* HORIZON TAB */
.horizonRow { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 4px; margin-bottom: 10px; }
.horizonTab {
  padding: 6px 0;
  border: 1px solid #333333;
  background: #1A1A1A;
  color: #8B8B8B;
  border-radius: 8px;
  cursor: pointer;
  font-size: 13px;
  font-weight: 600;
  font-family: inherit;
}
.horizonTab.active { background: #06C167; color: #000000; border-color: #06C167; }

/* STAT3 */
.stat3 { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 4px; }
.s3Box {
  padding: 8px 4px; text-align: center; border-radius: 8px;
  border: 1px solid #222222; background: #1A1A1A;
}
.s3Box .v { display: block; font-size: 20px; font-weight: 900; line-height: 1; }
.s3Box .l { display: block; font-size: 10px; color: #8B8B8B; margin-top: 2px; }
.s3Box.shortage .v { color: #F04438; }
.s3Box.healthy .v { color: #8B8B8B; }
.s3Box.surplus .v { color: #06C167; }

/* PLANS */
.plans { display: flex; flex-direction: column; gap: 2px; }
.planRow {
  display: grid; grid-template-columns: 1fr auto 1fr auto; gap: 6px;
  align-items: center; font-size: 12px;
  padding: 5px 8px; background: #1A1A1A; border: 1px solid #222222; border-radius: 8px;
}
.planFrom, .planTo { color: #FFFFFF; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.planArrow { color: #8B8B8B; }
.planQty { color: #06C167; font-weight: 600; font-variant-numeric: tabular-nums; }
.planHint { margin-top: 6px; font-size: 11px; color: #8B8B8B; }

/* CHARTS */
.chartCard { height: 240px; flex-shrink: 0; min-height: 0; padding: 8px 12px; }
.chartTabBar {
  display: flex;
  gap: 2px;
  flex-shrink: 0;
  margin-bottom: 6px;
  border-bottom: 1px solid #222222;
  padding-bottom: 4px;
}
.chartTab {
  padding: 4px 10px;
  border: 1px solid #2A2A2A;
  background: #1A1A1A;
  color: #8B8B8B;
  border-radius: 6px;
  cursor: pointer;
  font-size: 11px;
  font-weight: 600;
  font-family: inherit;
  transition: all 0.12s ease;
}
.chartTab:hover { color: #FFFFFF; background: #222222; }
.chartTab.active { background: #06C167; border-color: #06C167; color: #000000; }
.chartTitle { font-size: 12px; font-weight: 700; color: #8B8B8B; margin-bottom: 8px; }
.chartBody { flex: 1; min-height: 0; position: relative; }
.chartBody :deep(.chart) { height: 100%; }
.chart { height: 100%; width: 100%; min-height: 160px; }
.empty {
  position: absolute; inset: 0;
  display: flex; align-items: center; justify-content: center; text-align: center;
  padding: 10px; color: #8B8B8B; font-size: 13px;
}

/* 站点详情浮层 */
.detailDrawer {
  position: absolute;
  top: 8px; right: 8px; bottom: 8px;
  width: 300px;
  background: rgba(20, 20, 20, 0.97);
  border: 1px solid #262626;
  border-radius: 12px;
  display: flex;
  flex-direction: column;
  z-index: 1000;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.5);
  backdrop-filter: blur(6px);
}
.drawerHead {
  display: flex; align-items: center; justify-content: space-between;
  padding: 12px 14px; border-bottom: 1px solid #222222;
}
.drawerTitle { font-weight: 700; font-size: 14px; color: #FFFFFF; }
.drawerTitleWrap { display: flex; flex-direction: column; min-width: 0; }
.drawerSubId { font-size: 11px; color: #666666; font-weight: 400; margin-top: 2px; font-variant-numeric: tabular-nums; }
.drawerClose {
  background: none; border: none; color: #8B8B8B; cursor: pointer;
  font-size: 16px; padding: 4px; font-family: inherit;
}
.drawerClose:hover { color: #FFFFFF; }
.drawerBody { flex: 1; overflow: auto; padding: 12px 14px; display: flex; flex-direction: column; gap: 4px; }
.rpRow { display: flex; justify-content: space-between; align-items: center; padding: 4px 0; font-size: 13px; }
.rpLabel { color: #8B8B8B; }
.rpValue { color: #FFFFFF; font-weight: 600; font-variant-numeric: tabular-nums; }
.rpValue.shortage { color: #F04438; }
.rpValue.surplus { color: #06C167; }
.rpValue.healthy { color: #8B8B8B; }
.rpSection {
  font-weight: 700; font-size: 11px; color: #8B8B8B; text-transform: uppercase;
  letter-spacing: 0.5px; margin-top: 8px; padding-bottom: 4px; border-bottom: 1px solid #222222;
}
.rpAdvice {
  font-size: 12px; color: #FFFFFF; line-height: 1.5; padding: 8px;
  background: #1A1A1A; border: 1px solid #222222; border-radius: 8px;
}
.rpStatus { padding: 2px 0 6px; }
.rpBadge {
  display: inline-block; padding: 3px 10px; border-radius: 999px;
  font-size: 12px; font-weight: 700;
}
.rpBadge.shortage { background: #F04438; color: #FFFFFF; }
.rpBadge.surplus { background: #06C167; color: #000000; }
.rpBadge.healthy { background: #2A2A2A; color: #8B8B8B; }
.rpAnchors {
  border: 1px solid #222222; border-radius: 8px; overflow: hidden;
  background: #1A1A1A; font-size: 12px;
}
.rpAnchorHead, .rpAnchorRow {
  display: grid; grid-template-columns: 1.5fr 0.7fr 0.9fr 0.9fr; gap: 4px;
  padding: 5px 8px; align-items: center;
}
.rpAnchorHead { color: #8B8B8B; font-weight: 600; background: #141414; border-bottom: 1px solid #222222; }
.rpAnchorRow { border-bottom: 1px solid #1A1A1A; }
.rpAnchorRow:last-child { border-bottom: none; }
.rpAnchorRow .c1 { color: #c9c9c9; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.rpAnchorRow .c2 { color: #FFFFFF; font-weight: 600; text-align: right; font-variant-numeric: tabular-nums; }
.rpAnchorRow .c3 { color: #8B8B8B; text-align: right; font-variant-numeric: tabular-nums; }
.rpAnchorRow .c4 { font-weight: 700; text-align: right; }
.rpAnchorRow .c4.shortage { color: #F04438; }
.rpAnchorRow .c4.surplus { color: #06C167; }
.rpAnchorRow .c4.healthy { color: #8B8B8B; }
.rpWorst {
  margin-top: 8px; padding: 6px 10px; font-size: 12px; color: #c9c9c9;
  background: #141414; border: 1px solid #222222; border-radius: 8px; line-height: 1.5;
}
.rpWorst b.shortage { color: #F04438; }
.rpWorst b.surplus { color: #06C167; }
.rpWorst b.healthy { color: #8B8B8B; }
.rpEmpty { font-size: 12px; color: #8B8B8B; padding: 8px 0; }
.rpPlans { display: flex; flex-direction: column; gap: 2px; }
.rpPlan {
  display: grid; grid-template-columns: 1fr auto 1fr auto; gap: 4px;
  font-size: 12px; padding: 4px 6px; background: #1A1A1A;
  border: 1px solid #222222; border-radius: 6px; align-items: center;
}
.rpPlanFrom, .rpPlanTo { color: #FFFFFF; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.rpPlanArrow { color: #8B8B8B; text-align: center; }
.rpPlanQty { color: #06C167; font-weight: 600; text-align: right; }

/* PREDICT + DISPATCH */
.predInfo { margin-bottom: 8px; font-size: 12px; color: #8B8B8B; }
.predRow { margin: 2px 0; }
.btnGroup { display: flex; gap: 4px; }
.timePick { margin-bottom: 8px; display: flex; align-items: center; gap: 8px; }
.timePick label { font-size: 12px; color: #8B8B8B; white-space: nowrap; }
.dispatchInfo { margin-top: 8px; font-size: 12px; color: #06C167; font-weight: 600; }
.dispatchInfo .extra { color: #8B8B8B; font-weight: 400; font-size: 11px; }
.emptyHint {
  margin-top: 8px; font-size: 12px; color: #8B8B8B;
  padding: 8px; background: #1A1A1A; border: 1px solid #222222; border-radius: 8px;
}
.error { margin-top: 8px; font-size: 12px; color: #F04438; }

/* FORM (timeline / od / lisa / typical) */
.rowGrid { display: grid; grid-template-columns: 1fr 1fr; gap: 6px 8px; margin-bottom: 10px; }
.rowGrid label { display: block; font-size: 11px; color: #8B8B8B; margin-bottom: 2px; }

/* FRAME STATS */
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
.rowFlex .good { color: #06C167; }
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
.rkNet.good { color: #06C167; }
.rkNet.bad { color: #F04438; }

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

@media (max-width: 1200px) {
  .shell { grid-template-columns: 320px 1fr; }
}
@media (max-width: 860px) {
  .shell { grid-template-columns: 280px 1fr; }
  .detailDrawer { width: 260px; }
}
</style>
