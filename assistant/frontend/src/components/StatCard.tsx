interface StatCardProps { label: string; value: string | number; subtitle?: string; color?: string }
const colors: Record<string, string> = { blue: 'text-blue-600', green: 'text-green-600', orange: 'text-orange-600', purple: 'text-purple-600' }
export default function StatCard({ label, value, subtitle, color = 'blue' }: StatCardProps) {
  return (
    <div className="bg-white rounded-xl p-5 border border-gray-200">
      <p className="text-sm text-gray-500">{label}</p>
      <p className={`text-3xl font-bold mt-1 ${colors[color] || colors.blue}`}>{value}</p>
      {subtitle && <p className="text-xs text-gray-400 mt-1">{subtitle}</p>}
    </div>
  )
}
