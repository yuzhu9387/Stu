import { useEffect, useState } from 'react'
import { PieChart, Pie, Cell, Tooltip, ResponsiveContainer, Legend } from 'recharts'
import { api } from '../api/client'
import StatCard from '../components/StatCard'

const USER_ID = 1
const COLORS = ['#3B82F6', '#10B981', '#F59E0B', '#8B5CF6', '#EF4444', '#6B7280']

export default function TimeAnalyticsPage() {
  const [date, setDate] = useState(() => new Date().toISOString().slice(0, 10))
  const [screenTime, setScreenTime] = useState<any>(null)

  useEffect(() => {
    async function load() {
      try { setScreenTime(await api.getScreenTime(USER_ID, date)) } catch { setScreenTime(null) }
    }
    load()
  }, [date])

  const chartData = screenTime?.by_category ? Object.entries(screenTime.by_category).map(([name, value]) => ({ name, value })) : []

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-2xl font-semibold text-gray-800">Time Analytics</h2>
        <input type="date" value={date} onChange={e => setDate(e.target.value)} className="border border-gray-300 rounded-lg px-3 py-1.5 text-sm" />
      </div>
      <div className="grid grid-cols-3 gap-4">
        <StatCard label="Total Screen Time" value={screenTime ? `${Math.round(screenTime.total_minutes / 60 * 10) / 10}h` : '--'} color="blue" />
        <StatCard label="Categories" value={chartData.length} color="purple" />
        <StatCard label="Top App" value={screenTime?.by_app ? Object.entries(screenTime.by_app).sort((a: any, b: any) => b[1] - a[1])[0]?.[0] || '--' : '--'} color="orange" />
      </div>
      {chartData.length > 0 && (
        <div className="bg-white rounded-xl border border-gray-200 p-6">
          <h3 className="text-lg font-medium text-gray-700 mb-4">Screen Time by Category</h3>
          <ResponsiveContainer width="100%" height={300}>
            <PieChart>
              <Pie data={chartData} dataKey="value" nameKey="name" cx="50%" cy="50%" outerRadius={100} label>
                {chartData.map((_, i) => <Cell key={i} fill={COLORS[i % COLORS.length]} />)}
              </Pie>
              <Tooltip /><Legend />
            </PieChart>
          </ResponsiveContainer>
        </div>
      )}
      {!screenTime && <p className="text-gray-400">No screen time data for this date</p>}
    </div>
  )
}
