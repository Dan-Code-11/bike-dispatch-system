export const API_BASE = '/api'

export async function fetchZones() {
  const res = await fetch(`${API_BASE}/zones`)
  if (!res.ok) throw new Error(`zones failed: ${res.status}`)
  return await res.json()
}

export async function simulate(time) {
  const url = `${API_BASE}/simulate?time=${encodeURIComponent(time)}`
  const res = await fetch(url)
  if (!res.ok) throw new Error(`simulate failed: ${res.status}`)
  return await res.json()
}

export async function fetchHistory(time, steps = 24) {
  const url = `${API_BASE}/history?time=${encodeURIComponent(time)}&steps=${encodeURIComponent(steps)}`
  const res = await fetch(url)
  if (!res.ok) throw new Error(`history failed: ${res.status}`)
  return await res.json()
}

export async function predict15Min({ time, history, zone_order }) {
  const res = await fetch(`${API_BASE}/predict`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ time, history, zone_order }),
  })
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw new Error(`predict failed: ${res.status} ${text}`)
  }
  return await res.json()
}
export const predictMulti3Hour = predict15Min

export async function dispatchPlans(payload) {
  const res = await fetch(`${API_BASE}/dispatch`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw new Error(`dispatch failed: ${res.status} ${text}`)
  }
  return await res.json()
}

export async function updateZones(geojson) {
  const res = await fetch(`${API_BASE}/zones/update`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ geojson }),
  })
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw new Error(`zones/update failed: ${res.status} ${text}`)
  }
  return await res.json()
}

export async function fetchDashboardStats({ time, threshold = 5 } = {}) {
  const q = new URLSearchParams()
  if (time) q.set('time', time)
  q.set('threshold', String(threshold))
  const url = `${API_BASE}/dashboard/stats?${q.toString()}`
  const res = await fetch(url)
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw new Error(`dashboard stats failed: ${res.status} ${text}`)
  }
  return await res.json()
}

export async function listAlertRules() {
  const res = await fetch(`${API_BASE}/alerts/rules`)
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw new Error(`alerts/rules failed: ${res.status} ${text}`)
  }
  return await res.json()
}

export async function createAlertRule(payload) {
  const res = await fetch(`${API_BASE}/alerts/rules`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw new Error(`alerts/rules create failed: ${res.status} ${text}`)
  }
  return await res.json()
}

export async function updateAlertRule(ruleId, patch) {
  const res = await fetch(`${API_BASE}/alerts/rules/${encodeURIComponent(ruleId)}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(patch),
  })
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw new Error(`alerts/rules update failed: ${res.status} ${text}`)
  }
  return await res.json()
}

export async function deleteAlertRule(ruleId) {
  const res = await fetch(`${API_BASE}/alerts/rules/${encodeURIComponent(ruleId)}`, { method: 'DELETE' })
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw new Error(`alerts/rules delete failed: ${res.status} ${text}`)
  }
  return await res.json()
}

export async function checkAlerts({ time } = {}) {
  const res = await fetch(`${API_BASE}/alerts/check`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ time }),
  })
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw new Error(`alerts/check failed: ${res.status} ${text}`)
  }
  return await res.json()
}

export async function listAlertHistory({ limit = 100 } = {}) {
  const q = new URLSearchParams()
  q.set('limit', String(limit))
  const res = await fetch(`${API_BASE}/alerts/history?${q.toString()}`)
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw new Error(`alerts/history failed: ${res.status} ${text}`)
  }
  return await res.json()
}

export async function fetchModelStatus() {
  const res = await fetch(`${API_BASE}/lab/model/status`)
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw new Error(`lab/model/status failed: ${res.status} ${text}`)
  }
  return await res.json()
}

export async function trainModel(params = {}) {
  const res = await fetch(`${API_BASE}/lab/model/train`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params || {}),
  })
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw new Error(`lab/model/train failed: ${res.status} ${text}`)
  }
  return await res.json()
}

// GIS 空间分析 API（前缀 /api/gis）

export async function fetchTimeline({ time = '00:00', steps = 96, interval = 15, day_index = 0, mode = 'vehicle' } = {}) {
  const q = new URLSearchParams()
  q.set('time', time)
  q.set('steps', String(steps))
  q.set('interval', String(interval))
  q.set('day_index', String(day_index))
  q.set('mode', mode)
  const url = `${API_BASE}/gis/timeline?${q.toString()}`
  const res = await fetch(url)
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw new Error(`gis/timeline failed: ${res.status} ${text}`)
  }
  return await res.json()
}

export async function fetchSpatialStats({ time = '08:30', day_index = 0, weight = 'knn', k = 5, band_m = 800, attr = 'need', threshold_shortage = 3.0, threshold_surplus = 3.0 } = {}) {
  const q = new URLSearchParams()
  q.set('time', time)
  q.set('day_index', String(day_index))
  q.set('weight', weight)
  q.set('k', String(k))
  q.set('band_m', String(band_m))
  q.set('attr', attr)
  q.set('threshold_shortage', String(threshold_shortage))
  q.set('threshold_surplus', String(threshold_surplus))
  const url = `${API_BASE}/gis/spatial_stats?${q.toString()}`
  const res = await fetch(url)
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw new Error(`gis/spatial_stats failed: ${res.status} ${text}`)
  }
  return await res.json()
}

export async function fetchODFlows({ time = '08:30', window_minutes = 60, day_index = 0, top_k = 40, beta = 0.0012 } = {}) {
  const q = new URLSearchParams()
  q.set('time', time)
  q.set('window_minutes', String(window_minutes))
  q.set('day_index', String(day_index))
  q.set('top_k', String(top_k))
  q.set('beta', String(beta))
  const url = `${API_BASE}/gis/od_flows?${q.toString()}`
  const res = await fetch(url)
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw new Error(`gis/od_flows failed: ${res.status} ${text}`)
  }
  return await res.json()
}

export async function fetchTypicalDay({ interval_minutes = 30 } = {}) {
  const q = new URLSearchParams()
  q.set('interval_minutes', String(interval_minutes))
  const url = `${API_BASE}/gis/typical_day?${q.toString()}`
  const res = await fetch(url)
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw new Error(`gis/typical_day failed: ${res.status} ${text}`)
  }
  return await res.json()
}
