import React, { useState } from 'react'
import { motion } from 'framer-motion'
import { X, User, PlayCircle, PauseCircle, RotateCcw, CheckCircle2 } from 'lucide-react'
import { DetailGroup } from './DetailGroup'
import { CountdownTimer } from './CountdownTimer'
import { apiFetch } from '../utils/api'
import { useLanguage } from '../hooks/useLanguage'
import { formatDateTime } from '../utils/formatDate'

const getStatusLabels = (t) => ({
  new:         { label: t('ticketDetails.statusNew'),        color: '#3b82f6', bg: '#eff6ff' },
  in_progress: { label: t('ticketDetails.statusInProgress'), color: '#10b981', bg: '#f0fdf4' },
  on_hold:     { label: t('ticketDetails.statusOnHold'),     color: '#f97316', bg: '#fff7ed' },
  done:        { label: t('ticketDetails.statusDone'),       color: '#94a3b8', bg: '#f8fafc' },
})

const getWaitMotiveLabels = (t) => ({
  contact_principal:  t('ticketDetails.motiveContactPrincipal'),
  changement:          t('ticketDetails.motiveChangement'),
  resolution_probleme: t('ticketDetails.motiveResolutionProbleme'),
})

function fmtDateTime(iso, language) {
  return formatDateTime(iso, language, {
    day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit',
  })
}

function fmtDuration(seconds) {
  if (seconds == null) return '—'
  const abs = Math.max(0, Math.round(seconds))
  const h = Math.floor(abs / 3600)
  const m = Math.round((abs % 3600) / 60)
  return `${h}h ${String(m).padStart(2, '0')}min`
}

