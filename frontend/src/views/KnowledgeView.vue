<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'

import { ApiError, projectApi } from '../services/api'
import type {
  ConversationDetail,
  ConversationSummary,
  MemoryStats,
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
const conversations = ref<ConversationSummary[]>([])
const selectedConversationId = ref('')
const conversationDetail = ref<ConversationDetail | null>(null)
const memoryStats = ref<MemoryStats | null>(null)
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

async function loadConversations(selectId?: string) {
  conversations.value = []
  conversationDetail.value = null
  if (!selectedProjectId.value) return
  try {
    conversations.value = await projectApi.listConversations(selectedProjectId.value)
    memoryStats.value = await projectApi.memoryStats(selectedProjectId.value)
    selectedConversationId.value =
      selectId ??
      (conversations.value.some((item) => item.id === selectedConversationId.value)
        ? selectedConversationId.value
        : conversations.value[0]?.id ?? '')
  } catch {
    errorMessage.value = '无法读取对话列表。'
  }
}

async function createConversation() {
  if (!selectedProjectId.value) return ''
  try {
    const conversation = await projectApi.createConversation(selectedProjectId.value)
    await loadConversations(conversation.id)
    return conversation.id
  } catch {
    errorMessage.value = '新建对话失败，请确认后端已重启。'
    return ''
  }
}

async function loadConversationDetail() {
  conversationDetail.value = null
  if (!selectedProjectId.value || !selectedConversationId.value) return
  try {
    conversationDetail.value = await projectApi.getConversation(
      selectedProjectId.value,
      selectedConversationId.value,
    )
  } catch {
    errorMessage.value = '无法读取对话消息。'
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
  const conversationId = selectedConversationId.value || (await createConversation())
  if (!conversationId) return
  answering.value = true
  errorMessage.value = ''
  results.value = []
  // 先创建空回答卡片，后续收到 token 时直接追加，形成打字机式展示。
  ragAnswer.value = {
    run_id: null,
    conversation_id: conversationId,
    project_id: selectedProjectId.value,
    question,
    answer: '',
    citations: [],
    retrieved_chunks: [],
    retrieved_memories: [],
    steps: [],
    warnings: [],
    usage: { prompt_tokens: 0, completion_tokens: 0, total_tokens: 0 },
    duration_ms: 0,
  }
  try {
    await projectApi.askRagStream(selectedProjectId.value, question, (event) => {
      if (!ragAnswer.value) return
      if (event.type === 'run') {
        ragAnswer.value.run_id = event.run_id
      } else if (event.type === 'retrieval') {
        results.value = event.retrieved_chunks
        ragAnswer.value.retrieved_chunks = event.retrieved_chunks
        ragAnswer.value.retrieved_memories = event.retrieved_memories
        ragAnswer.value.steps.push(event.step)
      } else if (event.type === 'token') {
        ragAnswer.value.answer += event.delta
      } else if (event.type === 'step') {
        ragAnswer.value.steps.push(event.step)
      } else if (event.type === 'complete') {
        ragAnswer.value = event.response
        results.value = event.response.retrieved_chunks
      }
    }, 8, conversationId)
  } catch (error) {
    errorMessage.value =
      error instanceof ApiError && error.status === 409
        ? '需要先为这个项目构建向量索引。'
        : error instanceof ApiError && error.status === 502
          ? error.message
          : 'RAG 问答失败，请查看后端日志。'
  } finally {
    answering.value = false
    // 问答完成后刷新当前对话，让用户可以继续追问并提交反馈。
    void loadConversations(conversationId).then(loadConversationDetail)
  }
}

function formatDuration(durationMs: number) {
  return durationMs ? `${(durationMs / 1000).toFixed(1)} 秒` : '—'
}

watch(selectedProjectId, () => {
  void loadIndexStats()
  selectedConversationId.value = ''
  void loadConversations()
})
watch(selectedConversationId, () => void loadConversationDetail())
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
      <div class="phase-pill">第八阶段 · 对话 RAG</div>
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

    <article class="panel conversation-panel">
      <div class="panel-heading">
        <div><p class="eyebrow">CONVERSATION MEMORY</p><h2>对话记录</h2></div>
        <button class="secondary-button" type="button" :disabled="!selectedProjectId" @click="createConversation">
          新建对话
        </button>
      </div>
      <p class="memory-summary">
        短期记忆读取当前对话最近 6 条消息；长期记忆已索引
        {{ memoryStats?.indexed_memories ?? 0 }} 个切片。
      </p>
      <label class="conversation-selector">
        当前对话
        <select v-model="selectedConversationId">
          <option value="" disabled>新建或选择一段对话</option>
          <option v-for="conversation in conversations" :key="conversation.id" :value="conversation.id">
            {{ conversation.title }}
          </option>
        </select>
      </label>
      <div v-if="conversationDetail?.messages.length" class="conversation-messages">
        <article
          v-for="message in conversationDetail.messages"
          :key="message.id"
          :data-role="message.role"
          class="conversation-message"
        >
          <strong>{{ message.role === 'user' ? '你' : 'RepoPilot' }}</strong>
          <p>{{ message.content }}</p>
          <div v-if="message.role === 'assistant'" class="message-feedback">
            <button type="button" @click="projectApi.setMessageFeedback(selectedProjectId, selectedConversationId, message.id, 'helpful').then(loadConversationDetail)">有帮助</button>
            <button type="button" @click="projectApi.setMessageFeedback(selectedProjectId, selectedConversationId, message.id, 'unhelpful').then(loadConversationDetail)">没帮助</button>
            <small v-if="message.feedback">已记录：{{ message.feedback === 'helpful' ? '有帮助' : '没帮助' }}</small>
          </div>
        </article>
      </div>
      <p v-else class="history-empty">新问题和回答会自动保存在当前对话中。</p>
    </article>

    <article v-if="ragAnswer" class="answer-panel">
      <div class="answer-heading">
        <div>
          <p class="eyebrow">RAG ANSWER</p>
          <h2>仓库回答</h2>
        </div>
        <span>
          {{ ragAnswer.usage.total_tokens }} tokens · {{ formatDuration(ragAnswer.duration_ms) }} ·
          {{ ragAnswer.citations.length }} 个有效引用
        </span>
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
      <div v-if="ragAnswer.retrieved_memories.length" class="memory-source-list">
        <strong>召回的历史记忆</strong>
        <article v-for="memory in ragAnswer.retrieved_memories" :key="memory.memory_id">
          <span>{{ memory.source_type === 'diagnosis' ? '历史诊断' : '历史对话' }}</span>
          <small>相似度 {{ (memory.score * 100).toFixed(1) }}%</small>
          <p>{{ memory.content }}</p>
        </article>
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
