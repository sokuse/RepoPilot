<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'

import { ApiError, projectApi } from '../services/api'
import type {
  Project,
  RagAnswerResponse,
  SemanticSearchResult,
  VectorIndexStats,
} from '../types/project'

const projects = ref<Project[]>([])
const selectedProjectId = ref('')
const indexStats = ref<VectorIndexStats | null>(null)
const query = ref('')
const results = ref<SemanticSearchResult[]>([])
const ragAnswer = ref<RagAnswerResponse | null>(null)
const loading = ref(true)
const indexing = ref(false)
const searching = ref(false)
const answering = ref(false)
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
  ragAnswer.value = null
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
  ragAnswer.value = null
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

async function askKnowledge() {
  if (!selectedProjectId.value || !query.value.trim()) return
  const question = query.value.trim()
  answering.value = true
  errorMessage.value = ''
  results.value = []
  // 先创建空回答卡片，后续收到 token 时直接追加，形成打字机式展示。
  ragAnswer.value = {
    project_id: selectedProjectId.value,
    question,
    answer: '',
    citations: [],
    retrieved_chunks: [],
    steps: [],
    warnings: [],
  }
  try {
    await projectApi.askRagStream(selectedProjectId.value, question, (event) => {
      if (!ragAnswer.value) return
      if (event.type === 'retrieval') {
        results.value = event.retrieved_chunks
        ragAnswer.value.retrieved_chunks = event.retrieved_chunks
        ragAnswer.value.steps.push(event.step)
      } else if (event.type === 'token') {
        ragAnswer.value.answer += event.delta
      } else if (event.type === 'step') {
        ragAnswer.value.steps.push(event.step)
      } else if (event.type === 'complete') {
        ragAnswer.value = event.response
        results.value = event.response.retrieved_chunks
      }
    })
  } catch (error) {
    errorMessage.value =
      error instanceof ApiError && error.status === 409
        ? '需要先为这个项目构建向量索引。'
        : error instanceof ApiError && error.status === 502
          ? error.message
          : 'RAG 问答失败，请查看后端日志。'
  } finally {
    answering.value = false
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
        <p>从 Qdrant 检索相关代码，再由 LangGraph 编排 Qwen 生成带真实引用的中文答案。</p>
      </div>
      <div class="phase-pill">第四阶段 · 流式 RAG</div>
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

      <form class="search-form" @submit.prevent="askKnowledge">
        <input
          v-model="query"
          minlength="2"
          required
          placeholder="例如：项目是在哪里创建 FastAPI 应用的？"
        />
        <div class="search-actions">
          <button
            class="secondary-button"
            type="button"
            :disabled="!indexStats?.ready || searching || answering"
            @click="searchKnowledge"
          >
            {{ searching ? '检索中…' : '仅检索' }}
          </button>
          <button
            class="primary-button"
            type="submit"
            :disabled="!indexStats?.ready || searching || answering"
          >
            {{ answering ? '正在流式生成…' : '生成回答' }}
          </button>
        </div>
      </form>
      <p v-if="errorMessage" class="error-banner">{{ errorMessage }}</p>
    </article>

    <article v-if="ragAnswer" class="answer-panel">
      <div class="answer-heading">
        <div>
          <p class="eyebrow">RAG ANSWER</p>
          <h2>仓库回答</h2>
        </div>
        <span>{{ ragAnswer.citations.length }} 个有效引用</span>
      </div>

      <div class="workflow-steps">
        <div v-for="(step, index) in ragAnswer.steps" :key="step.name" class="workflow-step">
          <span>{{ index + 1 }}</span>
          <div><strong>{{ step.label }}</strong><small>{{ step.detail }}</small></div>
        </div>
      </div>

      <div :class="['answer-content', { streaming: answering }]">{{ ragAnswer.answer }}</div>
      <p v-for="warning in ragAnswer.warnings" :key="warning" class="answer-warning">
        {{ warning }}
      </p>

      <div v-if="ragAnswer.citations.length" class="citation-list">
        <strong>引用来源</strong>
        <div v-for="citation in ragAnswer.citations" :key="citation.source_id" class="citation-item">
          <span>{{ citation.source_id }}</span>
          <div>
            <strong>{{ citation.source_path }}</strong>
            <small>
              第 {{ citation.start_line }}～{{ citation.end_line }} 行
              <template v-if="citation.symbol_name"> · {{ citation.symbol_name }}</template>
            </small>
          </div>
        </div>
      </div>
    </article>

    <div v-if="results.length" class="search-results">
      <div class="results-heading">
        <p class="eyebrow">RETRIEVAL EVIDENCE</p>
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
