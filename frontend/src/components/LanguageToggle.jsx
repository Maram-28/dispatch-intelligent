import React from 'react'
import { useLanguage } from '../hooks/useLanguage'

// Compact EN | FR segmented control — sits in the sidebar footer (both the
// admin sidebar in App.jsx and the agent sidebar in views/AgentView.jsx) so
// it's reachable from every page.
export function LanguageToggle() {
  const { language, setLanguage } = useLanguage()

  const optionStyle = (code) => ({
    flex: 1,
    padding: '5px 0',
    borderRadius: '6px',
    border: 'none',
    cursor: 'pointer',
    fontSize: '11px',
    fontWeight: 700,
    letterSpacing: '0.4px',
    background: language === code ? 'var(--primary-color)' : 'transparent',
    color: language === code ? '#0f172a' : 'var(--sidebar-text-muted)',
    transition: 'all 0.15s',
  })

  return (
    <div
      role="group"
      aria-label="Language"
      style={{
        display: 'flex', gap: '2px', padding: '3px',
        background: 'var(--sidebar-divider)', borderRadius: '8px',
        margin: '0 12px 10px',
      }}
    >
      <button type="button" style={optionStyle('en')} onClick={() => setLanguage('en')}>EN</button>
      <button type="button" style={optionStyle('fr')} onClick={() => setLanguage('fr')}>FR</button>
    </div>
  )
}
