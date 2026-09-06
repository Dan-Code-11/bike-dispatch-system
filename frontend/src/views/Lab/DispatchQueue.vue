<template>
  <div class="wrap">
    <div class="head">
      <div>
        <div class="title">调度任务队列</div>
        <div class="sub">预测 + 一键调度后自动生成 · 点击任务查看单条调度路线</div>
      </div>
      <div class="actions">
        <button class="btn" @click="reload" :disabled="loading">{{ loading ? '刷新中…' : '刷新' }}</button>
      </div>
    </div>

    <div class="body">
      <div class="card listCard">
        <div class="cardTitle">调度列表（{{ tasks.length }}）</div>
        <div class="empty" v-if="!tasks.length">暂无任务。先在「调度大屏」点击「一键调度」即可看到记录。</div>
        <div class="list" v-else>
          <div
            v-for="(t, i) in tasks"
            :key="t.id || i"
            class="item"
            :class="{ active: activeIdx === i }"
            @click="selectTask(i)"
          >
            <div class="route">
              <span class="zFrom">{{ zoneName(t.from_zone) }}</span>
              <span class="arrow">→</span>
              <span class="zTo">{{ zoneName(t.to_zone) }}</span>
              <span class="qty">{{ t.quantity }}辆</span>
            </div>
            <div class="meta">
              {{ t.created_at }}
              <template v-if="t.distance_m"> · {{ fmtDist(t.distance_m) }}</template>
              <template v-if="!t.route_lonlats"> · 无路线数据</template>
            </div>
          </div>
        </div>
      </div>

      <div class="card mapCard">
        <div class="mapHead">
          <div v-if="activeTask" class="mapTitle">
            {{ zoneName(activeTask.from_zone) }} → {{ zoneName(activeTask.to_zone) }} ·
            {{ activeTask.quantity }} 辆
          </div>
          <div v-else class="mapTitle placeholder">点击左侧任务查看调度路线</div>
        </div>
        <div class="map" ref="mapEl"></div>
        <div class="legend" v-if="activeTask">
          <span class="lg"><span class="dot from"></span>{{ zoneName(activeTask.from_zone) }}（调出）</span>
          <span class="lg"><span class="dot to"></span>{{ zoneName(activeTask.to_zone) }}（调入）</span>
          <span class="lg"><span class="line"></span>调度路线</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import L from 'leaflet'
import { fetchZones } from '../../api/index'

const loading = ref(false)
const tasks = ref([])
const activeIdx = ref(-1)
const activeTask = computed(() => (activeIdx.value >= 0 ? tasks.value[activeIdx.value] : null))
const zoneNameMap = ref({})

const mapEl = ref(null)
let map = null
let routeLayer = null

const TILE_URL = '/api/tiles/esri/{z}/{x}/{y}'

function fmtDist(m) {
  if (m >= 1000) return (m / 1000).toFixed(2) + ' km'
  return Math.round(m) + ' m'
}

function zoneName(zid) {
  return zoneNameMap.value[zid] || zid
}

function markerIcon(color, size) {
  const s = size || 18
  const inner = Math.round(s * 0.5)
  return L.divIcon({
    className: '',
    html:
      `<div style="width:${s}px;height:${s}px;border-radius:50%;background:#0A0A0A;` +
      `border:2px solid ${color};box-shadow:0 2px 8px rgba(0,0,0,0.6);` +
      `display:flex;align-items:center;justify-content:center;box-sizing:border-box;">` +
      `<span style="width:${inner}px;height:${inner}px;border-radius:50%;background:${color};display:block;"></span></div>`,
    iconSize: [s, s],
    iconAnchor: [s / 2, s / 2],
  })
}

function renderTask(t) {
  if (!map) return
  if (routeLayer) { map.removeLayer(routeLayer); routeLayer = null }
  const coords = t.route_lonlats
  if (!Array.isArray(coords) || coords.length < 2) return
  const group = L.layerGroup()
  const [fx, fy] = coords[0]
  const [tx, ty] = coords[coords.length - 1]
  group.addLayer(L.marker([fy, fx], { icon: markerIcon('#06C167', 20) }))
  group.addLayer(L.marker([ty, tx], { icon: markerIcon('#F04438', 20) }))
  const latlngs = coords.map(([lo, la]) => [la, lo])
  group.addLayer(
    L.polyline(latlngs, {
      color: '#FF6B35',
      weight: 4,
      opacity: 0.95,
      lineJoin: 'round',
    })
  )
  routeLayer = group
  map.addLayer(group)
  map.fitBounds(L.latLngBounds(latlngs), { padding: [36, 36], maxZoom: 15 })
}

function selectTask(i) {
  activeIdx.value = i
  const t = tasks.value[i]
  if (t) renderTask(t)
}

