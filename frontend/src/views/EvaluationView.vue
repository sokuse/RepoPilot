<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'

import { ApiError, projectApi } from '../services/api'
import type {
  EvaluationCase,
  EvaluationMode,
  EvaluationRunDetail,
  EvaluationRunSummary,
  Project,
} from '../types/project'

const projects = ref<Project[]>([])
const selectedProjectId = ref('')
const cases = ref<EvaluationCase[]>([])
const selectedCaseIds = ref<string[]>([])
const runs = ref<EvaluationRunSummary[]>([])
const activeRun = ref<EvaluationRunDetail | null>(null)
const mode = ref<EvaluationMode>('rag')
const runName = ref('RAG 基线实验')
const loading = ref(true)
const saving = ref(false)
const running = ref(false)
const errorMessage = ref('')

const caseName = ref('')
const question = ref('')
const expectedFiles = ref('')
const requiredKeywords = ref('')

const modeLabels: Record<EvaluationMode, string> = {
  retrieval: '纯检索 · 只测试召回',
  rag: 'RAG · 检索后生成答案',
  single_agent: '单 Agent · Function Call',
  multi_agent: '多 Agent · 规划、调查、审查',
}

const allSelected = computed(
  () => cases.value.length > 0 && selectedCaseIds.value.length === cases.value.length,
)

function splitValues(value: string) {
  return [...new Set(value.split(/[，,\n]/).map((item) => item.trim()).filter(Boolean))]
}

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

async function loadEvaluationData() {
  cases.value = []
  runs.value = []
  activeRun.value = null
  selectedCaseIds.value = []
  if (!selectedProjectId.value) return
  errorMessage.value = ''
  try {
    const [caseRows, runRows] = await Promise.all([
      projectApi.listEvaluationCases(selectedProjectId.value),
      projectApi.listEvaluationRuns(selectedProjectId.value),
    ])
    cases.value = caseRows
    runs.value = runRows
    selectedCaseIds.value = caseRows.map((item) => item.id)
    if (runRows[0]) activeRun.value = await projectApi.getEvaluationRun(selectedProjectId.value, runRows[0].id)
  } catch (error) {
    errorMessage.value = error instanceof ApiError ? error.message : '无法读取评测数据。'
  }
}

async function createCase() {
  if (!selectedProjectId.value) return
  saving.value = true
  errorMessage.value = ''
  try {
    const created = await projectApi.createEvaluationCase(selectedProjectId.value, {
      name: caseName.value.trim(),
      question: question.value.trim(),
      expected_files: splitValues(expectedFiles.value),
      required_keywords: splitValues(requiredKeywords.value),
    })
    cases.value.unshift(created)
    selectedCaseIds.value.push(created.id)
    caseName.value = ''
    question.value = ''
    expectedFiles.value = ''
    requiredKeywords.value = ''
  } catch (error) {
    errorMessage.value = error instanceof ApiError ? error.message : '保存测试题失败。'
  } finally {
    saving.value = false
  }
}

async function removeCase(item: EvaluationCase) {
  if (!selectedProjectId.value) return
  await projectApi.deleteEvaluationCase(selectedProjectId.value, item.id)
  cases.value = cases.value.filter((value) => value.id !== item.id)
  selectedCaseIds.value = selectedCaseIds.value.filter((id) => id !== item.id)
}

function toggleAll() {
  selectedCaseIds.value = allSelected.value ? [] : cases.value.map((item) => item.id)
}

async function runEvaluation() {
  if (!selectedProjectId.value || !selectedCaseIds.value.length) return
  running.value = true
  activeRun.value = null
  errorMessage.value = ''
  try {
    activeRun.value = await projectApi.runEvaluation(selectedProjectId.value, {
      name: runName.value.trim(),
      mode: mode.value,
      case_ids: selectedCaseIds.value,
      retrieval_limit: 8,
      max_iterations: 3,
    })
    runs.value = await projectApi.listEvaluationRuns(selectedProjectId.value)
  } catch (error) {
    errorMessage.value = error instanceof ApiError ? error.message : '评测运行失败，请查看后端日志。'
  } finally {
    running.value = false
  }
}

async function openRun(run: EvaluationRunSummary) {
  if (!selectedProjectId.value) return
  activeRun.value = await projectApi.getEvaluationRun(selectedProjectId.value, run.id)
}

function formatMode(value: EvaluationMode) {
  return modeLabels[value].split(' · ')[0]
}

function formatDuration(durationMs: number) {
  return durationMs >= 1000 ? `${(durationMs / 1000).toFixed(1)} 秒` : `${durationMs} ms`
}

watch(selectedProjectId, () => void loadEvaluationData())
onMounted(() => void loadProjects())
</script>

