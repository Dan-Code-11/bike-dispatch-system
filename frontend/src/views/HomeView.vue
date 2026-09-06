<template>
  <div class="home">
    <!-- 顶部：品牌 + 状态 -->
    <header class="header">
      <div class="title-block">
        <div class="gis-brand-row">
          <span class="gis-badge">GIS · Spatio-Temporal</span>
          <span class="gis-sub">Citi Bike NYC · Rebalancing Analytics</span>
        </div>
        <h1 class="title">潮汐调度总览</h1>
        <p class="subtitle">151 天 × 30 站 × 5 分钟 · 真实时空立方体</p>
      </div>
      <div class="status-badge" :class="statusClass">
        <span class="dot"></span>
        <span>{{ statusText }}</span>
      </div>
    </header>

    <!-- A · 状态总览行 -->
    <section class="overview">
      <div class="ov-main">
        <div class="ov-time">{{ stats?.time || '--:--' }} 实时快照</div>
        <div class="ov-metrics">
          <div class="m">
            <span class="mLabel">监控站点</span>
            <span class="mVal">{{ stats?.zones_count ?? '—' }}</span>
          </div>
          <div class="m">
            <span class="mLabel">在库车辆</span>
            <span class="mVal">{{ stats?.current_total_bikes ?? '—' }}</span>
          </div>
          <div class="m warn">
            <span class="mLabel">短缺站</span>
            <span class="mVal">{{ stats?.shortage_zone_count ?? '—' }}</span>
          </div>
          <div class="m danger">
            <span class="mLabel">富余站</span>
            <span class="mVal">{{ stats?.surplus_zone_count ?? '—' }}</span>
          </div>
        </div>
      </div>
      <div class="ov-ratio">
        <div ref="ratioEl" class="ratioChart"></div>
        <div class="ratioHint">供需占比</div>
      </div>
      <button class="cta" @click="go('/dashboard/live')">
        进入调度大屏
        <span class="ctaArrow">→</span>
      </button>
    </section>

    <!-- B · 核心入口 -->
    <section class="nav-section">
      <div class="section-title">
        <h2>工作台</h2>
        <span class="tag">常用入口</span>
      </div>
      <div class="nav-grid">
        <button class="nav-card primary" @click="go('/dashboard/live')">
          <span class="nav-icon">
            <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6l6-3 6 3 6-3v15l-6 3-6-3-6 3V6z M9 3v15 M15 6v15"/></svg>
          </span>
          <div class="nav-text">
            <div class="nav-title">调度大屏</div>
            <div class="nav-desc">实时调度 · 预测 · 一键调度 · 单站详情</div>
          </div>
          <span class="nav-badge" :class="badgeTone">{{ liveBadge }}</span>
        </button>
        <button class="nav-card" @click="go('/ops/analytics')">
          <span class="nav-icon">
            <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 3v18h18 M7 15v4 M12 11v8 M17 7v12"/></svg>
          </span>
          <div class="nav-text">
            <div class="nav-title">运营分析</div>
            <div class="nav-desc">KPI · 分布 · 明细 · 实时/固定时刻</div>
          </div>
          <span class="nav-badge">实时</span>
        </button>
        <button class="nav-card" @click="go('/ops/replay')">
          <span class="nav-icon">
            <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3a9 9 0 1 0 9 9 M12 7v5l3 2 M21 3v6h-6"/></svg>
          </span>
          <div class="nav-text">
            <div class="nav-title">空间可视化</div>
            <div class="nav-desc">时间回放 · OD · Moran · 典型日</div>
          </div>
          <span class="nav-badge">4 图层</span>
        </button>
        <button class="nav-card" @click="go('/alerts')">
          <span class="nav-icon">
            <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3 2 20h20L12 3z M12 10v4 M12 17h.01"/></svg>
          </span>
          <div class="nav-text">
            <div class="nav-title">预警中心</div>
            <div class="nav-desc">短缺/富余预警规则与历史</div>
          </div>
          <span class="nav-badge">规则</span>
        </button>
      </div>
    </section>

    <!-- 数据声明 -->
    <footer class="foot">
      <div><b>Data Source:</b> Citi Bike NYC (Lyft) · 2025-01 ~ 2025-05 parquet · 5 months public ridership</div>
      <div><b>Tech Stack:</b> Vue 3 · FastAPI · Leaflet + OSRM · ECharts · LSTM Prediction · Min-Cost Flow Dispatch</div>
    </footer>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import * as echarts from 'echarts'
