import { useTranslation } from 'react-i18next'

// Thin wrapper around react-i18next's useTranslation() that keeps the exact
// same public shape ({ t, language, setLanguage, toggleLanguage }) every
// component in the app already consumes — swapping the underlying engine
// (custom Context → react-i18next) never required touching call sites.
export function useLanguage() {
  const { t, i18n } = useTranslation()
  const language = i18n.language
  const setLanguage = (lang) => i18n.changeLanguage(lang)
  const toggleLanguage = () => setLanguage(language === 'en' ? 'fr' : 'en')

  return { t, language, setLanguage, toggleLanguage }
}
