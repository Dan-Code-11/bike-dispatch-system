import { createApp } from 'vue'
import App from './App.vue'
import { createPinia } from 'pinia'

import 'leaflet/dist/leaflet.css'
import 'vant/lib/index.css'
import './style.css'
import { router } from './router'

// 全局错误捕获：任何未捕获的 JS 异常都在页面顶部显示红条，
// 避免 WebView 里"点了没反应/卡死"且无任何提示的问题
function showFatal(msg) {
  try {
    let el = document.getElementById('__fatal__')
    if (!el) {
      el = document.createElement('div')
      el.id = '__fatal__'
      el.style.cssText =
        'position:fixed;top:0;left:0;right:0;z-index:99999;background:#F04438;color:#fff;font:12px/1.5 system-ui,sans-serif;padding:8px 14px;display:flex;align-items:center;gap:10px;box-shadow:0 2px 12px rgba(0,0,0,.4);'
      const span = document.createElement('span')
      span.id = '__fatal_msg__'
      el.appendChild(span)
      const btn = document.createElement('button')
      btn.textContent = '关闭'
      btn.style.cssText =
        'margin-left:auto;background:#fff;color:#F04438;border:none;border-radius:6px;padding:3px 12px;cursor:pointer;font-size:12px;font-weight:700;flex:none;'
      btn.onclick = () => el.remove()
      el.appendChild(btn)
      document.body.appendChild(el)
    }
    const span = el.querySelector('#__fatal_msg__')
    if (span) span.textContent = '⚠ 页面异常: ' + String(msg).slice(0, 220)
    el.style.display = 'flex'
  } catch (e) { /* ignore */ }
}

const app = createApp(App)
app.config.errorHandler = (err, instance, info) => {
  console.error('[Vue error]', err, info)
  showFatal(err?.message || String(err))
}
window.addEventListener('unhandledrejection', (e) => {
  const msg = e?.reason?.message || e?.reason || 'unknown'
  console.error('[Unhandled rejection]', msg)
  showFatal(msg)
})
app.use(createPinia()).use(router).mount('#app')
