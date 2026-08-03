import React, { useState, useEffect, useCallback } from 'react'
import { motion } from 'framer-motion'
import { Clock, AlertCircle, CheckCircle2, RefreshCw, Bell } from 'lucide-react'
import { StatCard } from '../components/StatCard'
import { CountdownTimer } from '../components/CountdownTimer'
import { getSlaTrackedTickets, getSlaComplianceStats } from '../utils/sla'
import { getDefaultRange, isWithinRange } from '../utils/dateRange'
import { DateRangeFilter } from '../components/DateRangeFilter'
import { apiFetch } from '../utils/api'
import { useLanguage } from '../hooks/useLanguage'
import { formatDateTime } from '../utils/formatDate'

const PRIORITY_COLORS = {
  '1-Critique': '#ef4444',
  '2-Majeure':  '#f97316',
  '3-Mineure':  '#3b82f6',
  '4-Standard': '#94a3b8',
}

const getTierLabels = (t) => ({
  sla_40:     { label: t('sla.tier40'),     color: '#fbbf24', bg: '#fffbeb' },
  sla_10:     { label: t('sla.tier10'),     color: '#f97316', bg: '#fff7ed' },
  sla_breach: { label: t('sla.tierBreach'), color: '#ef4444', bg: '#fef2f2' },
})

// Filtre sur `created_at` (tickets) / `created_at` (alertes) : ni `tickets` (chargé
// en une fois par App.jsx) ni `alerts` (renvoyé intégralement par
// /manager/sla-notifications) ne sont paginés côté backend, donc le filtrage se
// fait entièrement côté client, sans appel réseau supplémentaire. Composant et
// bornes partagés avec DashboardView/AgentsView (voir utils/dateRange.js).

function fmtDateTime(iso, language) {
  return formatDateTime(iso, language, {
    day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit',
  })
}

