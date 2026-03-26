const BASE = import.meta.env.VITE_API_URL || '/api'

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const url = BASE.startsWith('http') ? `${BASE}${path}` : `${BASE}${path}`
  const opts: RequestInit = {
    method,
    headers: { 'Content-Type': 'application/json' },
  }
  if (body) opts.body = JSON.stringify(body)
  const res = await fetch(url, opts)
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
  return res.json()
}

export const api = {
  get: <T>(path: string) => request<T>('GET', path),
  post: <T>(path: string, body?: unknown) => request<T>('POST', path, body),
}