export function TicketDetailsModal({ ticket, onClose, onUpdated }) {
  const { t, language } = useLanguage()
  const [result, setResult] = useState(ticket.fullData)
  const [actionLoading, setActionLoading] = useState(false)
  const [error, setError] = useState(null)
  const [pauseForm, setPauseForm] = useState(null) // null ou { motive, comment, note }

  if (!result) return null

  const STATUS_LABELS = getStatusLabels(t)
  const WAIT_MOTIVE_LABELS = getWaitMotiveLabels(t)
  const st = STATUS_LABELS[result.status] ?? STATUS_LABELS.new

  const doAction = async (action, extra = {}) => {
    setActionLoading(true)
    setError(null)
    try {
      const res = await apiFetch(`/agent/tickets/${result.numero}/status`, {
        method: 'PATCH',
        body: JSON.stringify({ action, ...extra }),
      })
      if (!res) return
      const data = await res.json()
      if (!res.ok) {
        setError(data.detail || t('ticketDetails.statusUpdateError'))
        return
      }
      setResult(data)
      setPauseForm(null)
      onUpdated?.(data)
    } catch {
      setError(t('ticketDetails.statusUpdateNetworkError'))
    } finally {
      setActionLoading(false)
    }
  }

  const confirmPause = () => {
    if (!pauseForm?.motive) {
      setError(t('ticketDetails.chooseMotiveError'))
      return
    }
    if (pauseForm.motive === 'contact_principal' && !pauseForm.comment?.trim()) {
      setError(t('ticketDetails.commentRequiredError'))
      return
    }
    doAction('pause', {
      wait_motive: pauseForm.motive,
      wait_comment: pauseForm.comment || null,
      note: pauseForm.note?.trim() || null,
    })
  }

  return (
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.5)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000, backdropFilter: 'blur(4px)' }}>
      <motion.div
        initial={{ scale: 0.9, opacity: 0 }}
        animate={{ scale: 1, opacity: 1 }}
        style={{ background: 'white', padding: '32px', borderRadius: '16px', width: '620px', maxHeight: '90vh', overflowY: 'auto', boxShadow: '0 20px 25px -5px rgba(0,0,0,0.1)' }}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '24px' }}>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
              <span style={{ fontSize: '12px', fontWeight: 600, color: '#94a3b8' }}>{result.numero}</span>
              {result.entreprise && (
                <span style={{ fontSize: '12px', fontWeight: 600, color: '#f6c026', background: '#fffbeb', padding: '2px 8px', borderRadius: '99px', border: '1px solid #fde68a' }}>
                  {result.entreprise}
                </span>
              )}
              <span style={{ fontSize: '11px', fontWeight: 600, padding: '2px 9px', borderRadius: '99px', color: st.color, background: st.bg }}>
                {st.label}
              </span>
            </div>
            <h2 style={{ fontSize: '20px', fontWeight: 700, marginTop: '6px' }}>{ticket.title}</h2>
            <p style={{ fontSize: '12px', color: '#94a3b8', marginTop: '2px' }}>{t('ticketDetails.createdOn')} {fmtDateTime(result.created_at, language)}</p>
          </div>
          <button onClick={onClose} style={{ border: 'none', background: 'none', cursor: 'pointer', color: '#94a3b8' }}><X size={20}/></button>
        </div>

        {/* Description */}
        <div style={{ marginBottom: '20px' }}>
          <div style={{ fontSize: '12px', fontWeight: 700, color: '#64748b', textTransform: 'uppercase', marginBottom: '8px', letterSpacing: '0.05em' }}>
            {t('ticketDetails.description')}
          </div>
          <div style={{ background: '#f8fafc', padding: '16px', borderRadius: '12px', border: '1px solid #e2e8f0' }}>
            <p style={{ fontSize: '14px', fontWeight: 600, color: '#1e293b', margin: 0 }}>
              {result.breve_description || ticket.title}
            </p>
            <p style={{ fontSize: '13px', color: '#475569', lineHeight: 1.6, margin: '8px 0 0' }}>
              {result.description || t('ticketDetails.noFullDescription')}
            </p>
          </div>
        </div>

        {/* Classification fields */}
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '20px', marginBottom: '24px' }}>
          <DetailGroup label={t('ticketDetails.category')} value={result.categorie} />
          <DetailGroup label={t('ticketDetails.subCategory')} value={result.sous_categorie} />
          <DetailGroup label={t('ticketDetails.service')} value={result.service} />
          <DetailGroup label={t('ticketDetails.priority')} value={result.priorite_calculee} color="#ef4444" />
          <DetailGroup label={t('ticketDetails.impact')} value={result.impact} />
          <DetailGroup label={t('ticketDetails.urgency')} value={result.urgence} />
        </div>

        {/* Motif d'attente */}
        {result.status === 'on_hold' && (
          <div style={{ marginBottom: '20px', background: '#fff7ed', padding: '16px', borderRadius: '12px', border: '1px solid #fed7aa' }}>
            <div style={{ fontSize: '11px', fontWeight: 700, color: '#9a3412', textTransform: 'uppercase', marginBottom: '6px' }}>
              {t('ticketDetails.waitMotive')}
            </div>
            <p style={{ fontSize: '14px', fontWeight: 600, color: '#1e293b', margin: 0 }}>
              {WAIT_MOTIVE_LABELS[result.wait_motive] || result.wait_motive || '—'}
            </p>
            {result.wait_comment && (
              <p style={{ fontSize: '13px', color: '#475569', lineHeight: 1.6, margin: '6px 0 0' }}>{result.wait_comment}</p>
            )}
          </div>
        )}

        {/* Commentaire optionnel de mise en attente (les 3 motifs, écrit dans work_notes
            côté ServiceNow — voir hold_note/StatusUpdate.note) */}
        {result.status === 'on_hold' && result.hold_note && (
          <div style={{ marginBottom: '20px', background: '#fff7ed', padding: '16px', borderRadius: '12px', border: '1px solid #fed7aa' }}>
            <div style={{ fontSize: '11px', fontWeight: 700, color: '#9a3412', textTransform: 'uppercase', marginBottom: '6px' }}>
              {t('ticketDetails.holdComment')}
            </div>
            <p style={{ fontSize: '14px', color: '#1e293b', lineHeight: 1.6, margin: 0 }}>
              {result.hold_note}
            </p>
          </div>
        )}

        {/* SLA */}
        <div style={{ marginBottom: '20px' }}>
          <div style={{ fontSize: '12px', fontWeight: 700, color: '#64748b', textTransform: 'uppercase', marginBottom: '8px', letterSpacing: '0.05em' }}>
            SLA
          </div>
          {result.status === 'done' ? (
            <p style={{ fontSize: '14px', color: '#1e293b', margin: 0 }}>
              {t('ticketDetails.resolutionTime')} <strong>{fmtDuration(result.resolution_time_business_seconds)}</strong>
            </p>
          ) : (
            <CountdownTimer slaDeadline={result.sla_deadline} status={result.status} priorite={result.priorite_calculee} pausedAt={result.paused_at} />
          )}
        </div>

        {/* Assignment section */}
        {result.assigned_to && (
          <div style={{ marginBottom: '20px' }}>
            <div style={{ fontSize: '12px', fontWeight: 700, color: '#64748b', textTransform: 'uppercase', marginBottom: '10px', letterSpacing: '0.05em' }}>
              {t('ticketDetails.assignment')}
            </div>
            <div style={{ background: '#fffbeb', padding: '16px', borderRadius: '12px', border: '1px solid #fde68a' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '12px' }}>
                <div style={{ background: '#f6c026', borderRadius: '50%', width: '38px', height: '38px', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
                  <User size={18} color="#000" />
                </div>
                <div>
                  <div style={{ fontWeight: 700, fontSize: '15px' }}>{result.assigned_to.nom}</div>
                  <div style={{ fontSize: '12px', color: '#78716c' }}>
                    {t('ticketDetails.assignmentScore')} <strong>{Math.round(result.assigned_to.score_assignation * 100)}%</strong>
                  </div>
                </div>
              </div>
              <div style={{ borderTop: '1px solid #fde68a', paddingTop: '12px' }}>
                <div style={{ fontSize: '11px', fontWeight: 700, color: '#92400e', textTransform: 'uppercase', marginBottom: '4px' }}>
                  {t('ticketDetails.justification')}
                </div>
                <p style={{ fontSize: '13px', lineHeight: 1.6, color: '#1e293b', margin: 0 }}>
                  {result.assigned_to.justification}
                </p>
              </div>
            </div>
          </div>
        )}

        {/* AI Reasoning */}
        <div style={{ background: '#f8fafc', padding: '20px', borderRadius: '12px', border: '1px solid #e2e8f0' }}>
          <h3 style={{ fontSize: '12px', fontWeight: 700, color: '#64748b', textTransform: 'uppercase', marginBottom: '8px' }}>{t('ticketDetails.aiReasoning')}</h3>
          <p style={{ fontSize: '14px', lineHeight: 1.6, color: '#1e293b', margin: 0 }}>{result.reasoning}</p>
        </div>

        {/* Erreur */}
        {error && (
          <div style={{ marginTop: '16px', padding: '10px 14px', borderRadius: '8px', background: '#fef2f2', border: '1px solid #fecaca', color: '#b91c1c', fontSize: '13px' }}>
            {error}
          </div>
        )}

        {/* Formulaire de mise en attente */}
        {pauseForm && (
          <div style={{ marginTop: '16px', padding: '16px', borderRadius: '12px', background: '#fff7ed', border: '1px solid #fed7aa' }}>
            <div style={{ fontSize: '12px', fontWeight: 700, color: '#9a3412', textTransform: 'uppercase', marginBottom: '10px' }}>
              {t('ticketDetails.pauseMotive')}
            </div>
            <select
              value={pauseForm.motive}
              onChange={(e) => setPauseForm({ ...pauseForm, motive: e.target.value })}
              style={{ width: '100%', padding: '8px 10px', borderRadius: '8px', border: '1px solid #e2e8f0', fontSize: '13px', marginBottom: '10px' }}
            >
              <option value="">{t('ticketDetails.chooseMotive')}</option>
              {Object.entries(WAIT_MOTIVE_LABELS).map(([value, label]) => (
                <option key={value} value={value}>{label}</option>
              ))}
            </select>
            <textarea
              placeholder={t('ticketDetails.optionalNotePlaceholder')}
              value={pauseForm.note}
              onChange={(e) => setPauseForm({ ...pauseForm, note: e.target.value })}
              style={{ width: '100%', minHeight: '60px', padding: '8px 10px', borderRadius: '8px', border: '1px solid #e2e8f0', fontSize: '13px', marginBottom: '10px', resize: 'vertical' }}
            />
            {pauseForm.motive === 'contact_principal' && (
              <textarea
                placeholder={t('ticketDetails.commentPlaceholder')}
                value={pauseForm.comment}
                onChange={(e) => setPauseForm({ ...pauseForm, comment: e.target.value })}
                style={{ width: '100%', minHeight: '70px', padding: '8px 10px', borderRadius: '8px', border: '1px solid #e2e8f0', fontSize: '13px', marginBottom: '10px', resize: 'vertical' }}
              />
            )}
            <div style={{ display: 'flex', gap: '8px', justifyContent: 'flex-end' }}>
              <button
                onClick={() => { setPauseForm(null); setError(null) }}
                style={{ padding: '8px 14px', borderRadius: '8px', border: '1px solid #e2e8f0', background: '#fff', color: '#475569', fontWeight: 600, cursor: 'pointer', fontSize: '13px' }}
              >
                {t('common.cancel')}
              </button>
              <button
                onClick={confirmPause}
                disabled={actionLoading}
                style={{ padding: '8px 14px', borderRadius: '8px', border: 'none', background: '#f97316', color: '#fff', fontWeight: 600, cursor: actionLoading ? 'wait' : 'pointer', fontSize: '13px', opacity: actionLoading ? 0.6 : 1 }}
              >
                {t('common.confirm')}
              </button>
            </div>
          </div>
        )}

        {/* Boutons de transition de statut */}
        {!pauseForm && result.status !== 'done' && (
          <div style={{ marginTop: '20px', display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
            {result.status === 'new' && (
              <StatusBtn onClick={() => doAction('start')} loading={actionLoading} color="#10b981" icon={<PlayCircle size={15} />} label={t('ticketDetails.start')} />
            )}
            {result.status === 'in_progress' && (
              <>
                <StatusBtn onClick={() => setPauseForm({ motive: '', comment: '', note: '' })} loading={actionLoading} color="#f97316" icon={<PauseCircle size={15} />} label={t('ticketDetails.putOnHold')} outlined />
                <StatusBtn onClick={() => doAction('done')} loading={actionLoading} color="#10b981" icon={<CheckCircle2 size={15} />} label={t('ticketDetails.resolve')} />
              </>
            )}
            {result.status === 'on_hold' && (
              <StatusBtn onClick={() => doAction('resume')} loading={actionLoading} color="#3b82f6" icon={<RotateCcw size={15} />} label={t('ticketDetails.resume')} />
            )}
          </div>
        )}

        <div style={{ marginTop: '24px', display: 'flex', justifyContent: 'flex-end' }}>
          <button onClick={onClose} style={{ padding: '10px 20px', borderRadius: '8px', border: 'none', background: '#000', color: '#fff', fontWeight: 600, cursor: 'pointer' }}>{t('common.close')}</button>
        </div>
      </motion.div>
    </div>
  )
}

function StatusBtn({ onClick, loading, color, icon, label, outlined }) {
  return (
    <button
      onClick={onClick}
      disabled={loading}
      style={{
        display: 'flex', alignItems: 'center', gap: '6px',
        padding: '9px 16px', borderRadius: '8px', fontSize: '13px', fontWeight: 600,
        cursor: loading ? 'wait' : 'pointer',
        border: outlined ? `1.5px solid ${color}` : 'none',
        background: outlined ? 'transparent' : color,
        color: outlined ? color : '#fff',
        opacity: loading ? 0.6 : 1,
      }}
    >
      {icon}{label}
    </button>
  )
}