import { fetchDashboardStats } from '../api'

const router = useRouter()
const stats = ref(null)
const err = ref(false)

const ratioEl = ref(null)
let ratioChart = null

const statusClass = computed(() => (err.value ? 'err' : stats.value ? 'ok' : 'loading'))
const statusText = computed(() => {
  if (err.value) return '后端未连接'
  if (!stats.value) return '加载中'
  return '运行中'
})

const liveBadge = computed(() => {
  if (!stats.value) return '—'
  return `短缺 ${stats.value.shortage_zone_count} · 富余 ${stats.value.surplus_zone_count}`
})
const badgeTone = computed(() => {
  if (!stats.value) return ''
  const s = stats.value.shortage_zone_count
  const p = stats.value.surplus_zone_count
  if (s > 0 && p > 0) return 'mixed'
  if (s > 0) return 'warn'
  if (p > 0) return 'danger'
  return ''
})

function go(path) { router.push(path) }

function renderRatio() {
  if (!ratioEl.value || !stats.value) return
  if (!ratioChart) ratioChart = echarts.init(ratioEl.value)
  const total = stats.value.zones_count || 0
  const short = stats.value.shortage_zone_count || 0
  const sur = stats.value.surplus_zone_count || 0
  const healthy = Math.max(0, total - short - sur)
  const pct = total > 0 ? Math.round((healthy / total) * 100) : 0
  ratioChart.setOption(
    {
      tooltip: {
        trigger: 'item',
        backgroundColor: '#1A1A1A',
        borderColor: '#2A2A2A',
        textStyle: { color: '#fff', fontSize: 11 },
        formatter: function () {
          return `健康 ${healthy} 站 · 短缺 ${short} 站 · 富余 ${sur} 站`
        },
      },
      series: [
        {
          type: 'gauge',
          center: ['50%', '48%'],
          radius: '68%',
          startAngle: 90,
          endAngle: -270,
          pointer: { show: false },
          progress: {
            show: true,
            overlap: false,
            roundCap: true,
            clip: false,
            itemStyle: {
              color: {
                type: 'linear',
                x: 0, y: 0, x2: 1, y2: 1,
                colorStops: [
                  { offset: 0, color: '#06C167' },
                  { offset: 1, color: '#04a858' },
                ],
              },
            },
          },
          axisLine: {
            lineStyle: {
              width: 10,
              color: [[1, 'rgba(255,255,255,0.06)']],
            },
          },
          splitLine: { show: false },
          axisTick: { show: false },
          axisLabel: { show: false },
          title: { show: false },
          detail: { show: false },
          data: [{ value: pct }],
        },
        {
          type: 'gauge',
          center: ['50%', '48%'],
          radius: '68%',
          startAngle: 90,
          endAngle: -270,
          pointer: { show: false },
          progress: { show: false },
          axisLine: { show: false },
          splitLine: { show: false },
          axisTick: { show: false },
          axisLabel: { show: false },
          title: { show: false },
          detail: {
            valueAnimation: true,
            offsetCenter: [0, '-2%'],
            formatter: function () {
              return `{num|${total}}\n{label|站点}`
            },
            rich: {
              num: {
                fontSize: 18,
                fontWeight: 800,
                color: '#fff',
                lineHeight: 22,
              },
              label: {
                fontSize: 9,
                color: '#8B8B8B',
                fontWeight: 400,
                lineHeight: 12,
              },
            },
          },
          data: [{ value: 0 }],
        },
      ],
    },
    true
  )
}

