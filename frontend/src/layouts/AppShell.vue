<template>
  <div class="shell">
    <aside class="sider" :class="{ collapsed }">
      <div class="brand" @click="go('/')">
        <div class="logo">
          <svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="#000" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">
            <circle cx="6" cy="17" r="4"/>
            <circle cx="18" cy="17" r="4"/>
            <path d="M6 17 L11 9 L15 9 L18 17"/>
            <path d="M11 9 L14.5 17"/>
            <path d="M11 9 L9 6 L7 6"/>
            <path d="M15 9 L17.5 7"/>
          </svg>
        </div>
        <div class="name" v-if="!collapsed">
          <div class="t1">BikeDispatch</div>
          <div class="t2">Citi Bike Rebalancing Dashboard</div>
        </div>
      </div>

      <nav class="nav">
        <div class="group" v-for="g in groups" :key="g.title">
          <div class="gtitle" v-if="!collapsed">{{ g.title }}</div>
          <button
            v-for="item in g.items"
            :key="item.path"
            class="item"
            :class="{ active: route.path === item.path }"
            @click="go(item.path)"
            :title="item.label"
          >
            <span class="icon">
              <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
                <path :d="item.icon" />
              </svg>
            </span>
            <span class="label" v-if="!collapsed">{{ item.label }}</span>
            <span class="spacer"></span>
          </button>
        </div>
      </nav>

      <div class="sider-footer">
        <button class="collapseBtn" @click="collapsed = !collapsed" :title="collapsed ? '展开' : '收起'">
          <svg v-if="collapsed" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 6l6 6-6 6" /></svg>
          <svg v-else viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M15 6l-6 6 6 6" /></svg>
        </button>
      </div>
    </aside>

    <div class="main-content-wrapper">
      <main class="main">
        <div class="content">
          <router-view />
        </div>
      </main>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

const route = useRoute()
const router = useRouter()

const collapsed = ref(false)

const groups = [
  {
    title: '总览',
    items: [
      { path: '/', label: '首页', icon: 'M3 10.5 12 3l9 7.5V21h-6v-6h-6v6H3z' },
      { path: '/dashboard/live', label: '调度大屏', icon: 'M3 6l6-3 6 3 6-3v15l-6 3-6-3-6 3V6z M9 3v15 M15 6v15' },
    ],
  },
  {
    title: '运营',
    items: [
      { path: '/ops/analytics', label: '运营分析', icon: 'M3 3v18h18 M7 15v4 M12 11v8 M17 7v12' },
      { path: '/ops/health', label: '系统健康', icon: 'M3 12h4l3-8 4 16 3-8h4' },
      { path: '/ops/replay', label: '空间可视化', icon: 'M12 3a9 9 0 1 0 9 9 M12 7v5l3 2 M21 3v6h-6' },
      { path: '/alerts', label: '预警中心', icon: 'M12 3 2 20h20L12 3z M12 10v4 M12 17h.01' },
    ],
  },
  {
    title: '调度',
    items: [
      { path: '/dispatch/queue', label: '调度队列', icon: 'M8 6h13 M8 12h13 M8 18h13 M3 6h.01 M3 12h.01 M3 18h.01' },
    ],
  },
  {
    title: '数据与模型',
    items: [
      { path: '/zones', label: '区域编辑', icon: 'M12 2 20 7v10l-8 5-8-5V7l8-5z M12 2v20' },
      { path: '/ml', label: 'ML 实验室', icon: 'M7 7h10v10H7z M3 9h4 M3 15h4 M17 9h4 M17 15h4 M9 3v4 M15 3v4 M9 17v4 M15 17v4' },
      { path: '/dev', label: '开发门户', icon: 'M8 9l-4 3 4 3 M16 9l4 3-4 3 M13 5l-2 14' },
    ],
  },
]

function go(path) {
  router.push(path)
}
</script>

<style scoped>
.shell {
  height: 100vh;
  display: flex;
  background: #0a0a0a;
}
.sider {
  width: 232px;
  transition: width 0.18s ease;
  background: #0a0a0a;
  border-right: 1px solid rgba(255, 255, 255, 0.07);
  display: flex;
  flex-direction: column;
}
.sider.collapsed {
  width: 64px;
}
.brand {
  display: flex;
  gap: 11px;
  align-items: center;
  padding: 16px 14px 12px;
  cursor: pointer;
}
.logo {
  width: 34px;
  height: 34px;
  border-radius: 9px;
  background: #06c167;
  display: grid;
  place-items: center;
  font-weight: 900;
  font-size: 17px;
  color: #000;
  flex-shrink: 0;
}
.name .t1 {
  color: #fff;
  font-weight: 800;
  font-size: 15px;
  letter-spacing: 0.2px;
  line-height: 1.1;
}
.name .t2 {
  margin-top: 3px;
  font-size: 11px;
  color: #8b8b8b;
}
.nav {
  padding: 4px 10px 10px;
  overflow: auto;
  flex: 1;
}
.group {
  margin-top: 12px;
}
.gtitle {
  font-size: 11px;
  font-weight: 700;
  color: #5a5a5a;
  padding: 4px 8px;
  letter-spacing: 0.4px;
  text-transform: uppercase;
}
.item {
  width: 100%;
  border: 1px solid transparent;
  background: transparent;
  color: #b9b9b9;
  border-radius: 8px;
  padding: 8px 9px 8px 13px;
  display: flex;
  align-items: center;
  gap: 10px;
  cursor: pointer;
  transition: background 0.12s ease, color 0.12s ease;
  position: relative;
  margin-bottom: 2px;
}
.sider.collapsed .item {
  justify-content: center;
  padding: 9px 0;
}
.sider.collapsed .item .spacer {
  display: none;
}
.item:hover {
  background: rgba(255, 255, 255, 0.05);
  color: #fff;
}
.item.active {
  background: rgba(6, 193, 103, 0.12);
  color: #fff;
}
.item.active::before {
  content: '';
  position: absolute;
  left: 4px;
  top: 20%;
  bottom: 20%;
  width: 3px;
  border-radius: 2px;
  background: #06c167;
}
.sider.collapsed .item.active::before {
  display: none;
}
.icon {
  display: grid;
  place-items: center;
  flex-shrink: 0;
  color: #8b8b8b;
}
.item.active .icon,
.item:hover .icon {
  color: #06c167;
}
.label {
  font-weight: 600;
  font-size: 13px;
}
.spacer {
  flex: 1;
}
.sider-footer {
  margin-top: auto;
  padding: 10px;
}
.collapseBtn {
  width: 100%;
  border: 1px solid rgba(255, 255, 255, 0.08);
  background: rgba(255, 255, 255, 0.03);
  color: #8b8b8b;
  border-radius: 8px;
  padding: 9px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
}
.collapseBtn:hover {
  background: rgba(255, 255, 255, 0.06);
  color: #fff;
}
.main-content-wrapper {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
}
.main {
  flex: 1;
  min-width: 0;
}
.content {
  flex: 1;
  overflow: auto;
  min-width: 0;
  background: #0a0a0a;
  padding: 16px;
}
</style>
