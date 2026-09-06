<template>
  <div class="mapWrap">
    <div class="map" ref="mapEl"></div>
    <div class="legend">
      <div class="legendTitle">{{ legendTitle }}</div>

      <!-- 基础状态图例（status 模式 & 时间帧） -->
      <template v-if="activeLayer === 'status' || activeLayer === 'timeline'">
        <div class="row">
          <span class="dot shortage"></span>
          <span>短缺（need ≥ 阈值，需调入）</span>
        </div>
        <div class="row">
          <span class="dot neutral"></span>
          <span>健康（靠近 50% 水位）</span>
        </div>
        <div class="row">
          <span class="dot surplus"></span>
          <span>盈余（need ≤ -阈值，可调出）</span>
        </div>
        <div class="legendSub" v-if="horizonLegend.length">
          <div class="subTitle">最差锚点分布</div>
          <div class="horizonRow">
            <span v-for="h in horizonLegend" :key="h.label" class="hzTag" :class="h.status">
              {{ h.label }} · {{ h.count }}
            </span>
          </div>
        </div>
      </template>

      <!-- OD 潮汐流线图例 -->
      <template v-else-if="activeLayer === 'od'">
        <div class="row"><span class="odSample odOut"></span><span>起点 → 终点 流向</span></div>
        <div class="row"><span class="odBar odBar5"></span><span>高峰 Top 流量</span></div>
        <div class="row"><span class="odBar odBar1"></span><span>低流量</span></div>
        <div v-if="odMeta" class="subTitle" style="margin-top:6px">
          {{ odMeta.time }} · 窗口 {{ odMeta.window_minutes }}min ·
          来源 <b :class="{good: odMeta.source==='real_od'}">{{ odMeta.source }}</b>
        </div>
      </template>

      <!-- LISA 冷热点图例 -->
      <template v-else-if="activeLayer === 'lisa'">
        <div class="row"><span class="dot hh"></span><span>HH · 高-高集聚（热点）</span></div>
        <div class="row"><span class="dot ll"></span><span>LL · 低-低集聚（冷点）</span></div>
        <div class="row"><span class="dot hl"></span><span>HL · 高低异常（空间离群）</span></div>
        <div class="row"><span class="dot lh"></span><span>LH · 低高异常（空间离群）</span></div>
        <div class="row"><span class="dot ns"></span><span>NS · 不显著</span></div>
        <div v-if="lisaMeta?.global" class="subTitle" style="margin-top:8px">
          Moran's I = <b>{{ fmtNum(lisaMeta.global.I) }}</b>
          （期望值 {{ fmtNum(lisaMeta.global.expected) }}）
        </div>
        <div class="subTitle">Z = {{ fmtNum(lisaMeta?.global?.z_score) }}
          · {{ lisaMeta?.global?.interpretation }}
        </div>
      </template>

      <div class="hint" v-if="activeLayer === 'timeline' && timelineLabel">
        当前帧: <b>{{ timelineLabel }}</b>
        <span v-if="playing" class="playingTag">▶ 播放中</span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import L from 'leaflet'
import { fetchZones } from '../api/index'

const props = defineProps({
  zones: { type: Array, default: () => [] },
  zonesVersion: { type: Number, default: 0 },
  baselineByZoneId: { type: Object, default: () => ({}) },
  selectedZoneId: { type: String, default: null },
  predictionByZoneId: { type: Object, default: () => ({}) },
  dispatchPlans: { type: Array, default: () => [] },
  dispatchRouteSource: { type: String, default: '' },
  // ===== GIS 作品集扩展：P0 / P1 图层切换 =====
  activeLayer: {
    type: String,
    default: 'status', // status | timeline | od | lisa | typical
    validator: (v) => ['status', 'timeline', 'od', 'lisa', 'typical'].includes(v),
  },
  // P0 时间帧: { zone_id → value(vehicle/need/ratio) }
  timelineFrameValues: { type: Object, default: () => ({}) },
  timelineMode: { type: String, default: 'vehicle' }, // vehicle | need | ratio
  timelineThresholds: {
    type: Object,
    default: () => ({ shortage: 3, surplus: 3 }),
  },
  timelineLabel: { type: String, default: '' },
  playing: { type: Boolean, default: false },
  // P1 OD 流线 edges: [{from_id,to_id,from_lonlat,to_lonlat,count,weight_norm}]
  odEdges: { type: Array, default: () => [] },
  odMeta: { type: Object, default: null },
  // P1 LISA 局部结果: [{zone_id, cluster, center_lonlat, ...}]
  lisaLocal: { type: Array, default: () => [] },
  lisaMeta: { type: Object, default: null },
})

