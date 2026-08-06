import { UserManager, WebStorageStateStore } from 'oidc-client-ts'

export const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8000'

const KEYCLOAK_URL = import.meta.env.VITE_KEYCLOAK_URL || 'http://localhost:8180'
const KEYCLOAK_REALM = 'lvmh-tickets'
const KEYCLOAK_CLIENT_ID = 'ticket-dispatch-frontend'

// Instance partagée : App.jsx (bootstrap de session, callback OIDC, logout) et
// apiFetch (ci-dessous) doivent utiliser exactement le même UserManager pour
// partager l'état de session (access token courant, renouvellement silencieux).
export const userManager = new UserManager({
  authority: `${KEYCLOAK_URL}/realms/${KEYCLOAK_REALM}`,
  client_id: KEYCLOAK_CLIENT_ID,
  redirect_uri: `${window.location.origin}/`,
  post_logout_redirect_uri: `${window.location.origin}/`,
  response_type: 'code',
  scope: 'openid',
  userStore: new WebStorageStateStore({ store: window.localStorage }),
  automaticSilentRenew: true,
  useRefreshToken: true,
})

// Délais AVANT chaque nouvelle tentative (backoff croissant) — 1 essai immédiat
// + ces 3 retries = 4 sondes au total avant d'abandonner.
const KEYCLOAK_PING_RETRY_DELAYS_MS = [2000, 4000, 8000]

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

// Sonde légère et sans effet de bord sur le document de découverte OIDC de
// Keycloak, AVANT tout appel à signinRedirect(). But : absorber la course de
// démarrage propre à ce stack de dev (infra/keycloak/, Keycloak 26 sur JVM via
// Docker Compose) — le conteneur peut être "up" plusieurs secondes avant que
// son port HTTP n'accepte réellement des connexions. signinRedirect()
// (oidc-client-ts) fait ce même fetch en interne (voir createSigninRequest →
// MetadataService) avant de rediriger le navigateur — donc un échec ici ne
// redirige jamais vers une page cassée, il empêche seulement l'appel — mais
// répéter signinRedirect() directement répéterait aussi la génération PKCE/
// nonce/state à chaque tentative pour rien : on sonde juste l'URL ici.
// Réutilise `userManager.settings.metadataUrl` (calculé par oidc-client-ts,
// voir OidcClientSettingsStore) plutôt que de reconstruire l'URL à la main,
// pour ne jamais diverger de ce que signinRedirect() ira réellement fetch.
export const waitForKeycloak = async () => {
  for (let attempt = 0; ; attempt++) {
    try {
      const res = await fetch(userManager.settings.metadataUrl, { cache: 'no-store' })
      if (!res.ok) throw new Error(`Keycloak discovery HTTP ${res.status}`)
      return
    } catch (err) {
      if (attempt >= KEYCLOAK_PING_RETRY_DELAYS_MS.length) throw err
      await sleep(KEYCLOAK_PING_RETRY_DELAYS_MS[attempt])
    }
  }
}

const getAccessToken = async () => {
  const user = await userManager.getUser()
  return user && !user.expired ? user.access_token : null
}

export const apiFetch = async (path, options = {}) => {
  const token = await getAccessToken()
  const isFormData = options.body instanceof FormData
  const headers = {
    ...(isFormData ? {} : { 'Content-Type': 'application/json' }),
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...(options.headers || {}),
  }

  const doFetch = (h) => fetch(`${API_BASE}${path}`, { ...options, headers: h })

  let res = await doFetch(headers)
  if (res.status !== 401) return res

  // Le token a pu expirer entre la lecture ci-dessus et la requête (course
  // bénigne) — une tentative de renouvellement silencieux avant d'abandonner
  // et de renvoyer l'utilisateur au login, plutôt que de recharger la page
  // immédiatement comme le faisait l'ancienne implémentation JWT maison.
  try {
    const refreshed = await userManager.signinSilent()
    const retryHeaders = { ...headers, Authorization: `Bearer ${refreshed.access_token}` }
    res = await doFetch(retryHeaders)
    if (res.status !== 401) return res
  } catch {
    // signinSilent a échoué (session Keycloak elle-même expirée) — redirection ci-dessous
  }

  await userManager.signinRedirect()
  return null
}
