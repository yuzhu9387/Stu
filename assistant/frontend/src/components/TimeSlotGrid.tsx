interface TimeSlot { id: number; start_time: string; end_time: string; slot_type: string }
const typeStyles: Record<string, string> = {
  task: 'bg-blue-100 border-blue-300 text-blue-800',
  habit: 'bg-green-100 border-green-300 text-green-800',
  calendar_event: 'bg-purple-100 border-purple-300 text-purple-800',
  break: 'bg-gray-100 border-gray-300 text-gray-500',
  free: 'bg-white border-gray-200 text-gray-400',
}
const typeLabels: Record<string, string> = { task: 'Task', habit: 'Habit', calendar_event: 'Meeting', break: 'Break', free: 'Free' }

export default function TimeSlotGrid({ slots }: { slots: TimeSlot[] }) {
  return (
    <div className="space-y-1">
      {slots.map(slot => (
        <div key={slot.id} className={`flex items-center px-3 py-2 rounded border ${typeStyles[slot.slot_type] || typeStyles.free}`}>
          <span className="text-xs font-mono w-28">{slot.start_time.slice(0, 5)} - {slot.end_time.slice(0, 5)}</span>
          <span className="text-sm font-medium ml-2">{typeLabels[slot.slot_type] || slot.slot_type}</span>
        </div>
      ))}
    </div>
  )
}
