// Plage de dates personnalisée (bornes ISO YYYY-MM-DD) partagée entre les 4 vues
// qui avaient un filtre temporel (Dashboard, Agents, Suivi SLA, Mon Profil agent) —
// remplace l'ancien filtre à presets fixes (utils/period.js, supprimé) et l'ancien
// GET /agent/profile/stats?period= (backend, supprimé) au profit d'un filtrage
// 100% client, cohérent sur les 4 vues.

const pad = (n) => String(n).padStart(2, '0')

export function toISODate(date) {
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
}

// new Date('YYYY-MM-DD') parse en UTC minuit (décale d'un jour selon le fuseau
// local) — on construit la date en local explicitement pour éviter ce piège.
function parseISODate(iso) {
  const [y, m, d] = iso.split('-').map(Number)
  return new Date(y, m - 1, d)
}

// Valeur par défaut au premier chargement : du 1er du mois en cours à aujourd'hui.
export function getDefaultRange() {
  const now = new Date()
  return {
    startDate: toISODate(new Date(now.getFullYear(), now.getMonth(), 1)),
    endDate: toISODate(now),
  }
}

// endDate est inclusif jusqu'à 23:59:59.999 : sans ce +1 jour - 1ms, un ticket
// créé le jour même de endDate (souvent "aujourd'hui") serait exclu par une
// comparaison à minuit.
export function isWithinRange(iso, startDate, endDate) {
  if (!iso) return false
  const t = new Date(iso).getTime()
  const startMs = parseISODate(startDate).getTime()
  const endMs = parseISODate(endDate).getTime() + (24 * 3600 * 1000 - 1)
  return t >= startMs && t <= endMs
}

const localeFor = (language) => (language === 'fr' ? 'fr-FR' : 'en-US')

// "01 juin – 30 juin 2026" (même année) / "28 déc. 2025 – 03 janv. 2026" (années différentes)
export function formatRangeLabel(startDate, endDate, language) {
  const start = parseISODate(startDate)
  const end = parseISODate(endDate)
  const sameYear = start.getFullYear() === end.getFullYear()
  const dayMonth = (d) => d.toLocaleDateString(localeFor(language), { day: '2-digit', month: 'long' })
  const dayMonthYear = (d) => d.toLocaleDateString(localeFor(language), { day: '2-digit', month: 'long', year: 'numeric' })
  return `${sameYear ? dayMonth(start) : dayMonthYear(start)} – ${dayMonthYear(end)}`
}
