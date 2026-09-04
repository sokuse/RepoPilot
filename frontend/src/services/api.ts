import type {
  ChunkingStats,
  DiagnosisResponse,
  MultiAgentDiagnosisResponse,
  Project,
  ProjectCreate,
  RagAnswerResponse,
  RagRunDetail,
  RagRunSummary,
  RagStreamEvent,
  RepositoryStats,
  SemanticSearchResponse,
  VectorIndexStats,
} from '../types/project'

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

async function readEventStream(
  response: Response,
  onEvent: (event: RagStreamEvent) => void,
): Promise<void> {
  if (!response.body) throw new ApiError(500, '浏览器没有提供可读取的响应流。')

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  // fetch 的每个网络块不一定刚好对应一个 SSE 事件，因此必须自行拼接完整数据帧。
  while (true) {
    const { value, done } = await reader.read()
    buffer += decoder.decode(value, { stream: !done })

    let boundary = buffer.indexOf('\n\n')
    while (boundary >= 0) {
      const frame = buffer.slice(0, boundary)
      buffer = buffer.slice(boundary + 2)
      const data = frame
        .split('\n')
        .filter((line) => line.startsWith('data:'))
        .map((line) => line.slice(5).trimStart())
        .join('\n')
      if (data) onEvent(JSON.parse(data) as RagStreamEvent)
      boundary = buffer.indexOf('\n\n')
    }

    if (done) break
  }
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
  indexStats: (projectId: string) =>
    request<VectorIndexStats>(`/projects/${projectId}/index/stats`),
  rebuildIndex: (projectId: string) =>
    request<VectorIndexStats>(`/projects/${projectId}/index`, { method: 'POST' }),
  semanticSearch: (projectId: string, query: string, limit = 5) =>
    request<SemanticSearchResponse>(`/projects/${projectId}/index/search`, {
      method: 'POST',
      body: JSON.stringify({ query, limit }),
    }),
  askRag: (projectId: string, question: string, retrievalLimit = 8) =>
    request<RagAnswerResponse>(`/projects/${projectId}/rag/ask`, {
      method: 'POST',
      body: JSON.stringify({ question, retrieval_limit: retrievalLimit }),
    }),
  listRagRuns: (projectId: string, limit = 20) =>
    request<RagRunSummary[]>(`/projects/${projectId}/rag/runs?limit=${limit}`),
  getRagRun: (projectId: string, runId: string) =>
    request<RagRunDetail>(`/projects/${projectId}/rag/runs/${runId}`),
  askRagStream: async (
    projectId: string,
    question: string,
    onEvent: (event: RagStreamEvent) => void,
    retrievalLimit = 8,
  ) => {
    const response = await fetch(`${API_PREFIX}/projects/${projectId}/rag/stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question, retrieval_limit: retrievalLimit }),
    })
    if (!response.ok) {
      const body = (await response.json().catch(() => null)) as { detail?: string } | null
      throw new ApiError(response.status, body?.detail ?? `请求失败：${response.status}`)
    }

    let streamError = ''
    await readEventStream(response, (event) => {
      if (event.type === 'error') streamError = event.message
      else onEvent(event)
    })
    if (streamError) throw new ApiError(502, streamError)
  },
  diagnose: (projectId: string, question: string, maxIterations = 3) =>
    request<DiagnosisResponse>(`/projects/${projectId}/diagnosis`, {
      method: 'POST',
      body: JSON.stringify({ question, max_iterations: maxIterations }),
    }),
  multiAgentDiagnose: (projectId: string, question: string, maxIterations = 3) =>
    request<MultiAgentDiagnosisResponse>(`/projects/${projectId}/diagnosis/multi-agent`, {
      method: 'POST',
      body: JSON.stringify({ question, max_iterations: maxIterations }),
    }),
}
