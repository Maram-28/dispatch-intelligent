# Keycloak — realm `lvmh-tickets`

Stack de développement local pour l'authentification OIDC du projet Ticket Dispatch. Ce n'est
**pas** une configuration de production (pas de TLS, `start-dev`, mot de passe admin en clair dans
`infra/.env`).

## Démarrer

```powershell
cd infra
copy .env.example .env
# éditer .env : mots de passe admin/DB

docker compose up -d
```

Console admin : http://localhost:8180 (identifiants = `KEYCLOAK_ADMIN` / `KEYCLOAK_ADMIN_PASSWORD`
définis dans `infra/.env`). Le realm `lvmh-tickets` est importé automatiquement au premier
démarrage depuis `import/lvmh-tickets-realm.json` (grâce à `--import-realm`) — il ne réimporte pas
si le realm existe déjà en base.

## Thème de connexion personnalisé

`themes/lvmh-dispatch/login/` surcharge `keycloak.v2` (fond marine, bouton doré, logo "LVMH
Dispatch", locale française) plutôt que de dupliquer tout le template — voir
`themes/lvmh-dispatch/login/resources/css/custom.css`. Monté dans le conteneur via
`docker-compose.yml` (`./keycloak/themes/lvmh-dispatch:/opt/keycloak/themes/lvmh-dispatch`), activé
sur le realm via `loginTheme` (déjà dans `import/lvmh-tickets-realm.json`).

Le cache de thème est désactivé (`KC_SPI_THEME_CACHE_THEMES=false`, etc.) : modifier `custom.css`
et recharger la page de login suffit, **sauf** pour ajouter un tout nouveau fichier `theme.properties`
(un thème inédit n'est découvert qu'au démarrage — `docker compose restart keycloak` dans ce cas).

**Piège constaté** : l'API admin de Keycloak assainit l'attribut `style=` inline dans
`realm.displayNameHtml` et retire silencieusement certaines propriétés (ex. `display: flex`,
`align-items`) sans erreur — d'où le choix de classes CSS (`.lvmh-brand`, `.lvmh-brand-badge`
définies dans `custom.css`) plutôt que du style inline pour tout élément avec une mise en page non
triviale.

## Après le premier démarrage

Le fichier realm ne contient pas de secret client committé en clair. Après le premier import :

1. Console admin → realm `lvmh-tickets` → **Clients** → `ticket-dispatch-backend` → onglet
   **Credentials** → copier le **Client secret** généré automatiquement par Keycloak.
2. Le coller dans `Ticket-Classifier--main - Copie/.env` sous `KEYCLOAK_BACKEND_CLIENT_SECRET`.

Aucune action requise pour `ticket-dispatch-frontend` (client public, pas de secret — Authorization
Code + PKCE).

## Créer les utilisateurs

Les comptes utilisateurs ne sont **pas** dans le realm export (pour rester reproductible/idempotent
sans données de test figées). Utiliser `scripts/migrate_users_to_keycloak.py` (voir le backend) pour
créer les comptes à partir de `data/processed/users.json`, ou créer manuellement via
**Users → Add user** + onglet **Role mapping** (`admin` ou `agent`).

## Reconstituer le realm après une modification manuelle

Si vous ajustez la configuration à la main dans la console admin (nouveau redirect URI, rôle
supplémentaire, etc.), ré-exportez le realm pour que `lvmh-tickets-realm.json` reste la source de
vérité versionnée — sinon le changement disparaît au prochain `docker compose down -v` :

```powershell
docker compose exec keycloak /opt/keycloak/bin/kc.sh export `
  --realm lvmh-tickets --file /tmp/lvmh-tickets-realm.json --users skip
docker compose cp keycloak:/tmp/lvmh-tickets-realm.json ./keycloak/import/lvmh-tickets-realm.json
```

`--users skip` évite d'exporter les comptes utilisateurs réels (identifiants/hashes) dans un fichier
versionné — seule la structure du realm (clients, rôles, réglages) doit être committée.

## Vérification manuelle du flow Authorization Code + PKCE

1. Ouvrir dans un navigateur (remplacer `<verifier>`/`<challenge>` par une paire PKCE générée, ex.
   via https://example-app.com/pkce ou un petit script) :
   ```
   http://localhost:8180/realms/lvmh-tickets/protocol/openid-connect/auth
     ?client_id=ticket-dispatch-frontend
     &response_type=code
     &scope=openid
     &redirect_uri=http://localhost:5173/
     &code_challenge=<challenge>
     &code_challenge_method=S256
   ```
2. Se connecter avec un utilisateur de test, récupérer le paramètre `code` dans l'URL de redirection.
3. Échanger le code :
   ```bash
   curl -X POST http://localhost:8180/realms/lvmh-tickets/protocol/openid-connect/token \
     -d grant_type=authorization_code \
     -d client_id=ticket-dispatch-frontend \
     -d redirect_uri=http://localhost:5173/ \
     -d code=<code> \
     -d code_verifier=<verifier>
   ```
4. Décoder l'`access_token` reçu (ex. sur jwt.io) et vérifier : `preferred_username` = username
   Keycloak, `realm_access.roles` contient `admin` ou `agent`, `azp` = `ticket-dispatch-frontend`.
