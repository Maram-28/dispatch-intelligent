import React, { useState, useEffect } from 'react'
import { motion } from 'framer-motion'
import {
  Loader, AlertCircle, Award, CheckCircle2, Gauge, AlertTriangle,
  Timer, Clock, ShieldCheck, Info, Flame, Circle,
} from 'lucide-react'
import { apiFetch } from '../../utils/api'
import { useLanguage } from '../../hooks/useLanguage'
import { getDefaultRange, isWithinRange } from '../../utils/dateRange'
import { DateRangeFilter } from '../../components/DateRangeFilter'

const PRIORITY_META = {
  P1_critique: { color: '#ef4444', icon: <Flame size={12} color="#ef4444" /> },
  P2_majeure:  { color: '#f97316', icon: <AlertTriangle size={12} color="#f97316" /> },
  P3_mineure:  { color: '#3b82f6', icon: <AlertCircle size={12} color="#3b82f6" /> },
  P4_standard: { color: '#94a3b8', icon: <Circle size={12} color="#94a3b8" /> },
}

const scoreColor = s => s >= 70 ? '#10b981' : s >= 40 ? '#f97316' : '#ef4444'
const scoreLabel = (s, t) => s >= 70 ? t('agents.scoreExcellent') : s >= 40 ? t('agents.scoreAverage') : t('agents.scoreLow')
const scoreIcon  = s => s >= 70 ? <CheckCircle2 size={13} /> : s >= 40 ? <Gauge size={13} /> : <AlertTriangle size={13} />

const PRIORITE_TO_REPARTITION_KEY = {
  '1-Critique': 'P1_critique',
  '2-Majeure':  'P2_majeure',
  '3-Mineure':  'P3_mineure',
  '4-Standard': 'P4_standard',
}

function median(nums) {
  if (!nums.length) return null
  const sorted = [...nums].sort((a, b) => a - b)
  const mid = Math.floor(sorted.length / 2)
  return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2
}

// Port client-side de l'ancien GET /agent/profile/stats?period= (backend) : ne filtre
// que les tuiles de stats + la répartition par priorité, PAS le score /100 (comparatif
// all-time entre agents, sans équivalent par fenêtre temporelle). Filtre sur
// `resolved_at` (pas `created_at`) pour matcher exactement la sémantique de l'ancien
// endpoint — "tickets résolus dans cette fenêtre", et non "créés dans cette fenêtre".
// resolution_*_heures: null (pas 0) sur fenêtre vide — évite un flash de "0h" pour une
// absence de donnée, affiché comme "—" au rendu. taux_respect_sla_pct: 100 (pas 0) sur
// fenêtre vide — même convention que utils/sla.js:getSlaComplianceStats ("rien à
// reprocher" plutôt qu'une absence de donnée déguisée en 0%).
function computeProfileStats(tickets, startDate, endDate) {
  const mine = tickets.filter(t => t.status === 'done' && isWithinRange(t.resolved_at, startDate, endDate))
  const total = mine.length
  const resolutionHours = mine
    .map(t => t.resolution_time_business_seconds)
    .filter(s => s != null)
    .map(s => s / 3600)
  const mean = resolutionHours.length
    ? resolutionHours.reduce((sum, h) => sum + h, 0) / resolutionHours.length
    : null
  const med = median(resolutionHours)
  const taux_respect_sla_pct = total
    ? Math.round((mine.filter(t => !t.sla_breached).length / total) * 10000) / 100
    : 100

  const repartition_priorites = { P1_critique: 0, P2_majeure: 0, P3_mineure: 0, P4_standard: 0 }
  for (const t of mine) {
    const key = PRIORITE_TO_REPARTITION_KEY[t.priorite_calculee]
    if (key) repartition_priorites[key] += 1
  }

  return {
    total_tickets: total,
    resolution_moy_heures: mean != null ? Math.round(mean * 100) / 100 : null,
    resolution_median_heures: med != null ? Math.round(med * 100) / 100 : null,
    taux_respect_sla_pct,
    repartition_priorites,
  }
}

