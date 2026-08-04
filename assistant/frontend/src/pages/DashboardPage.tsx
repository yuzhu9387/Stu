import { useEffect, useState } from 'react'
import { api } from '../api/client'
import StatCard from '../components/StatCard'
import TaskCard from '../components/TaskCard'
import GoalProgress from '../components/GoalProgress'

const USER_ID = 1

export default function DashboardPage() {
  const [tasks, setTasks] = useState<any[]>([])
  const [goals, setGoals] = useState<any[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    async function load() {
      try {
        const [t, g] = await Promise.all([api.listTasks(USER_ID), api.listGoals(USER_ID)])
        setTasks(t); setGoals(g)
      } catch (e) { console.error(e) }
      finally { setLoading(false) }
    }
    load()
  }, [])

  if (loading) return <p className="text-gray-400">Loading...</p>

  const completed = tasks.filter(t => t.status === 'completed').length
  const pending = tasks.filter(t => t.status === 'pending')
  const rate = tasks.length > 0 ? Math.round((completed / tasks.length) * 100) : 0

  return (
    <div className="space-y-6">
      <h2 className="text-2xl font-semibold text-gray-800">Dashboard</h2>
      <div className="grid grid-cols-4 gap-4">
        <StatCard label="Total Tasks" value={tasks.length} color="blue" />
        <StatCard label="Completed" value={completed} color="green" />
        <StatCard label="Pending" value={pending.length} color="orange" />
        <StatCard label="Completion Rate" value={`${rate}%`} color="purple" />
      </div>
      <div className="grid grid-cols-2 gap-6">
        <div>
          <h3 className="text-lg font-medium text-gray-700 mb-3">Pending Tasks</h3>
          <div className="space-y-2">
            {pending.slice(0, 5).map(task => (
              <TaskCard key={task.id} title={task.title} quadrant={task.quadrant} status={task.status} deadline={task.deadline}
                onComplete={async () => { await api.updateTask(task.id, { status: 'completed' }); setTasks(tasks.map(t => t.id === task.id ? {...t, status: 'completed'} : t)) }} />
            ))}
            {pending.length === 0 && <p className="text-gray-400 text-sm">No pending tasks</p>}
          </div>
        </div>
        <div>
          <h3 className="text-lg font-medium text-gray-700 mb-3">Goals</h3>
          <div className="space-y-3">
            {goals.map(g => <GoalProgress key={g.id} title={g.title} current={g.current_value} target={g.target_value} unit={g.unit} />)}
            {goals.length === 0 && <p className="text-gray-400 text-sm">No goals set</p>}
          </div>
        </div>
      </div>
    </div>
  )
}