async function reload() {
  loading.value = true
  try {
    const res = await fetch('/api/monitor/stats')
    if (!res.ok) throw new Error(`monitor/stats failed: ${res.status}`)
    const data = await res.json()
    tasks.value = data.dispatch_tasks || []
    if (activeIdx.value >= tasks.value.length) activeIdx.value = -1
    if (activeTask.value) renderTask(activeTask.value)
  } catch (e) {
    console.error(e)
  } finally {
    loading.value = false
  }
}

async function loadZoneNames() {
  try {
    const geo = await fetchZones()
    const m = {}
    const feats = (geo && (geo.features || geo.zones)) || []
    for (const f of feats) {
      const p = f.properties || f
      if (p.zone_id) m[p.zone_id] = p.name || p.zone_id
    }
    zoneNameMap.value = m
  } catch (e) {
    console.error('loadZoneNames', e)
  }
}

onMounted(async () => {
  await nextTick()
  if (mapEl.value) {
    map = L.map(mapEl.value, { zoomControl: true }).setView([40.7293, -73.9974], 13)
    L.tileLayer(TILE_URL, { maxZoom: 19 }).addTo(map)
  }
  loadZoneNames()
  reload().catch(() => {})
})

onBeforeUnmount(() => {
  if (map) { map.remove(); map = null }
})
</script>

<style scoped>
.wrap {
  color: #c9c9c9;
  height: calc(100vh - 32px);
  display: flex;
  flex-direction: column;
  gap: 4px;
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
  flex-shrink: 0;
}
.title { font-weight: 800; color: #fff; }
.sub { margin-top: 6px; font-size: 12px; color: #8b8b8b; }
.actions { display: flex; gap: 10px; }
.btn {
  border: 1px solid #262626;
  background: #1a1a1a;
  color: #e6e6e6;
  border-radius: 8px;
  padding: 9px 12px;
  cursor: pointer;
}
.btn:hover { background: #222222; }
.body {
  flex: 1;
  min-height: 0;
  display: grid;
  grid-template-columns: 340px 1fr;
  gap: 4px;
}
.card {
  border: 1px solid #1f1f1f;
  background: #141414;
  border-radius: 8px;
  padding: 12px;
  min-width: 0;
  min-height: 0;
}
.listCard { display: flex; flex-direction: column; }
.cardTitle { font-weight: 800; margin-bottom: 10px; color: #fff; }
.list { display: grid; gap: 8px; overflow: auto; min-height: 0; }
.item {
  border: 1px solid #1f1f1f;
  background: #1a1a1a;
  border-radius: 8px;
  padding: 10px 10px;
  cursor: pointer;
  transition: border-color 0.12s ease, background 0.12s ease;
}
.item:hover { border-color: #333; }
.item.active {
  border-color: #06C167;
  background: #16211a;
}
.route { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.zFrom { color: #06C167; font-weight: 700; }
.arrow { color: #8b8b8b; }
.zTo { color: #F04438; font-weight: 700; }
.qty {
  margin-left: auto;
  font-size: 12px;
  color: #fff;
  background: #262626;
  border-radius: 10px;
  padding: 1px 8px;
}
.meta { margin-top: 4px; font-size: 12px; color: #8b8b8b; }
.empty { font-size: 13px; color: #8b8b8b; }
.mapCard {
  display: flex;
  flex-direction: column;
  padding: 8px;
  position: relative;
}
.mapHead { padding: 4px 4px 8px; flex-shrink: 0; }
.mapTitle { font-weight: 800; color: #fff; font-size: 14px; }
.mapTitle.placeholder { color: #5a5a5a; font-weight: 500; }
.map {
  flex: 1;
  min-height: 280px;
  border-radius: 8px;
  overflow: hidden;
  background: #0d0d0d;
  z-index: 0;
}
.legend {
  display: flex;
  gap: 14px;
  flex-wrap: wrap;
  padding: 8px 4px 0;
  font-size: 12px;
  color: #8b8b8b;
}
.lg { display: inline-flex; align-items: center; gap: 5px; }
.dot { width: 10px; height: 10px; border-radius: 50%; display: inline-block; }
.dot.from { background: #06C167; }
.dot.to { background: #F04438; }
.line {
  width: 14px; height: 3px; border-radius: 2px;
  background: #FF6B35; display: inline-block;
}
:deep(.leaflet-container) { background: #0d0d0d; font-family: inherit; }
:deep(.leaflet-control-zoom a) {
  background: #1a1a1a !important;
  color: #e6e6e6 !important;
  border-color: #262626 !important;
}
:deep(.leaflet-bar) { border: 1px solid #262626 !important; }
</style>
