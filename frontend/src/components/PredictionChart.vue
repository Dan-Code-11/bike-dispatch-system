<template>
  <div class="wrap">
    <template v-if="!zoneId">
      <div class="empty">点击地图站点，查看该站供需曲线与调度建议</div>
    </template>
    <template v-else>
      <div class="head">
        <span class="name">{{ zoneName }}</span>
        <span class="badge">{{ currentVehicles ?? '-' }} 辆<span v-if="capacity"> / 容量 {{ capacity }}</span></span>
      </div>
      <div ref="chartRef" class="chart"></div>
      <div class="chips" v-if="anchors.length">
        <div
          v-for="a in anchors"
          :key="a.label"
          class="chip"
          :class="needClass(a.need)"
          :title="`${a.label}（${a.time}）调度量 ${fmtNeed(a.need)}`"
        >
          <span class="chipLabel">{{ a.label }}</span>
          <span class="chipVal">{{ fmtNeed(a.need) }}</span>
        </div>
      </div>
    </template>
  </div>
</template>

<script setup>
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts'

const props = defineProps({
  zoneId: { type: String, default: null },
  zoneName: { type: String, default: '' },
  currentVehicles: { type: Number, default: null },
  capacity: { type: Number, default: null },
  historyTimes: { type: Array, default: () => [] },
  historySeries: { type: Array, default: () => [] },
  curveTimes: { type: Array, default: () => [] },
  curveSeriesLSTM: { type: Array, default: () => [] },
  curveSeriesPersistent: { type: Array, default: () => [] },
  anchors: { type: Array, default: () => [] },
  worstHorizon: { type: Object, default: null },
})

const chartRef = ref(null)
let chart = null

function needClass(n) {
  if (n == null) return ''
  if (n >= 3) return 'shortage'
  if (n <= -3) return 'surplus'
  return 'ok'
}
function fmtNeed(n) {
  if (n == null || Number.isNaN(n)) return '平衡'
  const v = Math.round(n)
  if (v > 0) return `+${v}`
  if (v < 0) return `${v}`
  return '平衡'
}

async function ensureChart() {
  if (chart) return
  if (!chartRef.value) return
  chart = echarts.init(chartRef.value)
}

