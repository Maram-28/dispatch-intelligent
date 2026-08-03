// Locale-aware date/time formatting, replacing hardcoded 'fr-FR' calls —
// the locale now follows the current UI language (see hooks/useLanguage.js).

const localeFor = (language) => (language === 'fr' ? 'fr-FR' : 'en-US')

export function formatDate(iso, language, opts) {
  if (!iso) return '—'
  return new Date(iso).toLocaleDateString(localeFor(language), opts)
}

export function formatTime(iso, language, opts) {
  if (!iso) return '—'
  return new Date(iso).toLocaleTimeString(localeFor(language), opts)
}

export function formatDateTime(iso, language, opts) {
  if (!iso) return '—'
  return new Date(iso).toLocaleString(localeFor(language), opts)
}

export function formatNumber(n, language) {
  return n.toLocaleString(localeFor(language))
}

// Locale-aware "Month Year" label (e.g. "January 2026" / "Janvier 2026"),
// capitalized — used by calendar-style month navigation headers.
export function monthYearLabel(date, language) {
  const label = date.toLocaleDateString(localeFor(language), { month: 'long', year: 'numeric' })
  return label.charAt(0).toUpperCase() + label.slice(1)
}

// Locale-aware short weekday labels, Monday-first (Mon..Sun / Lu..Di).
// 2024-01-01 is a Monday, used as an anchor regardless of the current date.
export function weekdayLabels(language) {
  return Array.from({ length: 7 }, (_, i) =>
    new Date(2024, 0, i + 1).toLocaleDateString(localeFor(language), { weekday: 'short' })
  )
}
