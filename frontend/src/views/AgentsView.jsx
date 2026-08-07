import React, { useState, useEffect, useCallback, useRef } from 'react'
import { motion } from 'framer-motion'
import {
  Users, RefreshCw, AlertCircle, Clock, Loader, ShieldAlert, ChevronLeft, ChevronRight, X,
  AlertTriangle, UserCheck, Award, Gauge, Briefcase, CalendarDays,
} from 'lucide-react'
import { StatCard } from '../components/StatCard'
import { apiFetch } from '../utils/api'
import { useLanguage } from '../hooks/useLanguage'
import { formatDate, formatTime, monthYearLabel, weekdayLabels } from '../utils/formatDate'
import { getDefaultRange, isWithinRange } from '../utils/dateRange'
import { DateRangeFilter } from '../components/DateRangeFilter'

// ─── helpers ───────────────────────────────────────────────────────────────

const scoreColor = (s) => s >= 70 ? '#10b981' : s >= 40 ? '#f97316' : '#ef4444'
const scoreLabel = (s, t) => s >= 70 ? t('agents.scoreExcellent') : s >= 40 ? t('agents.scoreAverage') : t('agents.scoreLow')

const PRIORITY_COLORS = {
  P1_critique: '#ef4444',
  P2_majeure:  '#f97316',
  P3_mineure:  '#3b82f6',
  P4_standard: '#94a3b8',
}

const initials = (nom) => nom.split(' ').map(w => w[0]).join('').toUpperCase().slice(0, 2)

const fmtDay = (d, language) =>
  d ? formatDate(d, language, { day: '2-digit', month: '2-digit', year: 'numeric' }) : ''

// ─── Calendar ──────────────────────────────────────────────────────────────

