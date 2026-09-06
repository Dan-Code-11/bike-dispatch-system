<template>
  <div class="replay">
    <div class="head">
      <div>
        <div class="title">空间可视化</div>
        <div class="sub">时间回放 · OD 潮汐流线 · Moran/LISA 冷热点 · 典型日对比</div>
      </div>
    </div>
    <div class="body">
      <SpatialLab />
    </div>
  </div>
</template>

<script setup>
import SpatialLab from '../../components/SpatialLab.vue'
</script>

<style scoped>
.replay {
  height: calc(100vh - 32px);
  display: flex;
  flex-direction: column;
  gap: 4px;
  color: #FFFFFF;
  font-family: -apple-system, 'Segoe UI', "PingFang SC", "Microsoft YaHei", sans-serif;
}
.head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
  padding: 14px 16px;
  border: 1px solid #222222;
  background: #141414;
  border-radius: 10px;
  flex-shrink: 0;
}
.title { font-weight: 800; font-size: 16px; color: #FFFFFF; }
.sub { margin-top: 4px; font-size: 12px; color: #8B8B8B; }
.body { flex: 1; min-height: 0; }
</style>
