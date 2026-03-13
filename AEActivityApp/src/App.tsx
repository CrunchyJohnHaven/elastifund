import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { ThemeProvider } from './components/ThemeProvider'
import { Layout } from './components/Layout'
import { Leaderboard } from './components/Leaderboard'
import { CalendarOverlay } from './components/CalendarOverlay'
import { ScoringDashboard } from './components/ScoringDashboard'
import { PDFExport } from './components/PDFExport'

export default function App() {
  return (
    <ThemeProvider>
      <BrowserRouter>
        <Layout>
          <Routes>
            <Route path="/" element={<Leaderboard />} />
            <Route path="/calendar" element={<CalendarOverlay />} />
            <Route path="/scoring" element={<ScoringDashboard />} />
            <Route path="/export" element={<PDFExport />} />
          </Routes>
        </Layout>
      </BrowserRouter>
    </ThemeProvider>
  )
}
