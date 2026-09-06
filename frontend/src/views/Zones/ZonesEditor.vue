<template>
  <div class="wrap">
    <div class="head">
      <div>
        <div class="title">区域编辑器</div>
        <div class="sub">在线编辑 GeoJSON 区域，并保存到后端（`/api/zones/update`）。</div>
      </div>
      <div class="actions">
      <button class="btn" @click="startPolygon" :disabled="!map || drawMode !== 'idle'">绘制多边形</button>
      <button class="btn" @click="startRect" :disabled="!map || drawMode !== 'idle'">绘制矩形</button>
      <button class="btn" v-if="drawMode !== 'idle'" @click="finishOrStop">结束绘制</button>
        <button class="btn" @click="fitAll" :disabled="!map">适配视图</button>
        <button class="btn" @click="reload" :disabled="loading">{{ loading ? '加载中…' : '重新加载' }}</button>
        <button class="btn primary" @click="save" :disabled="saving || !dirty">
          {{ saving ? '保存中…' : dirty ? '保存更改' : '已保存' }}
        </button>
      </div>
    </div>

    <div class="body">
      <div class="mapCard">
        <div class="mapHead">
          <div class="mapTitle">编辑画布</div>
          <div class="mapHint">在地图上绘制/编辑/删除多边形后点击保存</div>
        </div>
        <div class="map" ref="mapEl"></div>
        <div class="hint">
          <div class="hRow"><span class="k">绘制</span><span class="v">左侧工具栏：多边形 / 矩形 / 编辑 / 删除</span></div>
          <div class="hRow"><span class="k">命名</span><span class="v">选中区域后在右侧“属性”里修改 `name`</span></div>
          <div class="hRow"><span class="k">保存</span><span class="v">保存会覆盖后端当前 GeoJSON，并触发区域热更新</span></div>
        </div>
      </div>

      <div class="side">
        <div class="card">
          <div class="cardTitle">状态</div>
          <div class="kv">
            <div class="row"><span class="k">区域数量</span><span class="v">{{ featureCount }}</span></div>
            <div class="row"><span class="k">是否有改动</span><span class="v">{{ dirty ? '是' : '否' }}</span></div>
            <div class="row"><span class="k">后端版本</span><span class="v">{{ zonesVersion ?? '-' }}</span></div>
            <div class="row"><span class="k">当前选择</span><span class="v">{{ selectedName || '-' }}</span></div>
          </div>
        </div>

        <div class="card">
          <div class="cardTitle">属性</div>
          <div class="field">
            <div class="label">name</div>
            <input class="input" v-model="selectedName" :disabled="!selectedFeature" placeholder="例如：图书馆区" />
          </div>
          <div class="field">
            <div class="label">zone_id</div>
            <input class="input" v-model="selectedZoneId" :disabled="!selectedFeature" placeholder="例如：zone_1" />
          </div>
          <div class="tip">建议 `zone_id` 唯一；若留空，保存时会自动生成。</div>
        </div>

        <div class="card">
          <div class="cardTitle">导入/导出</div>
          <div class="importRow">
            <input ref="fileEl" type="file" accept=".json,.geojson,application/geo+json" style="display:none" @change="onFile" />
            <button class="btn" @click="fileEl?.click()">导入 GeoJSON</button>
            <button class="btn" @click="exportGeoJSON" :disabled="!featureCount">导出 GeoJSON</button>
          </div>
          <div class="tip">导入会替换当前编辑内容（不自动保存到后端）。</div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { showConfirmDialog, showToast } from 'vant'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import 'leaflet-draw'
import 'leaflet-draw/dist/leaflet.draw.css'

import { API_BASE, fetchZones, updateZones } from '../../api'

const mapEl = ref(null)
const fileEl = ref(null)

const map = ref(null)
const drawn = ref(null)
const zonesVersion = ref(null)
const loading = ref(false)
const saving = ref(false)
const dirty = ref(false)
let mapResizeObserver = null