const emit = defineEmits(['zone-selected'])

const TILE_PROVIDERS = [
  { name: 'ESRI Street(代理)', url: '/api/tiles/esri/{z}/{x}/{y}', options: { maxZoom: 19 } },
  { name: 'OSM France(代理)', url: '/api/tiles/osmfr/{z}/{x}/{y}', options: { maxZoom: 20 } },
  { name: '高德(代理)', url: '/api/tiles/amap/{z}/{x}/{y}', options: { maxZoom: 18 } },
]
let currentTileProviderIdx = 0
let currentTileLayer = null
let tileFailureCount = 0
const TILE_FAIL_THRESHOLD = 4

function applyNextTileProvider() {
  if (!map) return
  currentTileProviderIdx = (currentTileProviderIdx + 1) % TILE_PROVIDERS.length
  const p = TILE_PROVIDERS[currentTileProviderIdx]
  console.warn(`[Map] tile switch → ${p.name}`)
  if (currentTileLayer) map.removeLayer(currentTileLayer)
  tileFailureCount = 0
  currentTileLayer = L.tileLayer(p.url, { ...p.options }).on('tileerror', () => {
    tileFailureCount++
    if (tileFailureCount >= TILE_FAIL_THRESHOLD) applyNextTileProvider()
  }).addTo(map)
  zonesLayer?.bringToFront()
  overlaysLayer?.bringToFront()
}

const mapEl = ref(null)
let map = null
let zonesLayer = null
const layerByZoneId = new Map()
let overlaysLayer = null // 存放OD弧线、LISA标记、调度箭头
let dispatchPolylines = []
let stationLayer = null // 站点图标层（所有图层统一显示）
const stationMarkers = new Map() // zone_id → L.marker

// ===================== 颜色逻辑 =====================
const vehiclesMap = computed(() => {
  const m = {}
  for (const z of props.zones || []) {
    m[z.zone_id] = z.vehicles
  }
  return m
})

const horizonLegend = computed(() => {
  const pred = props.predictionByZoneId || {}
  const zids = Object.keys(pred)
  if (!zids.length) return []
  const labels = ['1h', '2h', '3h']
  const counts = { '1h': 0, '2h': 0, '3h': 0 }
  const stCounts = {}
  for (const lbl of labels) for (const st of ['shortage','surplus','healthy']) stCounts[`${lbl} ${st}`] = 0
  for (const zid of zids) {
    const z = pred[zid] || {}
    const w = z.worst_horizon || {}
    const lbl = w.label || '1h'
    counts[lbl] = (counts[lbl] || 0) + 1
    const st = z.status || 'healthy'
    stCounts[`${lbl} ${st}`] += 1
  }
  return labels.map((lbl) => {
    const s = stCounts[`${lbl} shortage`] || 0
    const u = stCounts[`${lbl} surplus`] || 0
    const h = stCounts[`${lbl} healthy`] || 0
    let dom = 'healthy'
    if (s >= u && s >= h) dom = 'shortage'
    else if (u >= s && u >= h) dom = 'surplus'
    return { label: lbl, count: counts[lbl] || 0, status: dom }
  })
})

const legendTitle = computed(() => {
  switch (props.activeLayer) {
    case 'timeline': return `时间帧 · ${props.timelineMode.toUpperCase()} 分布`
    case 'od': return 'OD 潮汐流线（起点→终点流量）'
    case 'lisa': return '空间自相关 · LISA 冷热点'
    default: return '区域状态（容量水位 + 未来3h最差锚点）'
  }
})

function fmtNum(v) {
  if (v == null || Number.isNaN(v)) return '--'
  return Number(v).toFixed(3)
}

// 状态(短缺/盈余/健康)色
function SHORTAGE() { return '#F04438' }
function SURPLUS() { return '#06C167' }
function NEUTRAL() { return '#6B6B6B' }

// LISA 颜色（Anselin 经典配色 → 主题色板）
function LISA_COLOR(cluster) {
  switch (cluster) {
    case 'HH': return '#F04438'  // 红：热点
    case 'LL': return '#06C167'  // 绿：冷点
    case 'HL': return '#FFB224'  // 黄：高值被低值包围
    case 'LH': return '#3B82F6'  // 蓝：低值被高值包围
    default: return '#4A4A4A'    // 灰：不显著
  }
}

