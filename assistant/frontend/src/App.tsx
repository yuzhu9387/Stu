import { BrowserRouter, Routes, Route, NavLink } from 'react-router-dom'
import DashboardPage from './pages/DashboardPage'
import PlanPage from './pages/PlanPage'
import TimeAnalyticsPage from './pages/TimeAnalyticsPage'
import GoalsPage from './pages/GoalsPage'
import ReportPage from './pages/ReportPage'
import ChatPage from './pages/ChatPage'

function Layout({ children }: { children: React.ReactNode }) {
  const links = [
    { to: '/', label: 'Dashboard' },
    { to: '/plan', label: 'Plan' },
    { to: '/analytics', label: 'Analytics' },
    { to: '/goals', label: 'Goals' },
    { to: '/reports', label: 'Reports' },
    { to: '/chat', label: 'Chat' },
  ]
  return (
    <div className="flex h-screen bg-gray-50">
      <nav className="w-56 bg-white border-r border-gray-200 p-4">
        <h1 className="text-xl font-bold text-gray-800 mb-6">Assistant</h1>
        <ul className="space-y-1">
          {links.map((l) => (
            <li key={l.to}>
              <NavLink to={l.to} className={({ isActive }) =>
                `block px-3 py-2 rounded-lg text-sm ${isActive ? 'bg-blue-50 text-blue-700 font-medium' : 'text-gray-600 hover:bg-gray-100'}`
              }>{l.label}</NavLink>
            </li>
          ))}
        </ul>
      </nav>
      <main className="flex-1 overflow-auto p-6">{children}</main>
    </div>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <Layout>
        <Routes>
          <Route path="/" element={<DashboardPage />} />
          <Route path="/plan" element={<PlanPage />} />
          <Route path="/analytics" element={<TimeAnalyticsPage />} />
          <Route path="/goals" element={<GoalsPage />} />
          <Route path="/reports" element={<ReportPage />} />
          <Route path="/chat" element={<ChatPage />} />
        </Routes>
      </Layout>
    </BrowserRouter>
  )
}
