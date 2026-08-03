import React from 'react'
import { LogIn, AlertCircle, Loader2 } from 'lucide-react'
import { useLanguage } from '../hooks/useLanguage'

function Logo() {
  return (
    <div style={{ display: 'inline-flex', alignItems: 'center', gap: '12px' }}>
      <div style={{
        width: 48, height: 48,
        background: '#f6c026',
        borderRadius: '12px',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        fontWeight: 800, fontSize: '18px', color: '#0f172a',
      }}>
        AI
      </div>
      <span style={{ fontSize: '22px', fontWeight: 700, color: '#f1f5f9', letterSpacing: '-0.3px' }}>
        SmartDispatch
      </span>
    </div>
  )
}

// N'est affiché que dans deux cas : brièvement pendant le bootstrap de session
// (restauration, callback OIDC, ou sonde de disponibilité Keycloak avant la
// redirection auto — voir App.jsx, `connecting`), ou en fallback avec un
// message d'erreur + bouton de reprise manuelle si tout ça a échoué — jamais
// comme étape volontaire dans le parcours normal (pas de clic requis pour se
// connecter en temps normal).
export function LoginPage({ error, connecting, onRetry }) {
  const { t } = useLanguage()

  const background = 'linear-gradient(135deg, #0f172a 0%, #1e293b 100%)'

  // État "connecting" : juste le logo + un loader, pas de carte ni de bouton —
  // rien à faire de son côté pendant le bootstrap, le retry manuel n'a de sens
  // qu'une fois qu'on est sûr que ça a échoué (état "error" ci-dessous).
  if (connecting) {
    return (
      <div style={{
        minHeight: '100vh',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        gap: '28px',
        background,
        padding: '20px',
      }}>
        <Logo />
        <Loader2 size={32} color="#f6c026" style={{ animation: 'spin 1s linear infinite' }} />
        <style>{`@keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }`}</style>
      </div>
    )
  }

  return (
    <div style={{
      minHeight: '100vh',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      background,
      padding: '20px',
    }}>
      <div style={{ width: '100%', maxWidth: '400px' }}>

        {/* Logo */}
        <div style={{ textAlign: 'center', marginBottom: '32px' }}>
          <div style={{ marginBottom: '10px' }}>
            <Logo />
          </div>
          <p style={{ color: '#64748b', fontSize: '14px', margin: 0 }}>
            {t('login.subtitle')}
          </p>
        </div>

        {/* Card */}
        <div style={{
          background: 'white',
          borderRadius: '16px',
          padding: '32px',
          boxShadow: '0 25px 50px rgba(0,0,0,0.35)',
          textAlign: 'center',
        }}>
          <h2 style={{ margin: '0 0 24px', fontSize: '20px', fontWeight: 700, color: '#1e293b' }}>
            {t('login.title')}
          </h2>

          {error ? (
            <div style={{
              display: 'flex', alignItems: 'flex-start', gap: '8px', textAlign: 'left',
              background: '#fef2f2', border: '1px solid #fecaca',
              borderRadius: '8px', padding: '10px 14px',
              marginBottom: '20px', color: '#dc2626', fontSize: '13px',
            }}>
              <AlertCircle size={15} style={{ marginTop: '1px', flexShrink: 0 }} />
              {error}
            </div>
          ) : (
            <p style={{ margin: '0 0 24px', fontSize: '13px', color: '#64748b' }}>
              {t('login.redirecting')}
            </p>
          )}

          <button
            type="button"
            onClick={onRetry}
            style={{
              width: '100%', padding: '11px',
              background: '#f6c026',
              border: 'none', borderRadius: '8px',
              fontWeight: 700, fontSize: '14px',
              cursor: 'pointer',
              display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '8px',
              color: '#0f172a',
            }}
          >
            <LogIn size={16} />
            {t('login.signIn')}
          </button>
        </div>
      </div>
    </div>
  )
}