// 图层通用颜色入口
function colorFor(zoneId) {
  const layer = props.activeLayer
  // P1 LISA
  if (layer === 'lisa') {
    const it = props.lisaLocal.find((x) => x.zone_id === zoneId)
    return LISA_COLOR(it?.cluster || 'NS')
  }
  // P0 Timeline
  if (layer === 'timeline') {
    const v = props.timelineFrameValues[zoneId]
    if (v == null) return '#bdbdbd'
    if (props.timelineMode === 'need') {
      if (v >= props.timelineThresholds.shortage) return SHORTAGE()
      if (v <= -props.timelineThresholds.surplus) return SURPLUS()
      return NEUTRAL()
    } else if (props.timelineMode === 'ratio') {
      if (v >= 0.80) return SURPLUS() // 80% 容量：盈余
      if (v <= 0.20) return SHORTAGE() // 20% 容量：短缺
      return NEUTRAL()
    } else {
      // vehicle（用默认阈值 10 / 50，对应容量 20~100 的常见场景）
      if (v < 10) return SHORTAGE()
      if (v > 50) return SURPLUS()
      return NEUTRAL()
    }
  }
  // Status（prediction 优先 → fallback baseline）
  const info = props.predictionByZoneId?.[zoneId]
  const status = info?.status
  const need = info?.need
  if (status === 'shortage') return SHORTAGE()
  if (status === 'surplus') return SURPLUS()
  if (status === 'healthy') return NEUTRAL()
  if (need != null && typeof need === 'number' && !Number.isNaN(need)) {
    if (need >= 3) return SHORTAGE()
    if (need <= -3) return SURPLUS()
    return NEUTRAL()
  }
  const cur = vehiclesMap.value[zoneId]
  if (cur == null) return '#bdbdbd'
  if (cur < 10) return SHORTAGE()
  if (cur > 50) return SURPLUS()
  return NEUTRAL()
}

// =====================  tooltip & popup 文本 =====================
function zoneStory(zoneId) {
  const cur = vehiclesMap.value[zoneId]
  const info = props.predictionByZoneId?.[zoneId]
  const anchors = info?.forecast_anchors || []
  const worst = info?.worst_horizon || {}
  const status = info?.status
  const need = info?.need
  const capacity = info?.capacity
  // Timeline 模式：直接用帧值
  if (props.activeLayer === 'timeline') {
    const v = props.timelineFrameValues[zoneId]
    const mode = props.timelineMode
    let label = `${mode}: ${v != null ? (mode === 'need' ? (v >= 0 ? `+${v|0}` : `${v|0}`) : Math.round(v)) : '--'}`
    if (mode === 'ratio' && v != null) label = `容量: ${Math.round(v * 100)}%`
    return {
      current: cur, capacity, anchors: [], worst: null, need: null, status: null,
      label, advice: `时间帧 ${props.timelineLabel || ''}`,
    }
  }
  if (props.activeLayer === 'lisa') {
    const it = props.lisaLocal.find((x) => x.zone_id === zoneId)
    return {
      current: cur, capacity, anchors: [], worst: null,
      need: null, status: null,
      label: it ? `LISA ${it.cluster} · Ii=${fmtNum(it.Ii)} · z=${fmtNum(it.z_x)}` : '--',
      advice: it?.p_sim != null ? `置换 p_sim = ${it.p_sim.toFixed(3)}` : '',
    }
  }
  if (props.activeLayer === 'od') {
    // OD 模式：找以该站为起点/终点的流量 Top3
    const out = props.odEdges.filter((e) => e.from_id === zoneId).slice(0, 3)
    const inn = props.odEdges.filter((e) => e.to_id === zoneId).slice(0, 3)
    const outText = out.map((e) => `→ ${e.to_name} ${e.count|0}`).join('<br/>') || '（无出流 TopK）'
    const inText = inn.map((e) => `${e.from_name} → ${e.count|0}`).join('<br/>') || '（无入流 TopK）'
    return {
      current: cur, capacity, anchors: [], worst: null,
      need: null, status: null,
      label: 'OD 潮汐流向',
      advice: `出流 Top3:<br/>${outText}<br/>入流 Top3:<br/>${inText}`,
    }
  }
  if (!info || !anchors.length) {
    return {
      current: cur, capacity, anchors: [], worst: null, need: null, status: null,
      label: cur == null ? '无数据' : (cur < 10 ? '当前短缺' : cur > 50 ? '当前盈余' : '当前正常'),
      advice: '点击左侧「预测未来3小时」获取多尺度调度建议',
    }
  }
  let label, advice
  if (status === 'shortage') {
    label = '短缺（需调入）'
    advice = `最差锚点 ${worst.label || ''}（${worst.time || ''}）需调入 ${Math.round(Math.abs(need || 0))} 辆`
  } else if (status === 'surplus') {
    label = '盈余（可调出）'
    advice = `最差锚点 ${worst.label || ''}（${worst.time || ''}）可调出 ${Math.round(Math.abs(need || 0))} 辆`
  } else {
    label = '容量水位健康'
    advice = '未来3h内水位在健康区间，暂无调度需求'
  }
  return { current: cur, capacity, anchors, worst, need, status, label, advice }
}

