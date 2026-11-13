# konzinfo-rdv-bot

Surveillance et **réservation semi-automatique** de rendez-vous consulaires hongrois sur
<https://konzinfobooking.mfa.gov.hu/> (Konzinfo Booking, Ministère hongrois des Affaires étrangères).

- `watch` : vérifie régulièrement s'il existe des créneaux pour un consulat / type de demande et **alerte sur Telegram**
  (tourne sur GitHub Actions toutes les 5 min, ou en local).
- `book` : sur ton PC, dans un **navigateur visible**, remplit le formulaire avec tes données, choisit le premier créneau
  conforme, passe à l'étape « Validate »… puis **s'arrête** : c'est **toi** qui saisis le code reçu par e-mail et qui
  cliques « Complete booking ». Le script ne finalise jamais une réservation à ta place.

> Usage strictement personnel : une seule réservation, pour la personne configurée. Aucun contournement de captcha,
> aucun masquage de l'automatisation, interrogation du site à intervalle raisonnable (≥ 3 min). Une fois le RDV réservé,
> le script refuse de repartir (`state/BOOKED`) sauf `--force`.

## Prérequis

- Windows 10/11 (Edge installé) — ou Linux/macOS avec Chromium Playwright.
- Python 3.12, Git.
- Un bot Telegram : parle à [@BotFather](https://t.me/BotFather) → `/newbot` → récupère le **token**. Envoie un message
  à ton bot, puis ouvre `https://api.telegram.org/bot<TOKEN>/getUpdates` pour lire ton **chat_id**.

## Installation

```bash
git clone <ton-depot> konzinfo-rdv-bot
cd konzinfo-rdv-bot
pip install -r requirements.txt
python -m playwright install chromium        # facultatif sous Windows : Edge est utilisé s'il est présent
copy config.example.yaml config.yaml         # puis remplir (données personnelles) — fichier gitignoré
copy .env.example .env                       # puis remplir TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID — gitignoré
python -m konzinfo notify-test               # doit afficher un message dans Telegram
```

## Configuration (`config.yaml`)

| Clé | Rôle |
|---|---|
| `booking.consulate` | Sous-chaîne du libellé dans « Select location », ex. `Morocco - Rabat` |
| `booking.applications` | Sous-chaîne(s) des cases de la modal « Applications », ex. `Schengen` |
| `booking.applicants` | Nombre de personnes |
| `booking.person.*` | Nom (comme sur le passeport), date de naissance `AAAA-MM-JJ`, téléphone international, e-mail, n° de passeport |
| `booking.extra_fields` | Autres champs éventuels `{ "Libellé exact": "valeur" }` |
| `slots.earliest / latest / weekdays / hours` | Filtres de créneaux (`null` = n'importe lequel, le plus tôt possible) |
| `polling.*` | Intervalle, aléa, re-alerte, plafond du backoff, fréquence max des alertes d'erreur, battement de cœur (`heartbeat_hours`, 0 = désactivé) |
| `human.confirm_timeout_minutes` | Temps laissé pour saisir le code e-mail et cliquer « Complete booking » |

L'e-mail configuré reçoit le **code de validation** (étape « Validate ») et la **confirmation** : garde cette boîte
ouverte (spams compris) pendant que `book` tourne.

## Commandes

```bash
python -m konzinfo watch                 # surveillance locale en boucle (headless), alertes Telegram
python -m konzinfo watch --once --show   # une vérification, navigateur visible
python -m konzinfo book --dry-run        # remplit l'étape 1 et s'arrête (vérifie les données)
python -m konzinfo book --loop           # cherche un créneau en boucle, puis attend TON clic final
python -m konzinfo discover              # exporte le DOM dans discovery/ (maintenance des sélecteurs)
python -m konzinfo -v <commande>         # logs détaillés (aussi dans logs/konzinfo.log)
```

Déroulé de `book` quand un créneau existe : capture d'écran + message Telegram + bip → tu ouvres la boîte e-mail,
recopies le code, cliques « Complete booking » → le script détecte la confirmation, l'enregistre dans `state/BOOKED`
et t'envoie la capture. Si le créneau est perdu entre-temps, il relance la recherche ; si rien n'est confirmé dans le
délai, il te prévient et **laisse le navigateur ouvert**.

## GitHub Actions (surveillance cloud)

Le workflow `.github/workflows/watch.yml` lance `watch --once` toutes les 5 min avec `config.watch.yaml`
(sans donnée personnelle versionnée). Le site exige un formulaire **valide** avant d'interroger les créneaux : les
données sont donc fournies par des **secrets** du dépôt (Settings → Secrets and variables → Actions) :

`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `KONZINFO_PERSON_NAME`, `KONZINFO_PERSON_BIRTH_DATE`,
`KONZINFO_PERSON_PHONE`, `KONZINFO_PERSON_EMAIL`, `KONZINFO_PERSON_PASSPORT` — plus `CALLMEBOT_USER` (et
`CALLMEBOT_LANG`) si l'appel vocal est activé (voir plus bas).

Limites : le cron GitHub est indicatif (souvent en retard), l'IP des runners peut être bloquée par le site, et le
navigateur y est forcément invisible — la réservation elle-même se fait toujours depuis ton PC.

Cadence et quota : le cron est réglé au minimum GitHub (5 min). Sur un dépôt **privé**, le forfait gratuit
(2 000 min/mois, ~2 min par run) ne tiendrait que quelques jours : le dépôt est donc **public** (minutes illimitées)
et ne contient aucune donnée personnelle. GitHub désactive automatiquement les crons d'un dépôt public après
**60 jours sans activité** (aucun commit) : pousse un petit changement de temps en temps, ou ré-active le workflow dans
l'onglet Actions. Pour qu'un arrêt ne passe pas inaperçu, le surveillant envoie un **battement de cœur** Telegram
(« Surveillance active ») au plus une fois par jour (`polling.heartbeat_hours`) : plus aucun message pendant plus
d'un jour signifie que la surveillance est arrêtée.

## Appel vocal (optionnel)

Un bot Telegram ne peut pas téléphoner. Pour être réveillé quand un créneau apparaît, le script peut déclencher en plus
un **appel vocal Telegram** via le service tiers gratuit [CallMeBot](https://www.callmebot.com/telegram-call-api/) :
ton téléphone sonne comme pour un appel Telegram et une voix lit le message en français.

1. Dans Telegram, ouvre **@CallMeBot_txtbot** et envoie `/start` (autorisation, une seule fois). Vérifie dans
   Réglages → Confidentialité → Appels que les appels sont autorisés.
2. Dans `.env` : `CALLMEBOT_USER=@ton_username` (ou ton numéro international), éventuellement `CALLMEBOT_LANG`
   (`fr-FR-Standard-F` voix féminine, `fr-FR-Standard-G` masculine) et `CALLMEBOT_REPEAT` (nombre de lectures, 1 à 5).
3. `python -m konzinfo notify-test --call` : le téléphone doit sonner dans la minute.
4. Pour la surveillance cloud : secrets `CALLMEBOT_USER` (et `CALLMEBOT_LANG` si besoin) dans le dépôt.

Appels déclenchés : créneaux détectés, créneau sélectionné (code à saisir), délai de confirmation dépassé, captcha,
erreurs et blocages. Jamais pour le battement de cœur ni les simples vérifications. Chaque appel suit une alerte déjà
limitée en fréquence (re-alerte, erreurs), donc pas de rafale. Le message Telegram est toujours envoyé ; l'appel est un
complément « meilleur effort » : CallMeBot est un service non officiel, en file d'attente partagée (retard possible),
appel de 30 s, texte lu limité à 256 caractères, et seul ton @username lui est transmis (aucune donnée du dossier).
Quand le service est saturé (réponse « FLOOD ») ou refuse deux appels en moins de 65 s, le script réessaie jusqu'à
3 fois à 70 s d'intervalle ; au-delà, il abandonne l'appel (le message Telegram, lui, est déjà parti).

Android : règle la discussion avec ton bot sur un son fort et, dans les paramètres Android de notification de cette
discussion, coche « Ignorer Ne pas déranger » ; autorise aussi les appels Telegram en mode Ne pas déranger.

## Comment ça marche (technique)

Le site est une application **Blazor WebAssembly** : tout est rendu côté client, d'où Playwright (Edge/Chromium).
Étapes automatisées : modal consulat (`#modal2`) → modal types de demande (`#modalCases`) → champs
(`#label4` nom, Duet `#birthDateComponent` date de naissance au format `JJ/MM/AAAA`, `#label9` téléphone,
`#label10` e-mail, « Re-enter the email address », `#label1000` passeport, cases `#slabel13` / `#label13`) → bouton
« Select date » » (appels `CheckPhoneNumber` puis `CheckAvailableBookingTimes`) → bannière « no appointments » ou
étape 2 (calendrier Duet `#idoszakComponent`, créneaux `div.box.free`) → « Continue to validation ».
Tous les sélecteurs sont centralisés dans `konzinfo/selectors.py`.

Le site embarque reCAPTCHA v3 (invisible) et un widget hCaptcha : s'il s'affiche, le script te le signale et attend.

## Dépannage

- `configuration invalide` → compare `config.yaml` avec `config.example.yaml`.
- `Consulat … introuvable` / `Type de demande … introuvable` → le message liste les libellés disponibles ; ajuste la config.
- `Etape 2 non atteinte` → une capture est écrite dans `screenshots/` ; le site a peut-être changé : lance `discover`.
- `Le site indique que l'adresse IP est bloquee` → attends, augmente `polling.interval_minutes`.
- Rien sur Telegram → `python -m konzinfo notify-test`, vérifie `.env`.

## Structure

```
konzinfo/        cli.py (commandes) · config.py · browser.py · site.py (étape 1) · dates.py (étape 2)
                 slots.py (filtres) · watcher.py · booker.py · notify.py (Telegram) · state.py · selectors.py
tests/           pytest (config, créneaux, notifications, politique d'alerte)
.github/         workflows/watch.yml
config.example.yaml · config.watch.yaml · .env.example
```
