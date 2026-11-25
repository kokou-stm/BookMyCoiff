# Déploiement sur Azure (GitHub Actions)

Chaque push sur `master` lance les tests puis déploie sur Azure App Service.
Les pull requests lancent seulement les tests.
Workflow : [.github/workflows/azure-deploy.yml](.github/workflows/azure-deploy.yml).

```
GitHub Actions ── tests, check --deploy, collectstatic ──► release.zip ──► Azure App Service (Linux, Python 3.14)
                                                                          ├─ gunicorn (startup.sh, migrations au démarrage)
                                                                          ├─ Azure Database for PostgreSQL  (données)
                                                                          └─ Azure Blob Storage             (photos des salons)
```

La mise en place ci-dessous se fait **une seule fois**, avec [Azure CLI](https://learn.microsoft.com/cli/azure/) (`az login` d'abord).

## 1. Variables

Choisissez vos noms. Ceux de l'application web, du serveur PostgreSQL et du compte de stockage doivent être uniques dans tout Azure.

```bash
RG=bookmycoiff-rg
LOC=francecentral              # région la plus proche de vos utilisateurs
APP=bookmycoiff                # → https://bookmycoiff.azurewebsites.net
PLAN=bookmycoiff-plan
PG=bookmycoiff-db
PG_USER=bmcadmin
PG_PASSWORD='un-mot-de-passe-long-sans-caracteres-speciaux-url'   # lettres, chiffres, - et _ seulement
ST=bookmycoiffmedia            # minuscules et chiffres, 3 à 24 caractères
GITHUB_REPO=kokou-stm/BookMyCoiff
SUB=$(az account show --query id -o tsv)
```

## 2. Ressources Azure

```bash
az group create -n $RG -l $LOC

# Application web (B1 ≈ 13 $/mois ; F1 gratuit possible pour tester, mais lent et sans « Always On »)
az appservice plan create -g $RG -n $PLAN --is-linux --sku B1
az webapp create -g $RG -p $PLAN -n $APP --runtime "PYTHON:3.14"
az webapp config set -g $RG -n $APP --startup-file "bash startup.sh"
az webapp update -g $RG -n $APP --https-only true

# Base PostgreSQL (Burstable B1ms ≈ 15 $/mois). 0.0.0.0 = accès autorisé depuis les services Azure.
az postgres flexible-server create -g $RG -n $PG -l $LOC \
  --tier Burstable --sku-name Standard_B1ms --storage-size 32 --version 16 \
  --admin-user $PG_USER --admin-password "$PG_PASSWORD" --public-access 0.0.0.0
az postgres flexible-server db create -g $RG --server-name $PG --database-name bookmycoiff

# Stockage des photos (conteneur privé : le site génère des liens signés)
az storage account create -g $RG -n $ST -l $LOC --sku Standard_LRS --min-tls-version TLS1_2
ST_CONN=$(az storage account show-connection-string -g $RG -n $ST -o tsv)
az storage container create -n media --connection-string "$ST_CONN"
```

## 3. Paramètres de l'application

Les secrets sont stockés dans Azure. Ils ne sont jamais dans le code ni dans GitHub.

```bash
az webapp config appsettings set -g $RG -n $APP --settings \
  SCM_DO_BUILD_DURING_DEPLOYMENT=true \
  DISABLE_COLLECTSTATIC=true \
  DJANGO_SECRET_KEY="$(python3 -c 'import secrets; print(secrets.token_urlsafe(50))')" \
  DATABASE_URL="postgres://$PG_USER:$PG_PASSWORD@$PG.postgres.database.azure.com:5432/bookmycoiff?sslmode=require" \
  AZURE_STORAGE_CONNECTION_STRING="$ST_CONN" \
  DJANGO_SUPERUSER_USERNAME=admin \
  DJANGO_SUPERUSER_EMAIL=vous@example.com \
  DJANGO_SUPERUSER_PASSWORD='choisissez-un-mot-de-passe-admin'
```

Après le premier déploiement réussi, l'administrateur existe. Supprimez alors son mot de passe des paramètres :

```bash
az webapp config appsettings delete -g $RG -n $APP --setting-names DJANGO_SUPERUSER_PASSWORD
```

## 4. Connexion GitHub → Azure (sans mot de passe, OpenID Connect)

```bash
APP_ID=$(az ad app create --display-name bookmycoiff-github --query appId -o tsv)
az ad sp create --id $APP_ID
az role assignment create --assignee $APP_ID --role "Website Contributor" \
  --scope /subscriptions/$SUB/resourceGroups/$RG/providers/Microsoft.Web/sites/$APP
az ad app federated-credential create --id $APP_ID --parameters "{
  \"name\": \"github-production\",
  \"issuer\": \"https://token.actions.githubusercontent.com\",
  \"subject\": \"repo:${GITHUB_REPO}:environment:production\",
  \"audiences\": [\"api://AzureADTokenExchange\"]
}"
echo "AZURE_CLIENT_ID=$APP_ID"; echo "AZURE_TENANT_ID=$(az account show --query tenantId -o tsv)"; echo "AZURE_SUBSCRIPTION_ID=$SUB"
```

> GitHub peut présenter un sujet avec les identifiants numériques du compte et du dépôt,
> par ex. `repo:kokou-stm@187449235/BookMyCoiff@1445335457:environment:production`.
> Si la connexion échoue avec `AADSTS700213: No matching federated identity record`, ajoutez un second identifiant
> fédéré avec **exactement** le sujet affiché dans l'erreur (même commande, autre `name`).

Puis dans GitHub, ouvrez **Settings → Secrets and variables → Actions** :

| Type | Nom | Valeur |
|---|---|---|
| Secret | `AZURE_CLIENT_ID` | affiché ci-dessus |
| Secret | `AZURE_TENANT_ID` | affiché ci-dessus |
| Secret | `AZURE_SUBSCRIPTION_ID` | affiché ci-dessus |
| Variable | `AZURE_WEBAPP_NAME` | `bookmycoiff` (valeur de `$APP`) |

L'environnement GitHub `production` est créé automatiquement au premier déploiement.
Dans **Settings → Environments → production**, vous pouvez exiger une validation manuelle avant chaque mise en ligne.

## 5. Déployer

Poussez sur `master`, ou lancez le workflow à la main depuis l'onglet **Actions** (*Run workflow*).
Le site est en ligne sur `https://<APP>.azurewebsites.net`, et l'admin sur `/admin/`.

- Journaux en direct : `az webapp log tail -g $RG -n $APP`
- Commandes Django sur le serveur : `az webapp ssh -g $RG -n $APP`, puis `python manage.py seed_demo` par exemple (données de démo). Si Django est introuvable, activez d'abord l'environnement : `source /tmp/*/antenv/bin/activate`, puis placez-vous dans le dossier de l'app avec `cd /tmp/*/`.

## Variables d'environnement reconnues

| Variable | Rôle |
|---|---|
| `DJANGO_SECRET_KEY` | **Obligatoire** en production |
| `DATABASE_URL` | **Obligatoire** en production (PostgreSQL) |
| `AZURE_STORAGE_CONNECTION_STRING` | Stockage des photos (fortement conseillé : le disque de l'app est effacé à chaque déploiement) |
| `AZURE_MEDIA_CONTAINER` | Conteneur des photos (défaut `media`) |
| `DJANGO_ALLOWED_HOSTS` | Domaines personnalisés, séparés par des virgules (le domaine `*.azurewebsites.net` est ajouté automatiquement) |
| `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `DEFAULT_FROM_EMAIL` | Envoi d'e-mails (SMTP), pour plus tard |
| `GUNICORN_WORKERS` | Nombre de processus (défaut 2) |
| `DJANGO_HSTS_SECONDS` | Durée HSTS (défaut 3600 ; passez à 31536000 une fois le domaine définitif en place) |
| `DJANGO_DEBUG` | Ne jamais mettre à `true` en production |

En local, rien ne change : `python manage.py runserver` utilise SQLite et le mode développement.