function needText(n) {
  if (n == null || Number.isNaN(n)) return '平衡'
  const v = Math.round(n)
  if (v > 0) return `+${v} 调入`
  if (v < 0) return `${v} 调出`
  return '平衡'
}

function zoneTooltipHtml(zoneId, zoneName) {
  const s = zoneStory(zoneId)
  if (!s.anchors.length) {
    const parts = []
    parts.push(`<b style="color:#fff">${zoneName}</b>`)
    if (s.current != null) parts.push(`<span style="color:#c9c9c9">现在 ${s.current} 辆${s.capacity ? ` / 容量 ${s.capacity}` : ''}</span>`)
    if (s.label) parts.push(`<span style="color:#06C167;font-weight:700">${s.label}</span>`)
    if (s.advice) parts.push(`<div style="margin-top:4px;color:#8B8B8B;font-size:11px;white-space:pre-line">${s.advice}</div>`)
    return `<div style="min-width:200px;color:#fff">${parts.join('<br/>')}</div>`
  }
  const stColor = s.status === 'shortage' ? '#F04438' : s.status === 'surplus' ? '#06C167' : '#888'
  const rows = s.anchors.map((a) => {
    const nc = a.need >= 3 ? '#F04438' : a.need <= -3 ? '#06C167' : '#8B8B8B'
    return `<div style="display:flex;justify-content:space-between;gap:10px;font-size:12px">
      <span style="color:#c9c9c9">${a.label}（${a.time}）车 ${Math.round(a.vehicles)}</span>
      <span style="color:${nc};font-weight:700">${needText(a.need)}</span>
    </div>`
  }).join('')
  return `<div style="min-width:220px;color:#fff">
    <div style="font-weight:800;font-size:13px;margin-bottom:6px">${zoneName}</div>
    <div style="font-size:12px;color:#8B8B8B;margin-bottom:6px">现在 ${s.current ?? '-'} / 容量 ${s.capacity ?? '-'}
      <span style="float:right;color:${stColor};font-weight:700">${s.label}</span>
    </div>
    <div style="border-top:1px solid #2A2A2A;padding-top:6px">${rows}</div>
    ${s.worst ? `<div style="border-top:1px solid #2A2A2A;padding-top:6px;margin-top:6px;font-size:12px">
      <b style="color:#fff">最差锚点 ${s.worst.label}（${s.worst.time}）:</b>
      <span style="color:${stColor};font-weight:800">${needText(s.worst.need)}</span>
    </div>` : ''}
  </div>`
}

// ===================== 样式更新 =====================
// 纯圆点地图：所有图层区域多边形一律不可见（无填充、无边界圈），
// 状态/时间帧/LISA 等颜色语义全部由站点圆点承载，避免"大圈/色块"观感
function updateStyles() {
  try {
    if (!layerByZoneId.size) return
    for (const [zoneId, layer] of layerByZoneId.entries()) {
      try {
        const col = colorFor(zoneId) || '#bdbdbd'
        layer.setStyle({
          fillColor: col,
          fillOpacity: 0,
          color: 'transparent',
          weight: 0.6,
        })
        const feature = layer.feature
        const zoneName = feature?.properties?.name || zoneId
        if (layer.getTooltip()) layer.setTooltipContent(zoneTooltipHtml(zoneId, zoneName))
      } catch (eLayer) { /* 单站失败不影响整体 */ continue }
    }
    updateStationMarkers()
  } catch (e) {
    console.warn('[updateStyles]', e)
  }
}

