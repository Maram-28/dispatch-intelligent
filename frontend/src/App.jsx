import React, { useState, useEffect, useCallback, useRef } from 'react'
import { LayoutDashboard, Users, Clock, Settings, LogOut, ClipboardList, Bell, User } from 'lucide-react'
import { AnimatePresence } from 'framer-motion'

import { NavItem } from './components/NavItem'
import { DashboardView } from './views/DashboardView'
import { AgentsView } from './views/AgentsView'
import { SLAMonitorView } from './views/SLAMonitorView'
import { ClassificationModal } from './components/ClassificationModal'
import { TicketDetailsModal } from './components/TicketDetailsModal'
import { LoginPage } from './components/LoginPage'
import { AgentView } from './views/AgentView'
import { AgentDashboardView } from './views/agent/AgentDashboardView'
import { AgentNotificationsView } from './views/agent/AgentNotificationsView'
import { AgentProfileView } from './views/agent/AgentProfileView'
import { SettingsView } from './views/SettingsView'
import { SkipLink } from './components/SkipLink'
import { LanguageToggle } from './components/LanguageToggle'
import { useAccessibility } from './hooks/useAccessibility'
import { useLanguage } from './hooks/useLanguage'
import { userManager, apiFetch, API_BASE, waitForKeycloak } from './utils/api'
import { useNotifications } from './hooks/useNotifications'
import { ToastContainer } from './components/ToastContainer'
import { formatDate, formatTime } from './utils/formatDate'

