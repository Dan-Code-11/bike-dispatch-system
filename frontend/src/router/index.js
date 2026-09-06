import { createRouter, createWebHistory } from 'vue-router'

import AppShell from '../layouts/AppShell.vue'
import StandaloneShell from '../layouts/StandaloneShell.vue'
import HomeView from '../views/HomeView.vue'
import LiveMonitor from '../views/Dashboard/LiveMonitor.vue'
import ZonesEditor from '../views/Zones/ZonesEditor.vue'
import AlertsCenter from '../views/Alerts/AlertsCenter.vue'
import MLLab from '../views/Lab/MLLab.vue'
import DispatchQueue from '../views/Lab/DispatchQueue.vue'
import DevPortal from '../views/Lab/DevPortal.vue'
import KPIAnalytics from '../views/Ops/KPIAnalytics.vue'
import ReplayCenter from '../views/Ops/ReplayCenter.vue'
import SystemHealth from '../views/Ops/SystemHealth.vue'

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      component: AppShell,
      children: [
        { path: '', name: 'home', component: HomeView },
        { path: 'dashboard/live', name: 'live-monitor', component: LiveMonitor },
        { path: 'ops/health', name: 'ops-health', component: SystemHealth },
        { path: 'ops/analytics', name: 'ops-analytics', component: KPIAnalytics },
        { path: 'ops/replay', name: 'ops-replay', component: ReplayCenter },
        { path: 'zones', name: 'zones', component: ZonesEditor },
        { path: 'alerts', name: 'alerts', component: AlertsCenter },
        { path: 'ml', name: 'ml', component: MLLab },
        { path: 'dispatch/queue', name: 'dispatch-queue', component: DispatchQueue },
        { path: 'dev', name: 'dev', component: DevPortal },
      ],
    },
    {
      path: '/standalone',
      component: StandaloneShell,
      children: [
        { path: 'dashboard/live', name: 'standalone-live-monitor', component: LiveMonitor },
        { path: 'ops/health', name: 'standalone-ops-health', component: SystemHealth },
        { path: 'ops/analytics', name: 'standalone-ops-analytics', component: KPIAnalytics },
        { path: 'ops/replay', name: 'standalone-ops-replay', component: ReplayCenter },
        { path: 'zones', name: 'standalone-zones', component: ZonesEditor },
        { path: 'alerts', name: 'standalone-alerts', component: AlertsCenter },
        { path: 'ml', name: 'standalone-ml', component: MLLab },
        { path: 'dispatch/queue', name: 'standalone-dispatch-queue', component: DispatchQueue },
        { path: 'dev', name: 'standalone-dev', component: DevPortal },
      ],
    },
  ],
})