export function SLAMonitorView({ tickets, onTicketClick }) {
  const { t, language } = useLanguage()
  const TIER_LABELS = getTierLabels(t)
  const [alerts, setAlerts]           = useState([])
  const [alertsLoading, setAlertsLoading] = useState(true)
  const [scanning, setScanning]       = useState(false)
  const [scanMessage, setScanMessage] = useState(null)
  const [range, setRange]             = useState(getDefaultRange)

  const fetchAlerts = useCallback(async () => {
    const res = await apiFetch('/manager/sla-notifications')
    if (!res) return
    const data = await res.json()
    setAlerts(data.notifications || [])
    setAlertsLoading(false)
  }, [])

  useEffect(() => {
    fetchAlerts()
    const id = setInterval(fetchAlerts, 60_000)
    return () => clearInterval(id)
  }, [fetchAlerts])

  const handleScanNow = async () => {
    setScanning(true)
    setScanMessage(null)
    try {
      const res = await apiFetch('/manager/sla-check-now', { method: 'POST' })
      if (!res) return
      const data = await res.json()
      const results = data.triggered || []
      const tierCount = results.reduce((sum, r) => sum + r.triggered.length, 0)
      setScanMessage(
        tierCount > 0
          ? `${t('sla.scanDoneWithTiers')} ${tierCount} / ${results.length}.`
          : t('sla.scanDoneNoTiers')
      )
      fetchAlerts()
    } catch {
      setScanMessage(t('sla.scanError'))
    } finally {
      setScanning(false)
    }
  }

  // Tickets créés dans la fenêtre sélectionnée — un ticket créé avant la fenêtre
  // sort des compteurs/de la liste, même s'il est toujours activement suivi.
  const periodTickets = tickets.filter(t => isWithinRange(t.fullData?.created_at, range.startDate, range.endDate))

  // Tickets suivis SLA de toute l'équipe (actifs + résolus en dépassement — voir
  // getSlaTrackedTickets), pour la liste "Tickets actifs" et les compteurs
  // Dépassés/Critique/Alerte, qui décrivent "ce qui a besoin d'attention".
  const activeTickets = getSlaTrackedTickets(periodTickets)
    .sort((a, b) => (a.urgency.bucket - b.urgency.bucket) || ((a.urgency.remainingSecs ?? 0) - (b.urgency.remainingSecs ?? 0)))

  const breachedCount = activeTickets.filter(a => a.urgency.bucket === 0).length
  const under10Count  = activeTickets.filter(a => a.urgency.bucket === 1).length
  const under40Count  = activeTickets.filter(a => a.urgency.bucket === 2).length

  // Conformité : PAS basée sur activeTickets ci-dessus (qui exclut délibérément les
  // tickets résolus dans les délais — voir getSlaComplianceStats), sinon un ticket
  // résolu en retard sans ticket actif pour "diluer" fait chuter le taux à 0% de
  // façon trompeuse dès qu'on filtre sur une petite fenêtre temporelle.
  const { compliancePct: compliance } = getSlaComplianceStats(periodTickets)

  const filteredAlerts = alerts.filter(n => isWithinRange(n.created_at, range.startDate, range.endDate))

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -10 }}
      transition={{ duration: 0.3 }}
    >
      <div className="header">
        <div className="header-title">
          <h1>{t('sla.title')}</h1>
          <p>{t('sla.subtitle')}</p>
        </div>
        <div className="header-actions">
          <button
            onClick={handleScanNow}
            disabled={scanning}
            className="glass"
            style={{
              padding: '8px 16px', borderRadius: '8px', display: 'flex', alignItems: 'center', gap: 8,
              cursor: scanning ? 'wait' : 'pointer', border: 'none',
              backgroundColor: '#f6c026', color: '#000', fontWeight: 600,
              opacity: scanning ? 0.6 : 1,
            }}
          >
            <RefreshCw size={16} style={scanning ? { animation: 'spin 1s linear infinite' } : undefined} />
            {t('sla.scanNow')}
          </button>
        </div>
      </div>

      {scanMessage && (
        <div style={{ marginBottom: '16px', padding: '10px 14px', borderRadius: '8px', background: '#f0fdf4', border: '1px solid #bbf7d0', color: '#15803d', fontSize: '13px' }}>
          {scanMessage}
        </div>
      )}

      <DateRangeFilter startDate={range.startDate} endDate={range.endDate} onChange={setRange} />

      <div className="stats-grid">
        <StatCard label={t('sla.breached')} value={breachedCount} icon={<AlertCircle size={16} color="#ef4444" />} />
        <StatCard label={t('sla.critical')} value={under10Count} icon={<Clock size={16} color="#f97316" />} />
        <StatCard label={t('sla.warning')} value={under40Count} icon={<Clock size={16} color="#fbbf24" />} />
        <StatCard label={t('sla.compliance')} value={`${compliance}%`} icon={<CheckCircle2 size={16} color="#10b981" />} />
      </div>

      <div style={{ display: 'flex', gap: '24px', alignItems: 'flex-start' }}>
        {/* Tickets actifs triés par urgence SLA */}
        <div style={{ flex: 2, display: 'flex', flexDirection: 'column', gap: '10px' }}>
          <h2 style={{ fontSize: '14px', color: '#1e293b', fontWeight: 700 }}>
            {t('sla.activeTickets')} ({activeTickets.length})
          </h2>
          {activeTickets.length === 0 && (
            <p style={{ fontSize: '13px', color: '#94a3b8' }}>{t('sla.noActiveTickets')}</p>
          )}
          {activeTickets.map(({ ticket }) => {
            const f = ticket.fullData
            const pColor = PRIORITY_COLORS[f.priorite_calculee] ?? '#94a3b8'
            return (
              <div
                key={ticket.id}
                className="ticket-card"
                onClick={() => onTicketClick?.(ticket)}
                style={{ display: 'flex', alignItems: 'center', gap: '16px', cursor: 'pointer' }}
              >
                <div style={{ background: pColor, color: 'white', padding: '2px 6px', borderRadius: '4px', fontSize: '11px', fontWeight: 700 }}>
                  {f.priorite_calculee}
                </div>
                <span style={{ fontSize: '13px', color: '#94a3b8' }}>{f.numero}</span>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontWeight: 600, fontSize: '14px' }}>{f.sous_categorie} — {f.service}</div>
                  <div style={{ fontSize: '12px', color: '#64748b' }}>
                    {t('sla.assignedTo')} {f.assigned_to ? f.assigned_to.nom : '—'}
                  </div>
                </div>
                <CountdownTimer slaDeadline={f.sla_deadline} status={f.status} priorite={f.priorite_calculee} pausedAt={f.paused_at} resolvedAt={f.resolved_at} />
              </div>
            )
          })}
        </div>

        {/* Alertes SLA de toute l'équipe */}
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: '10px', minWidth: 0 }}>
          <h2 style={{ fontSize: '14px', color: '#1e293b', fontWeight: 700, display: 'flex', alignItems: 'center', gap: '6px' }}>
            <Bell size={15} /> {t('sla.alerts')} ({filteredAlerts.length})
          </h2>
          {alertsLoading && <p style={{ fontSize: '13px', color: '#94a3b8' }}>{t('sla.loading')}</p>}
          {!alertsLoading && filteredAlerts.length === 0 && (
            <p style={{ fontSize: '13px', color: '#94a3b8' }}>{t('sla.noAlerts')}</p>
          )}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', maxHeight: '600px', overflowY: 'auto' }}>
            {filteredAlerts.map(n => {
              const tier = TIER_LABELS[n.type] ?? { label: n.type, color: '#94a3b8', bg: '#f8fafc' }
              return (
                <div
                  key={n.id}
                  style={{
                    padding: '10px 12px', borderRadius: '10px', background: '#fff',
                    border: `1px solid ${n.lu ? '#e2e8f0' : tier.color + '60'}`,
                    boxShadow: '0 1px 3px rgba(0,0,0,0.05)',
                  }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '4px' }}>
                    <span style={{ fontSize: '10px', fontWeight: 700, padding: '1px 8px', borderRadius: '999px', color: tier.color, background: tier.bg }}>
                      {tier.label}
                    </span>
                    {!n.lu && <span style={{ width: '7px', height: '7px', borderRadius: '50%', background: '#f6c026', flexShrink: 0 }} />}
                  </div>
                  <p style={{ fontSize: '12px', color: '#334155', margin: 0, lineHeight: 1.5 }}>{n.message}</p>
                  <p style={{ fontSize: '11px', color: '#94a3b8', margin: '4px 0 0' }}>{fmtDateTime(n.created_at, language)}</p>
                </div>
              )
            })}
          </div>
        </div>
      </div>

      <style>{`@keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }`}</style>
    </motion.div>
  )
}
