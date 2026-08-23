<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'

import { ApiError, projectApi } from '../services/api'
import type {
  Project,
  SemanticSearchResult,
  VectorIndexStats,
} from '../types/project'

const projects = ref<Project[]>([])
const selectedProjectId = ref('')
const indexStats = ref<VectorIndexStats | null>(null)
const query = ref('')
const results = ref<SemanticSearchResult[]>([])
const loading = ref(true)
const indexing = ref(false)
const searching = ref(false)
const errorMessage = ref('')

async function loadProjects() {
  loading.value = true
  errorMessage.value = ''
  try {
    projects.value = (await projectApi.list()).filter((project) => project.status === 'ready')
    selectedProjectId.value ||= projects.value[0]?.id ?? ''
  } catch {
    errorMessage.value = '无法读取项目，请确认 FastAPI 已启动。'
  } finally {
    loading.value = false
  }
}

async function loadIndexStats() {
  indexStats.value = null
  results.value = []
  if (!selectedProjectId.value) return
  try {
    indexStats.value = await projectApi.indexStats(selectedProjectId.value)
  } catch {
    errorMessage.value = '无法读取向量索引状态。'
  }
}

async function rebuildIndex() {
  if (!selectedProjectId.value) return
  indexing.value = true
  errorMessage.value = ''
  try {
    indexStats.value = await projectApi.rebuildIndex(selectedProjectId.value)
  } catch (error) {
    errorMessage.value =
      error instanceof ApiError && error.status === 409
        ? '请先回到项目工作台生成知识切片。'
        : '向量索引构建失败，请查看后端日志。'
  } finally {
    indexing.value = false
  }
}

async function searchKnowledge() {
  if (!selectedProjectId.value || !query.value.trim()) return
  searching.value = true
  errorMessage.value = ''
  try {
    const response = await projectApi.semanticSearch(
      selectedProjectId.value,
      query.value.trim(),
    )
    results.value = response.results
  } catch (error) {
    errorMessage.value =
      error instanceof ApiError && error.status === 409
        ? '需要先为这个项目构建向量索引。'
        : '语义检索失败，请查看后端日志。'
  } finally {
    searching.value = false
  }
}

watch(selectedProjectId, () => void loadIndexStats())
onMounted(() => void loadProjects())
</script>

<template>
  <section class="page knowledge-page">
    <header class="page-header">
      <div>
        <p class="eyebrow">SEMANTIC RETRIEVAL</p>
        <h1>知识检索</h1>
        <p>将自然语言问题转换为向量，从 Qdrant 找到语义最相关的代码与文档切片。</p>
      </div>
      <div class="phase-pill">第三阶段 · Embedding</div>
    </header>

    <article class="panel retrieval-control">
      <div class="project-selector">
        <label>
          选择项目
          <select v-model="selectedProjectId" :disabled="loading">
            <option value="" disabled>请选择已就绪项目</option>
            <option v-for="project in projects" :key="project.id" :value="project.id">
              {{ project.name }}
            </option>
          </select>
        </label>
        <div class="index-summary">
          <span :class="['index-dot', { ready: indexStats?.ready }]" />
          <div>
            <strong>{{ indexStats?.ready ? '向量索引已就绪' : '尚未构建向量索引' }}</strong>
            <small v-if="indexStats?.ready">
              {{ indexStats.indexed_chunks }} 个向量 · {{ indexStats.vector_size }} 维 ·
              {{ indexStats.embedding_model }}
            </small>
            <small v-else>使用百炼 text-embedding-v4 API，向量保存在本地 Qdrant。</small>
          </div>
        </div>
        <button
          class="primary-button index-button"
          type="button"
          :disabled="!selectedProjectId || indexing"
          @click="rebuildIndex"
        >
          {{ indexing ? '正在生成向量…' : indexStats?.ready ? '重建索引' : '构建索引' }}
        </button>
      </div>

      <form class="search-form" @submit.prevent="searchKnowledge">
        <input
          v-model="query"
          minlength="2"
          required
          placeholder="例如：项目是在哪里创建 FastAPI 应用的？"
        />
        <button class="primary-button" type="submit" :disabled="!indexStats?.ready || searching">
          {{ searching ? '检索中…' : '语义检索' }}
        </button>
      </form>
      <p v-if="errorMessage" class="error-banner">{{ errorMessage }}</p>
    </article>

    <div v-if="results.length" class="search-results">
      <div class="results-heading">
        <p class="eyebrow">RETRIEVAL RESULTS</p>
        <span>{{ results.length }} 条结果</span>
      </div>
      <article v-for="result in results" :key="result.chunk_id" class="result-card">
        <header>
          <div>
            <strong>{{ result.source_path }}</strong>
            <small>
              第 {{ result.start_line }}～{{ result.end_line }} 行
              <template v-if="result.symbol_name"> · {{ result.symbol_name }}</template>
            </small>
          </div>
          <span class="score">相似度 {{ (result.score * 100).toFixed(1) }}%</span>
        </header>
        <pre><code>{{ result.content }}</code></pre>
      </article>
    </div>
    <div v-else-if="!loading" class="retrieval-empty">
      构建索引后输入一个与代码或文档相关的问题，检索结果会保留文件路径和行号。
    </div>
  </section>
</template>
