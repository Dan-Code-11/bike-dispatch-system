<template>
  <div class="wrap">
    <div class="head">
      <div>
        <div class="title">开发者门户</div>
        <div class="sub">OpenAPI 浏览入口、常用接口示例与调试指引。</div>
      </div>
      <div class="actions">
        <button class="btn" @click="openDocs('swagger')">Swagger</button>
        <button class="btn" @click="openDocs('redoc')">ReDoc</button>
      </div>
    </div>

    <div class="grid">
      <div class="card">
        <div class="cardTitle">接口地址</div>
        <div class="kv">
          <div class="row"><span class="k">Backend</span><span class="v mono">{{ backendOrigin }}</span></div>
          <div class="row"><span class="k">REST Base</span><span class="v mono">{{ backendOrigin }}/api</span></div>
          <div class="row"><span class="k">WS Live</span><span class="v mono">{{ wsOrigin }}/api/ws/live</span></div>
        </div>
      </div>

      <div class="card">
        <div class="cardTitle">示例（curl）</div>
        <pre class="code">{{ examples }}</pre>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const backendOrigin = computed(() => {
  // In docker/dev we normally use relative /api through Vite proxy
  return window.location.origin
})

const wsOrigin = computed(() => (location.protocol === 'https:' ? 'wss://' : 'ws://') + location.host)

function openDocs(type) {
  const path = type === 'redoc' ? '/redoc' : '/docs'
  // backend runs on 8000 usually; in Vite dev /docs isn't proxied, so open explicit backend URL.
  window.open(`http://localhost:8000${path}`, '_blank', 'noopener,noreferrer')
}

const examples = `# simulate
curl "http://localhost:8000/api/simulate?time=12:30"

# history
curl "http://localhost:8000/api/history?time=12:30&steps=12"

# predict
curl -X POST "http://localhost:8000/api/predict" -H "Content-Type: application/json" -d "{\\"time\\":\\"12:30\\",\\"history\\":[[0],[0]],\\"zone_order\\":[\\"zone_1\\"]}"

# live dashboard (ws)
# ws://localhost:8000/api/ws/live
`
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
}
.sub {
  margin-top: 6px;
  font-size: 12px;
  color: #8b8b8b;
}
.actions {
  display: flex;
  gap: 10px;
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
.grid {
  margin-top: 14px;
  display: grid;
  grid-template-columns: 1fr 1fr;
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
.k {
  color: #8b8b8b;
  font-weight: 900;
}
.mono {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
  font-size: 12px;
}
.code {
  margin: 0;
  white-space: pre-wrap;
  border: 1px solid #1f1f1f;
  background: rgba(11, 18, 32, 0.55);
  border-radius: 8px;
  padding: 10px;
  color: #d4d4d4;
}
@media (max-width: 1100px) {
  .grid {
    grid-template-columns: 1fr;
  }
}
</style>