// ===================== 调度层 =====================
function clearDispatch() {
  dispatchPolylines = []
}
function renderDispatch() {
  if (!overlaysLayer || !map) return
  try {
    clearDispatch()
    overlaysLayer.clearLayers()
    if (props.activeLayer === 'od') return renderOD()
    if (props.activeLayer === 'lisa') return renderLISA()
    if (!props.dispatchPlans?.length) return

    // 点击站点后：只显示与该站相关的调度路线（from 或 to）
    const plans = props.selectedZoneId
      ? props.dispatchPlans.filter((p) => p.from_zone === props.selectedZoneId || p.to_zone === props.selectedZoneId)
      : props.dispatchPlans

    plans.forEach((plan, idx) => {
      try {
        const coords = plan?.route_geometry?.coordinates || []
        if (!coords || coords.length < 2) return
        const latlngs = coords.map((c) => [c[1], c[0]])
        // 校验坐标有效性（防止 OSRM 返回 NaN 或越界）
        const allValid = latlngs.every(([lat, lon]) => validLatLng(lon, lat))
        if (!allValid) return
        const first = coords[0], last = coords[coords.length - 1]
        if (!validLatLng(first[0], first[1]) || !validLatLng(last[0], last[1])) return
        const from = { lon: first[0], lat: first[1] }, to = { lon: last[0], lat: last[1] }
        const isOSRM = plan.route_source === 'osrm'
        const qty = plan.quantity ?? 0
        const weight = Math.max(3, Math.min(7, 3 + Math.log10(qty + 1) * 2.5))

        // 白色边框底线（让路线在浅色地图上也清晰）
        const bgLine = L.polyline(latlngs, { color: '#FFFFFF', weight: weight + 3, opacity: 0.5 })
        overlaysLayer.addLayer(bgLine)
        dispatchPolylines[idx] = bgLine

        // 主路线：橙色（从盈余站调出）
        const color = '#FF6B35'
        const mainLine = L.polyline(latlngs, { color, weight, opacity: 0.9, dashArray: isOSRM ? '' : '6,8' })
        const srcTag = isOSRM ? 'OSRM 真实街道' : '直线降级'
        mainLine.bindTooltip(`调度 ${qty} 辆 · ${plan.from_zone} → ${plan.to_zone} · ${srcTag}`, { direction: 'top', sticky: true })
        overlaysLayer.addLayer(mainLine)
        dispatchPolylines[idx] = mainLine
      } catch (ePlan) {
        console.warn('[renderDispatch plan]', ePlan)
      }
    })
  } catch (e) {
    console.warn('[renderDispatch]', e)
  }
}

// ===================== 站点状态图标 =====================
// 统一站点显示：所有图层都渲染站点圆点，颜色由圆点承载
//  status/timeline/od/typical → 状态色/时间帧色；lisa → 中性定位点（簇颜色由 LISA 标记承载）
function stationIconHtml(zoneId) {
  const isSelected = props.selectedZoneId === zoneId
  const isLISA = props.activeLayer === 'lisa'
  const isStatus = props.activeLayer === 'status'
  const size = isSelected ? 24 : (isStatus ? 17 : 15)
  const color = isLISA ? '#5A5A5A' : colorFor(zoneId)
  const halo = isSelected
    ? 'box-shadow:0 0 0 4px rgba(6,193,103,0.28), 0 2px 10px rgba(0,0,0,0.6);'
    : 'box-shadow:0 1px 5px rgba(0,0,0,0.5);'
  const borderW = isSelected ? 2 : (isLISA ? 1 : 1.5)
  const inner = Math.round(size * 0.5)
  return `<div style="width:${size}px;height:${size}px;border-radius:50%;background:#0A0A0A;border:${borderW}px solid ${color};${halo}display:flex;align-items:center;justify-content:center;box-sizing:border-box;"><span style="width:${inner}px;height:${inner}px;border-radius:50%;background:${color};display:block;"></span></div>`
}

function buildStationMarkers() {
  if (!stationLayer || !zonesLayer) return
  stationLayer.clearLayers()
  stationMarkers.clear()
  zonesLayer.eachLayer((layer) => {
    const zoneId = layer.feature?.properties?.zone_id
    if (!zoneId) return
    const c = layer.getBounds?.().getCenter()
    if (!c) return
    const mk = L.marker(c, {
      icon: L.divIcon({ html: stationIconHtml(zoneId), className: '', iconSize: [30, 30], iconAnchor: [15, 15] }),
      interactive: true,
      zIndexOffset: 800,
    })
    mk.bindTooltip(zoneTooltipHtml(zoneId, layer.feature?.properties?.name || zoneId), { direction: 'top', className: 'zone-tip', sticky: true })
    mk.on('click', () => {
      // 详情统一走右侧抽屉，地图上不再弹卡片
      emit('zone-selected', zoneId)
    })
    stationLayer.addLayer(mk)
    stationMarkers.set(zoneId, mk)
  })
}

