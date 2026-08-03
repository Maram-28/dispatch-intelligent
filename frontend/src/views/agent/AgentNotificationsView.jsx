import React, { useState, useEffect, useCallback } from 'react'
import { motion } from 'framer-motion'
import {
  Bell, BellOff, AlertTriangle, Clock, Loader,
  CheckCheck, Ticket, ChevronRight,
} from 'lucide-react'
import { apiFetch } from '../../utils/api'
import { useLanguage } from '../../hooks/useLanguage'
import { formatTime, formatDateTime } from '../../utils/formatDate'

// notif_store persiste plusieurs types sous la même inbox (voir notifications/store.py) :
// "assignment" (nouveau ticket assigné) mais aussi "sla_40"/"sla_10"/"sla_breach"/
// "priority_escalation"/"priority_deescalation" (alertes/escalades sur un ticket, pas
// forcément le sien — ex. un manager recevant l'escalade SLA du ticket d'un agent).
// Seul "assignment" doit apparaître dans la section "Assignations" (icône Ticket) ;
// le reste va dans "Alertes" pour ne pas laisser croire à un nouveau ticket assigné.
const ASSIGNMENT_TYPE = 'assignment'

const PRIORITY_COLORS = {
  '1-Critique': '#ef4444',
  '2-Majeure':  '#f97316',
  '3-Mineure':  '#3b82f6',
  '4-Standard': '#94a3b8',
}

