interface TaskCardProps { title: string; quadrant?: string; status: string; deadline?: string; onComplete?: () => void }
const qLabels: Record<string, { label: string; color: string }> = {
  urgent_important: { label: 'Urgent & Important', color: 'bg-red-100 text-red-700' },
  important: { label: 'Important', color: 'bg-blue-100 text-blue-700' },
  urgent: { label: 'Urgent', color: 'bg-orange-100 text-orange-700' },
  neither: { label: 'Low Priority', color: 'bg-gray-100 text-gray-600' },
}
export default function TaskCard({ title, quadrant, status, deadline, onComplete }: TaskCardProps) {
  const q = quadrant ? qLabels[quadrant] : null
  return (
    <div className="bg-white rounded-lg p-4 border border-gray-200 flex items-center justify-between">
      <div>
        <p className={`font-medium ${status === 'completed' ? 'line-through text-gray-400' : 'text-gray-800'}`}>{title}</p>
        <div className="flex gap-2 mt-1">
          {q && <span className={`text-xs px-2 py-0.5 rounded-full ${q.color}`}>{q.label}</span>}
          {deadline && <span className="text-xs text-gray-400">{deadline}</span>}
        </div>
      </div>
      {status !== 'completed' && onComplete && <button onClick={onComplete} className="text-sm text-blue-600 hover:text-blue-800">Done</button>}
    </div>
  )
}