function updateStationMarkers() {
  if (!stationLayer) return
  stationMarkers.forEach((mk, zoneId) => {
    mk.setIcon(L.divIcon({ html: stationIconHtml(zoneId), className: '', iconSize: [30, 30], iconAnchor: [15, 15] }))
  })
}

// ===================== P1 OD 弧线层 =====================
// 用二次贝塞尔弧线展示 OD 流向，避免往返重叠
function isFiniteNum(v) { return typeof v === 'number' && Number.isFinite(v) }
function validLatLng(lon, lat) {
  // 经纬度合理范围校验，NaN/Inf/越界都拒绝（避免 Leaflet 重绘死循环）
  if (!isFiniteNum(lon) || !isFiniteNum(lat)) return false
  if (lon < -180 || lon > 180 || lat < -90 || lat > 90) return false
  return true
}
function bezierMidpoint(fromLon, fromLat, toLon, toLat, t = 0.5, offsetPct = 0.18) {
  if (!validLatLng(fromLon, fromLat) || !validLatLng(toLon, toLat)) return null
  const dx = toLon - fromLon
  const dy = toLat - fromLat
  const len = Math.sqrt(dx * dx + dy * dy) || 1e-9
  if (len < 1e-8) {
    // 同站点：避免除零，直接稍偏移上方作为弧线
    return [fromLon - 0.0005, fromLat + 0.0005]
  }
  const mlon = fromLon + dx * t
  const mlat = fromLat + dy * t
  const nx = -dy / len
  const ny = dx / len
  const ox = dx * offsetPct
  const oy = dy * offsetPct
  const midLon = mlon + nx * ox + nx * (len * 0.08)
  const midLat = mlat + ny * oy + ny * (len * 0.08)
  // 最终再校验一次
  if (!validLatLng(midLon, midLat)) return null
  return [midLon, midLat]
}

function renderOD() {
  if (!overlaysLayer || !map) return
  try {
    clearDispatch()
    overlaysLayer.clearLayers()
    const edges = props.odEdges || []
    const total = Math.min(edges.length, 80) // 硬上限：最多渲染 80 条弧线（性能）
    for (let idx = 0; idx < total; idx++) {
      try {
        const e = edges[idx]
        if (!e) continue
        const [flon, flat] = e.from_lonlat || [null, null]
        const [tlon, tlat] = e.to_lonlat || [null, null]
        if (!validLatLng(flon, flat) || !validLatLng(tlon, tlat)) continue
        // 同站点跳过（避免 0 长度 polyline 渲染异常）
        if (Math.abs(flon - tlon) < 1e-10 && Math.abs(flat - tlat) < 1e-10) continue
        const mid = bezierMidpoint(flon, flat, tlon, tlat)
        if (!mid) continue
        const [mlon, mlat] = mid
        if (!validLatLng(mlon, mlat)) continue
        const latlngs = [[flat, flon], [mlat, mlon], [tlat, tlon]]
        const wn = isFiniteNum(e.weight_norm) && e.weight_norm > 0.01 ? e.weight_norm : 0.08
        const hue = 40 - 40 * Math.min(1, Math.max(0, wn))
        const color = `hsl(${hue}, 85%, 50%)`
        const weight = Math.max(1.2, Math.min(8, wn * 8))
        const poly = L.polyline(latlngs, { color, weight, opacity: 0.55 + wn * 0.35 })
        overlaysLayer.addLayer(poly)
        // 弧线中点放流量标签（仅前 15 条 + 权重 >=0.3 显示，避免 DOM 爆炸）
        if (idx < 15 || wn >= 0.3) {
          const count = Math.max(1, Math.round(e.count || 0))
          const fontSize = 10 + Math.round(Math.min(1, Math.max(0, wn)) * 3)
          const labelHtml = `<div style="background:#fff;color:${color};padding:0 6px;border-radius:999px;border:1px solid ${color};font-weight:800;font-size:${fontSize}px;line-height:18px;white-space:nowrap;box-shadow:0 1px 3px rgba(0,0,0,0.2);">${count}</div>`
          const labelIcon = L.divIcon({ html: labelHtml, className: '', iconSize: null })
          const label = L.marker([mlat, mlon], { icon: labelIcon, interactive: false, zIndexOffset: 500 })
          overlaysLayer.addLayer(label)
        }
      } catch (eEdge) {
        console.warn('[renderOD edge]', eEdge)
        continue
      }
    }
  } catch (e) {
    console.warn('[renderOD]', e)
  }
}

