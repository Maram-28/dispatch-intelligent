import React, { useState, useEffect, useCallback } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { Loader, CheckCircle, Inbox } from 'lucide-react'
import { apiFetch } from '../../utils/api'
import { CountdownTimer } from '../../components/CountdownTimer'
import { TicketDetailsModal } from '../../components/TicketDetailsModal'
import { useLanguage } from '../../hooks/useLanguage'
import { formatDateTime } from '../../utils/formatDate'

const PRIORITY_COLORS = {
  '1-Critique': '#ef4444',
  '2-Majeure':  '#f97316',
  '3-Mineure':  '#3b82f6',
  '4-Standard': '#94a3b8',
}

const getStatusLabels = (t) => ({
  new:         { label: t('ticketDetails.statusNew'),        color: '#3b82f6', bg: '#eff6ff' },
  in_progress: { label: t('ticketDetails.statusInProgress'), color: '#10b981', bg: '#f0fdf4' },
  on_hold:     { label: t('ticketDetails.statusOnHold'),     color: '#f97316', bg: '#fff7ed' },
  done:        { label: t('ticketDetails.statusDone'),       color: '#94a3b8', bg: '#f8fafc' },
})

function TicketWorkCard({ ticket, onClick }) {
  const { t, language } = useLanguage()
  const STATUS_LABELS = getStatusLabels(t)
  const pColor = PRIORITY_COLORS[ticket.priorite_calculee] ?? '#94a3b8'
  const st     = STATUS_LABELS[ticket.status] ?? STATUS_LABELS.new

  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, scale: 0.97 }}
      onClick={onClick}
      style={{
        background: '#fff',
        borderRadius: '12px',
        padding: '18px 20px',
        boxShadow: '0 1px 4px rgba(0,0,0,0.07)',
        borderLeft: `4px solid ${pColor}`,
        display: 'flex',
        flexDirection: 'column',
        gap: '12px',
        opacity: ticket.status === 'done' ? 0.6 : 1,
        cursor: 'pointer',
      }}
    >
      {/* Header row */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '12px' }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '4px' }}>
            <span style={{ fontSize: '11px', fontWeight: 700, color: '#94a3b8', letterSpacing: '0.5px' }}>
              {ticket.numero}
            </span>
            <span style={{
              fontSize: '11px', fontWeight: 600, padding: '1px 8px', borderRadius: '999px',
              color: pColor, background: pColor + '18', border: `1px solid ${pColor}40`,
            }}>
              {ticket.priorite_calculee}
            </span>
          </div>
          <p style={{ fontSize: '14px', fontWeight: 600, color: '#1e293b', margin: 0, lineHeight: 1.4 }}>
            {ticket.sous_categorie} — {ticket.service}
          </p>
          <p style={{ fontSize: '12px', color: '#64748b', margin: '2px 0 0' }}>
            {ticket.categorie} · {ticket.entreprise || 'LVMH'}
          </p>
        </div>
        <span style={{
          fontSize: '11px', fontWeight: 600, padding: '3px 10px', borderRadius: '6px',
          color: st.color, background: st.bg, flexShrink: 0,
        }}>
          {st.label}
        </span>
      </div>

      {/* SLA Timer (lecture seule — les transitions se font dans la fiche) */}
      <CountdownTimer
        slaDeadline={ticket.sla_deadline}
        status={ticket.status}
        priorite={ticket.priorite_calculee}
        pausedAt={ticket.paused_at}
        resolvedAt={ticket.resolved_at}
      />

      {ticket.status === 'done' && ticket.resolved_at && (
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '12px', color: '#94a3b8' }}>
          <CheckCircle size={13} color="#10b981" />
          {t('agentDashboard.resolvedOn')} {formatDateTime(ticket.resolved_at, language)}
        </div>
      )}
    </motion.div>
  )
}

export function AgentDashboardView() {
  const { t } = useLanguage()
  const [tickets, setTickets]           = useState([])
  const [loading, setLoading]           = useState(true)
  const [selectedTicket, setSelectedTicket] = useState(null)

  const fetchTickets = useCallback(async () => {
    const res = await apiFetch('/agent/tickets')
    if (!res) return
    const data = await res.json()
    setTickets(data)
    setLoading(false)
  }, [])

  useEffect(() => {
    // fetchTickets only calls setState after its `await`s resolve — the
    // effect body itself is synchronous and never calls setState directly.
    // Known false positive for this pattern: react/react#34743.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    fetchTickets()
    const id = setInterval(fetchTickets, 30_000)
    return () => clearInterval(id)
  }, [fetchTickets])

  const sortByStatus = (list) => [...list].sort((a, b) => {
    const o = { in_progress: 0, on_hold: 1, new: 2, done: 3 }
    return (o[a.status] ?? 9) - (o[b.status] ?? 9)
  })

  // Remplace l'objet ticket ENTIER (sla_deadline, wait_motive, status, etc. sont
  // tous recalculés côté backend à chaque transition) — un patch partiel
  // afficherait une deadline ou un motif obsolète sur la carte.
  const handleTicketUpdated = (updatedResult) => {
    setTickets(prev => sortByStatus(prev.map(t => (t.numero === updatedResult.numero ? updatedResult : t))))
    setSelectedTicket(updatedResult)
  }

  const active = tickets.filter(t => t.status !== 'done')
  const done   = tickets.filter(t => t.status === 'done')

  if (loading) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '60vh', gap: '12px', color: '#94a3b8' }}>
        <Loader size={24} style={{ animation: 'spin 1s linear infinite' }} />
        {t('agentDashboard.loading')}
      </div>
    )
  }

  return (
    <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.3 }}>
      {/* Header */}
      <div className="header">
        <div className="header-title">
          <h1>{t('agentNav.myTickets')}</h1>
          <p>{active.length} {t('agentDashboard.active')} · {done.length} {t('agentDashboard.resolved')}</p>
        </div>
      </div>

      {tickets.length === 0 && (
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', padding: '80px 0', gap: '16px', color: '#94a3b8' }}>
          <Inbox size={40} />
          <p style={{ fontSize: '15px' }}>{t('agentDashboard.noTickets')}</p>
        </div>
      )}

      {active.length > 0 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '12px', marginBottom: '32px' }}>
          <AnimatePresence mode="popLayout">
            {active.map(ticket => (
              <TicketWorkCard
                key={ticket.numero}
                ticket={ticket}
                onClick={() => setSelectedTicket(ticket)}
              />
            ))}
          </AnimatePresence>
        </div>
      )}

      {done.length > 0 && (
        <>
          <div style={{ fontSize: '12px', fontWeight: 600, color: '#94a3b8', textTransform: 'uppercase', letterSpacing: '0.8px', marginBottom: '10px' }}>
            {t('agentDashboard.resolvedSection')} ({done.length})
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
            <AnimatePresence>
              {done.map(ticket => (
                <TicketWorkCard key={ticket.numero} ticket={ticket} onClick={() => setSelectedTicket(ticket)} />
              ))}
            </AnimatePresence>
          </div>
        </>
      )}

      {selectedTicket && (
        <TicketDetailsModal
          ticket={{
            title: selectedTicket.titre || selectedTicket.breve_description || selectedTicket.numero,
            fullData: selectedTicket,
          }}
          onClose={() => setSelectedTicket(null)}
          onUpdated={handleTicketUpdated}
        />
      )}

      <style>{`@keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }`}</style>
    </motion.div>
  )
}