export function AgentNotificationsView({ onCountChange }) {
  const { t, language } = useLanguage()
  const [slaNotifs,   setSlaNotifs]   = useState([])
  const [inboxNotifs, setInboxNotifs] = useState([])
  const [loading,     setLoading]     = useState(true)
  const [lastRefresh, setLastRefresh] = useState(null)
  const [marking,     setMarking]     = useState(false)

  const fetchAll = useCallback(async () => {
    const [slaRes, inboxRes] = await Promise.all([
      apiFetch('/agent/notifications'),
      apiFetch('/agent/notifications/inbox'),
    ])

    let slaCount    = 0
    let inboxUnread = 0

    if (slaRes) {
      const data = await slaRes.json()
      setSlaNotifs(data.notifications ?? [])
      slaCount = data.count ?? 0
    }
    if (inboxRes) {
      const data = await inboxRes.json()
      setInboxNotifs(data.notifications ?? [])
      inboxUnread = data.unread_count ?? 0
    }

    onCountChange?.(slaCount + inboxUnread)
    setLastRefresh(new Date())
    setLoading(false)
  }, [onCountChange])

  useEffect(() => {
    // fetchAll only calls setState after its `await`s resolve — the effect
    // body itself is synchronous and never calls setState directly.
    // Known false positive for this pattern: react/react#34743.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    fetchAll()
    const id = setInterval(fetchAll, 30_000)
    return () => clearInterval(id)
  }, [fetchAll])

  const handleMarkRead = async (notifId) => {
    const res = await apiFetch(`/agent/notifications/${notifId}/read`, { method: 'POST' })
    if (res && res.ok) {
      setInboxNotifs(prev =>
        prev.map(n => n.id === notifId ? { ...n, lu: true } : n)
      )
      // Mettre à jour le badge : unread − 1
      const newUnread = inboxNotifs.filter(n => !n.lu && n.id !== notifId).length
      onCountChange?.(slaNotifs.length + newUnread)
    }
  }

  const handleMarkAllRead = async () => {
    setMarking(true)
    const res = await apiFetch('/agent/notifications/read-all', { method: 'POST' })
    if (res && res.ok) {
      setInboxNotifs(prev => prev.map(n => ({ ...n, lu: true })))
      onCountChange?.(slaNotifs.length)
    }
    setMarking(false)
  }

  const breached = slaNotifs.filter(n => n.overdue_minutes > 0)
  const warning  = slaNotifs.filter(n => n.overdue_minutes === 0)

  const assignmentNotifs = inboxNotifs.filter(n => n.type === ASSIGNMENT_TYPE)
  const alertInboxNotifs = inboxNotifs.filter(n => n.type !== ASSIGNMENT_TYPE)
  const unreadAssignments = assignmentNotifs.filter(n => !n.lu)
  const unreadAlertInbox  = alertInboxNotifs.filter(n => !n.lu)
  const unreadInbox = inboxNotifs.filter(n => !n.lu)

  const isEmpty = !loading && inboxNotifs.length === 0 && slaNotifs.length === 0

  return (
    <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.3 }}>
      {/* En-tête */}
      <div className="header">
        <div className="header-title">
          <h1>{t('agentNotifications.title')}</h1>
          <p>
            {lastRefresh
              ? `${t('agentNotifications.updated')} ${formatTime(lastRefresh, language)}`
              : t('agentNotifications.loading')}
          </p>
        </div>
        <div style={{ display: 'flex', gap: '8px' }}>
          {unreadInbox.length > 0 && (
            <button
              onClick={handleMarkAllRead}
              disabled={marking}
              style={{
                display: 'flex', alignItems: 'center', gap: '6px',
                background: '#f0fdf4', border: '1px solid #bbf7d0',
                borderRadius: '8px', padding: '6px 14px', cursor: 'pointer',
                fontSize: '13px', color: '#16a34a', fontWeight: 500,
                opacity: marking ? 0.6 : 1,
              }}
            >
              <CheckCheck size={13} />
              {marking ? t('agentNotifications.markingInProgress') : t('agentNotifications.markAllRead')}
            </button>
          )}
          <button
            onClick={fetchAll}
            style={{
              display: 'flex', alignItems: 'center', gap: '6px',
              background: '#f8fafc', border: '1px solid #e2e8f0',
              borderRadius: '8px', padding: '6px 14px', cursor: 'pointer',
              fontSize: '13px', color: '#475569',
            }}
          >
            <Clock size={13} /> {t('agentNotifications.refresh')}
          </button>
        </div>
      </div>

      {loading && (
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px', padding: '60px 0', justifyContent: 'center', color: '#94a3b8' }}>
          <Loader size={22} style={{ animation: 'spin 1s linear infinite' }} />
          {t('agentNotifications.loading')}
        </div>
      )}

      {isEmpty && (
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', padding: '80px 0', gap: '16px', color: '#94a3b8' }}>
          <BellOff size={40} />
          <p style={{ fontSize: '15px' }}>{t('agentNotifications.allCaughtUp')}</p>
        </div>
      )}

      {/* ── Section Assignations (inbox persisté, type "assignment" uniquement) ── */}
      {!loading && assignmentNotifs.length > 0 && (
        <div style={{ marginBottom: '28px' }}>
          <div style={{
            fontSize: '12px', fontWeight: 700, color: '#7c3aed',
            textTransform: 'uppercase', letterSpacing: '0.8px',
            marginBottom: '10px', display: 'flex', alignItems: 'center', gap: '6px',
          }}>
            <Ticket size={13} />
            {t('agentNotifications.assignments')} ({assignmentNotifs.length})
            {unreadAssignments.length > 0 && (
              <span style={{
                background: '#7c3aed', color: '#fff', fontSize: '10px',
                fontWeight: 700, padding: '1px 7px', borderRadius: '999px',
              }}>
                {unreadAssignments.length} {t('agentNotifications.unread')}
              </span>
            )}
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
            {assignmentNotifs.map(n => (
              <InboxCard key={n.id} notif={n} onMarkRead={handleMarkRead} />
            ))}
          </div>
        </div>
      )}

      {/* ── Section Alertes (inbox persisté, tout sauf "assignment" : SLA + escalades de priorité) ── */}
      {!loading && alertInboxNotifs.length > 0 && (
        <div style={{ marginBottom: '28px' }}>
          <div style={{
            fontSize: '12px', fontWeight: 700, color: '#f97316',
            textTransform: 'uppercase', letterSpacing: '0.8px',
            marginBottom: '10px', display: 'flex', alignItems: 'center', gap: '6px',
          }}>
            <Bell size={13} />
            {t('agentNotifications.alerts')} ({alertInboxNotifs.length})
            {unreadAlertInbox.length > 0 && (
              <span style={{
                background: '#f97316', color: '#fff', fontSize: '10px',
                fontWeight: 700, padding: '1px 7px', borderRadius: '999px',
              }}>
                {unreadAlertInbox.length} {t('agentNotifications.unread')}
              </span>
            )}
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
            {alertInboxNotifs.map(n => (
              <InboxCard key={n.id} notif={n} onMarkRead={handleMarkRead} icon={Bell} accentColor="#f97316" />
            ))}
          </div>
        </div>
      )}

      {/* ── Section SLA dépassé ── */}
      {!loading && breached.length > 0 && (
        <div style={{ marginBottom: '28px' }}>
          <div style={{ fontSize: '12px', fontWeight: 700, color: '#ef4444', textTransform: 'uppercase', letterSpacing: '0.8px', marginBottom: '10px', display: 'flex', alignItems: 'center', gap: '6px' }}>
            <AlertTriangle size={13} /> {t('agentNotifications.slaBreached')} ({breached.length})
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
            {breached.map((n, i) => <SlaCard key={i} notif={n} type="breach" />)}
          </div>
        </div>
      )}

      {/* ── Section SLA approchant ── */}
      {!loading && warning.length > 0 && (
        <div>
          <div style={{ fontSize: '12px', fontWeight: 700, color: '#f97316', textTransform: 'uppercase', letterSpacing: '0.8px', marginBottom: '10px', display: 'flex', alignItems: 'center', gap: '6px' }}>
            <Bell size={13} /> {t('agentNotifications.slaApproaching')} ({warning.length})
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
            {warning.map((n, i) => <SlaCard key={i} notif={n} type="warning" />)}
          </div>
        </div>
      )}

      <style>{`@keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }`}</style>
    </motion.div>
  )
}