// ===================== P1 LISA 冷热点：叠加标记 =====================
function renderLISA() {
  if (!overlaysLayer || !map) return
  try {
    clearDispatch()
    overlaysLayer.clearLayers()
    const items = props.lisaLocal || []
    // 渲染上限：避免过多 DOM 节点导致卡顿
    const limit = Math.min(items.length, 60)
    for (let i = 0; i < limit; i++) {
      try {
        const it = items[i]
        if (!it) continue
        if (it.cluster === 'NS') continue
        const cll = it.center_lonlat || []
        const lon = cll[0], lat = cll[1]
        if (!validLatLng(lon, lat)) continue
        const color = LISA_COLOR(it.cluster)
        // 星形 DivIcon，突出冷热点
        const size = 26
        const html = `<div style="width:${size}px;height:${size}px;border-radius:50%;background:${color};border:2px solid #fff;box-shadow:0 0 0 1px rgba(0,0,0,0.35), 0 2px 8px rgba(0,0,0,0.5);opacity:0.92;"></div>`
        const icon = L.divIcon({ html, className: '', iconSize: [size, size], iconAnchor: [size / 2, size / 2] })
        const mk = L.marker([lat, lon], { icon, interactive: false, keyboard: false, zIndexOffset: 400 })
        overlaysLayer.addLayer(mk)
      } catch (eItem) {
        console.warn('[renderLISA item]', eItem)
        continue
      }
    }
  } catch (e) {
    console.warn('[renderLISA]', e)
  }
}

// ===================== 初始化 =====================
async function init() {
  const MAP_CENTER = [40.7308, -73.9973]
  const DEFAULT_ZOOM = 14
  if (!map) {
    map = L.map(mapEl.value, { zoomControl: true }).setView(MAP_CENTER, DEFAULT_ZOOM)
    currentTileProviderIdx = 0
    const first = TILE_PROVIDERS[0]
    tileFailureCount = 0
    currentTileLayer = L.tileLayer(first.url, { ...first.options }).on('tileerror', () => {
      tileFailureCount++
      if (tileFailureCount >= TILE_FAIL_THRESHOLD) applyNextTileProvider()
    }).addTo(map)
  }
  const geo = await fetchZones()
  if (zonesLayer) {
    map.removeLayer(zonesLayer)
    zonesLayer = null
    layerByZoneId.clear()
  }
  zonesLayer = L.geoJSON(geo, {
    style: () => ({ fillColor: '#000', fillOpacity: 0, color: 'transparent', weight: 0.6 }),
    onEachFeature: (feature, layer) => {
      const zoneId = feature.properties?.zone_id
      const zoneName = feature.properties?.name || zoneId
      layerByZoneId.set(zoneId, layer)
      layer.bindTooltip(zoneTooltipHtml(zoneId, zoneName), { direction: 'top', className: 'zone-tip', sticky: true })
      layer.on('click', () => {
        // 站点详情统一由右侧抽屉展示，不再弹地图小卡片（避免遮挡调度路线）
        emit('zone-selected', zoneId)
      })
    },
  }).addTo(map)

  if (overlaysLayer) map.removeLayer(overlaysLayer)
  overlaysLayer = L.layerGroup().addTo(map)
  if (stationLayer) map.removeLayer(stationLayer)
  stationLayer = L.layerGroup().addTo(map)
  buildStationMarkers()

  try {
    const bounds = zonesLayer.getBounds()
    if (bounds && bounds.isValid()) map.fitBounds(bounds, { padding: [20, 20] })
    else map.setView(MAP_CENTER, DEFAULT_ZOOM)
  } catch (e) {
    map.setView(MAP_CENTER, DEFAULT_ZOOM)
  }
  updateStyles()
  renderDispatch()
}

onMounted(async () => { try { await init() } catch (e) { console.warn('[init]', e) } })

watch(() => props.zonesVersion, async () => { try { if (map) { await nextTick(); await init() } } catch (e) { console.warn('[watch zonesVersion]', e) } })
watch(() => props.zones, async () => { try { await nextTick(); updateStyles() } catch (e) { console.warn('[watch zones]', e) } }, { deep: true })
watch(() => props.baselineByZoneId, async () => { try { await nextTick(); updateStyles() } catch (e) { console.warn('[watch baseline]', e) } }, { deep: true })
watch(() => props.predictionByZoneId, async () => {
  try { await nextTick(); updateStyles() } catch (e) { console.warn('[watch prediction]', e) }
}, { deep: true })
watch(() => props.selectedZoneId, async () => { try { await nextTick(); updateStyles(); renderDispatch() } catch (e) { console.warn('[watch selectedZoneId]', e) } })
watch(() => props.dispatchPlans, async () => { try { await nextTick(); renderDispatch() } catch (e) { console.warn('[watch dispatchPlans]', e) } }, { deep: true })

