<template>
  <div class="wrap">
    <div class="head">
      <div>
        <div class="title">系统健康</div>
        <div class="sub">快速检查后端关键接口可用性（用于部署验证）。</div>
      </div>
      <div class="actions">
        <button class="btn" @click="run" :disabled="loading">{{ loading ? '检查中…' : '立即检查' }}</button>
      </div>
    </div>

    <div class="grid">
      <div class="card" v-for="c in checks" :key="c.name">
        <div class="cardTitle">{{ c.name }}</div>
        <div class="line">
          <span class="k">状态</span>
          <span class="pill" :class="{ ok: c.ok, bad: c.ok === false }">{{ c.ok == null ? '未检查' : c.ok ? 'OK' : 'FAIL' }}</span>
        </div>
        <div class="line"><span class="k">耗时</span><span class="v">{{ c.ms == null ? '-' : c.ms + 'ms' }}</span></div>
        <div class="line"><span class="k">详情</span><span class="v mono">{{ c.detail || '-' }}</span></div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { showToast } from 'vant'

const loading = ref(false)
const checks = ref([
  { name: 'simulate', url: '/api/simulate?time=12:30', ok: null, ms: null, detail: '' },
  { name: 'zones', url: '/api/zones', ok: null, ms: null, detail: '' },
  { name: 'monitor/stats', url: '/api/monitor/stats', ok: null, ms: null, detail: '' },
  { name: 'alerts/rules', url: '/api/alerts/rules', ok: null, ms: null, detail: '' },
  { name: 'lab/model/status', url: '/api/lab/model/status', ok: null, ms: null, detail: '' },
])

async function run() {
  loading.value = true
  try {
    for (const c of checks.value) {
      const t0 = performance.now()
      try {
        const res = await fetch(c.url)
        c.ok = res.ok
        c.ms = Math.round(performance.now() - t0)
        c.detail = `${res.status}`
      } catch (e) {
        c.ok = false
        c.ms = Math.round(performance.now() - t0)
        c.detail = e?.message || String(e)
      }
    }
    showToast({ type: 'success', message: '检查完成' })
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.wrap { color: #c9c9c9; }
.head {
  display:flex; justify-content:space-between; align-items:flex-start; gap:12px;
  padding:14px 14px 12px; border:1px solid #1f1f1f; background:#141414;
  border-radius:8px; 
}
.title { font-weight:800; }
.sub { margin-top:6px; font-size:12px; color:#8b8b8b; }
.actions { display:flex; gap:10px; }
.btn {
  border:1px solid #262626; background:#1a1a1a; color:#e6e6e6;
  border-radius:8px; padding:9px 12px; cursor:pointer; transition:transform .12s ease, box-shadow .12s ease, background .12s ease;
}
.btn:hover { background:#222222; }
.grid { margin-top:14px; display:grid; grid-template-columns: 1fr 1fr 1fr; gap:14px; }
.card {
  border:1px solid #1f1f1f; background:#141414; border-radius:8px;
   padding:12px;
}
.cardTitle { font-weight:800; margin-bottom:10px; }
.line { display:flex; justify-content:space-between; gap:10px; margin-top:6px; font-size:13px; }
.k { color: #8b8b8b; font-weight:900; }
.v { color: #c9c9c9; text-align:right; }
.mono { font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace; font-size:12px; }
.pill { padding:3px 8px; border-radius:999px; border:1px solid #262626; background:#1a1a1a; font-weight:800; }
.pill.ok { border-color: rgba(26,152,80,.55); background: rgba(26,152,80,.14); }
.pill.bad { border-color: rgba(215,48,39,.55); background: rgba(215,48,39,.14); }
@media (max-width: 1100px) {
  .grid { grid-template-columns: 1fr; }
}
</style>

