<script setup lang="ts">
import { onMounted, onUnmounted, reactive, ref } from 'vue'

import { ApiError, projectApi } from '../services/api'
import type { Project, ProjectCreate, RepositoryStats } from '../types/project'

const projects = ref<Project[]>([])
const loading = ref(true)
const submitting = ref(false)
const deletingProjectId = ref<string | null>(null)
const ingestingProjectId = ref<string | null>(null)
const errorMessage = ref('')
const projectStats = ref<Record<string, RepositoryStats>>({})
const form = reactive<ProjectCreate>({ name: '', repository_url: '', default_branch: 'main' })

const statusText: Record<Project['status'], string> = {
  pending: '等待接入',
  indexing: '正在索引',
  ready: '已就绪',
  failed: '接入失败',
}

async function loadProjects(silent = false) {
  if (!silent) loading.value = true
  if (!silent) errorMessage.value = ''
  try {
    projects.value = await projectApi.list()
    await loadReadyProjectStats()
  } catch {
    if (!silent) errorMessage.value = '无法连接 Python 后端，请确认 FastAPI 已在 8000 端口启动。'
  } finally {
    if (!silent) loading.value = false
  }
}

async function loadReadyProjectStats() {
  const readyProjects = projects.value.filter((project) => project.status === 'ready')
  const entries = await Promise.all(
    readyProjects.map(async (project) => {
      try {
        return [project.id, await projectApi.stats(project.id)] as const
      } catch {
        return null
      }
    }),
  )
  projectStats.value = Object.fromEntries(entries.filter((entry) => entry !== null))
}

async function createProject() {
  submitting.value = true
  errorMessage.value = ''
  try {
    const project = await projectApi.create(form)
    projects.value.unshift(project)
    Object.assign(form, { name: '', repository_url: '', default_branch: 'main' })
  } catch (error) {
    errorMessage.value =
      error instanceof ApiError && error.status === 409
        ? '这个仓库已经接入，无需重复创建。'
        : '项目创建失败，请检查仓库地址和后端状态。'
  } finally {
    submitting.value = false
  }
}

async function deleteProject(project: Project) {
  if (!window.confirm(`确定删除项目“${project.name}”吗？`)) return

  deletingProjectId.value = project.id
  errorMessage.value = ''
  try {
    await projectApi.remove(project.id)
    projects.value = projects.value.filter((item) => item.id !== project.id)
  } catch {
    errorMessage.value = '项目删除失败，请刷新页面后重试。'
  } finally {
    deletingProjectId.value = null
  }
}

async function startIngestion(project: Project) {
  ingestingProjectId.value = project.id
  errorMessage.value = ''
  try {
    const updatedProject = await projectApi.ingest(project.id)
    projects.value = projects.value.map((item) =>
      item.id === updatedProject.id ? updatedProject : item,
    )
  } catch (error) {
    errorMessage.value =
      error instanceof ApiError && error.status === 409
        ? error.message
        : '仓库采集启动失败，请检查后端日志和仓库分支。'
  } finally {
    ingestingProjectId.value = null
  }
}

function formatBytes(bytes: number) {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

function topLanguages(stats: RepositoryStats) {
  return Object.entries(stats.language_breakdown)
    .slice(0, 3)
    .map(([language, count]) => `${language} ${count}`)
    .join(' · ')
}

let pollingTimer: number | undefined
onMounted(async () => {
  await loadProjects()
  // 仅在存在采集任务时轮询，避免页面空闲时不断请求后端。
  pollingTimer = window.setInterval(() => {
    if (projects.value.some((project) => project.status === 'indexing')) {
      void loadProjects(true)
    }
  }, 3000)
})
onUnmounted(() => window.clearInterval(pollingTimer))
</script>

<template>
  <section class="page">
    <header class="page-header">
      <div>
        <p class="eyebrow">KNOWLEDGE WORKSPACE</p>
        <h1>项目工作台</h1>
        <p>接入代码仓库，为后续代码切片、知识索引和智能诊断准备数据。</p>
      </div>
      <div class="phase-pill">第一阶段</div>
    </header>

    <div class="metrics-grid">
      <article class="metric-card">
        <span>已接入项目</span><strong>{{ projects.length }}</strong><small>跨仓库知识将在此汇总</small>
      </article>
      <article class="metric-card">
        <span>知识切片</span><strong>0</strong><small>下一阶段接入 AST 切片</small>
      </article>
      <article class="metric-card accent-card">
        <span>系统状态</span><strong>{{ errorMessage ? '离线' : '可用' }}</strong><small>Vue → FastAPI</small>
      </article>
    </div>

    <div class="content-grid">
      <article class="panel">
        <div class="panel-heading">
          <div><p class="eyebrow">NEW PROJECT</p><h2>接入 GitHub 仓库</h2></div>
        </div>

        <form class="project-form" @submit.prevent="createProject">
          <label>项目名称<input v-model.trim="form.name" minlength="2" required placeholder="例如：LangGraph" /></label>
          <label>
            仓库地址
            <input v-model.trim="form.repository_url" type="url" required placeholder="https://github.com/org/repository" />
          </label>
          <label>默认分支<input v-model.trim="form.default_branch" required placeholder="main" /></label>
          <button class="primary-button" type="submit" :disabled="submitting">
            {{ submitting ? '正在创建…' : '创建项目' }}
          </button>
        </form>

        <p v-if="errorMessage" class="error-banner">{{ errorMessage }}</p>
      </article>

      <article class="panel project-panel">
        <div class="panel-heading">
          <div><p class="eyebrow">REPOSITORIES</p><h2>项目列表</h2></div>
          <button class="text-button" type="button" @click="loadProjects()">刷新</button>
        </div>

        <div v-if="loading" class="empty-state">正在读取项目…</div>
        <div v-else-if="projects.length === 0" class="empty-state">
          <span class="empty-icon">＋</span><strong>还没有项目</strong><p>从左侧接入第一个公开 GitHub 仓库。</p>
        </div>
        <ul v-else class="project-list">
          <li v-for="project in projects" :key="project.id">
            <div class="repo-icon">{{ project.name.slice(0, 1).toUpperCase() }}</div>
            <div class="repo-info">
              <strong>{{ project.name }}</strong>
              <a :href="project.repository_url" target="_blank" rel="noreferrer">{{ project.repository_url }}</a>
              <small>{{ project.default_branch }} · {{ new Date(project.created_at).toLocaleString() }}</small>
              <small v-if="projectStats[project.id]" class="repo-stats">
                {{ projectStats[project.id].total_files }} 个文件 ·
                {{ formatBytes(projectStats[project.id].total_bytes) }} ·
                {{ topLanguages(projectStats[project.id]) }}
              </small>
            </div>
            <div class="project-actions">
              <span class="status-badge" :data-status="project.status">{{ statusText[project.status] }}</span>
              <button
                v-if="project.status === 'pending' || project.status === 'failed'"
                class="ingest-button"
                type="button"
                :disabled="ingestingProjectId === project.id"
                @click="startIngestion(project)"
              >
                {{ ingestingProjectId === project.id ? '启动中' : project.status === 'failed' ? '重试' : '开始采集' }}
              </button>
              <button
                class="delete-button"
                type="button"
                :disabled="deletingProjectId === project.id"
                @click="deleteProject(project)"
              >
                {{ deletingProjectId === project.id ? '删除中' : '删除' }}
              </button>
            </div>
          </li>
        </ul>
      </article>
    </div>
  </section>
</template>