export function AgentProfileView() {
  const { t } = useLanguage()
  const [profile, setProfile] = useState(null)
  const [tickets, setTickets] = useState([])
  const [range, setRange] = useState(getDefaultRange)
  const [loading, setLoading] = useState(true)
  const [error, setError]     = useState(false)

  useEffect(() => {
    apiFetch('/agent/profile')
      .then(r => r?.json())
      .then(d => { setProfile(d); setLoading(false) })
      .catch(() => { setError(true); setLoading(false) })
  }, [])

  // Récupère TOUS les tickets de l'agent une seule fois (pas par plage — le filtrage
  // par date se fait ensuite côté client via computeProfileStats, comme sur les 3 autres
  // vues management). Repolled toutes les 30s, même cadence que AgentDashboardView.
  useEffect(() => {
    let cancelled = false
    const fetchTickets = () => apiFetch('/agent/tickets')
      .then(r => r?.json())
      .then(d => { if (!cancelled && d) setTickets(d) })
      .catch(() => {})
    fetchTickets()
    const id = setInterval(fetchTickets, 30_000)
    return () => { cancelled = true; clearInterval(id) }
  }, [])

  if (loading) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '60vh', gap: '12px', color: '#94a3b8' }}>
        <Loader size={24} style={{ animation: 'spin 1s linear infinite' }} />
        {t('agentProfile.loading')}
      </div>
    )
  }

  if (error || !profile) {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', padding: '80px 0', gap: '12px', color: '#94a3b8' }}>
        <AlertCircle size={36} color="#ef4444" />
        <p>{t('agentProfile.loadError')}</p>
      </div>
    )
  }

  const color     = scoreColor(profile.score_performance)
  const s         = computeProfileStats(tickets, range.startDate, range.endDate)
  const prio      = s.repartition_priorites
  const skills    = profile.competences ?? []
  const svcs      = profile.specialisations?.services ?? []
  const cats      = profile.specialisations?.sous_categories ?? []
  const hasHistory = s.total_tickets > 0

  return (
    <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.3 }}>
      <div className="header">
        <div className="header-title">
          <h1>{t('agentNav.myProfile')}</h1>
          <p>{profile.groupe ?? 'WW - POWERBI - L2'}</p>
        </div>
      </div>

      <div className="profile-grid">

        <div className="profile-main">
          {/* Identity card */}
          <div className="stat-card" style={{ display: 'flex', alignItems: 'center', gap: '20px' }}>
            <div style={{
              width: 64, height: 64, borderRadius: '50%', background: '#f6c026',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              fontWeight: 800, fontSize: '22px', color: '#0f172a', flexShrink: 0,
              boxShadow: '0 0 0 4px rgba(246, 192, 38, 0.18)',
            }}>
              {profile.nom.split(' ').map(w => w[0]).join('').toUpperCase().slice(0, 2)}
            </div>
            <div style={{ flex: 1 }}>
              <h2 style={{ margin: '0 0 2px', fontSize: '18px', fontWeight: 700 }}>{profile.nom}</h2>
              <p style={{ margin: '0 0 6px', fontSize: '13px', color: '#64748b' }}>{profile.email}</p>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
                <span style={{
                  width: 9, height: 9, borderRadius: '50%',
                  background: profile.disponible ? '#10b981' : '#ef4444',
                  display: 'inline-block',
                }} />
                <span style={{ fontSize: '12px', color: '#64748b' }}>
                  {profile.disponible ? t('agents.available') : t('agents.unavailable')}
                </span>
                <span style={{ fontSize: '12px', background: '#f1f5f9', borderRadius: '999px', padding: '2px 10px', color: '#475569', fontWeight: 500 }}>
                  {t('agentProfile.currentLoad')} <strong>{profile.charge_actuelle}</strong>
                </span>
              </div>
            </div>
          </div>

          {/* Performance */}
          <div className="stat-card">
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px', flexWrap: 'wrap', gap: '8px' }}>
              <span style={{ display: 'flex', alignItems: 'center', gap: '7px', fontSize: '13px', color: '#475569', fontWeight: 600 }}>
                <Award size={15} color="#94a3b8" />
                {t('agentProfile.performanceScore')}
              </span>
              <span style={{
                display: 'flex', alignItems: 'center', gap: '5px', fontSize: '12px', fontWeight: 700,
                color, background: color + '14', borderRadius: '999px', padding: '3px 10px',
              }}>
                {scoreIcon(profile.score_performance)}
                {profile.score_performance}/100 — {scoreLabel(profile.score_performance, t)}
              </span>
            </div>
            <div style={{ width: '100%', height: '10px', background: color + '14', borderRadius: '999px', overflow: 'hidden' }}>
              <div style={{
                width: `${profile.score_performance}%`, height: '100%', background: color,
                borderRadius: '999px', transition: 'width 0.6s ease',
              }} />
            </div>

            {/* Filtre temporel — s'applique aux tuiles ci-dessous et à la répartition
                par priorité, pas au score /100 ci-dessus. Même composant/plage par
                défaut que Dashboard/Agents/SLA Monitor (voir utils/dateRange.js). */}
            <div style={{ marginTop: '16px' }}>
              <DateRangeFilter startDate={range.startDate} endDate={range.endDate} onChange={setRange} />
            </div>

            <div className="profile-stats-row" style={{ display: 'flex', gap: '10px', marginTop: '12px', flexWrap: 'wrap' }}>
              <Stat icon={<CheckCircle2 size={15} color="#3b82f6" />} iconColor="#3b82f6" label={t('agentProfile.ticketsHandled')} value={s.total_tickets} />
              <Stat icon={<Timer size={15} color="#8b5cf6" />}        iconColor="#8b5cf6" label={t('agentProfile.medianResolution')} value={s.resolution_median_heures != null ? `${s.resolution_median_heures}h` : '—'} />
              <Stat icon={<Clock size={15} color="#f97316" />}        iconColor="#f97316" label={t('agentProfile.averageResolution')} value={s.resolution_moy_heures != null ? `${s.resolution_moy_heures}h` : '—'} />
              <Stat icon={<ShieldCheck size={15} color="#10b981" />}  iconColor="#10b981" label={t('agentProfile.slaCompliance')} value={`${s.taux_respect_sla_pct}%`} />
            </div>

            {!hasHistory && (
              <div style={{
                display: 'flex', alignItems: 'center', gap: '8px', marginTop: '16px',
                padding: '10px 12px', background: '#f8fafc', borderRadius: '8px',
                fontSize: '12px', color: '#64748b',
              }}>
                <Info size={14} color="#94a3b8" style={{ flexShrink: 0 }} />
                {t('agentProfile.noHistory')}
              </div>
            )}
          </div>

          {/* Priorities */}
          <div className="stat-card">
            <p style={{ display: 'flex', alignItems: 'center', gap: '7px', fontSize: '13px', fontWeight: 600, color: '#475569', marginBottom: '12px' }}>
              <Gauge size={15} color="#94a3b8" />
              {t('agentProfile.priorityBreakdown')}
            </p>
            <div style={{ display: 'flex', gap: '12px', flexWrap: 'wrap' }}>
              {Object.entries(PRIORITY_META).map(([key, { color: c, icon }]) => (
                <div key={key} style={{
                  flex: '1 1 100px', background: c + '12', borderRadius: '8px', padding: '10px 14px',
                  borderLeft: `3px solid ${c}`,
                }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '5px', fontSize: '11px', color: '#64748b', marginBottom: '4px' }}>
                    {icon}
                    {key.replace('_', ' ').toUpperCase()}
                  </div>
                  <div style={{ fontSize: '22px', fontWeight: 700, color: c }}>{prio[key] ?? 0}</div>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Skills + specialisations */}
        <div className="profile-side">
          {skills.length > 0 && (
            <div className="stat-card">
              <p style={{ fontSize: '13px', fontWeight: 600, color: '#475569', marginBottom: '10px' }}>{t('agents.skills')}</p>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
                {skills.map(s => (
                  <span key={s} style={{
                    fontSize: '12px', padding: '3px 10px', borderRadius: '999px',
                    background: '#eff6ff', color: '#1d4ed8', border: '1px solid #bfdbfe', fontWeight: 500,
                  }}>{s}</span>
                ))}
              </div>
            </div>
          )}

          {cats.length > 0 && (
            <div className="stat-card">
              <p style={{ fontSize: '13px', fontWeight: 600, color: '#475569', marginBottom: '8px' }}>{t('agentProfile.subCategories')}</p>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
                {cats.map(c => (
                  <span key={c} style={{ fontSize: '12px', padding: '2px 9px', borderRadius: '6px', background: '#f0fdf4', color: '#16a34a', border: '1px solid #bbf7d0' }}>{c}</span>
                ))}
              </div>
            </div>
          )}

          {svcs.length > 0 && (
            <div className="stat-card">
              <p style={{ fontSize: '13px', fontWeight: 600, color: '#475569', marginBottom: '8px' }}>{t('agentProfile.specializedServices')}</p>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
                {svcs.map(s => (
                  <span key={s} style={{ fontSize: '12px', padding: '2px 9px', borderRadius: '6px', background: '#fefce8', color: '#854d0e', border: '1px solid #fde68a' }}>{s}</span>
                ))}
              </div>
            </div>
          )}
        </div>

      </div>
      <style>{`
        @keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
        .profile-grid { display: grid; grid-template-columns: minmax(0, 1.6fr) minmax(280px, 1fr); gap: 20px; align-items: start; }
        .profile-main, .profile-side { display: flex; flex-direction: column; gap: 20px; min-width: 0; }
        @media (max-width: 980px) {
          .profile-grid { grid-template-columns: 1fr; }
        }
      `}</style>
    </motion.div>
  )
}

function Stat({ icon, iconColor, label, value }) {
  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: '10px', flex: '1 1 130px',
      padding: '10px 12px', background: '#f8fafc', borderRadius: '10px',
    }}>
      <div style={{
        width: 30, height: 30, borderRadius: '8px', flexShrink: 0,
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        background: iconColor + '18', color: iconColor,
      }}>
        {icon}
      </div>
      <div style={{ minWidth: 0 }}>
        <div style={{ fontSize: '11px', color: '#94a3b8', whiteSpace: 'nowrap' }}>{label}</div>
        <div style={{ fontSize: '16px', fontWeight: 700, color: '#1e293b' }}>{value}</div>
      </div>
    </div>
  )
}