function render() {
  if (!chart) return
  const historyTimes = props.historyTimes || []
  const curveTimes = props.curveTimes || []
  const history = props.historySeries || []
  const lstm = props.curveSeriesLSTM || []
  const categories = [...historyTimes, ...curveTimes]

  // 锚点在曲线上打点（对齐时间）
  const anchorScatter = []
  for (const a of props.anchors || []) {
    const idx = categories.indexOf(a.time)
    if (idx < 0) continue
    anchorScatter.push({
      value: [idx, Math.round(a.vehicles)],
      symbol: 'circle',
      symbolSize: 11,
      itemStyle: { color: '#06C167', borderColor: '#0A0A0A', borderWidth: 2 },
      label: {
        show: true,
        formatter: a.label,
        position: 'top',
        color: '#06C167',
        fontWeight: 700,
        fontSize: 11,
      },
    })
  }

  const historyPad = Array(curveTimes.length).fill(null)
  const lstmPad = Array(historyTimes.length).fill(null)
  const splitLineIdx = historyTimes.length - 0.5
  const axisLabelInterval = Math.max(0, Math.floor(categories.length / 10) - 1)

  chart.setOption(
    {
      tooltip: { trigger: 'axis', axisPointer: { type: 'cross' } },
      grid: { left: 8, right: 8, bottom: 24, top: 26, containLabel: true },
      legend: {
        data: ['已发生', '预测（未来3h）'],
        top: 0,
        right: 0,
        textStyle: { color: '#8B8B8B', fontSize: 11 },
        itemWidth: 14,
        itemHeight: 8,
      },
      xAxis: {
        type: 'category',
        data: categories,
        axisLabel: { interval: axisLabelInterval, rotate: 30, fontSize: 10, color: '#5A5A5A' },
        axisLine: { lineStyle: { color: '#262626' } },
        axisTick: { show: false },
      },
      yAxis: {
        type: 'value',
        name: '车辆数',
        nameTextStyle: { color: '#5A5A5A', fontSize: 10 },
        axisLabel: { fontSize: 10, color: '#5A5A5A' },
        splitLine: { lineStyle: { color: '#1F1F1F' } },
      },
      series: [
        {
          type: 'line',
          name: '已发生',
          data: [...history, ...historyPad],
          smooth: true,
          symbol: 'none',
          lineStyle: { width: 2, color: '#8B8B8B' },
          itemStyle: { color: '#8B8B8B' },
          areaStyle: {
            color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
              { offset: 0, color: 'rgba(139,139,139,0.22)' },
              { offset: 1, color: 'rgba(139,139,139,0.02)' },
            ]),
          },
        },
        {
          type: 'line',
          name: '预测（未来3h）',
          data: [...lstmPad, ...lstm],
          smooth: true,
          symbol: 'none',
          lineStyle: { width: 2.5, color: '#06C167' },
          itemStyle: { color: '#06C167' },
          areaStyle: {
            color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
              { offset: 0, color: 'rgba(6,193,103,0.28)' },
              { offset: 1, color: 'rgba(6,193,103,0.02)' },
            ]),
          },
          markLine: {
            silent: true,
            symbol: 'none',
            lineStyle: { color: '#3A3A3A', type: 'dashed', width: 1 },
            label: { formatter: '现在 → 未来', position: 'insideEndTop', color: '#5A5A5A', fontSize: 10 },
            data: [{ xAxis: splitLineIdx }],
          },
        },
        {
          type: 'scatter',
          name: '',
          data: anchorScatter,
          coordinateSystem: 'cartesian2d',
        },
      ],
      animation: false,
    },
    true,
  )
}

onMounted(async () => {
  await nextTick()
  if (props.zoneId) {
    await ensureChart()
    render()
  }
})

watch(
  () => props.zoneId,
  async () => {
    await nextTick()
    if (!props.zoneId) {
      if (chart) { chart.dispose(); chart = null }
      return
    }
    await ensureChart()
    render()
  },
)

watch(
  () => [props.currentVehicles, props.capacity, props.historyTimes, props.historySeries, props.curveTimes, props.curveSeriesLSTM, props.anchors],
  async () => {
    await nextTick()
    if (!props.zoneId) return
    await ensureChart()
    render()
  },
  { deep: true },
)

let _resizeTimer = null
function onWinResize() {
  if (_resizeTimer) clearTimeout(_resizeTimer)
  _resizeTimer = setTimeout(() => chart?.resize(), 120)
}

onBeforeUnmount(() => {
  if (chart) chart.dispose()
  chart = null
})
</script>

<style scoped>
.wrap { display: flex; flex-direction: column; gap: 10px; }
.empty { color: #5A5A5A; font-size: 12px; padding: 24px 0; text-align: center; }
.head { display: flex; align-items: baseline; justify-content: space-between; gap: 10px; }
.name { font-weight: 800; font-size: 13px; color: #FFFFFF; }
.badge { font-size: 12px; color: #8B8B8B; background: #1A1A1A; padding: 3px 9px; border-radius: 999px; }
.chart { width: 100%; height: 210px; }
.chips { display: flex; gap: 6px; }
.chip {
  flex: 1; display: flex; flex-direction: column; gap: 2px;
  padding: 6px 8px; border-radius: 8px; border: 1px solid #262626; background: #1A1A1A;
}
.chipLabel { font-size: 10px; color: #5A5A5A; }
.chipVal { font-size: 13px; font-weight: 800; }
.chip.shortage .chipVal { color: #F04438; }
.chip.surplus .chipVal { color: #06C167; }
.chip.ok .chipVal { color: #8B8B8B; }
</style>