// GIS 扩展联动
watch(() => props.activeLayer, async () => {
  try {
    await nextTick()
    updateStyles()
    renderDispatch()
  } catch (e) { console.warn('[watch activeLayer]', e) }
})
watch(() => props.timelineFrameValues, async () => {
  try { await nextTick(); updateStyles() } catch (e) { console.warn('[watch timelineFrame]', e) }
}, { deep: true })
watch(() => props.odEdges, async () => {
  try { await nextTick(); renderDispatch() } catch (e) { console.warn('[watch odEdges]', e) }
}, { deep: true })
watch(() => props.lisaLocal, async () => {
  try {
    await nextTick()
    updateStyles()
    renderDispatch()
  } catch (e) { console.warn('[watch lisaLocal]', e) }
}, { deep: true })

onBeforeUnmount(() => {
  clearDispatch()
  layerByZoneId.clear()
  if (overlaysLayer) overlaysLayer.clearLayers()
  if (map) map.remove()
  map = null
})
</script>

<style scoped>
.mapWrap { position: relative; height: 100%; min-height: 520px; }
.map { height: 100%; }
.legend {
  position: absolute; top: 12px; right: 12px; z-index: 1000;
  width: 250px; background: rgba(20, 20, 20, 0.92);
  border: 1px solid #2a2a2a; border-radius: 10px; padding: 10px 12px;
  box-shadow: 0 8px 24px rgba(0,0,0,0.45); font-size: 12px; color: #c9c9c9;
}
.legendTitle { font-weight: 700; margin-bottom: 8px; color: #fff; }
.legendSub { margin-top: 10px; padding-top: 8px; border-top: 1px solid #2a2a2a; }
.subTitle { font-size: 11px; color: #8b8b8b; margin-bottom: 6px; line-height: 1.5; }
.subTitle .good { color: #06c167; }
.horizonRow { display: flex; gap: 6px; flex-wrap: wrap; }
.hzTag { padding: 2px 8px; border-radius: 999px; font-size: 11px; font-weight: 700; border: 1px solid rgba(255,255,255,0.12); background: rgba(255,255,255,0.05); color: #c9c9c9; }
.hzTag.shortage { background: rgba(240,68,56,0.15); color: #fca5a0; border-color: rgba(240,68,56,0.3); }
.hzTag.surplus  { background: rgba(6,193,103,0.15); color: #4ddc97; border-color: rgba(6,193,103,0.3); }
.hzTag.healthy  { background: rgba(255,255,255,0.06); color: #8b8b8b; border-color: rgba(255,255,255,0.12); }
.hint { margin-top: 10px; padding-top: 8px; border-top: 1px solid #2a2a2a; font-size: 11px; color: #8b8b8b; line-height: 1.5; }
.hint b { color: #fff; }
.playingTag { margin-left:6px; padding: 1px 6px; border-radius:999px; background: rgba(6,193,103,0.18); color: #06c167; font-weight:700; }
.row { display: flex; align-items: center; gap: 8px; margin: 6px 0; color: #c9c9c9; }
.dot { width: 12px; height: 12px; border-radius: 3px; display: inline-block; flex-shrink: 0; }
.shortage { background: #f04438; }
.neutral  { background: #6b6b6b; }
.surplus  { background: #06c167; }
.hh { background: #f04438; }
.ll { background: #06c167; }
.hl { background: #ffb224; border: 1px solid rgba(255,178,36,0.4); }
.lh { background: #3b82f6; }
.ns { background: #4a4a4a; }
.odSample { width: 36px; height: 8px; border-radius: 4px; background: linear-gradient(90deg, #ffb224, #f04438); display:inline-block; }
.odOut {}
.odBar { width: 24px; height: 10px; border-radius: 3px; display: inline-block; }
.odBar5 { background: #f04438; }
.odBar1 { background: #ffb224; }

:deep(.zone-tip) {
  background: rgba(26, 26, 26, 0.97); border: 1px solid #2a2a2a; border-radius: 8px;
  padding: 8px 10px; font-size: 12px; color: #fff; box-shadow: 0 4px 16px rgba(0,0,0,0.5); max-width: 280px;
}
:deep(.zone-tip::before) { border-top-color: rgba(26, 26, 26, 0.97); }
</style>
