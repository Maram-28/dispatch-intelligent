const WORK_START_H = 7
const WORK_END_H   = 19

export const SLA_TOTAL_SECS = {
  '1-Critique': 8  * 3600,
  '2-Majeure':  16 * 3600,
  '3-Mineure':  48 * 3600,
  '4-Standard': 96 * 3600,
}

export const SLA_LABEL = {
  '1-Critique': '8h',
  '2-Majeure':  '16h',
  '3-Mineure':  '48h',
  '4-Standard': '96h',
}

export function isWorkingTime(d) {
  const dow = d.getDay() // 0=Sun, 6=Sat
  if (dow === 0 || dow === 6) return false
  const h = d.getHours()
  return h >= WORK_START_H && h < WORK_END_H
}

// Returns the number of business seconds between fromMs and toMs (toMs > fromMs).
export function businessSecsBetween(fromMs, toMs) {
  let total = 0
  let cur   = new Date(fromMs)
  const end = new Date(toMs)

  while (cur < end) {
    const dow = cur.getDay()
    if (dow === 0 || dow === 6) {
      // Jump to next Monday 07:00
      const d = new Date(cur)
      d.setDate(d.getDate() + (dow === 0 ? 1 : 2))
      d.setHours(WORK_START_H, 0, 0, 0)
      cur = d
      continue
    }
    const curSecs = cur.getHours() * 3600 + cur.getMinutes() * 60 + cur.getSeconds()
    const ws = WORK_START_H * 3600
    const we = WORK_END_H   * 3600
    if (curSecs < ws) {
      const d = new Date(cur); d.setHours(WORK_START_H, 0, 0, 0); cur = d; continue
    }
    if (curSecs >= we) {
      const d = new Date(cur)
      d.setDate(d.getDate() + 1); d.setHours(WORK_START_H, 0, 0, 0); cur = d; continue
    }
    // Currently inside business hours
    const endOfWork = new Date(cur); endOfWork.setHours(WORK_END_H, 0, 0, 0)
    if (end <= endOfWork) {
      total += Math.floor((end - cur) / 1000)
      break
    }
    total += we - curSecs
    const d = new Date(cur)
    d.setDate(d.getDate() + 1); d.setHours(WORK_START_H, 0, 0, 0); cur = d
  }
  return total
}

// Point de vérité unique pour "combien de temps ouvré reste-t-il" — reflète
// EXACTEMENT sla_engine.business_seconds_remaining / sla_percent_remaining
// (mêmes bornes 7h-19h lun-ven, même gel de la référence sur `pausedAt`
// pendant une pause manuelle) afin que le Monitor SLA et le widget CountdownTimer
// n'affichent jamais deux nombres différents pour le même ticket.
export function getSlaUrgency({ slaDeadline, status, priorite, pausedAt, resolvedAt }, nowMs = Date.now()) {
  if (!slaDeadline) return { remainingSecs: null, breached: false, pct: null, bucket: 3 }

  const deadlineMs  = new Date(slaDeadline).getTime()
  const referenceMs = (status === 'done' && resolvedAt) ? new Date(resolvedAt).getTime()
    : (status === 'on_hold' && pausedAt) ? new Date(pausedAt).getTime()
    : nowMs
  const breached    = referenceMs > deadlineMs

  const remainingSecs = breached
    ? -businessSecsBetween(deadlineMs, referenceMs)
    : businessSecsBetween(referenceMs, deadlineMs)

  const totalSecs = SLA_TOTAL_SECS[priorite] ?? SLA_TOTAL_SECS['4-Standard']
  const pct       = (remainingSecs / totalSecs) * 100

  // Aligné sur sla_watchdog.evaluate_ticket_alerts : "40" si percent<=40, "10" si percent<=10.
  let bucket = 3
  if (breached) bucket = 0
  else if (pct <= 10) bucket = 1
  else if (pct <= 40) bucket = 2

  return { remainingSecs, breached, pct, bucket }
}

// Ensemble des tickets à considérer pour le suivi SLA (Monitor + KPIs manager) :
// les tickets actifs (chrono en cours, in_progress/on_hold) ET les tickets déjà
// résolus mais en dépassement (done + sla_breached). Sans ce second groupe, un
// ticket résolu en retard disparaît silencieusement des compteurs de breach et
// de la liste du Monitor dès qu'il passe à "done" — alors que le backend a bien
// persisté `sla_breached: true` dessus (voir sla_engine.on_status_change) et que
// CountdownTimer sait déjà l'afficher correctement via `resolvedAt` (utilisé
// dans "Mes tickets"). Single source de vérité pour ce filtre, partagée par
// SLAMonitorView et DashboardView pour qu'ils ne divergent jamais.
export function getSlaTrackedTickets(tickets) {
  return tickets
    .filter(t => {
      const status = t.fullData?.status
      if (status === 'in_progress' || status === 'on_hold') return true
      return status === 'done' && t.fullData?.sla_breached === true
    })
    .map(t => ({
      ticket: t,
      urgency: getSlaUrgency({
        slaDeadline: t.fullData.sla_deadline,
        status: t.fullData.status,
        priorite: t.fullData.priorite_calculee,
        pausedAt: t.fullData.paused_at,
        resolvedAt: t.fullData.resolved_at,
      }),
    }))
}

// Taux de conformité SLA — PAS basé sur getSlaTrackedTickets ci-dessus : celui-ci
// exclut délibérément les tickets résolus DANS les délais (utile pour "quels tickets
// ont besoin d'attention", faux pour un pourcentage — un ticket résolu à temps
// n'entrerait alors jamais dans le calcul, ni au numérateur ni au dénominateur).
// Ici, TOUT ticket dont le chrono SLA a démarré (in_progress/on_hold/done — "new"
// exclu, chrono jamais démarré) compte, résolu à temps ou non. Sans ça, un filtre
// temporel qui isole un petit échantillon contenant un ticket résolu en retard
// sans ticket actif pour "diluer" fait chuter le taux à 0% de façon trompeuse,
// même si la plupart des tickets de la période ont bien respecté leur SLA.
export function getSlaComplianceStats(tickets, nowMs = Date.now()) {
  const breachedFlags = tickets
    .filter(t => ['in_progress', 'on_hold', 'done'].includes(t.fullData?.status))
    .map(t => {
      const f = t.fullData
      if (f.status === 'done') return f.sla_breached === true
      return getSlaUrgency({
        slaDeadline: f.sla_deadline, status: f.status, priorite: f.priorite_calculee,
        pausedAt: f.paused_at, resolvedAt: f.resolved_at,
      }, nowMs).breached
    })

  const total = breachedFlags.length
  const breachedCount = breachedFlags.filter(Boolean).length
  const compliancePct = total > 0 ? Math.round(((total - breachedCount) / total) * 100) : 100
  return { total, breachedCount, compliancePct }
}