function App() {
  const [currentUser, setCurrentUser] = useState(null)
  // 'connecting' (bootstrap en cours — restauration de session, callback OIDC,
  // ou sonde de disponibilité Keycloak avant signinRedirect()) | 'error'
  // (bootstrap terminé en échec, reprise manuelle via le bouton) | 'done'
  // (session valide, currentUser hydraté).
  const [authPhase, setAuthPhase] = useState('connecting')
  const [authError, setAuthError] = useState(null)
  const authBootstrapRan = useRef(false)
  const [activeTab, setActiveTab] = useState('Dashboard')
  const [isModalOpen, setIsModalOpen] = useState(false)
  const [selectedTicket, setSelectedTicket] = useState(null)
  const [classifiedTickets, setClassifiedTickets] = useState([])
  const [isClassifying, setIsClassifying] = useState(false)
  const [lastResult, setLastResult] = useState(null)
  const [notifCount, setNotifCount] = useState(0)
  const esRef = useRef(null)
  const { toasts, removeToast, triggerNotification, armAudio, requestNotifPermission } = useNotifications()
  const { settings: a11ySettings } = useAccessibility()
  const { t, language } = useLanguage()

  // Récupère {id, nom, email, role} depuis GET /me (source de vérité déjà
  // utilisée par le backend pour l'enforcement des rôles) plutôt que de
  // décoder nous-mêmes les claims du token OIDC — évite toute divergence
  // entre ce que l'UI affiche et ce que le backend autorise réellement.
  const hydrateCurrentUser = async () => {
    const res = await apiFetch('/me')
    if (!res || !res.ok) return null
    const me = await res.json()
    const user = { membre_id: me.id, nom: me.nom, email: me.email, role: me.role }
    setCurrentUser(user)
    armAudio()
    requestNotifPermission()
    return user
  }

  // Bootstrap de session au montage : termine le callback OIDC (retour de
  // Keycloak avec ?code=&state=) si présent, sinon tente de restaurer une
  // session déjà persistée par oidc-client-ts (localStorage). Si aucune session
  // n'existe, on sonde d'abord la disponibilité de Keycloak (waitForKeycloak,
  // retry borné avec backoff — absorbe la course de démarrage Docker/JVM où le
  // conteneur est "up" avant que son port HTTP ne réponde vraiment) puis
  // redirige — pas d'écran intermédiaire avec un bouton "Se connecter" à
  // cliquer dans le cas normal.
  //
  // authBootstrapRan (ref, pas juste un flag de cleanup) : StrictMode (voir
  // main.jsx) monte-démonte-remonte ce composant en dev, donc cet effet
  // s'exécute deux fois. signinRedirectCallback() consomme le `code` OIDC à
  // usage unique de l'URL — un simple flag "ignore" mis à true au cleanup ne
  // suffit pas, puisque les DEUX exécutions appelleraient quand même
  // signinRedirectCallback() avant qu'aucune n'ait connaissance de l'autre ;
  // celle qui perd la course reçoit "Code not valid" de Keycloak et affiche
  // l'écran d'erreur alors que la connexion a en fait réussi. Le ref (pas un
  // state) est lu et écrit de façon synchrone AVANT le premier point d'attente
  // async, donc la deuxième exécution sort immédiatement sans jamais appeler
  // signinRedirectCallback().
  useEffect(() => {
    if (authBootstrapRan.current) return
    authBootstrapRan.current = true
    ;(async () => {
      try {
        const params = new URLSearchParams(window.location.search)
        const isCallback = params.has('code') && params.has('state')
        if (isCallback) {
          await userManager.signinRedirectCallback()
          window.history.replaceState({}, document.title, window.location.pathname)
        }

        const oidcUser = await userManager.getUser()
        if (oidcUser && !oidcUser.expired) {
          await hydrateCurrentUser()
          setAuthPhase('done')
          return
        }

        if (isCallback) {
          // Revenu de Keycloak mais toujours pas de session exploitable (ex:
          // /me a échoué, aucun rôle applicatif) — ne JAMAIS rediriger à nouveau
          // automatiquement ici, ce serait une boucle infinie. On affiche plutôt
          // un état d'erreur avec reprise manuelle.
          setAuthError(t('auth.loginFailed'))
          setAuthPhase('error')
          return
        }

        // Visite normale sans session : on confirme d'abord que Keycloak répond
        // avant de déclencher signinRedirect() — pas de retry sur
        // signinRedirect() lui-même, il redirige déjà le navigateur dès qu'il
        // réussit (voir waitForKeycloak dans utils/api.js pour le détail).
        await waitForKeycloak()
        await userManager.signinRedirect()
        // signinRedirect() navigue le navigateur hors de cette page dès son
        // succès — authPhase reste "connecting" jusqu'à ce départ, pas de
        // setAuthPhase('done') ici.
      } catch (err) {
        console.error('[AUTH] Échec du bootstrap de session :', err)
        setAuthError(t('auth.serverUnreachable'))
        setAuthPhase('error')
      }
    })()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const fmtDate = useCallback((iso) => {
    if (!iso) return '—'
    return formatDate(iso, language, { day: '2-digit', month: '2-digit', year: 'numeric' })
      + ' ' + formatTime(iso, language, { hour: '2-digit', minute: '2-digit' })
  }, [language])

  const mapStatus = useCallback((result) => {
    if (result.status === 'in_progress') return 'In Progress'
    if (result.status === 'on_hold')     return 'In Progress'
    if (result.status === 'done')        return 'Done'
    return 'Assigned'
  }, [])

  const formatTicket = useCallback((result) => ({
    id: result.numero,
    title: result.titre || result.breve_description || result.numero,
    desc: result.reasoning,
    category: result.categorie,
    priority: 'P' + (result.priorite_calculee || '4-Standard').split('-')[0],
    confidence: Math.round(result.confidence * 100),
    agent: result.assigned_to ? result.assigned_to.nom : 'AI System',
    time: fmtDate(result.created_at),
    status: mapStatus(result),
    fullData: result
  }), [fmtDate, mapStatus])

  const fetchTickets = useCallback(async () => {
    try {
      const response = await apiFetch('/tickets')
      if (!response) return
      const data = await response.json()
      setClassifiedTickets(data.map(formatTicket))
    } catch (error) {
      console.error('Failed to fetch tickets:', error)
      setClassifiedTickets([])
    }
  }, [formatTicket])

  useEffect(() => {
    if (!currentUser) return
    fetchTickets()
    const id = setInterval(fetchTickets, 15_000)
    return () => clearInterval(id)
  }, [currentUser, fetchTickets])

  // Canal SSE temps réel — reçoit les notifications dès qu'elles sont créées.
  // Dépend de membre_id (string) et non de l'objet currentUser pour éviter les
  // ré-ouvertures dues aux nouvelles références d'objet à chaque render.
  //
  // Authentification par ticket court (60s, usage unique — voir
  // POST /agent/notifications/sse-ticket côté backend), pas par le token OIDC :
  // EventSource ne peut pas envoyer d'en-tête Authorization, et un token Keycloak
  // dans l'URL fuiterait dans les logs serveur/l'historique navigateur/Referer.
  // Conséquence : on ne peut plus compter sur l'auto-reconnect natif d'EventSource
  // (il rejouerait le même ticket, déjà consommé) — sur erreur, on ferme et on
  // remint un ticket frais avant de rouvrir, avec un backoff jusqu'à ~15s.
  useEffect(() => {
    if (esRef.current) {
      esRef.current.close()
      esRef.current = null
    }

    if (!currentUser) return

    let cancelled = false
    let retryDelay = 1000
    let retryTimer = null

    const connect = async () => {
      if (cancelled) return
      try {
        const res = await apiFetch('/agent/notifications/sse-ticket', { method: 'POST' })
        if (!res || !res.ok) throw new Error('sse-ticket request failed')
        const { ticket } = await res.json()
        if (cancelled) return

        const es = new EventSource(`${API_BASE}/agent/notifications/stream?ticket=${encodeURIComponent(ticket)}`)
        esRef.current = es

        es.addEventListener('connected', () => {
          console.log('[SSE] Connecté — user:', currentUser.membre_id)
          retryDelay = 1000
        })

        es.onmessage = (e) => {
          try {
            const event = JSON.parse(e.data)
            console.log('[SSE] Notification reçue :', event)
            triggerNotification(event)
          } catch {
            console.log('[SSE] Message brut :', e.data)
          }
        }

        es.onerror = () => {
          es.close()
          if (esRef.current === es) esRef.current = null
          if (cancelled) return
          retryTimer = setTimeout(connect, retryDelay)
          retryDelay = Math.min(retryDelay * 2, 15_000)
        }
      } catch (err) {
        console.warn('[SSE] Échec ouverture connexion, nouvelle tentative dans', retryDelay, 'ms :', err)
        if (!cancelled) retryTimer = setTimeout(connect, retryDelay)
        retryDelay = Math.min(retryDelay * 2, 15_000)
      }
    }

    connect()

    return () => {
      cancelled = true
      if (retryTimer) clearTimeout(retryTimer)
      if (esRef.current) {
        esRef.current.close()
        esRef.current = null
      }
      console.log('[SSE] Connexion fermée (cleanup)')
    }
    // currentUser is intentionally omitted — see the comment above (depends
    // on membre_id only, to avoid reopening the connection on every render).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentUser?.membre_id, triggerNotification])

  // Poll le compte unifié (alertes SLA + inbox non lues) pour les admins
  useEffect(() => {
    if (!currentUser || currentUser.role !== 'admin') return
    const poll = async () => {
      const [slaRes, inboxRes] = await Promise.all([
        apiFetch('/agent/notifications'),
        apiFetch('/agent/notifications/inbox'),
      ])
      let total = 0
      if (slaRes) { const d = await slaRes.json(); total += d.count ?? 0 }
      if (inboxRes) { const d = await inboxRes.json(); total += d.unread_count ?? 0 }
      setNotifCount(total)
    }
    poll()
    const id = setInterval(poll, 60_000)
    return () => clearInterval(id)
  }, [currentUser])

  const handleTicketUpdated = (updatedResult) => {
    const formatted = formatTicket(updatedResult)
    setClassifiedTickets(prev => prev.map(t => (t.id === formatted.id ? formatted : t)))
  }

  const handleClassify = async (ticketData) => {
    setIsClassifying(true)
    setLastResult(null)
    try {
      const response = await apiFetch('/classify', {
        method: 'POST',
        body: JSON.stringify(ticketData),
      })
      if (!response) return
      const result = await response.json()
      setLastResult(result)

      setClassifiedTickets(prev => [formatTicket(result), ...prev])
    } catch (error) {
      console.error('Classification failed:', error)
      alert('Internal AI error. Please check if the backend is running.')
    } finally {
      setIsClassifying(false)
    }
  }

  const handleLogout = async () => {
    setCurrentUser(null)
    setClassifiedTickets([])
    // Déconnexion RP-initiated : sans ça l'utilisateur garderait une session SSO
    // active côté Keycloak et serait reconnecté silencieusement à la prochaine visite.
    await userManager.signoutRedirect()
  }

  if (authPhase !== 'done') {
    return (
      <LoginPage
        connecting={authPhase === 'connecting'}
        error={authPhase === 'error' ? authError : null}
        onRetry={() => userManager.signinRedirect()}
      />
    )
  }

  // Agents → espace personnel uniquement
  if (currentUser.role === 'agent') {
    return (
      <>
        {a11ySettings.keyboardNav && <SkipLink />}
        <AgentView currentUser={currentUser} onLogout={handleLogout} />
        <ToastContainer toasts={toasts} onRemove={removeToast} />
      </>
    )
  }

  // Admins → vue complète : management + espace personnel
  const initials = currentUser.nom
    .split(' ').map(w => w[0]).join('').toUpperCase().slice(0, 2)

  return (
    <div className="app-container">
      {a11ySettings.keyboardNav && <SkipLink />}
      {/* Sidebar */}
      <aside className="sidebar">
        <div className="logo-container">
          <div className="logo-box">AI</div>
          <span className="logo-text">SmartDispatch</span>
        </div>

        <nav className="nav-menu" style={{ flex: 1 }}>

          {/* ── Section Management ── */}
          <div style={{ fontSize: '10px', fontWeight: 700, color: 'var(--sidebar-label)', textTransform: 'uppercase', letterSpacing: '0.8px', padding: '0 20px 6px' }}>
            {t('nav.management')}
          </div>
          <NavItem
            icon={<LayoutDashboard size={20} />}
            label={t('nav.dashboard')}
            active={activeTab === 'Dashboard'}
            onClick={() => setActiveTab('Dashboard')}
          />
          <NavItem
            icon={<Users size={20} />}
            label={t('nav.agents')}
            active={activeTab === 'Agents'}
            onClick={() => setActiveTab('Agents')}
          />
          <NavItem
            icon={<Clock size={20} />}
            label={t('nav.slaMonitor')}
            active={activeTab === 'SLA Monitor'}
            onClick={() => setActiveTab('SLA Monitor')}
          />

          {/* ── Section Mon Espace ── */}
          <div style={{ fontSize: '10px', fontWeight: 700, color: 'var(--sidebar-label)', textTransform: 'uppercase', letterSpacing: '0.8px', padding: '16px 20px 6px' }}>
            {t('nav.mySpace')}
          </div>
          <NavItem
            icon={<ClipboardList size={20} />}
            label={t('nav.myTickets')}
            active={activeTab === 'MesTickets'}
            onClick={() => setActiveTab('MesTickets')}
          />
          {/* Notifications with badge */}
          <div style={{ position: 'relative' }}>
            <NavItem
              icon={<Bell size={20} />}
              label={t('nav.myAlerts')}
              active={activeTab === 'MesAlertes'}
              onClick={() => { setActiveTab('MesAlertes'); setNotifCount(0) }}
            />
            {notifCount > 0 && (
              <span style={{
                position: 'absolute', top: '8px', right: '16px',
                background: '#ef4444', color: '#fff', borderRadius: '999px',
                fontSize: '10px', fontWeight: 700, padding: '1px 6px', minWidth: '18px', textAlign: 'center',
                pointerEvents: 'none',
              }}>
                {notifCount}
              </span>
            )}
          </div>
          <NavItem
            icon={<User size={20} />}
            label={t('nav.myProfile')}
            active={activeTab === 'MonProfil'}
            onClick={() => setActiveTab('MonProfil')}
          />

        </nav>

        <div className="nav-footer">
          <NavItem
            icon={<Settings size={20} />}
            label={t('nav.settings')}
            active={activeTab === 'Settings'}
            onClick={() => setActiveTab('Settings')}
          />
          <LanguageToggle />

          {/* User info + logout */}
          <div style={{ borderTop: '1px solid var(--sidebar-divider)', paddingTop: '12px', marginTop: '8px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px', padding: '6px 12px' }}>
              <div style={{
                width: 32, height: 32, borderRadius: '50%',
                background: 'var(--primary-color)',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                fontWeight: 700, fontSize: '12px', color: '#0f172a', flexShrink: 0,
              }}>
                {initials}
              </div>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{
                  fontSize: '12px', fontWeight: 600, color: 'var(--sidebar-text-active)',
                  overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                }}>
                  {currentUser.nom}
                </div>
                <div style={{ fontSize: '10px', color: 'var(--primary-color)' }}>
                  {t('nav.manager')}
                </div>
              </div>
            </div>
            <button
              onClick={handleLogout}
              style={{
                display: 'flex', alignItems: 'center', gap: '10px',
                width: '100%', padding: '8px 12px',
                background: 'none', border: 'none', cursor: 'pointer',
                color: 'var(--sidebar-text-muted)', fontSize: '13px', fontWeight: 500,
                borderRadius: '8px', marginTop: '4px',
                transition: 'background 0.15s, color 0.15s',
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.background = 'rgba(239,68,68,0.12)'
                e.currentTarget.style.color = '#ef4444'
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.background = 'none'
                e.currentTarget.style.color = 'var(--sidebar-text-muted)'
              }}
            >
              <LogOut size={16} />
              {t('nav.logout')}
            </button>
          </div>
        </div>
      </aside>

      {/* Main Content */}
      <main className="main-content" id="main-content">
        <AnimatePresence mode="wait">
          {activeTab === 'Dashboard' && (
            <DashboardView
              key="dashboard"
              tickets={classifiedTickets}
              onOpenModal={() => { setIsModalOpen(true); setLastResult(null) }}
              onTicketClick={setSelectedTicket}
            />
          )}
          {activeTab === 'Agents'     && <AgentsView key="agents" currentUser={currentUser} tickets={classifiedTickets} />}
          {activeTab === 'SLA Monitor' && <SLAMonitorView key="sla" tickets={classifiedTickets} onTicketClick={setSelectedTicket} />}
          {activeTab === 'MesTickets' && <AgentDashboardView key="mes-tickets" />}
          {activeTab === 'MesAlertes' && (
            <AgentNotificationsView key="mes-alertes" onCountChange={setNotifCount} />
          )}
          {activeTab === 'MonProfil' && <AgentProfileView key="mon-profil" />}
          {activeTab === 'Settings' && <SettingsView key="settings" />}
        </AnimatePresence>
      </main>

      {isModalOpen && (
        <ClassificationModal
          onClose={() => setIsModalOpen(false)}
          onSubmit={handleClassify}
          isClassifying={isClassifying}
          result={lastResult}
        />
      )}

      {selectedTicket && (
        <TicketDetailsModal
          ticket={selectedTicket}
          onClose={() => setSelectedTicket(null)}
          onUpdated={handleTicketUpdated}
        />
      )}

      <ToastContainer toasts={toasts} onRemove={removeToast} />
    </div>
  )
}

export default App
