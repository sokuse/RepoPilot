<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { ApiError, projectApi } from '../services/api'
import type { DiagnosisResponse, DiagnosisStreamEvent, Project } from '../types/project'

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
const result = ref<DiagnosisResponse | null>(null)
const activities = ref<DiagnosisActivity[]>([])
const loading = ref(true)
const diagnosing = ref(false)
const errorMessage = ref('')

const exampleQuestions = [
  '定位最近一次改动可能引入的故障，并给出修复和验证步骤。',
  '追踪一个 API 请求从前端到数据库的完整调用链。',
  '分析异常为什么没有正确显示到前端，并列出代码证据。',
]

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
  activities.value = []
  errorMessage.value = ''
  try {
    await projectApi.diagnoseStream(
      selectedProjectId.value,
      question.value.trim(),
      handleStreamEvent,
      maxIterations.value,
    )
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
        <p class="eyebrow">TOOL-CALLING AGENT</p>
        <h1>智能诊断</h1>
        <p>面向复杂故障和根因分析：让 Qwen 多轮选择工具、读取代码证据并给出验证步骤。</p>
      </div>
      <div class="phase-pill">第六阶段 · Function Call</div>
    </header>

    <aside class="diagnosis-guide">
      <div><strong>什么时候使用智能诊断？</strong><span>当你要回答“为什么出错、怎么修、如何验证”时使用。</span></div>
      <div><strong>只想快速找代码？</strong><span>“知识检索”更快、成本更低，适合回答“是什么、在哪里”。</span></div>
    </aside>

    <article class="panel diagnosis-control">
      <form class="diagnosis-form" @submit.prevent="diagnose">
        <div class="diagnosis-options">
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
          {{ diagnosing ? 'Agent 正在调查…' : '开始智能诊断' }}
        </button>
      </form>
      <p v-if="errorMessage" class="error-banner">{{ errorMessage }}</p>
    </article>

    <section v-if="activities.length" class="panel diagnosis-progress">
      <div class="diagnosis-progress-heading">
        <div><span v-if="diagnosing" class="agent-pulse" /><strong>Agent 调查过程</strong></div>
        <small>{{ diagnosing ? '实时执行中' : '调查已完成' }}</small>
      </div>
      <ol class="diagnosis-timeline">
        <li v-for="activity in activities" :key="activity.id" :data-status="activity.status">
          <span />
          <div><strong>{{ activity.label }}</strong><small>{{ activity.detail }}</small></div>
        </li>
      </ol>
    </section>

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
