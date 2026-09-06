<template>
  <div class="standalone">
    <router-view />
  </div>
</template>

<script setup></script>

<style scoped>
.standalone {
  min-height: 100vh;
  background: radial-gradient(1200px 600px at 20% 0%, rgba(6, 193, 103, 0.04), transparent 55%),
    radial-gradient(1000px 500px at 80% 20%, rgba(6, 193, 103, 0.03), transparent 60%),
    #0a0a0a;
}
</style>

