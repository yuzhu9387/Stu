import { useEffect, useState } from 'react'
import { api } from '../api/client'
import TimeSlotGrid from '../components/TimeSlotGrid'

const USER_ID = 1

export default function PlanPage() {
  const [date, setDate] = useState(() => new Date().toISOString().slice(0, 10))
  const [plan, setPlan] = useState<any>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    async function load() {
      setLoading(true)
      try { setPlan(await api.getPlan(USER_ID, date)) } catch (e) { console.error(e) }
      finally { setLoading(false) }
    }
    load()
  }, [date])

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-2xl font-semibold text-gray-800">Daily Plan</h2>
        <input type="date" value={date} onChange={e => setDate(e.target.value)} className="border border-gray-300 rounded-lg px-3 py-1.5 text-sm" />
      </div>
      {plan && <div className="flex gap-3 text-sm text-gray-500"><span>Version: {plan.version}</span><span>{plan.slots?.length || 0} slots</span></div>}
      {loading ? <p className="text-gray-400">Loading...</p> : plan?.slots?.length > 0 ? <TimeSlotGrid slots={plan.slots} /> : <p className="text-gray-400">No plan for this day</p>}
    </div>
  )
}