const drawMode = ref('idle') // 'idle' | 'polygon' | 'rect'
let polyPoints = []
let polyPreview = null
let rectStart = null
let rectPreview = null
let stopFns = []
let rectDragging = false
let lastDownLatLng = null
let polygonFinish = null

const selectedLayer = ref(null)
const selectedFeature = computed(() => selectedLayer.value?.feature || null)

const selectedName = ref('')
const selectedZoneId = ref('')

const featureCount = computed(() => {
  if (!drawn.value) return 0
  let n = 0
  drawn.value.eachLayer(() => (n += 1))
  return n
})

function markDirty() {
  dirty.value = true
}

function normalizeFeatureProps(layer) {
  if (!layer.feature) layer.feature = { type: 'Feature', properties: {}, geometry: null }
  if (!layer.feature.properties) layer.feature.properties = {}
}

function selectLayer(layer) {
  selectedLayer.value = layer || null
  if (!layer) {
    selectedName.value = ''
    selectedZoneId.value = ''
    return
  }
  normalizeFeatureProps(layer)
  selectedName.value = layer.feature.properties?.name || ''
  selectedZoneId.value = layer.feature.properties?.zone_id || ''
}

function bindLayerEvents(layer) {
  layer.on('click', () => selectLayer(layer))
}

function _setUserDrawMode(active) {
  if (!map.value) return
  if (active) {
    map.value.dragging?.disable()
    map.value.scrollWheelZoom?.disable()
    map.value.doubleClickZoom?.disable()
  } else {
    map.value.dragging?.enable()
    map.value.scrollWheelZoom?.enable()
    map.value.doubleClickZoom?.disable()
  }
}

function stopDraw() {
  const fns = stopFns
  stopFns = []
  // Put state into a safe baseline BEFORE executing cleanup functions,
  // so cleanup can't re-enter finish/stop logic and freeze the UI.
  drawMode.value = 'idle'
  polygonFinish = null
  _setUserDrawMode(false)

  fns.forEach((fn) => {
    try {
      fn()
    } catch {}
  })
  polyPoints = []
  if (polyPreview) {
    polyPreview.remove()
    polyPreview = null
  }
  rectStart = null
  rectDragging = false
  lastDownLatLng = null
  if (rectPreview) {
    rectPreview.remove()
    rectPreview = null
  }
}

function startPolygon() {
  if (!map.value || !drawn.value) return
  stopDraw()
  drawMode.value = 'polygon'
  _setUserDrawMode(true)
  showToast({ message: '多边形绘制：单击打点，点“结束绘制”生成多边形。', duration: 2000 })

  const onClick = (e) => {
    polyPoints.push(e.latlng)
    if (!polyPreview) {
      polyPreview = L.polyline(polyPoints, { color: '#06c167', weight: 2, dashArray: '6 6' }).addTo(map.value)
    } else {
      polyPreview.setLatLngs(polyPoints)
    }
  }

  const finish = () => {
    if (polyPoints.length < 3) {
      showToast({ type: 'fail', message: '至少需要 3 个点' })
      return
    }
    const layer = L.polygon(polyPoints, {
      color: '#06c167',
      weight: 2,
      opacity: 0.95,
      fill: true,
      fillColor: '#06c167',
      fillOpacity: 0.18,
    })
    normalizeFeatureProps(layer)
    layer.feature.geometry = layer.toGeoJSON().geometry
    bindLayerEvents(layer)
    drawn.value.addLayer(layer)
    selectLayer(layer)
    markDirty()
    stopDraw()
  }
  polygonFinish = finish

  map.value.on('click', onClick)
  stopFns.push(() => map.value?.off('click', onClick))
}

