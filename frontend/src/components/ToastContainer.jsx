import React from 'react'
import { useLanguage } from '../hooks/useLanguage'

export function ToastContainer({ toasts, onRemove }) {
  const { t } = useLanguage()
  if (toasts.length === 0) return null

  return (
    <div style={{
      position: 'fixed',
      bottom: '24px',
      right: '24px',
      zIndex: 9999,
      display: 'flex',
      flexDirection: 'column-reverse',
      gap: '10px',
      maxWidth: '340px',
      pointerEvents: 'none',
    }}>
      {toasts.map(toast => (
        <div
          key={toast.id}
          className="toast-item"
          style={{
            background: '#0f172a',
            border: '1px solid rgba(246,192,38,0.35)',
            borderLeft: '4px solid #f6c026',
            borderRadius: '8px',
            padding: '12px 36px 12px 16px',
            boxShadow: '0 8px 24px rgba(0,0,0,0.5)',
            position: 'relative',
            pointerEvents: 'all',
          }}
        >
          <div style={{ fontSize: '11px', fontWeight: 700, color: '#f6c026', marginBottom: '4px', letterSpacing: '0.3px' }}>
            {toast.titre}
          </div>
          <div style={{ fontSize: '12px', color: '#cbd5e1', lineHeight: 1.45 }}>
            {toast.message}
          </div>
          <button
            onClick={() => onRemove(toast.id)}
            aria-label={t('common.close')}
            style={{
              position: 'absolute', top: '8px', right: '8px',
              background: 'none', border: 'none', cursor: 'pointer',
              color: '#475569', fontSize: '16px', lineHeight: 1,
              padding: '2px 5px', borderRadius: '4px',
              transition: 'color 0.15s',
            }}
            onMouseEnter={e => { e.currentTarget.style.color = '#f1f5f9' }}
            onMouseLeave={e => { e.currentTarget.style.color = '#475569' }}
          >
            ×
          </button>
        </div>
      ))}
    </div>
  )
}
