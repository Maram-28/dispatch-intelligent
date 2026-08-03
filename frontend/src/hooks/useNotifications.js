import { useState, useRef, useCallback } from 'react'
import { useLanguage } from './useLanguage'

/**
 * Encapsule les 3 canaux d'alerte : son, toast in-page, notification système.
 * Chaque canal est indépendant : l'échec de l'un n'impacte pas les autres.
 * Toutes les fonctions retournées sont mémoïsées (useCallback) pour avoir une
 * référence stable — App.jsx en dépend directement dans le tableau de
 * dépendances de son effet SSE, sans quoi la connexion se rouvrirait à
 * chaque render.
 */
export function useNotifications() {
  const { t } = useLanguage()
  const [toasts, setToasts] = useState([])
  const audioRef = useRef(null)
  const notifPermRef = useRef('default')

  /** À appeler sur le premier geste utilisateur (ex: clic Connexion) pour contourner l'autoplay policy. */
  const armAudio = useCallback(() => {
    if (audioRef.current) return
    try {
      const audio = new Audio('/notification-sound.wav')
      audio.load()
      audioRef.current = audio
    } catch { /* ignore */ }
  }, [])

  /** À appeler après login (sur geste) pour demander la permission de notification système. */
  const requestNotifPermission = useCallback(async () => {
    if (!('Notification' in window)) return
    try {
      const result = await Notification.requestPermission()
      notifPermRef.current = result
    } catch { /* non supporté sur ce navigateur */ }
  }, [])

  const removeToast = useCallback((id) => {
    setToasts(prev => prev.filter(t => t.id !== id))
  }, [])

  /**
   * Déclenche les 3 alertes pour un événement SSE reçu.
   * Filtre silencieusement tout ce qui n'est pas type === "assignment".
   */
  const triggerNotification = useCallback((event) => {
    if (!event || event.type !== 'assignment') return

    const titre = event.ticket_numero || t('notifications.newTicket')
    const message = event.message || t('notifications.newTicketAssigned')

    // Canal 1 — Son
    try {
      if (audioRef.current) {
        audioRef.current.currentTime = 0
        audioRef.current.play().catch(() => {})
      }
    } catch { /* ignore */ }

    // Canal 2 — Toast in-page (auto-dismiss 5 s)
    const id = `toast-${Date.now()}-${Math.random().toString(36).slice(2)}`
    setToasts(prev => [...prev, { id, titre, message }])
    setTimeout(() => setToasts(prev => prev.filter(t => t.id !== id)), 5000)

    // Canal 3 — Notification système
    try {
      if (notifPermRef.current === 'granted') {
        new Notification(titre, { body: message })
      }
    } catch { /* ignore */ }
  }, [t])

  return { toasts, removeToast, triggerNotification, armAudio, requestNotifPermission }
}
