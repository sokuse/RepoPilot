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
