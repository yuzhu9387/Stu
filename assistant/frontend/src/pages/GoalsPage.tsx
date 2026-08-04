import { useEffect, useState } from 'react'
import { api } from '../api/client'
import GoalProgress from '../components/GoalProgress'

const USER_ID = 1

export default function GoalsPage() {
  const [goals, setGoals] = useState<any[]>([])
  const [habits, setHabits] = useState<any[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    async function load() {
      try { const [g, h] = await Promise.all([api.listGoals(USER_ID), api.listHabits(USER_ID)]); setGoals(g); setHabits(h) }
      catch (e) { console.error(e) }
      finally { setLoading(false) }
    }
    load()
  }, [])

  if (loading) return <p className="text-gray-400">Loading...</p>

  return (
    <div className="space-y-6">
      <h2 className="text-2xl font-semibold text-gray-800">Goals & Habits</h2>
      <div>
        <h3 className="text-lg font-medium text-gray-700 mb-3">Annual Goals</h3>
        <div className="grid grid-cols-2 gap-4">
          {goals.map(g => <GoalProgress key={g.id} title={g.title} current={g.current_value} target={g.target_value} unit={g.unit} />)}
          {goals.length === 0 && <p className="text-gray-400 text-sm">No goals set</p>}
        </div>
      </div>
      <div>
        <h3 className="text-lg font-medium text-gray-700 mb-3">Habits</h3>
        <div className="grid grid-cols-2 gap-4">
          {habits.map(h => (
            <div key={h.id} className="bg-white rounded-lg p-4 border border-gray-200 flex items-center justify-between">
              <div>
                <p className="font-medium text-gray-800">{h.title}</p>
                <p className="text-xs text-gray-400">{h.frequency_count}x / {h.frequency_type}</p>
              </div>
              <button onClick={async () => { await api.recordHabit(h.id); alert('Recorded!') }} className="px-3 py-1 text-sm bg-green-50 text-green-700 rounded-lg hover:bg-green-100">Check In</button>
            </div>
          ))}
          {habits.length === 0 && <p className="text-gray-400 text-sm">No habits set</p>}
        </div>
      </div>
    </div>
  )
}
