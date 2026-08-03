import { useEffect } from 'react'
import { useLanguage } from './useLanguage'

// Éléments interactifs : un clic dessus doit garder son comportement normal
// (navigation, soumission, etc.) plutôt que déclencher la lecture vocale.
const INTERACTIVE_SELECTOR = 'button, a, input, select, textarea, [role="button"], [contenteditable="true"], svg'

// Lecture vocale au clic (Text Reader) — utilise l'API navigateur SpeechSynthesis,
// aucune dépendance externe. N'intercepte que les clics sur du texte simple ;
// les contrôles interactifs (boutons, liens, champs) gardent leur comportement normal.
export function useTextReader(enabled) {
  const { language } = useLanguage()

  useEffect(() => {
    if (!enabled || typeof window === 'undefined' || !window.speechSynthesis) return

    const handleClick = (e) => {
      if (e.target.closest(INTERACTIVE_SELECTOR)) return

      const text = (e.target.innerText || e.target.textContent || '').trim()
      if (!text) return

      window.speechSynthesis.cancel()
      const utterance = new SpeechSynthesisUtterance(text)
      utterance.lang = language === 'fr' ? 'fr-FR' : 'en-US'

      const target = e.target
      target.classList.add('a11y-reading')
      const clearHighlight = () => target.classList.remove('a11y-reading')
      utterance.onend = clearHighlight
      utterance.onerror = clearHighlight

      window.speechSynthesis.speak(utterance)
    }

    document.addEventListener('click', handleClick)
    return () => {
      document.removeEventListener('click', handleClick)
      window.speechSynthesis.cancel()
    }
  }, [enabled, language])
}
