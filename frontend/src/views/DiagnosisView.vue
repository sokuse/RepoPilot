<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { ApiError, projectApi } from '../services/api'
import type {
  DiagnosisResponse,
  DiagnosisStreamEvent,
  MultiAgentDiagnosisResponse,
  Project,
} from '../types/project'

type ActivityStatus = 'running' | 'success' | 'failed'

interface DiagnosisActivity {
  id: string
  label: string
  detail: string
  status: ActivityStatus
}

const projects = ref<Project[]>([])
const selectedProjectId = ref('')
const question = ref('')
const maxIterations = ref(3)
const diagnosisMode = ref<'multi' | 'single'>('multi')
const result = ref<DiagnosisResponse | null>(null)
const multiAgentResult = ref<MultiAgentDiagnosisResponse | null>(null)
const activities = ref<DiagnosisActivity[]>([])
const loading = ref(true)
const diagnosing = ref(false)
const errorMessage = ref('')

const exampleQuestions = [
  '定位最近一次改动可能引入的故障，并给出修复和验证步骤。',
  '追踪一个 API 请求从前端到数据库的完整调用链。',
  '分析异常为什么没有正确显示到前端，并列出代码证据。',
]
const activeToolCalls = computed(
  () => multiAgentResult.value?.tool_calls ?? result.value?.tool_calls ?? [],
)

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
  multiAgentResult.value = null
  activities.value = []
  errorMessage.value = ''
  try {
    if (diagnosisMode.value === 'multi') {
      const response = await projectApi.multiAgentDiagnose(
        selectedProjectId.value,
        question.value.trim(),
        maxIterations.value,
      )
      multiAgentResult.value = response
      activities.value = response.agents.map((agent) => ({
        id: agent.name,
        label: agent.label,
        detail: `${agent.duration_ms} ms · ${agent.usage.total_tokens} tokens`,
        status: 'success',
      }))
    } else {
      await projectApi.diagnoseStream(
        selectedProjectId.value,
        question.value.trim(),
        handleStreamEvent,
        maxIterations.value,
      )
    }
  } catch (error) {
    const runningActivity = [...activities.value].reverse().find((item) => item.status === 'running')
    if (runningActivity) runningActivity.status = 'failed'
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

function handleStreamEvent(event: DiagnosisStreamEvent) {
  if (event.type === 'start') {
    activities.value.push({
      id: 'start',
      label: '开始深度诊断',
      detail: `最多进行 ${event.max_iterations} 轮模型决策，第一轮必须调用仓库工具。`,
      status: 'success',
    })
  } else if (event.type === 'decision') {
    activities.value.push({
      id: `decision-${event.iteration}`,
      label: `第 ${event.iteration} 轮 · 模型决策`,
      detail: `准备调用 ${event.tool_calls.map((call) => toolName(call.name)).join('、')}。`,
      status: 'success',
    })
  } else if (event.type === 'tool_start') {
    activities.value.push({
      id: event.call_id,
      label: toolName(event.name),
      detail: `正在执行 · ${compactArguments(event.arguments)}`,
      status: 'running',
    })
  } else if (event.type === 'tool_complete') {
    const activity = activities.value.find((item) => item.id === event.trace.call_id)
    if (activity) {
      activity.detail = event.trace.summary
      activity.status = event.trace.success ? 'success' : 'failed'
    }
  } else if (event.type === 'complete') {
    result.value = event.response
    activities.value.push({
      id: 'complete',
      label: '形成诊断结论',
      detail: `完成 ${event.response.iterations} 轮决策和 ${event.response.tool_calls.length} 次工具调用。`,
      status: 'success',
    })
  }
}

function compactArguments(argumentsValue: Record<string, unknown>) {
  const text = Object.entries(argumentsValue)
    .map(([key, value]) => `${key}=${String(value)}`)
    .join('，')
  return text || '无参数'
}

function useExample(example: string) {
  question.value = example
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
        <p>多 Agent 负责规划、调查和证据审查，也可切换为低成本的单 Agent 实时诊断。</p>
      </div>
      <div class="phase-pill">第七阶段 · Multi-Agent</div>
    </header>

    <aside class="diagnosis-guide">
      <div><strong>多 Agent 审查</strong><span>规划、调查、审查分工协作，证据更严格，但耗时和 Token 更高。</span></div>
      <div><strong>单 Agent 实时</strong><span>实时展示工具执行过程，速度和成本更适合日常快速诊断。</span></div>
    </aside>

    <article class="panel diagnosis-control">
      <form class="diagnosis-form" @submit.prevent="diagnose">
        <div class="diagnosis-options">
          <label>
            诊断模式
            <select v-model="diagnosisMode" :disabled="diagnosing">
              <option value="multi">多 Agent · 规划 + 调查 + 审查</option>
              <option value="single">单 Agent · 实时工具调用</option>
            </select>
          </label>
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
            调查深度
            <select v-model.number="maxIterations" :disabled="diagnosing">
              <option :value="2">快速 · 最多 2 轮</option>
              <option :value="3">标准 · 最多 3 轮</option>
              <option :value="4">深入 · 最多 4 轮</option>
              <option :value="5">全面 · 最多 5 轮</option>
            </select>
          </label>
        </div>
        <label>
          描述故障现象、预期行为和相关线索
          <textarea
            v-model="question"
            minlength="2"
            required
            rows="5"
            placeholder="例如：项目的 RAG 流式回答失败时，错误是如何传递到前端的？"
          />
        </label>
        <div class="diagnosis-examples">
          <span>试试这些诊断任务：</span>
          <button
            v-for="example in exampleQuestions"
            :key="example"
            type="button"
            :disabled="diagnosing"
            @click="useExample(example)"
          >
            {{ example }}
          </button>
        </div>
        <button class="primary-button" type="submit" :disabled="!selectedProjectId || diagnosing">
          {{
            diagnosing
              ? diagnosisMode === 'multi'
                ? '多 Agent 正在协作…'
                : 'Agent 正在调查…'
              : '开始智能诊断'
          }}
        </button>
      </form>
      <p v-if="errorMessage" class="error-banner">{{ errorMessage }}</p>
    </article>

    <section v-if="diagnosing && diagnosisMode === 'multi' && !activities.length" class="panel diagnosis-progress">
      <div class="diagnosis-progress-heading">
        <div><span class="agent-pulse" /><strong>多 Agent 协作进行中</strong></div>
        <small>规划 → 工具调查 → 证据审查</small>
      </div>
    </section>

    <section v-if="activities.length" class="panel diagnosis-progress">
      <div class="diagnosis-progress-heading">
        <div><span v-if="diagnosing" class="agent-pulse" /><strong>Agent 执行过程</strong></div>
        <small>{{ diagnosing ? '实时执行中' : diagnosisMode === 'multi' ? '审查已完成' : '调查已完成' }}</small>
      </div>
      <ol class="diagnosis-timeline">
        <li v-for="activity in activities" :key="activity.id" :data-status="activity.status">
          <span />
          <div><strong>{{ activity.label }}</strong><small>{{ activity.detail }}</small></div>
        </li>
      </ol>
    </section>

    <template v-if="multiAgentResult">
      <section class="agent-workflow-section">
        <div class="results-heading">
          <p class="eyebrow">AGENT WORKFLOW</p>
          <span>
            {{ multiAgentResult.agents.length }} 个 Agent ·
            {{ multiAgentResult.usage.total_tokens }} tokens
          </span>
        </div>
        <div class="agent-step-list">
          <article
            v-for="(agent, index) in multiAgentResult.agents"
            :key="agent.name"
            class="agent-step-card"
          >
            <header>
              <span>{{ index + 1 }}</span>
              <div>
                <strong>{{ agent.label }}</strong>
                <small>{{ agent.duration_ms }} ms · {{ agent.usage.total_tokens }} tokens</small>
              </div>
            </header>
            <div class="agent-step-output">{{ agent.output }}</div>
          </article>
        </div>
      </section>

      <article class="answer-panel diagnosis-answer">
        <div class="answer-heading">
          <div><p class="eyebrow">REVIEWED DIAGNOSIS</p><h2>审查后的诊断结论</h2></div>
          <span>
            审查 {{ multiAgentResult.review.score }} 分 · {{ multiAgentResult.model }} ·
            {{ multiAgentResult.duration_ms }} ms
          </span>
        </div>
        <div class="answer-content">{{ multiAgentResult.final_answer }}</div>
        <div :class="['review-summary', { passed: multiAgentResult.review.passed }]">
          <strong>{{ multiAgentResult.review.passed ? '审查通过' : '审查后已修订' }}</strong>
          <span>证据质量评分 {{ multiAgentResult.review.score }}/100</span>
        </div>
        <ul v-if="multiAgentResult.review.issues.length" class="review-issues">
          <li v-for="issue in multiAgentResult.review.issues" :key="issue">{{ issue }}</li>
        </ul>
        <details class="draft-answer">
          <summary>查看审查前的调查草稿</summary>
          <div>{{ multiAgentResult.draft_answer }}</div>
        </details>
        <p v-for="warning in multiAgentResult.warnings" :key="warning" class="answer-warning">
          {{ warning }}
        </p>
      </article>
    </template>

    <template v-if="result">
      <article class="answer-panel diagnosis-answer">
        <div class="answer-heading">
          <div><p class="eyebrow">DIAGNOSIS</p><h2>诊断结论</h2></div>
          <span>
            {{ result.model }} · {{ result.iterations }} 轮 · {{ result.usage.total_tokens }} tokens ·
            {{ result.duration_ms }} ms
          </span>
        </div>
        <div class="answer-content">{{ result.answer }}</div>
        <p v-for="warning in result.warnings" :key="warning" class="answer-warning">
          {{ warning }}
        </p>
      </article>
    </template>

    <section v-if="activeToolCalls.length" class="tool-trace-section">
      <div class="results-heading">
        <p class="eyebrow">TOOL TRACE</p>
        <span>{{ activeToolCalls.length }} 次工具调用</span>
      </div>
      <article v-for="(call, index) in activeToolCalls" :key="call.call_id" class="tool-card">
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
  </section>
</template>
