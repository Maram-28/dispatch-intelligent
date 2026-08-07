import React, { useState, useEffect } from 'react'
import { ClipboardList, User, Bell, LogOut, Settings } from 'lucide-react'
import { AnimatePresence } from 'framer-motion'
import { apiFetch } from '../utils/api'
import { AgentDashboardView }     from './agent/AgentDashboardView'
import { AgentProfileView }       from './agent/AgentProfileView'
import { AgentNotificationsView } from './agent/AgentNotificationsView'
import { SettingsView }           from './SettingsView'
import { LanguageToggle }         from '../components/LanguageToggle'
import { useLanguage } from '../hooks/useLanguage'

function SidebarItem({ icon, label, active, onClick, badge }) {
  return (
    <button
      onClick={onClick}
      style={{
        display: 'flex', alignItems: 'center', gap: '12px',
        width: '100%', padding: '10px 20px',
        background: active ? 'var(--sidebar-active)' : 'none',
        border: 'none', cursor: 'pointer',
        color: active ? 'var(--primary-color)' : 'var(--sidebar-text-muted)',
        fontSize: '14px', fontWeight: active ? 600 : 400,
        borderLeft: active ? '3px solid var(--primary-color)' : '3px solid transparent',
        transition: 'all 0.15s',
        position: 'relative',
        textAlign: 'left',
      }}
    >
      {icon}
      <span style={{ flex: 1 }}>{label}</span>
      {badge > 0 && (
        <span style={{
          background: '#ef4444', color: '#fff', borderRadius: '999px',
          fontSize: '10px', fontWeight: 700, padding: '1px 6px', minWidth: '18px', textAlign: 'center',
        }}>
          {badge}
        </span>
      )}
    </button>
  )
}

export function AgentView({ currentUser, onLogout, deepLinkTicket, onDeepLinkConsumed }) {
  const [tab, setTab]             = useState('tickets')
  const [notifCount, setNotifCount] = useState(0)
  const { t } = useLanguage()

  // Lien de deep-link depuis un email (ex: "Voir mes tickets") : force l'onglet
  // Tickets, où AgentDashboardView ouvre la fiche du ticket ciblé une fois sa
  // propre liste chargée.
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- deriving the active tab from a prop that resolves asynchronously (OIDC redirect), not a cascading-render antipattern.
    if (deepLinkTicket) setTab('tickets')
  }, [deepLinkTicket])

  // Poll le compte unifié (alertes SLA + inbox non lues) toutes les 60s
  useEffect(() => {
    const fetchCount = async () => {
      const [slaRes, inboxRes] = await Promise.all([
        apiFetch('/agent/notifications'),
        apiFetch('/agent/notifications/inbox'),
      ])
      let total = 0
      if (slaRes) { const d = await slaRes.json(); total += d.count ?? 0 }
      if (inboxRes) { const d = await inboxRes.json(); total += d.unread_count ?? 0 }
      setNotifCount(total)
    }
    fetchCount()
    const id = setInterval(fetchCount, 60_000)
    return () => clearInterval(id)
  }, [])

  const initials = currentUser.nom
    .split(' ').map(w => w[0]).join('').toUpperCase().slice(0, 2)

  return (
    <div className="app-container">
      {/* Sidebar */}
      <aside className="sidebar">
        <div className="logo-container">
          <div className="logo-box">AI</div>
          <span className="logo-text">SmartDispatch</span>
        </div>

        <nav className="nav-menu" style={{ flex: 1 }}>
          <SidebarItem
            icon={<ClipboardList size={18} />}
            label={t('agentNav.myTickets')}
            active={tab === 'tickets'}
            onClick={() => setTab('tickets')}
          />
          <SidebarItem
            icon={<Bell size={18} />}
            label={t('agentNav.notifications')}
            active={tab === 'notifications'}
            onClick={() => { setTab('notifications'); setNotifCount(0) }}
            badge={notifCount}
          />
          <SidebarItem
            icon={<User size={18} />}
            label={t('agentNav.myProfile')}
            active={tab === 'profile'}
            onClick={() => setTab('profile')}
          />
        </nav>

        <SidebarItem
          icon={<Settings size={18} />}
          label={t('agentNav.settings')}
          active={tab === 'settings'}
          onClick={() => setTab('settings')}
        />
        <LanguageToggle />

        {/* User info + logout */}
        <div style={{ borderTop: '1px solid var(--sidebar-divider)', paddingTop: '12px', margin: '0 0 8px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px', padding: '6px 20px' }}>
            <div style={{
              width: 32, height: 32, borderRadius: '50%', background: 'var(--primary-color)',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              fontWeight: 700, fontSize: '12px', color: '#0f172a', flexShrink: 0,
            }}>
              {initials}
            </div>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontSize: '12px', fontWeight: 600, color: 'var(--sidebar-text-active)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {currentUser.nom}
              </div>
              <div style={{ fontSize: '10px', color: 'var(--sidebar-text-muted)' }}>{t('agentNav.agent')}</div>
            </div>
          </div>
          <button
            onClick={onLogout}
            style={{
              display: 'flex', alignItems: 'center', gap: '10px',
              width: '100%', padding: '8px 20px',
              background: 'none', border: 'none', cursor: 'pointer',
              color: 'var(--sidebar-text-muted)', fontSize: '13px', fontWeight: 500,
              transition: 'background 0.15s, color 0.15s',
            }}
            onMouseEnter={e => { e.currentTarget.style.background = 'rgba(239,68,68,0.12)'; e.currentTarget.style.color = '#ef4444' }}
            onMouseLeave={e => { e.currentTarget.style.background = 'none'; e.currentTarget.style.color = 'var(--sidebar-text-muted)' }}
          >
            <LogOut size={15} /> {t('agentNav.logout')}
          </button>
        </div>
      </aside>

      {/* Main */}
      <main className="main-content" id="main-content">
        <AnimatePresence mode="wait">
          {tab === 'tickets'       && (
            <AgentDashboardView
              key="tickets"
              openTicketNumero={deepLinkTicket}
              onTicketOpened={onDeepLinkConsumed}
            />
          )}
          {tab === 'notifications' && <AgentNotificationsView key="notifs" onCountChange={setNotifCount} />}
          {tab === 'profile'       && <AgentProfileView key="profile" />}
          {tab === 'settings'      && <SettingsView key="settings" />}
        </AnimatePresence>
      </main>
    </div>
  )
}
