import React, { useState, useEffect } from 'react'
import { motion } from 'framer-motion'
import { Search, Filter, CheckCircle2, Ticket, AlertCircle, Users, CheckCheck, AlertTriangle } from 'lucide-react'
import { StatCard } from '../components/StatCard'
import { KanbanColumn } from '../components/KanbanColumn'
import { getSlaTrackedTickets, getSlaComplianceStats } from '../utils/sla'
import { getDefaultRange, isWithinRange } from '../utils/dateRange'
import { DateRangeFilter } from '../components/DateRangeFilter'
import { apiFetch } from '../utils/api'
import { useLanguage } from '../hooks/useLanguage'

export function DashboardView({ tickets, onOpenModal, onTicketClick }) {
  const { t } = useLanguage()
  const [profiles, setProfiles] = useState([])
  const [range, setRange] = useState(getDefaultRange)

  useEffect(() => {
    let cancelled = false
    const fetchProfiles = async () => {
      const res = await apiFetch('/profiles')
      if (!res || cancelled) return
      const data = await res.json()
      if (!cancelled) setProfiles(data)
    }
    fetchProfiles()
    const id = setInterval(fetchProfiles, 60_000)
    return () => { cancelled = true; clearInterval(id) }
  }, [])

  // Filtre temporel (voir utils/dateRange.js) : s'applique aux tuiles de stats
  // ci-dessous UNIQUEMENT, pas au Kanban (qui a sa propre logique de filtrage par
  // statut, indépendante de ces variables) ni à "Charge moyenne" (snapshot en
  // direct de la charge actuelle des agents, pas un historique filtrable).
  const periodTickets = tickets.filter(t => isWithinRange(t.fullData?.created_at, range.startDate, range.endDate))

  const activeTickets = periodTickets.filter(t => t.fullData?.status !== 'done')

  // "SLA à risque" : tickets actifs proches de leur deadline (getSlaTrackedTickets,
  // même définition que SLAMonitorView) — un concept différent de la conformité
  // ci-dessous, qui doit couvrir TOUS les tickets résolus de la période (voir
  // getSlaComplianceStats).
  const atRiskCount = getSlaTrackedTickets(periodTickets)
    .map(({ urgency }) => urgency)
    .filter(u => u.bucket === 1 || u.bucket === 2).length

  const { compliancePct: slaCompliance } = getSlaComplianceStats(periodTickets)

  const avgWorkload = profiles.length > 0
    ? (profiles.reduce((sum, p) => sum + (p.charge_actuelle ?? 0), 0) / profiles.length).toFixed(1)
    : null

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -10 }}
      transition={{ duration: 0.3 }}
    >
      <div className="header">
        <div className="header-title">
          <h1>{t('dashboard.title')}</h1>
          <p>{t('dashboard.subtitle')}</p>
        </div>
        <div className="header-actions">
          <div className="search-bar">
            <Search size={18} color="#94a3b8" />
            <input type="text" placeholder={t('dashboard.searchPlaceholder')} />
          </div>
          <button
            className="glass"
            onClick={onOpenModal}
            style={{
              padding: '8px 16px',
              borderRadius: '8px',
              display: 'flex',
              alignItems: 'center',
              gap: 8,
              cursor: 'pointer',
              border: 'none',
              backgroundColor: '#f6c026',
              color: '#000',
              fontWeight: 600
            }}
          >
             + {t('dashboard.newTicket')}
          </button>
          <button className="glass" style={{ padding: '8px 12px', borderRadius: '8px', display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer', border: '1px solid #e2e8f0' }}>
            <Filter size={18} /> {t('dashboard.filters')}
          </button>
        </div>
      </div>

      <DateRangeFilter startDate={range.startDate} endDate={range.endDate} onChange={setRange} />

      <div className="stats-grid">
        <StatCard label={t('dashboard.slaCompliance')} value={`${slaCompliance}%`} icon={<CheckCircle2 size={16} color="#10b981" />} />
        <StatCard label={t('dashboard.totalTickets')} value={periodTickets.length} icon={<Ticket size={16} color="#f97316" />} />
        <StatCard label={t('dashboard.activeTickets')} value={activeTickets.length} icon={<AlertCircle size={16} color="#3b82f6" />} />
        <StatCard label={t('dashboard.avgWorkload')} value={avgWorkload != null ? avgWorkload : '—'} icon={<Users size={16} color="#636e72" />} />
        <StatCard label={t('dashboard.slaAtRisk')} value={atRiskCount} icon={<AlertTriangle size={16} color="#eab308" />} />
      </div>

      <div className="kanban-board">
        <KanbanColumn title={t('dashboard.assigned')}   count={tickets.filter(tk => tk.status === 'Assigned').length}    tickets={tickets.filter(tk => tk.status === 'Assigned')}    onTicketClick={onTicketClick} />
        <KanbanColumn title={t('dashboard.inProgress')} count={tickets.filter(tk => tk.status === 'In Progress').length} tickets={tickets.filter(tk => tk.status === 'In Progress')} onTicketClick={onTicketClick} />
        <KanbanColumn title={t('dashboard.done')}       count={tickets.filter(tk => tk.status === 'Done').length}        tickets={tickets.filter(tk => tk.status === 'Done')}        onTicketClick={onTicketClick} icon={<CheckCheck size={14} color="#10b981" />} />
      </div>
    </motion.div>
  )
}
