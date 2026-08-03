import i18next from 'i18next'
import { initReactI18next } from 'react-i18next'
import { translations } from './translations'

const STORAGE_KEY = 'smartdispatch_language'
const DEFAULT_LANGUAGE = 'en'

function loadLanguage() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    return raw === 'fr' || raw === 'en' ? raw : DEFAULT_LANGUAGE
  } catch {
    return DEFAULT_LANGUAGE
  }
}

// react-i18next resources derived directly from the existing flat
// translations dictionary — { 'nav.dashboard': { en, fr } } becomes one
// { 'nav.dashboard': '...' } bundle per language, rather than hand-copying
// ~150 entries into a second format.
const resources = {
  en: { translation: Object.fromEntries(Object.entries(translations).map(([key, v]) => [key, v.en])) },
  fr: { translation: Object.fromEntries(Object.entries(translations).map(([key, v]) => [key, v.fr])) },
}

i18next
  .use(initReactI18next)
  .init({
    resources,
    lng: loadLanguage(),
    fallbackLng: DEFAULT_LANGUAGE,
    // Our keys ("nav.dashboard", "ticketDetails.statusNew", ...) are flat
    // identifiers, not nested paths — disable i18next's default dot/colon
    // key-splitting so it looks them up literally.
    keySeparator: false,
    nsSeparator: false,
    interpolation: { escapeValue: false },
  })

i18next.on('languageChanged', (lng) => {
  try {
    localStorage.setItem(STORAGE_KEY, lng)
  } catch { /* ignore */ }
  document.documentElement.lang = lng
})

document.documentElement.lang = i18next.language

export default i18next
