export type ProjectStatus = 'pending' | 'indexing' | 'ready' | 'failed'

export interface Project {
  id: string
  name: string
  repository_url: string
  default_branch: string
  status: ProjectStatus
  created_at: string
  updated_at: string
}

export interface ProjectCreate {
  name: string
  repository_url: string
  default_branch: string
}

// 仓库采集完成后的文件规模和语言分布。
export interface RepositoryStats {
  project_id: string
  total_files: number
  total_bytes: number
  language_breakdown: Record<string, number>
}

// 切片统计会在后续 Embedding 阶段继续复用，用来展示知识库构建进度。
export interface ChunkingStats {
  project_id: string
  total_chunks: number
  total_chars: number
  strategy_breakdown: Record<string, number>
}

export interface VectorIndexStats {
  project_id: string
  ready: boolean
  embedding_model: string
  vector_size: number
  indexed_chunks: number
  indexed_at: string | null
}

export interface SemanticSearchResult {
  chunk_id: string
  score: number
  source_path: string
  start_line: number
  end_line: number
  symbol_name: string | null
  strategy: string
  content: string
}

export interface SemanticSearchResponse {
  project_id: string
  query: string
  results: SemanticSearchResult[]
}

export interface RagCitation {
  source_id: string
  chunk_id: string
  source_path: string
  start_line: number
  end_line: number
  symbol_name: string | null
  score: number
}

export interface RagExecutionStep {
  name: string
  label: string
  detail: string
}

export interface RagTokenUsage {
  prompt_tokens: number
  completion_tokens: number
  total_tokens: number
}

export interface RagAnswerResponse {
  run_id: string | null
  project_id: string
  question: string
  answer: string
  citations: RagCitation[]
  retrieved_chunks: SemanticSearchResult[]
  steps: RagExecutionStep[]
  warnings: string[]
  usage: RagTokenUsage
  duration_ms: number
}

export interface RagRunSummary {
  id: string
  project_id: string
  question: string
  status: 'running' | 'completed' | 'failed'
  chat_model: string
  embedding_model: string
  retrieval_limit: number
  retrieved_count: number
  citation_count: number
  prompt_tokens: number
  completion_tokens: number
  total_tokens: number
  duration_ms: number
  created_at: string
  completed_at: string | null
}

export interface RagRunDetail extends RagRunSummary {
  answer: string
  retrieved_chunks: SemanticSearchResult[]
  citations: RagCitation[]
  steps: RagExecutionStep[]
  warnings: string[]
  error_message: string | null
}

// 后端通过 SSE 依次发送召回结果、文本增量、工作流步骤和最终校验结果。
export type RagStreamEvent =
  | { type: 'run'; run_id: string }
  | {
      type: 'retrieval'
      retrieved_chunks: SemanticSearchResult[]
      step: RagExecutionStep
    }
  | { type: 'token'; delta: string }
  | { type: 'step'; step: RagExecutionStep }
  | { type: 'complete'; response: RagAnswerResponse }
  | { type: 'error'; message: string }

export interface ToolCallTrace {
  call_id: string
  name: string
  arguments: Record<string, unknown>
  summary: string
  result: string
  success: boolean
  duration_ms: number
}

export interface DiagnosisResponse {
  project_id: string
  question: string
  answer: string
  model: string
  iterations: number
  duration_ms: number
  usage: RagTokenUsage
  tool_calls: ToolCallTrace[]
  warnings: string[]
}

export interface AgentExecutionStep {
  name: string
  label: string
  output: string
  duration_ms: number
  usage: RagTokenUsage
}

export interface DiagnosisReview {
  passed: boolean
  score: number
  issues: string[]
  final_answer: string
}

export interface MultiAgentDiagnosisResponse {
  project_id: string
  question: string
  model: string
  plan: string
  draft_answer: string
  review: DiagnosisReview
  final_answer: string
  tool_calls: ToolCallTrace[]
  agents: AgentExecutionStep[]
  usage: RagTokenUsage
  duration_ms: number
  warnings: string[]
}

export interface RequestedDiagnosisToolCall {
  call_id: string
  name: string
  arguments: Record<string, unknown>
}

export type DiagnosisStreamEvent =
  | { type: 'start'; question: string; max_iterations: number }
  | {
      type: 'decision'
      iteration: number
      tool_calls: RequestedDiagnosisToolCall[]
    }
  | {
      type: 'tool_start'
      call_id: string
      name: string
      arguments: Record<string, unknown>
    }
  | { type: 'tool_complete'; trace: ToolCallTrace }
  | { type: 'complete'; response: DiagnosisResponse }
  | { type: 'error'; message: string }
