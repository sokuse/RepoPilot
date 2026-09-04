<script setup lang="ts">
import { RouterLink, RouterView, useRoute, useRouter } from 'vue-router'

import { useDeveloperMode } from './composables/useDeveloperMode'

const route = useRoute()
const router = useRouter()
const { developerLabAvailable, developerMode, setDeveloperMode } = useDeveloperMode()

function toggleDeveloperMode() {
  setDeveloperMode(!developerMode.value)
  if (!developerMode.value && route.meta.developerOnly) void router.push('/projects')
}
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
        <small class="nav-section-label">用户工作区</small>
        <RouterLink to="/projects">项目工作台</RouterLink>
        <RouterLink to="/knowledge">知识检索</RouterLink>
        <RouterLink to="/diagnosis">智能诊断</RouterLink>
        <template v-if="developerMode">
          <small class="nav-section-label developer-section-label">开发者实验室</small>
          <RouterLink to="/evaluation">评测实验</RouterLink>
          <span class="nav-disabled">执行追溯 <small>即将开放</small></span>
        </template>
      </nav>

      <div class="sidebar-footer">
        <button v-if="developerLabAvailable" class="developer-mode-toggle" type="button" @click="toggleDeveloperMode">
          <span class="status-dot" />
          {{ developerMode ? '切换到用户视图' : '打开开发者实验室' }}
        </button>
        <div class="sidebar-status"><span class="status-dot" />RepoPilot · 项目维护助手</div>
      </div>
    </aside>

    <main class="main-content">
      <RouterView />
    </main>
  </div>
</template>
