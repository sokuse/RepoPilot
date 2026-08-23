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

export interface RagAnswerResponse {
  project_id: string
  question: string
  answer: string
  citations: RagCitation[]
  retrieved_chunks: SemanticSearchResult[]
  steps: RagExecutionStep[]
  warnings: string[]
}

// 后端通过 SSE 依次发送召回结果、文本增量、工作流步骤和最终校验结果。
export type RagStreamEvent =
  | {
      type: 'retrieval'
      retrieved_chunks: SemanticSearchResult[]
      step: RagExecutionStep
    }
  | { type: 'token'; delta: string }
  | { type: 'step'; step: RagExecutionStep }
  | { type: 'complete'; response: RagAnswerResponse }
  | { type: 'error'; message: string }
