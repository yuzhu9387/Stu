const BASE = '/api'

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, { headers: { 'Content-Type': 'application/json' }, ...options })
  if (!res.ok) throw new Error(`API error: ${res.status}`)
  if (res.status === 204) return {} as T
  return res.json()
}

export const api = {
  getUser: (id: number) => request<any>(`/users/${id}`),
  listTasks: (userId: number, status?: string) => request<any[]>(`/users/${userId}/tasks${status ? `?status=${status}` : ''}`),
  createTask: (userId: number, data: any) => request<any>(`/users/${userId}/tasks`, { method: 'POST', body: JSON.stringify(data) }),
  updateTask: (taskId: number, data: any) => request<any>(`/tasks/${taskId}`, { method: 'PATCH', body: JSON.stringify(data) }),
  listGoals: (userId: number) => request<any[]>(`/users/${userId}/goals`),
  updateGoal: (goalId: number, data: any) => request<any>(`/goals/${goalId}`, { method: 'PATCH', body: JSON.stringify(data) }),
  listHabits: (userId: number) => request<any[]>(`/users/${userId}/habits`),
  recordHabit: (habitId: number) => request<any>(`/habits/${habitId}/records`, { method: 'POST' }),
  getPlan: (userId: number, date: string) => request<any>(`/users/${userId}/plans/${date}`),
  replaceSlots: (planId: number, slots: any[]) => request<any>(`/plans/${planId}/slots`, { method: 'PUT', body: JSON.stringify(slots) }),
  generateDailyReport: (userId: number, date: string) => request<any>(`/reports/${userId}/daily`, { method: 'POST', body: JSON.stringify({ date }) }),
  generateWeeklyReport: (userId: number, weekEnd: string) => request<any>(`/reports/${userId}/weekly`, { method: 'POST', body: JSON.stringify({ week_end: weekEnd }) }),
  listReports: (userId: number, type?: string) => request<any[]>(`/reports/${userId}${type ? `?report_type=${type}` : ''}`),
  chat: (userId: number, message: string, sessionId?: number) => request<any>(`/chat/${userId}`, { method: 'POST', body: JSON.stringify({ message, session_id: sessionId }) }),
  getScreenTime: (userId: number, date: string) => request<any>(`/ingestion/screen-time/${userId}/${date}`),
}
