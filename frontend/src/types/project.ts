export type ProjectStatus = 'pending' | 'indexing' | 'ready' | 'failed'

export interface Project {
  id: string
  name: string
  repository_url: string
  default_branch: string
  status: ProjectStatus
  created_at: string
}

export interface ProjectCreate {
  name: string
  repository_url: string
  default_branch: string
}

