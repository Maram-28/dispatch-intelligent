import { useState, useEffect } from 'react'
import { SLA_LABEL, isWorkingTime, getSlaUrgency } from '../utils/sla'
import { useLanguage } from '../hooks/useLanguage'

function fmt(secs) {
  const abs = Math.abs(Math.floor(secs))
  const h = Math.floor(abs / 3600)
  const m = Math.floor((abs % 3600) / 60)
  const s = abs % 60
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
}

export function CountdownTimer({ slaDeadline, status, priorite, pausedAt, resolvedAt }) {
  const { t } = useLanguage()
  const [now, setNow] = useState(() => Date.now())

  useEffect(() => {
    if (status !== 'in_progress') return
    const id = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(id)
  }, [status])

  // Ticket not started yet — show static SLA limit
  if (!slaDeadline) {
    return (
      <span style={{ fontSize: '12px', color: '#94a3b8' }}>
        {t('countdown.slaMax')} <strong>{SLA_LABEL[priorite] ?? '?'}</strong>
      </span>
    )
  }

  const { remainingSecs, breached, pct: rawPct } = getSlaUrgency({ slaDeadline, status, priorite, pausedAt, resolvedAt }, now)
  const outOfHours = !isWorkingTime(new Date(now))
  const pct        = Math.max(0, Math.min(100, rawPct))

  const color = breached
    ? '#ef4444'
    : remainingSecs < 3600  ? '#ef4444'   // < 1 h
    : remainingSecs < 14400 ? '#f97316'   // < 4 h
    : '#10b981'

  const barColor = breached ? '#ef4444' : pct < 20 ? '#f97316' : '#10b981'

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
        <span style={{ fontFamily: 'monospace', fontWeight: 700, fontSize: '15px', color }}>
          {breached ? '▲ +' : ''}{fmt(remainingSecs)}
        </span>
        {status === 'on_hold' && (
          <span style={{ fontSize: '11px', color: '#94a3b8', background: '#f1f5f9', padding: '1px 6px', borderRadius: '4px' }}>
            ⏸ {t('countdown.paused')}
          </span>
        )}
        {!breached && outOfHours && (
          <span style={{ fontSize: '11px', color: '#94a3b8', background: '#f1f5f9', padding: '1px 6px', borderRadius: '4px' }}>
            🌙 {t('countdown.outOfHours')}
          </span>
        )}
        {breached && (
          <span style={{ fontSize: '11px', color: '#ef4444', fontWeight: 600 }}>{t('countdown.slaBreached')}</span>
        )}
      </div>
      {/* Progress bar */}
      <div style={{ width: '100%', height: '4px', background: '#f1f5f9', borderRadius: '2px', overflow: 'hidden' }}>
        <div style={{
          width: `${breached ? 100 : pct}%`,
          height: '100%',
          background: barColor,
          borderRadius: '2px',
          transition: 'width 1s linear',
        }} />
      </div>
    </div>
  )
}
