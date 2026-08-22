import type { ChunkingStats, Project, ProjectCreate, RepositoryStats } from '../types/project'

const API_PREFIX = '/api/v1'

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
  ) {
    super(message)
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_PREFIX}${path}`, {
    headers: { 'Content-Type': 'application/json', ...init?.headers },
    ...init,
  })

  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as { detail?: string } | null
    throw new ApiError(response.status, body?.detail ?? `请求失败：${response.status}`)
  }

  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}

export const projectApi = {
  list: () => request<Project[]>('/projects'),
  create: (payload: ProjectCreate) =>
    request<Project>('/projects', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  remove: (projectId: string) => request<void>(`/projects/${projectId}`, { method: 'DELETE' }),
  ingest: (projectId: string) =>
    request<Project>(`/projects/${projectId}/ingest`, { method: 'POST' }),
  stats: (projectId: string) => request<RepositoryStats>(`/projects/${projectId}/stats`),
  chunkStats: (projectId: string) =>
    request<ChunkingStats>(`/projects/${projectId}/chunks/stats`),
  rebuildChunks: (projectId: string) =>
    request<ChunkingStats>(`/projects/${projectId}/chunks`, { method: 'POST' }),
}
