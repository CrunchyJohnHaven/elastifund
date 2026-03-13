import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'

type Theme = 'light' | 'dark' | 'system'

interface ThemeContextValue {
  theme: Theme
  resolved: 'light' | 'dark'
  setTheme: (theme: Theme) => void
}

const ThemeContext = createContext<ThemeContextValue>({
  theme: 'system',
  resolved: 'light',
  setTheme: () => {},
})

export function useTheme() {
  return useContext(ThemeContext)
}

function getSystemTheme(): 'light' | 'dark' {
  if (typeof window === 'undefined') return 'light'
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setTheme] = useState<Theme>(() => {
    const stored = localStorage.getItem('ae-activity-theme')
    return (stored as Theme) ?? 'system'
  })
  const [systemTheme, setSystemTheme] = useState<'light' | 'dark'>(getSystemTheme)

  useEffect(() => {
    const mq = window.matchMedia('(prefers-color-scheme: dark)')
    const handler = (e: MediaQueryListEvent) => setSystemTheme(e.matches ? 'dark' : 'light')
    mq.addEventListener('change', handler)
    return () => mq.removeEventListener('change', handler)
  }, [])

  useEffect(() => {
    localStorage.setItem('ae-activity-theme', theme)
    const resolved = theme === 'system' ? systemTheme : theme
    document.documentElement.classList.toggle('dark', resolved === 'dark')
  }, [theme, systemTheme])

  const resolved = theme === 'system' ? systemTheme : theme

  return (
    <ThemeContext.Provider value={{ theme, resolved, setTheme }}>
      {children}
    </ThemeContext.Provider>
  )
}