function InboxCard({ notif, onMarkRead, icon: Icon = Ticket, accentColor = '#7c3aed' }) {
  const { t, language } = useLanguage()
  const isUnread = !notif.lu
  return (
    <div style={{
      background: isUnread ? accentColor + '0d' : '#fff',
      borderRadius: '10px',
      padding: '14px 16px',
      borderLeft: `4px solid ${isUnread ? accentColor : '#e2e8f0'}`,
      boxShadow: '0 1px 3px rgba(0,0,0,0.06)',
      display: 'flex',
      alignItems: 'center',
      gap: '14px',
      transition: 'background 0.2s',
    }}>
      <Icon size={18} color={isUnread ? accentColor : '#94a3b8'} style={{ flexShrink: 0 }} />
      <div style={{ flex: 1 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '3px' }}>
          <span style={{ fontSize: '13px', fontWeight: isUnread ? 700 : 500, color: '#1e293b' }}>
            {notif.ticket_numero}
          </span>
          {isUnread && (
            <span style={{
              fontSize: '10px', fontWeight: 700, padding: '1px 7px', borderRadius: '999px',
              color: accentColor, background: accentColor + '20',
            }}>
              {t('agentNotifications.new')}
            </span>
          )}
        </div>
        <p style={{ fontSize: '12px', color: '#64748b', margin: 0 }}>{notif.message}</p>
        <p style={{ fontSize: '11px', color: '#94a3b8', margin: '4px 0 0' }}>
          {formatDateTime(notif.created_at, language, {
            day: '2-digit', month: '2-digit', year: 'numeric',
            hour: '2-digit', minute: '2-digit',
          })}
        </p>
      </div>
      {isUnread && (
        <button
          onClick={() => onMarkRead(notif.id)}
          style={{
            display: 'flex', alignItems: 'center', gap: '4px',
            background: 'none', border: `1px solid ${accentColor}40`,
            borderRadius: '6px', padding: '4px 10px', cursor: 'pointer',
            fontSize: '11px', color: accentColor, fontWeight: 600,
            flexShrink: 0, whiteSpace: 'nowrap',
          }}
        >
          <CheckCheck size={11} /> {t('agentNotifications.markRead')}
        </button>
      )}
    </div>
  )
}


function SlaCard({ notif, type }) {
  const { t, language } = useLanguage()
  const pColor   = PRIORITY_COLORS[notif.priorite] ?? '#94a3b8'
  const isBreach = type === 'breach'
  return (
    <div style={{
      background: '#fff', borderRadius: '10px', padding: '14px 16px',
      borderLeft: `4px solid ${isBreach ? '#ef4444' : '#f97316'}`,
      boxShadow: '0 1px 3px rgba(0,0,0,0.06)',
      display: 'flex', alignItems: 'center', gap: '14px',
    }}>
      <AlertTriangle size={18} color={isBreach ? '#ef4444' : '#f97316'} style={{ flexShrink: 0 }} />
      <div style={{ flex: 1 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '3px' }}>
          <span style={{ fontSize: '13px', fontWeight: 700, color: '#1e293b' }}>{notif.ticket_numero}</span>
          <span style={{
            fontSize: '11px', fontWeight: 600, padding: '1px 7px', borderRadius: '999px',
            color: pColor, background: pColor + '18',
          }}>
            {notif.priorite}
          </span>
        </div>
        <p style={{ fontSize: '12px', color: '#64748b', margin: 0 }}>
          {notif.sous_categorie} · {notif.service}
        </p>
        <p style={{ fontSize: '12px', fontWeight: 600, color: isBreach ? '#ef4444' : '#f97316', margin: '4px 0 0' }}>
          {notif.message}
        </p>
      </div>
      <div style={{ fontSize: '11px', color: '#94a3b8', textAlign: 'right', flexShrink: 0 }}>
        {t('agentNotifications.deadline')}<br />
        <strong style={{ color: '#475569' }}>
          {formatDateTime(notif.deadline, language, {
            hour: '2-digit', minute: '2-digit', day: '2-digit', month: '2-digit',
          })}
        </strong>
      </div>
    </div>
  )
}
