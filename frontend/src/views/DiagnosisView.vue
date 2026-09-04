<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { ApiError, projectApi } from '../services/api'
import type { MultiAgentDiagnosisResponse, Project } from '../types/project'

const projects = ref<Project[]>([])
const selectedProjectId = ref('')
const question = ref('')
const result = ref<MultiAgentDiagnosisResponse | null>(null)
const loading = ref(true)
const diagnosing = ref(false)
const errorMessage = ref('')

async function loadProjects() {
  loading.value = true
  try {
    projects.value = (await projectApi.list()).filter((project) => project.status === 'ready')
    selectedProjectId.value = projects.value[0]?.id ?? ''
  } catch {
    errorMessage.value = '无法读取项目，请确认 FastAPI 已启动。'
  } finally {
    loading.value = false
  }
}

async function diagnose() {
  if (!selectedProjectId.value || !question.value.trim()) return
  diagnosing.value = true
  result.value = null
  errorMessage.value = ''
  try {
    result.value = await projectApi.multiAgentDiagnose(
      selectedProjectId.value,
      question.value.trim(),
    )
  } catch (error) {
    errorMessage.value =
      error instanceof ApiError && error.status === 409
        ? '请先完成仓库切片和向量索引。'
        : error instanceof ApiError
          ? error.message
          : '智能诊断失败，请查看后端日志。'
  } finally {
    diagnosing.value = false
  }
}

function toolName(name: string) {
  return (
    {
      semantic_search: '语义搜索',
      read_file: '读取文件',
      list_files: '列出文件',
      get_repository_stats: '仓库统计',
    }[name] ?? name
  )
}

function formatJson(value: Record<string, unknown>) {
  return JSON.stringify(value, null, 2)
}

onMounted(() => void loadProjects())
</script>

<template>
  <section class="page diagnosis-page">
    <header class="page-header">
      <div>
        <p class="eyebrow">MULTI-AGENT DIAGNOSIS</p>
        <h1>智能诊断</h1>
        <p>规划、调查和审查 Agent 分工协作，调用仓库工具取得证据并修订最终结论。</p>
      </div>
      <div class="phase-pill">第七阶段 · Multi-Agent</div>
    </header>

    <article class="panel diagnosis-control">
      <form class="diagnosis-form" @submit.prevent="diagnose">
        <label>
          选择项目
          <select v-model="selectedProjectId" :disabled="loading">
            <option value="" disabled>请选择已就绪项目</option>
            <option v-for="project in projects" :key="project.id" :value="project.id">
              {{ project.name }}
            </option>
          </select>
        </label>
        <label>
          描述需要调查的问题
          <textarea
            v-model="question"
            minlength="2"
            required
            rows="5"
            placeholder="例如：项目的 RAG 流式回答失败时，错误是如何传递到前端的？"
          />
        </label>
        <button class="primary-button" type="submit" :disabled="!selectedProjectId || diagnosing">
          {{ diagnosing ? '多 Agent 正在协作…' : '开始多 Agent 诊断' }}
        </button>
      </form>
      <p v-if="errorMessage" class="error-banner">{{ errorMessage }}</p>
    </article>

    <section v-if="diagnosing" class="panel diagnosis-progress">
      <span class="agent-pulse" />
      <div>
        <strong>规划、调查与审查 Agent 正在协作</strong>
        <small>调查阶段可能进行多轮搜索与文件读取，请耐心等待。</small>
      </div>
    </section>

    <template v-if="result">
      <section class="agent-workflow-section">
        <div class="results-heading">
          <p class="eyebrow">AGENT WORKFLOW</p>
          <span>{{ result.agents.length }} 个 Agent · 累计 {{ result.usage.total_tokens }} tokens</span>
        </div>
        <div class="agent-step-list">
          <article v-for="(agent, index) in result.agents" :key="agent.name" class="agent-step-card">
            <header>
              <span>{{ index + 1 }}</span>
              <div><strong>{{ agent.label }}</strong><small>{{ agent.duration_ms }} ms · {{ agent.usage.total_tokens }} tokens</small></div>
            </header>
            <div class="agent-step-output">{{ agent.output }}</div>
          </article>
        </div>
      </section>

      <article class="answer-panel diagnosis-answer">
        <div class="answer-heading">
          <div><p class="eyebrow">DIAGNOSIS</p><h2>诊断结论</h2></div>
          <span>
            审查 {{ result.review.score }} 分 · {{ result.model }} · {{ result.duration_ms }} ms
          </span>
        </div>
        <div class="answer-content">{{ result.final_answer }}</div>
        <div :class="['review-summary', { passed: result.review.passed }]">
          <strong>{{ result.review.passed ? '审查通过' : '审查后已修订' }}</strong>
          <span>证据质量评分 {{ result.review.score }}/100</span>
        </div>
        <ul v-if="result.review.issues.length" class="review-issues">
          <li v-for="issue in result.review.issues" :key="issue">{{ issue }}</li>
        </ul>
        <details class="draft-answer">
          <summary>查看审查前的调查草稿</summary>
          <div>{{ result.draft_answer }}</div>
        </details>
        <p v-for="warning in result.warnings" :key="warning" class="answer-warning">
          {{ warning }}
        </p>
      </article>

      <section class="tool-trace-section">
        <div class="results-heading">
          <p class="eyebrow">TOOL TRACE</p>
          <span>{{ result.tool_calls.length }} 次工具调用</span>
        </div>
        <article v-for="(call, index) in result.tool_calls" :key="call.call_id" class="tool-card">
          <header>
            <span>{{ index + 1 }}</span>
            <div><strong>{{ toolName(call.name) }}</strong><small>{{ call.summary }}</small></div>
            <em :data-success="call.success">{{ call.success ? '成功' : '失败' }}</em>
          </header>
          <details>
            <summary>查看调用参数和返回结果</summary>
            <p>调用参数</p>
            <pre>{{ formatJson(call.arguments) }}</pre>
            <p>工具结果</p>
            <pre>{{ call.result }}</pre>
          </details>
        </article>
      </section>
    </template>
  </section>
</template>