async function load() {
  try {
    const s = await fetchDashboardStats({ threshold: 5 }).catch(() => null)
    if (s) stats.value = s
    if (!s) err.value = true
    await nextTick()
    renderRatio()
  } catch (e) {
    err.value = true
  }
}

function onResize() {
  ratioChart?.resize()
}

onMounted(() => {
  load()
  window.addEventListener?.('resize', onResize)
})
onBeforeUnmount(() => {
  window.removeEventListener?.('resize', onResize)
  ratioChart?.dispose()
  ratioChart = null
})
</script>

<style scoped>
.home {
  min-height: 100%;
  padding: 28px 40px 40px;
  color: #fff;
  background: #0a0a0a;
}

/* ======= Header ======= */
.header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 20px;
}
.gis-brand-row { display: flex; align-items: center; gap: 8px; margin-bottom: 10px; }
.gis-badge {
  font-size: 11px; font-weight: 700; letter-spacing: 0.4px; text-transform: uppercase;
  color: #06c167;
  background: rgba(6, 193, 103, 0.12);
  border: 1px solid rgba(6, 193, 103, 0.28);
  border-radius: 999px; padding: 4px 12px;
}
.gis-sub { font-size: 12px; color: #8b8b8b; }
.title {
  font-size: 28px;
  font-weight: 800;
  margin: 0;
  color: #fff;
  letter-spacing: -0.2px;
}
.subtitle {
  font-size: 13px;
  color: #8b8b8b;
  margin: 8px 0 0;
  line-height: 1.6;
}
.status-badge {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 6px 14px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 600;
  border: 1px solid;
  white-space: nowrap;
}
.status-badge .dot { width: 8px; height: 8px; border-radius: 50%; }
.status-badge.ok { color: #06c167; border-color: rgba(6,193,103,0.3); background: rgba(6,193,103,0.08); }
.status-badge.ok .dot { background: #06c167; }
.status-badge.loading { color: #ffb224; border-color: rgba(255,178,36,0.3); background: rgba(255,178,36,0.08); }
.status-badge.loading .dot { background: #ffb224; }
.status-badge.err { color: #f04438; border-color: rgba(240,68,56,0.3); background: rgba(240,68,56,0.08); }
.status-badge.err .dot { background: #f04438; }

/* ======= A · 状态总览行 ======= */
.overview {
  display: flex;
  align-items: stretch;
  gap: 14px;
  border: 1px solid #1f1f1f;
  background: #141414;
  border-radius: 14px;
  padding: 16px 18px;
  margin-bottom: 26px;
}
.ov-main { flex: 1; min-width: 0; display: flex; flex-direction: column; justify-content: space-between; gap: 12px; }
.ov-time { font-size: 12px; color: #8b8b8b; font-weight: 700; letter-spacing: 0.3px; }
.ov-metrics { display: flex; gap: 10px; flex-wrap: wrap; }
.m {
  flex: 1 1 100px; min-width: 0;
  background: #1a1a1a; border: 1px solid #1f1f1f; border-radius: 10px;
  padding: 10px 12px;
  display: flex; flex-direction: column; gap: 6px;
}
.mLabel { font-size: 11px; color: #8b8b8b; }
.mVal { font-size: 26px; font-weight: 800; color: #fff; line-height: 1; font-variant-numeric: tabular-nums; }
.m.warn .mVal { color: #ffb224; }
.m.danger .mVal { color: #f04438; }
.ov-ratio {
  width: 128px; flex-shrink: 0;
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  border-left: 1px solid #1f1f1f; padding-left: 14px;
}
.ratioChart { width: 92px; height: 92px; }
.ratioHint { font-size: 11px; color: #8b8b8b; margin-top: 2px; }
.cta {
  align-self: center;
  border: 1px solid rgba(6,193,103,0.5);
  background: rgba(6,193,103,0.14);
  color: #06c167;
  border-radius: 12px;
  padding: 18px 22px;
  font-size: 15px; font-weight: 800;
  cursor: pointer;
  white-space: nowrap;
  display: flex; align-items: center; gap: 10px;
  transition: background 0.15s ease;
}
.cta:hover { background: rgba(6,193,103,0.28); color: #fff; }
.ctaArrow { font-size: 18px; }

/* ======= B · 核心入口 ======= */
.nav-section { margin-bottom: 26px; }
.nav-grid {
  display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px;
}
.nav-card {
  display: flex; align-items: center; gap: 14px;
  padding: 16px 16px;
  background: #141414;
  border: 1px solid #1f1f1f;
  border-radius: 12px;
  cursor: pointer; text-align: left; color: inherit; font: inherit;
  transition: border-color 0.15s ease, background 0.15s ease;
}
.nav-card:hover {
  background: #1a1a1a;
  border-color: rgba(6,193,103,0.35);
}
.nav-card.primary {
  border-color: rgba(6, 193, 103, 0.4);
}
.nav-icon {
  font-size: 20px; color: #06c167;
  width: 40px; height: 40px;
  display: flex; align-items: center; justify-content: center;
  background: rgba(6,193,103,0.1);
  border-radius: 9px; flex-shrink: 0;
}
.nav-text { flex: 1; min-width: 0; }
.nav-title { font-size: 14px; font-weight: 700; color: #fff; margin-bottom: 2px; }
.nav-desc { font-size: 12px; color: #8b8b8b; line-height: 1.45; }
.nav-badge {
  flex-shrink: 0;
  font-size: 11px; font-weight: 700;
  padding: 3px 9px; border-radius: 999px;
  background: rgba(255,255,255,0.06); color: #8b8b8b;
  border: 1px solid rgba(255,255,255,0.1);
}
.nav-badge.warn { color: #ffb224; border-color: rgba(255,178,36,0.35); background: rgba(255,178,36,0.1); }
.nav-badge.danger { color: #f04438; border-color: rgba(240,68,56,0.35); background: rgba(240,68,56,0.1); }
.nav-badge.mixed { color: #ffb224; border-color: rgba(255,178,36,0.35); background: rgba(255,178,36,0.1); }

/* ======= Section titles ======= */
.section-title {
  display: flex; align-items: center; justify-content: space-between;
  margin-bottom: 12px;
}
.section-title h2 {
  font-size: 15px; font-weight: 700; margin: 0; color: #fff;
}
.tag {
  font-size: 11px; padding: 3px 10px;
  border-radius: 999px; font-weight: 700;
  background: rgba(255,255,255,0.05); color: #8b8b8b;
  border: 1px solid rgba(255,255,255,0.1);
}

/* ======= Foot ======= */
.foot {
  margin-top: 14px; padding: 14px 18px;
  background: #141414;
  border: 1px dashed #262626;
  border-radius: 10px;
  font-size: 12px; line-height: 1.75;
  color: #8b8b8b;
}
.foot b { color: #c9c9c9; font-weight: 700; }

@media (max-width: 1200px) {
  .home { padding: 20px; }
  .nav-grid { grid-template-columns: repeat(2, 1fr); }
  .overview { flex-wrap: wrap; }
  .ov-ratio { border-left: none; padding-left: 0; border-top: 1px solid #1f1f1f; padding-top: 10px; width: 100%; flex-direction: row; gap: 10px; }
  .cta { align-self: auto; width: 100%; justify-content: center; }
}
@media (max-width: 700px) {
  .title { font-size: 22px; }
  .nav-grid { grid-template-columns: 1fr; }
  .ov-metrics { grid-template-columns: repeat(2, 1fr); }
}
</style>
