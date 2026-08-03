import React from 'react'
import { useLanguage } from '../hooks/useLanguage'
import { formatRangeLabel } from '../utils/dateRange'

// Sélecteur de plage de dates personnalisée, partagé par DashboardView,
// AgentsView et SLAMonitorView (remplace l'ancien filtre à presets fixes,
// voir utils/dateRange.js). `min`/`max` sur les inputs natifs empêchent déjà le
// navigateur de proposer une fin avant le début ; les handlers ci-dessous
// clampent en plus par sécurité (ex. Firefox ne bloque pas toujours la saisie
// clavier directe hors bornes).
export function DateRangeFilter({ startDate, endDate, onChange }) {
  const { t, language } = useLanguage()

  const handleStartChange = (e) => {
    const newStart = e.target.value
    if (!newStart) return
    onChange({ startDate: newStart, endDate: endDate < newStart ? newStart : endDate })
  }

  const handleEndChange = (e) => {
    const newEnd = e.target.value
    if (!newEnd) return
    onChange({ startDate: startDate > newEnd ? newEnd : startDate, endDate: newEnd })
  }

  const inputStyle = {
    padding: '5px 10px',
    borderRadius: '8px',
    border: '1px solid #e2e8f0',
    fontSize: '12px',
    color: '#334155',
    background: '#fff',
  }

  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '16px', flexWrap: 'wrap' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
        <label style={{ fontSize: '12px', color: '#64748b', fontWeight: 600 }}>{t('common.startDate')}</label>
        <input type="date" value={startDate} max={endDate} onChange={handleStartChange} style={inputStyle} />
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
        <label style={{ fontSize: '12px', color: '#64748b', fontWeight: 600 }}>{t('common.endDate')}</label>
        <input type="date" value={endDate} min={startDate} onChange={handleEndChange} style={inputStyle} />
      </div>
      <span style={{
        fontSize: '12px', fontWeight: 600, color: '#0f172a',
        background: 'rgba(246, 192, 38, 0.18)', padding: '5px 12px', borderRadius: '999px',
      }}>
        {formatRangeLabel(startDate, endDate, language)}
      </span>
    </div>
  )
}
