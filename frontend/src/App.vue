<script setup lang="ts">
import { RouterLink, RouterView } from 'vue-router'
</script>

<template>
  <div class="app-shell">
    <aside class="sidebar">
      <RouterLink class="brand" to="/">
        <span class="brand-mark">R</span>
        <span>
          <strong>RepoPilot</strong>
          <small>Maintenance Intelligence</small>
        </span>
      </RouterLink>

      <nav class="nav-list" aria-label="主导航">
        <RouterLink to="/projects">项目工作台</RouterLink>
        <RouterLink to="/knowledge">知识检索</RouterLink>
        <RouterLink to="/diagnosis">智能诊断</RouterLink>
        <span class="nav-disabled">评测实验 <small>即将开放</small></span>
        <span class="nav-disabled">执行追溯 <small>即将开放</small></span>
      </nav>

      <div class="sidebar-status">
        <span class="status-dot" />
        Phase 6 · Function Call
      </div>
    </aside>

    <main class="main-content">
      <RouterView />
    </main>
  </div>
</template>
