import React from 'react'
import { useLanguage } from '../hooks/useLanguage'

// Visible seulement au focus clavier (Tab) — permet de sauter directement au
// contenu principal sans traverser toute la sidebar. Fait partie du réglage
// d'accessibilité "Navigation clavier" (voir SettingsView.jsx).
export function SkipLink({ targetId = 'main-content' }) {
  const { t } = useLanguage()
  return (
    <a href={`#${targetId}`} className="skip-link">
      {t('common.skipToContent')}
    </a>
  )
}
