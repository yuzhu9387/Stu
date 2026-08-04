interface GoalProgressProps { title: string; current: number; target: number; unit: string }
export default function GoalProgress({ title, current, target, unit }: GoalProgressProps) {
  const pct = target > 0 ? Math.min((current / target) * 100, 100) : 0
  return (
    <div className="bg-white rounded-lg p-4 border border-gray-200">
      <div className="flex justify-between items-center mb-2">
        <span className="font-medium text-gray-800">{title}</span>
        <span className="text-sm text-gray-500">{current}/{target} {unit}</span>
      </div>
      <div className="w-full bg-gray-200 rounded-full h-2.5">
        <div className="bg-blue-600 h-2.5 rounded-full transition-all" style={{ width: `${pct}%` }} />
      </div>
      <p className="text-xs text-gray-400 mt-1">{Math.round(pct)}%</p>
    </div>
  )
}
