import { useEffect, useState } from 'react'
import { api } from '../api/client'

const USER_ID = 1

export default function ReportPage() {
  const [reports, setReports] = useState<any[]>([])
  const [reportType, setReportType] = useState('daily')
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    async function load() { setLoading(true); try { setReports(await api.listReports(USER_ID, reportType)) } catch { setReports([]) } finally { setLoading(false) } }
    load()
  }, [reportType])

  const generate = async () => {
    const today = new Date().toISOString().slice(0, 10)
    try {
      if (reportType === 'daily') await api.generateDailyReport(USER_ID, today)
      else await api.generateWeeklyReport(USER_ID, today)
      setReports(await api.listReports(USER_ID, reportType))
    } catch (e) { console.error(e) }
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-2xl font-semibold text-gray-800">Reports</h2>
        <div className="flex gap-2">
          {['daily', 'weekly'].map(t => (
            <button key={t} onClick={() => setReportType(t)} className={`px-3 py-1.5 text-sm rounded-lg ${reportType === t ? 'bg-blue-600 text-white' : 'bg-gray-100 text-gray-600'}`}>
              {t.charAt(0).toUpperCase() + t.slice(1)}
            </button>
          ))}
          <button onClick={generate} className="px-3 py-1.5 text-sm bg-green-600 text-white rounded-lg">Generate</button>
        </div>
      </div>
      {loading ? <p className="text-gray-400">Loading...</p> : reports.length > 0 ? (
        <div className="space-y-4">
          {reports.map(r => (
            <div key={r.id} className="bg-white rounded-xl border border-gray-200 p-5">
              <div className="flex justify-between items-center mb-3">
                <span className="text-sm font-medium text-gray-600">{r.period_start}{r.period_start !== r.period_end ? ` → ${r.period_end}` : ''}</span>
                <span className="text-xs px-2 py-0.5 bg-blue-50 text-blue-600 rounded-full">{r.report_type}</span>
              </div>
              {r.data && (
                <div className="grid grid-cols-3 gap-3 mb-3">
                  <div className="text-center"><p className="text-2xl font-bold text-blue-600">{Math.round((r.data.completion_rate || 0) * 100)}%</p><p className="text-xs text-gray-400">Completion</p></div>
                  <div className="text-center"><p className="text-2xl font-bold text-green-600">{r.data.completed_tasks || 0}</p><p className="text-xs text-gray-400">Completed</p></div>
                  <div className="text-center"><p className="text-2xl font-bold text-gray-600">{r.data.total_tasks || 0}</p><p className="text-xs text-gray-400">Total</p></div>
                </div>
              )}
              {r.ai_insights && <p className="text-sm text-gray-600 bg-gray-50 rounded-lg p-3">{r.ai_insights}</p>}
            </div>
          ))}
        </div>
      ) : <p className="text-gray-400">No reports yet. Click Generate.</p>}
    </div>
  )
}