function startRect() {
  if (!map.value || !drawn.value) return
  stopDraw()
  drawMode.value = 'rect'
  _setUserDrawMode(true)
  showToast({ message: '矩形绘制：按下拖拽释放完成。', duration: 2000 })

  const onDown = (e) => {
    rectStart = e.latlng
    lastDownLatLng = e.latlng
    rectDragging = false
    if (rectPreview) {
      rectPreview.remove()
      rectPreview = null
    }
    rectPreview = L.rectangle([rectStart, rectStart], { color: '#06c167', weight: 2, fillOpacity: 0.12 }).addTo(map.value)
  }

  const onMove = (e) => {
    if (!rectStart || !rectPreview) return
    // require some movement before treating it as a drag, to avoid click->tiny rect
    if (!rectDragging && lastDownLatLng) {
      const a = map.value.latLngToContainerPoint(lastDownLatLng)
      const b = map.value.latLngToContainerPoint(e.latlng)
      if (a.distanceTo(b) >= 6) rectDragging = true
    }
    rectPreview.setBounds(L.latLngBounds(rectStart, e.latlng))
  }

  const onUp = (e) => {
    if (!rectStart || !rectPreview) return
    if (!rectDragging) {
      // treat as cancel (no drag)
      rectPreview.remove()
      rectPreview = null
      rectStart = null
      rectDragging = false
      lastDownLatLng = null
      return
    }
    rectPreview.setBounds(L.latLngBounds(rectStart, e.latlng))
    const bounds = rectPreview.getBounds()
    const layer = L.rectangle(bounds, { color: '#06c167', weight: 2, fillOpacity: 0.18 })
    rectPreview.remove()
    rectPreview = null
    rectStart = null

    normalizeFeatureProps(layer)
    layer.feature.geometry = layer.toGeoJSON().geometry
    bindLayerEvents(layer)
    drawn.value.addLayer(layer)
    selectLayer(layer)
    markDirty()
    stopDraw()
  }

  map.value.on('mousedown', onDown)
  map.value.on('mousemove', onMove)
  map.value.on('mouseup', onUp)
  stopFns.push(() => map.value?.off('mousedown', onDown))
  stopFns.push(() => map.value?.off('mousemove', onMove))
  stopFns.push(() => map.value?.off('mouseup', onUp))
  stopFns.push(() => {
    // if user clicks "结束绘制" mid-way
    rectStart = null
    rectDragging = false
    lastDownLatLng = null
    if (rectPreview) {
      rectPreview.remove()
      rectPreview = null
    }
  })
}

function finishOrStop() {
  // For polygon we want "finish". For rect we want "cancel/stop".
  if (drawMode.value === 'polygon' && typeof polygonFinish === 'function') {
    polygonFinish()
    return
  }
  stopDraw()
}

function setFromGeoJSON(geojson) {
  if (!drawn.value) return
  drawn.value.clearLayers()
  const gj = L.geoJSON(geojson, {
    onEachFeature: (feature, layer) => {
      layer.feature = feature
      bindLayerEvents(layer)
      drawn.value.addLayer(layer)
    },
  })
  gj.eachLayer(() => {})
  dirty.value = false
  selectLayer(null)
}

async function reload() {
  loading.value = true
  try {
    const res = await fetch(`${API_BASE}/zones`)
    if (!res.ok) throw new Error(`zones failed: ${res.status}`)
    const data = await res.json()
    zonesVersion.value = data.zones_version ?? null
    setFromGeoJSON(data.geojson || data)
    fitAll()
  } finally {
    loading.value = false
  }
}

function fitAll() {
  if (!map.value || !drawn.value) return
  const bounds = drawn.value.getBounds()
  if (bounds && bounds.isValid()) map.value.fitBounds(bounds.pad(0.1))
}

function toGeoJSON() {
  if (!drawn.value) return { type: 'FeatureCollection', features: [] }
  const geojson = drawn.value.toGeoJSON()
  if (!geojson?.features) geojson.features = []
  // ensure stable properties
  for (const f of geojson.features) {
    if (!f.properties) f.properties = {}
    if (!f.properties.zone_id) f.properties.zone_id = `zone_${Math.random().toString(16).slice(2, 8)}`
    if (!f.properties.name) f.properties.name = f.properties.zone_id
  }
  return geojson
}