<template>
  <section class="page evaluation-page">
    <header class="page-header">
      <div>
        <p class="eyebrow">AGENT EVALUATION</p>
        <h1>评测实验</h1>
        <p>用固定测试集比较检索、RAG、单 Agent 和多 Agent，记录准确率、证据质量、Token 与耗时。</p>
      </div>
      <div class="phase-pill">第九阶段 · Evals</div>
    </header>

    <article class="panel evaluation-control">
      <div class="evaluation-options">
        <label>选择项目
          <select v-model="selectedProjectId" :disabled="loading">
            <option value="" disabled>请选择已就绪项目</option>
            <option v-for="project in projects" :key="project.id" :value="project.id">{{ project.name }}</option>
          </select>
        </label>
        <label>评测模式
          <select v-model="mode" :disabled="running">
            <option v-for="(label, value) in modeLabels" :key="value" :value="value">{{ label }}</option>
          </select>
        </label>
        <label>实验名称
          <input v-model="runName" maxlength="200" :disabled="running" />
        </label>
        <button class="primary-button" type="button" :disabled="running || !selectedCaseIds.length" @click="runEvaluation">
          {{ running ? `正在执行 ${selectedCaseIds.length} 道题…` : `运行选中的 ${selectedCaseIds.length} 道题` }}
        </button>
      </div>
      <p class="evaluation-note">多 Agent 会产生更多模型调用。建议先用“纯检索”校验测试集，再分别运行其他模式进行比较。</p>
      <p v-if="errorMessage" class="error-banner">{{ errorMessage }}</p>
    </article>

    <div class="evaluation-grid">
      <article class="panel">
        <div class="panel-heading"><div><p class="eyebrow">DATASET</p><h2>测试问题集</h2></div></div>
        <form class="evaluation-case-form" @submit.prevent="createCase">
          <label>题目名称<input v-model="caseName" required placeholder="例如：FastAPI 应用入口" /></label>
          <label>问题<textarea v-model="question" required minlength="2" placeholder="项目在哪里创建 FastAPI 应用？" /></label>
          <label>期望文件<input v-model="expectedFiles" required placeholder="backend/src/repopilot/main.py" /></label>
          <label>必要关键词<input v-model="requiredKeywords" required placeholder="FastAPI, create_app" /></label>
          <small>多个文件或关键词使用逗号分隔。</small>
          <button class="secondary-button" type="submit" :disabled="saving || !selectedProjectId">{{ saving ? '保存中…' : '添加测试题' }}</button>
        </form>

        <div class="case-list-heading"><strong>{{ cases.length }} 道题</strong><button class="text-button" type="button" @click="toggleAll">{{ allSelected ? '取消全选' : '全选' }}</button></div>
        <div v-if="cases.length" class="evaluation-case-list">
          <article v-for="item in cases" :key="item.id">
            <input v-model="selectedCaseIds" type="checkbox" :value="item.id" />
            <div><strong>{{ item.name }}</strong><p>{{ item.question }}</p><small>文件：{{ item.expected_files.join('、') }}<br />关键词：{{ item.required_keywords.join('、') }}</small></div>
            <button class="delete-button" type="button" @click="removeCase(item)">删除</button>
          </article>
        </div>
        <p v-else class="history-empty">先添加一条有明确期望文件和关键词的测试题。</p>
      </article>

      <section>
        <article v-if="activeRun" class="panel evaluation-report">
          <div class="panel-heading"><div><p class="eyebrow">LATEST REPORT</p><h2>{{ activeRun.name }}</h2></div><span class="status-badge" data-status="ready">{{ formatMode(activeRun.mode) }}</span></div>
          <div class="evaluation-metrics">
            <div><span>综合得分</span><strong>{{ activeRun.average_overall_score.toFixed(1) }}</strong></div>
            <div><span>通过题目</span><strong>{{ activeRun.passed_count }}/{{ activeRun.case_count }}</strong></div>
            <div><span>文件召回</span><strong>{{ activeRun.average_retrieval_score.toFixed(1) }}</strong></div>
            <div><span>证据可信</span><strong>{{ activeRun.average_evidence_score.toFixed(1) }}</strong></div>
            <div><span>Token</span><strong>{{ activeRun.total_tokens }}</strong></div>
            <div><span>耗时</span><strong>{{ formatDuration(activeRun.duration_ms) }}</strong></div>
          </div>
          <p class="evaluation-snapshot">{{ activeRun.chat_model }} · {{ activeRun.embedding_model }} · 切片策略：{{ activeRun.chunk_strategies.join('、') || '未记录' }}</p>
          <div class="evaluation-results">
            <article v-for="result in activeRun.results" :key="result.id" :data-passed="result.passed">
              <header><div><strong>{{ result.case_name }}</strong><small>{{ result.question }}</small></div><b>{{ result.error_message ? '失败' : `${result.overall_score.toFixed(1)} 分` }}</b></header>
              <div class="result-scores"><span>召回 {{ result.retrieval_score.toFixed(0) }}</span><span>关键词 {{ result.keyword_score.toFixed(0) }}</span><span>证据 {{ result.evidence_score.toFixed(0) }}</span><span>{{ result.total_tokens }} tokens</span></div>
              <p v-if="result.error_message" class="error-banner">{{ result.error_message }}</p>
              <details v-else><summary>查看答案与召回文件</summary><p>{{ result.answer || '纯检索模式不生成答案。' }}</p><small>{{ result.retrieved_files.join('、') || '没有召回文件' }}</small></details>
            </article>
          </div>
        </article>
        <article v-else class="panel empty-state"><span class="empty-icon">◎</span><strong>尚无评测报告</strong><p>选择测试题并运行一次实验。</p></article>

        <article class="panel evaluation-history">
          <div class="panel-heading"><div><p class="eyebrow">EXPERIMENTS</p><h2>历史实验</h2></div></div>
          <div v-if="runs.length" class="evaluation-run-list">
            <button v-for="run in runs" :key="run.id" type="button" @click="openRun(run)"><strong>{{ run.name }}</strong><span>{{ formatMode(run.mode) }} · {{ run.average_overall_score.toFixed(1) }} 分 · {{ run.total_tokens }} tokens</span><small>{{ new Date(run.created_at).toLocaleString() }}</small></button>
          </div>
          <p v-else class="history-empty">不同模式的实验会保存在这里，方便横向比较。</p>
        </article>
      </section>
    </div>
  </section>
</template>