function Calendar({ selectedRange, onRangeChange }) {
  const { language } = useLanguage()
  const [viewDate, setViewDate] = useState(new Date())
  const year  = viewDate.getFullYear()
  const month = viewDate.getMonth()

  const firstDow    = new Date(year, month, 1).getDay()  // 0=Sun
  const startOffset = (firstDow + 6) % 7                 // Mon=0…Sun=6
  const daysInMonth = new Date(year, month + 1, 0).getDate()

  const cells = []
  for (let i = 0; i < startOffset; i++) cells.push(null)
  for (let d = 1; d <= daysInMonth; d++) cells.push(new Date(year, month, d))

  const handleClick = (day) => {
    if (!day) return
    const dow = day.getDay()
    if (dow === 0 || dow === 6) return  // weekends disabled

    const { start, end } = selectedRange
    if (!start || (start && end)) {
      onRangeChange({ start: day, end: null })
    } else {
      onRangeChange(day < start
        ? { start: day,   end: start }
        : { start,        end: day   })
    }
  }

  const isStart = (d) => d && selectedRange.start && d.toDateString() === selectedRange.start.toDateString()
  const isEnd   = (d) => d && selectedRange.end   && d.toDateString() === selectedRange.end.toDateString()
  const inRange = (d) => {
    if (!d || !selectedRange.start) return false
    if (!selectedRange.end) return d.toDateString() === selectedRange.start.toDateString()
    return d >= selectedRange.start && d <= selectedRange.end
  }

  const navBtn = {
    background: 'none', border: '1px solid #e2e8f0', borderRadius: '6px',
    width: 28, height: 28, cursor: 'pointer', display: 'flex', alignItems: 'center',
    justifyContent: 'center', color: '#475569',
  }

  return (
    <div>
      {/* Month nav */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '12px' }}>
        <button style={navBtn} onClick={() => setViewDate(new Date(year, month - 1))}>
          <ChevronLeft size={14} />
        </button>
        <span style={{ fontWeight: 600, fontSize: '14px' }}>{monthYearLabel(viewDate, language)}</span>
        <button style={navBtn} onClick={() => setViewDate(new Date(year, month + 1))}>
          <ChevronRight size={14} />
        </button>
      </div>

      {/* Day labels */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(7, 1fr)', marginBottom: '4px' }}>
        {weekdayLabels(language).map((d, i) => (
          <div key={i} style={{ textAlign: 'center', fontSize: '11px', fontWeight: 600, color: '#94a3b8', padding: '3px 0' }}>
            {d}
          </div>
        ))}
      </div>

      {/* Day cells */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(7, 1fr)', gap: '2px' }}>
        {cells.map((day, i) => {
          if (!day) return <div key={`e${i}`} />
          const weekend = day.getDay() === 0 || day.getDay() === 6
          const start   = isStart(day)
          const end     = isEnd(day)
          const inR     = inRange(day)
          return (
            <div
              key={day.toISOString()}
              onClick={() => handleClick(day)}
              style={{
                textAlign: 'center', padding: '6px 2px', fontSize: '12px', borderRadius: '6px',
                cursor: weekend ? 'default' : 'pointer',
                background: (start || end) ? '#ef4444' : inR ? '#fee2e2' : 'transparent',
                color: weekend ? '#cbd5e1' : (start || end) ? '#fff' : inR ? '#ef4444' : '#2d3436',
                fontWeight: (start || end) ? 700 : 400,
                userSelect: 'none',
              }}
            >
              {day.getDate()}
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ─── Agent Profile Modal ────────────────────────────────────────────────────

function AgentProfileModal({ profile, onClose, onRefresh }) {
  const { t, language } = useLanguage()
  const [range,  setRange]  = useState({ start: null, end: null })
  const [raison, setRaison] = useState('')
  const [saving, setSaving] = useState(false)

  const color = scoreColor(profile.score_performance)
  const prio  = profile.metriques.repartition_priorites

  // Auto-fill raison when range changes
  const handleRangeChange = (r) => {
    setRange(r)
    if (r.start && r.end && r.start.toDateString() !== r.end.toDateString()) {
      setRaison(`${t('agents.leaveFrom')} ${fmtDay(r.start, language)} ${t('agents.leaveTo')} ${fmtDay(r.end, language)}`)
    } else if (r.start) {
      setRaison(`${t('agents.leaveOn')} ${fmtDay(r.start, language)}`)
    }
  }

  const callAvailability = async (disponible, reason) => {
    setSaving(true)
    try {
      const res = await apiFetch(`/profiles/${profile.id}/availability`, {
        method: 'POST',
        body: JSON.stringify({ disponible, raison: reason }),
      })
      if (res?.ok) { onRefresh(); onClose() }
    } finally {
      setSaving(false)
    }
  }

  return (
    <div
      onClick={onClose}
      style={{
        position: 'fixed', inset: 0, background: 'rgba(15,23,42,0.55)',
        zIndex: 1000, display: 'flex', alignItems: 'center', justifyContent: 'center',
      }}
    >
      <div
        onClick={e => e.stopPropagation()}
        style={{
          background: '#fff', borderRadius: '16px', width: '860px', maxWidth: '95vw',
          maxHeight: '92vh', overflow: 'hidden', display: 'flex', flexDirection: 'column',
          boxShadow: '0 25px 60px rgba(0,0,0,0.18)',
        }}
      >
        {/* Header */}
        <div style={{ padding: '24px 24px 20px', borderBottom: '1px solid #f1f5f9', display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
          <div style={{ display: 'flex', gap: '14px', alignItems: 'center' }}>
            <div style={{
              width: 56, height: 56, borderRadius: '50%', background: '#f6c026', flexShrink: 0,
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              fontWeight: 700, fontSize: '20px', color: '#0f172a',
            }}>
              {initials(profile.nom)}
            </div>
            <div>
              <h2 style={{ fontSize: '18px', fontWeight: 700, margin: '0 0 2px' }}>{profile.nom}</h2>
              <p  style={{ fontSize: '13px', color: '#64748b', margin: '0 0 6px' }}>{profile.email}</p>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <span style={{
                  width: 9, height: 9, borderRadius: '50%',
                  background: profile.disponible ? '#10b981' : '#ef4444',
                  display: 'inline-block',
                }} />
                <span style={{ fontSize: '12px', color: '#64748b' }}>
                  {profile.disponible ? t('agents.available') : t('agents.unavailable')}
                </span>
                <span style={{ color: '#e2e8f0' }}>·</span>
                <span style={{ fontSize: '12px', color: '#64748b' }}>
                  {t('agents.currentLoad')} <strong>{profile.charge_actuelle}</strong>
                </span>
              </div>
            </div>
          </div>
          <button
            onClick={onClose}
            style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#94a3b8', padding: '4px' }}
          >
            <X size={20} />
          </button>
        </div>

        {/* Scrollable body */}
        <div style={{ overflowY: 'auto', padding: '24px', display: 'flex', flexDirection: 'column', gap: '24px' }}>

          {/* Performance */}
          <section>
            <p style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '11px', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.6px', color: '#94a3b8', margin: '0 0 12px' }}>
              <Award size={13} color="#94a3b8" />
              {t('agents.performance')}
            </p>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '13px', marginBottom: '6px' }}>
              <span style={{ color: '#64748b' }}>{t('agents.globalScore')}</span>
              <span style={{ fontWeight: 700, color }}>{profile.score_performance}/100 — {scoreLabel(profile.score_performance, t)}</span>
            </div>
            <div style={{ width: '100%', height: '8px', background: color + '18', borderRadius: '999px', overflow: 'hidden' }}>
              <div style={{ width: `${profile.score_performance}%`, height: '100%', background: color, borderRadius: '999px', transition: 'width 0.5s' }} />
            </div>
            <div style={{ display: 'flex', gap: '20px', marginTop: '10px', fontSize: '12px', color: '#64748b', flexWrap: 'wrap' }}>
              <span><Clock size={11} style={{ verticalAlign: 'middle' }} /> {t('agents.median')} <strong style={{ color: '#2d3436' }}>{profile.metriques.resolution_median_heures}h</strong></span>
              <span>{t('agents.average')} <strong style={{ color: '#2d3436' }}>{profile.metriques.resolution_moy_heures}h</strong></span>
              <span>{t('agents.slaCompliance')} <strong style={{ color: '#2d3436' }}>{profile.metriques.taux_respect_sla_pct}%</strong></span>
            </div>
          </section>

          {/* Priorités */}
          <section>
            <p style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '11px', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.6px', color: '#94a3b8', margin: '0 0 12px' }}>
              <Gauge size={13} color="#94a3b8" />
              {t('agents.priorityBreakdown')}
            </p>
            <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap' }}>
              {Object.entries(PRIORITY_COLORS).map(([key, col]) => (
                <div key={key} style={{ display: 'flex', alignItems: 'center', gap: '6px', background: '#f8fafc', borderRadius: '8px', padding: '7px 12px' }}>
                  <span style={{ width: 10, height: 10, borderRadius: '3px', background: col, display: 'inline-block' }} />
                  <span style={{ fontSize: '12px', color: '#64748b' }}>{key.replace('P','').split('_')[0]}</span>
                  <span style={{ fontSize: '13px', fontWeight: 700, color: '#2d3436' }}>{prio[key] ?? 0}</span>
                </div>
              ))}
            </div>
          </section>

          {/* Compétences */}
          {(profile.competences || []).length > 0 && (
            <section>
              <p style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '11px', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.6px', color: '#94a3b8', margin: '0 0 12px' }}>
                <UserCheck size={13} color="#94a3b8" />
                {t('agents.skills')}
              </p>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
                {profile.competences.map(s => (
                  <span key={s} style={{ fontSize: '11px', padding: '3px 10px', borderRadius: '999px', background: '#eff6ff', color: '#1d4ed8', border: '1px solid #bfdbfe' }}>
                    {s}
                  </span>
                ))}
              </div>
            </section>
          )}

          {/* Services */}
          {(profile.specialisations?.services || []).length > 0 && (
            <section>
              <p style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '11px', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.6px', color: '#94a3b8', margin: '0 0 12px' }}>
                <Briefcase size={13} color="#94a3b8" />
                {t('agents.lvmhServices')}
              </p>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
                {profile.specialisations.services.map(s => (
                  <span key={s} style={{ fontSize: '11px', padding: '3px 10px', borderRadius: '999px', background: '#f0fdf4', color: '#15803d', border: '1px solid #bbf7d0' }}>
                    {s}
                  </span>
                ))}
              </div>
            </section>
          )}

          {/* Congés */}
          <section style={{ borderTop: '1px solid #f1f5f9', paddingTop: '20px' }}>
            <p style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '11px', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.6px', color: '#94a3b8', margin: '0 0 16px' }}>
              <CalendarDays size={13} color="#94a3b8" />
              {t('agents.leaveManagement')}
            </p>
            <p style={{ fontSize: '12px', color: '#64748b', margin: '0 0 14px' }}>
              {t('agents.selectPeriodHint')}
            </p>

            <Calendar selectedRange={range} onRangeChange={handleRangeChange} />

            {range.start && (
              <div style={{ marginTop: '16px' }}>
                <label style={{ fontSize: '12px', color: '#64748b', fontWeight: 500, display: 'block', marginBottom: '6px' }}>
                  {t('agents.motive')}
                </label>
                <input
                  value={raison}
                  onChange={e => setRaison(e.target.value)}
                  placeholder={t('agents.motivePlaceholder')}
                  style={{ width: '100%', padding: '9px 12px', border: '1px solid #e2e8f0', borderRadius: '8px', fontSize: '13px', boxSizing: 'border-box', outline: 'none' }}
                />
              </div>
            )}

            <div style={{ display: 'flex', gap: '10px', marginTop: '16px' }}>
              <button
                disabled={saving || !range.start}
                onClick={() => callAvailability(false, raison || t('agents.leave'))}
                style={{
                  flex: 1, padding: '10px 0', borderRadius: '8px', border: 'none', fontWeight: 600, fontSize: '13px',
                  background: range.start ? '#ef4444' : '#f1f5f9',
                  color: range.start ? '#fff' : '#94a3b8',
                  cursor: (saving || !range.start) ? 'not-allowed' : 'pointer',
                  transition: 'opacity 0.2s',
                }}
              >
                {saving ? '…' : t('agents.markUnavailable')}
              </button>
              <button
                disabled={saving}
                onClick={() => callAvailability(true, '')}
                style={{
                  flex: 1, padding: '10px 0', borderRadius: '8px', fontWeight: 600, fontSize: '13px',
                  background: '#fff', border: '1px solid #10b981', color: '#10b981',
                  cursor: saving ? 'wait' : 'pointer',
                }}
              >
                {saving ? '…' : t('agents.markAvailable')}
              </button>
            </div>
          </section>

        </div>
      </div>
    </div>
  )
}

// ─── Minimal Member Card ────────────────────────────────────────────────────

function MemberCard({ profile, onClick }) {
  const { t } = useLanguage()
  const color = scoreColor(profile.score_performance)
  const ini   = initials(profile.nom)

  return (
    <div
      className="stat-card"
      onClick={onClick}
      style={{ display: 'flex', flexDirection: 'column', gap: '12px', cursor: 'pointer', transition: 'box-shadow 0.2s' }}
      onMouseEnter={e => e.currentTarget.style.boxShadow = '0 4px 20px rgba(0,0,0,0.10)'}
      onMouseLeave={e => e.currentTarget.style.boxShadow = ''}
    >
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div style={{ display: 'flex', gap: '10px', alignItems: 'center' }}>
          <div style={{
            width: 44, height: 44, borderRadius: '50%', background: '#f6c026', flexShrink: 0,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            fontWeight: 700, fontSize: '15px', color: '#0f172a',
          }}>
            {ini}
          </div>
          <div>
            <h3 style={{ fontSize: '14px', fontWeight: 600, margin: '0 0 2px' }}>{profile.nom}</h3>
            <p  style={{ fontSize: '11px', color: '#94a3b8', margin: 0 }}>{profile.email}</p>
          </div>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: '5px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '5px' }}>
            <span style={{
              width: 8, height: 8, borderRadius: '50%',
              background: profile.disponible ? '#10b981' : '#ef4444', display: 'inline-block',
            }} />
            <span style={{ fontSize: '11px', color: '#64748b' }}>
              {profile.disponible ? t('agents.available') : t('agents.unavailable')}
            </span>
          </div>
          <span style={{ fontSize: '11px', background: '#f1f5f9', borderRadius: '4px', padding: '2px 8px', color: '#475569' }}>
            {t('agents.load')} <strong>{profile.charge_actuelle}</strong>
          </span>
        </div>
      </div>

      {/* Performance bar */}
      <div>
        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '11px', marginBottom: '5px' }}>
          <span style={{ color: '#94a3b8' }}>{t('agents.performance')}</span>
          <span style={{ fontWeight: 700, color }}>{profile.score_performance}/100</span>
        </div>
        <div style={{ width: '100%', height: '6px', background: color + '18', borderRadius: '999px', overflow: 'hidden' }}>
          <div style={{ width: `${profile.score_performance}%`, height: '100%', background: color, borderRadius: '999px', transition: 'width 0.5s' }} />
        </div>
      </div>

      {/* Top 2 skills */}
      <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap', alignItems: 'center' }}>
        {(profile.competences || []).slice(0, 2).map(s => (
          <span key={s} style={{ fontSize: '10px', padding: '2px 8px', borderRadius: '999px', background: '#eff6ff', color: '#1d4ed8', border: '1px solid #bfdbfe' }}>
            {s}
          </span>
        ))}
        {(profile.competences || []).length > 2 && (
          <span style={{ fontSize: '10px', color: '#94a3b8' }}>+{profile.competences.length - 2}</span>
        )}
        <span style={{ marginLeft: 'auto', fontSize: '11px', color: '#cbd5e1' }}>{t('agents.viewProfile')} →</span>
      </div>
    </div>
  )
}

// ─── AgentsView ─────────────────────────────────────────────────────────────

export function AgentsView({ currentUser, tickets = [] }) {
  const { t, language } = useLanguage()
  const [profiles,      setProfiles]      = useState([])
  const [loading,       setLoading]       = useState(true)
  const [bootstrapping, setBootstrapping] = useState(false)
  const [errorState,    setErrorState]    = useState(null)
  const [lastRefresh,   setLastRefresh]   = useState(null)
  const [selectedProfile, setSelectedProfile] = useState(null)
  const [range, setRange] = useState(getDefaultRange)
const selectedProfileRef = useRef(null)
  useEffect(() => {
    selectedProfileRef.current = selectedProfile
  })

  const fetchProfiles = useCallback(async (silent = false) => {
    if (!silent) setLoading(true)
    try {
      const res = await apiFetch('/profiles')
      if (res.status === 404) { setErrorState('not_bootstrapped'); setProfiles([]); return }
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      setProfiles(data)
      setErrorState(null)
      setLastRefresh(new Date())
      // Sync modal data without creating a dependency on selectedProfile
      const cur = selectedProfileRef.current
      if (cur) {
        const updated = data.find(p => p.id === cur.id)
        if (updated) setSelectedProfile(updated)
      }
    } catch {
      setErrorState('fetch_error')
    } finally {
      setLoading(false)
    }
  }, [])  // stable — ref used instead of state dep

useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- fetch-on-mount + polling, pattern documenté par React
    fetchProfiles()
    const id = setInterval(() => fetchProfiles(true), 30_000)
    return () => clearInterval(id)
  }, [fetchProfiles])

  const handleBootstrap = async () => {
    setBootstrapping(true)
    try {
      const res = await apiFetch('/profiles/bootstrap', { method: 'POST' })
      if (!res.ok) throw new Error()
      await fetchProfiles()
    } catch {
      setErrorState('fetch_error')
    } finally {
      setBootstrapping(false)
    }
  }

  const availableCount = profiles.filter(p => p.disponible).length
  const avgScore       = profiles.length ? Math.round(profiles.reduce((s, p) => s + p.score_performance, 0) / profiles.length) : 0

  // Même calcul que DashboardView (avant sa propre suppression de cette tuile) :
  // moyenne PAR TICKET (pas par agent — un agent qui en résout 10 pèse 10x plus
  // qu'un agent qui en résout 1) sur les tickets "done" créés dans la fenêtre
  // sélectionnée. Remplace l'ancienne moyenne des moyennes par agent
  // (metriques.resolution_moy_heures, all-time, non filtrable par période) qui
  // divergeait du chiffre affiché sur le Dashboard pour ces deux raisons à la fois.
  const resolutionSecs = tickets
    .filter(t => t.fullData?.status === 'done' && isWithinRange(t.fullData?.created_at, range.startDate, range.endDate))
    .map(t => t.fullData?.resolution_time_business_seconds)
    .filter(s => s != null)
  // null (pas 0) sur fenêtre vide : "0h" laisserait croire à une résolution
  // instantanée mesurée plutôt qu'à une absence de ticket sur la période — même
  // convention que DashboardView.avgResolutionH.
  const avgResolutionH = resolutionSecs.length > 0
    ? Math.round((resolutionSecs.reduce((sum, s) => sum + s, 0) / resolutionSecs.length / 3600) * 10) / 10
    : null

  // Couverture des compétences : qui couvre quoi, et quelles compétences ne
  // reposent que sur une seule personne (point de défaillance unique).
  const skillCoverage = {}
  for (const p of profiles) {
    for (const skill of p.competences || []) {
      (skillCoverage[skill] ??= []).push(p.nom)
    }
  }
  const distinctSkillsCount = Object.keys(skillCoverage).length
  const singleCoverageSkills = Object.entries(skillCoverage)
    .filter(([, agents]) => agents.length === 1)
    .map(([skill, agents]) => ({ skill, agent: agents[0] }))
    .sort((a, b) => a.skill.localeCompare(b.skill))

  return (
    <>
      <motion.div
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        exit={{ opacity: 0, y: -10 }}
        transition={{ duration: 0.3 }}
      >
        {/* Header */}
        <div className="header">
          <div className="header-title">
            <h1>{t('agents.title')}</h1>
            <p>{t('agents.subtitle')}</p>
          </div>
          <div className="header-actions" style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
            {lastRefresh && (
              <span style={{ fontSize: '11px', color: '#94a3b8' }}>
                {t('agents.updated')} {formatTime(lastRefresh, language)}
              </span>
            )}
            <button
              onClick={() => fetchProfiles()}
              disabled={loading}
              style={{ display: 'flex', alignItems: 'center', gap: '6px', background: '#f8fafc', border: '1px solid #e2e8f0', borderRadius: '8px', padding: '6px 12px', cursor: 'pointer', fontSize: '13px', color: '#475569' }}
            >
              <RefreshCw size={14} style={{ animation: loading ? 'spin 1s linear infinite' : 'none' }} />
              {t('agents.refresh')}
            </button>
          </div>
        </div>

        {/* Loading */}
        {loading && (
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', padding: '80px 0', gap: '16px' }}>
            <Loader size={32} color="#94a3b8" style={{ animation: 'spin 1s linear infinite' }} />
            <p style={{ color: '#94a3b8', fontSize: '14px' }}>{t('agents.loadingProfiles')}</p>
          </div>
        )}

        {/* Not bootstrapped */}
        {!loading && errorState === 'not_bootstrapped' && (
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', padding: '80px 0', gap: '20px', textAlign: 'center' }}>
            {currentUser?.role === 'admin' ? (
              <>
                <AlertCircle size={40} color="#f59e0b" />
                <div>
                  <h3 style={{ margin: '0 0 8px', fontSize: '18px' }}>{t('agents.notInitialized')}</h3>
                  <p style={{ color: '#64748b', margin: 0, fontSize: '14px', maxWidth: '380px' }}>
                    {t('agents.bootstrapHint')}
                  </p>
                </div>
                <button
                  onClick={handleBootstrap}
                  disabled={bootstrapping}
                  style={{ background: '#f6c026', border: 'none', borderRadius: '8px', padding: '10px 24px', fontWeight: 600, fontSize: '14px', cursor: bootstrapping ? 'wait' : 'pointer', display: 'flex', alignItems: 'center', gap: '8px' }}
                >
                  {bootstrapping && <Loader size={16} style={{ animation: 'spin 1s linear infinite' }} />}
                  {bootstrapping ? t('agents.buildingProfiles') : `⚡ ${t('agents.runBootstrap')}`}
                </button>
              </>
            ) : (
              <>
                <ShieldAlert size={40} color="#94a3b8" />
                <div>
                  <h3 style={{ margin: '0 0 8px', fontSize: '18px' }}>{t('agents.notInitialized')}</h3>
                  <p style={{ color: '#64748b', margin: 0, fontSize: '14px', maxWidth: '380px' }}>
                    {t('agents.contactAdminHint')}
                  </p>
                </div>
              </>
            )}
          </div>
        )}

        {/* Fetch error */}
        {!loading && errorState === 'fetch_error' && (
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', padding: '80px 0', gap: '12px', textAlign: 'center' }}>
            <AlertCircle size={36} color="#ef4444" />
            <p style={{ color: '#64748b', fontSize: '14px' }}>{t('agents.fetchError')}</p>
            <button onClick={() => fetchProfiles()} style={{ background: '#f1f5f9', border: 'none', borderRadius: '8px', padding: '8px 20px', cursor: 'pointer', fontSize: '13px' }}>
              {t('agents.retry')}
            </button>
          </div>
        )}

        {/* Main content */}
        {!loading && !errorState && (
          <>
            {/* Filtre temporel — n'affecte que "Temps de résolution moyen" ci-dessous
                (seule tuile calculée depuis des tickets datés) ; les autres tuiles
                viennent des profils (snapshots en direct, non filtrables). */}
            <DateRangeFilter startDate={range.startDate} endDate={range.endDate} onChange={setRange} />

            <div className="stats-grid">
              <StatCard label={t('agents.availableAgents')} value={`${availableCount}/${profiles.length}`} icon={<UserCheck size={16} color="#10b981" />} />
              <StatCard label={t('agents.avgScore')}         value={`${avgScore}/100`}                       icon={<Award size={16} color="#f97316" />} />
              <StatCard label={t('dashboard.avgResolutionTime')} value={avgResolutionH != null ? `${avgResolutionH}h` : '—'} icon={<Clock size={16} color="#3b82f6" />} />
              <StatCard label={t('agents.distinctSkills')}   value={distinctSkillsCount}                     icon={<Users size={16} color="#8b5cf6" />} />
              <StatCard label={t('agents.skillsAtRisk')}     value={singleCoverageSkills.length}              icon={<AlertTriangle size={16} color="#eab308" />} />
            </div>

            {singleCoverageSkills.length > 0 && (
              <div className="stat-card" style={{ marginTop: '20px' }}>
                <p style={{ display: 'flex', alignItems: 'center', gap: '7px', fontSize: '13px', fontWeight: 600, color: '#475569', marginBottom: '10px' }}>
                  <AlertTriangle size={15} color="#eab308" />
                  {t('agents.singleCoverage')}
                </p>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
                  {singleCoverageSkills.map(({ skill, agent }) => (
                    <span key={skill} style={{
                      fontSize: '12px', padding: '4px 10px', borderRadius: '999px',
                      background: '#fffbeb', color: '#a16207', border: '1px solid #fde68a',
                    }}>
                      <strong>{skill}</strong> — {agent}
                    </span>
                  ))}
                </div>
              </div>
            )}

            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(360px, 1fr))', gap: '20px', marginTop: '24px' }}>
              {profiles.map(profile => (
                <MemberCard
                  key={profile.id}
                  profile={profile}
                  onClick={() => setSelectedProfile(profile)}
                />
              ))}
            </div>
          </>
        )}

        <style>{`@keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }`}</style>
      </motion.div>

      {/* Profile Modal */}
      {selectedProfile && (
        <AgentProfileModal
          profile={selectedProfile}
          onClose={() => setSelectedProfile(null)}
          onRefresh={() => fetchProfiles(true)}
        />
      )}
    </>
  )
}