async function save() {
  if (!dirty.value) return
  saving.value = true
  try {
    const geojson = toGeoJSON()
    const resp = await updateZones(geojson)
    zonesVersion.value = resp.zones_version ?? zonesVersion.value
    dirty.value = false
    showToast({ type: 'success', message: '保存成功：区域已更新' })
  } catch (e) {
    console.error(e)
    showToast({ type: 'fail', message: `保存失败：${e?.message || e}` })
  } finally {
    saving.value = false
  }
}

async function onFile(e) {
  const f = e?.target?.files?.[0]
  if (!f) return
  if (featureCount.value) {
    try {
      await showConfirmDialog({ title: '确认导入', message: '导入会替换当前编辑内容（未保存的改动会丢失），是否继续？' })
    } catch {
      if (fileEl.value) fileEl.value.value = ''
      return
    }
  }
  try {
    const text = await f.text()
    const geojson = JSON.parse(text)
    setFromGeoJSON(geojson)
    markDirty()
    fitAll()
  } catch (err) {
    console.error(err)
    showToast({ type: 'fail', message: `导入失败：${err?.message || err}` })
  } finally {
    if (fileEl.value) fileEl.value.value = ''
  }
}

function exportGeoJSON() {
  const geojson = toGeoJSON()
  const blob = new Blob([JSON.stringify(geojson, null, 2)], { type: 'application/geo+json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `zones_${Date.now()}.geojson`
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

watch(selectedName, (v) => {
  const layer = selectedLayer.value
  if (!layer) return
  normalizeFeatureProps(layer)
  if ((layer.feature.properties?.name || '') !== v) {
    layer.feature.properties.name = v
    markDirty()
  }
})

watch(selectedZoneId, (v) => {
  const layer = selectedLayer.value
  if (!layer) return
  normalizeFeatureProps(layer)
  if ((layer.feature.properties?.zone_id || '') !== v) {
    layer.feature.properties.zone_id = v
    markDirty()
  }
})

onMounted(async () => {
  // Leaflet default icon fix for Vite
  // eslint-disable-next-line no-underscore-dangle
  delete L.Icon.Default.prototype._getIconUrl
  L.Icon.Default.mergeOptions({
    iconRetinaUrl: new URL('leaflet/dist/images/marker-icon-2x.png', import.meta.url).toString(),
    iconUrl: new URL('leaflet/dist/images/marker-icon.png', import.meta.url).toString(),
    shadowUrl: new URL('leaflet/dist/images/marker-shadow.png', import.meta.url).toString(),
  })

  // tap=false is a known fix for touch/PointerEvent environments where leaflet-draw
  // can lose drag/move events on the very first draw interaction.
  map.value = L.map(mapEl.value, { zoomControl: true, tap: false }).setView([40.7308, -73.9973], 14)
  // Avoid interaction conflicts with leaflet-draw (dblclick zoom / box zoom).
  map.value.doubleClickZoom?.disable()
  map.value.boxZoom?.disable()
  // 后端同源瓦片代理：OSM France 镜像 (WGS84原生无偏移，国内200可直连)
  L.tileLayer('/api/tiles/osmfr/{z}/{x}/{y}', {
    maxZoom: 20,
  }).addTo(map.value)

  drawn.value = new L.FeatureGroup()
  map.value.addLayer(drawn.value)

  const drawControl = new L.Control.Draw({
    position: 'topleft',
    draw: {
      polyline: false,
      circle: false,
      circlemarker: false,
      marker: false,
      // Disable leaflet-draw creation (kept only for edit/remove).
      // Creation is handled by our custom tools above for stability.
      polygon: false,
      rectangle: false,
    },
    edit: {
      featureGroup: drawn.value,
      remove: true,
    },
  })
  map.value.addControl(drawControl)

  function setDrawMode(active) {
    // Reduce interference with drag/scroll during drawing (esp. rectangle drag).
    if (!map.value) return
    if (active) {
      map.value.dragging?.disable()
      map.value.scrollWheelZoom?.disable()
    } else {
      map.value.dragging?.enable()
      map.value.scrollWheelZoom?.enable()
    }
  }

  map.value.on('draw:drawstart', () => setDrawMode(true))
  map.value.on('draw:drawstop', () => setDrawMode(false))
  map.value.on('draw:editstart', () => {
    stopDraw()
    setDrawMode(false)
  })
  map.value.on('draw:deletestart', () => {
    stopDraw()
    setDrawMode(false)
  })

  map.value.on(L.Draw.Event.CREATED, (evt) => {
    const layer = evt.layer
    normalizeFeatureProps(layer)
    layer.feature.geometry = layer.toGeoJSON().geometry
    bindLayerEvents(layer)
    drawn.value.addLayer(layer)
    selectLayer(layer)
    markDirty()
  })

  map.value.on(L.Draw.Event.EDITED, (evt) => {
    evt.layers.eachLayer((layer) => {
      normalizeFeatureProps(layer)
      layer.feature.geometry = layer.toGeoJSON().geometry
    })
    markDirty()
  })

  map.value.on(L.Draw.Event.DELETED, () => {
    selectLayer(null)
    markDirty()
  })

  // initial load
  try {
    await reload()
  } catch (e) {
    console.error('zones reload failed:', e)
    // fallback: call old helper (kept for compatibility if backend returns unexpected shape)
    fetchZones().catch(() => {})
  }

  // Ensure correct initial sizing; Leaflet-draw relies on consistent container box.
  await nextTick()
  setTimeout(() => {
    try {
      map.value?.invalidateSize()
    } catch {}
  }, 120)

  // Keep size in sync on first interaction / resizes.
  if (window.ResizeObserver && mapEl.value) {
    mapResizeObserver = new ResizeObserver(() => {
      try {
        map.value?.invalidateSize()
      } catch {}
    })
    mapResizeObserver.observe(mapEl.value)
  }
})

onBeforeUnmount(() => {
  stopDraw()
  if (mapResizeObserver) {
    try {
      mapResizeObserver.disconnect()
    } catch {}
    mapResizeObserver = null
  }
  if (map.value) map.value.remove()
  map.value = null
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
.body {
  margin-top: 14px;
  display: grid;
  grid-template-columns: 1fr 360px;
  gap: 14px;
}
.mapCard {
  border: 1px solid #1f1f1f;
  background: #141414;
  border-radius: 8px;
  
  overflow: hidden;
  position: relative;
}
.mapHead {
  padding: 10px 12px;
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  border-bottom: 1px solid #222222;
  background: #161616;
}
.mapTitle {
  font-weight: 800;
}
.mapHint {
  font-size: 12px;
  color: #8b8b8b;
}
.map {
  height: calc(100vh - 260px);
  min-height: 560px;
}
.hint {
  position: absolute;
  left: 12px;
  bottom: 12px;
  right: 12px;
  max-width: 760px;
  border: 1px solid #1f1f1f;
  background: rgba(20, 20, 20, 0.85);
  backdrop-filter: blur(10px);
  border-radius: 8px;
  padding: 10px 12px;
  display: grid;
  gap: 6px;
  pointer-events: none;
}
.hRow {
  display: grid;
  grid-template-columns: 56px 1fr;
  gap: 10px;
  font-size: 12px;
}
.k {
  color: #8b8b8b;
  font-weight: 900;
}
.v {
  color: #d4d4d4;
}
.side {
  display: flex;
  flex-direction: column;
  gap: 14px;
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
.field {
  display: grid;
  gap: 6px;
  margin-bottom: 10px;
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
.input:disabled {
  opacity: 0.55;
}
.importRow {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}
.tip {
  margin-top: 8px;
  font-size: 12px;
  color: #8b8b8b;
}
@media (max-width: 1100px) {
  .body {
    grid-template-columns: 1fr;
  }
  .map {
    height: 64vh;
  }
}
</style>

