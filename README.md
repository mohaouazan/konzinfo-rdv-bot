# konzinfo-rdv-bot

Surveille **toutes les 5 minutes** les créneaux de rendez-vous du consulat de Hongrie à Rabat (visa Schengen) sur
<https://konzinfobooking.mfa.gov.hu/> et **prévient sur Telegram** dès qu'il y en a. Tourne sur GitHub Actions, sans PC.
Un seul fichier : `check.py`.

## Comment ça marche

Le site n'affiche les disponibilités qu'après un formulaire rempli. `check.py` ouvre donc le site dans un navigateur
Chromium invisible, choisit « Morocco - Rabat » et « Visa application (Schengen visa- type 'C') », remplit le formulaire
avec des **valeurs factices fixes** (aucune donnée personnelle), clique « Select date » et lit la réponse :

- bannière « no appointments available » → rien ;
- calendrier affiché → message Telegram 🎯 avec capture d'écran, puis rappel toutes les 60 min tant que ça dure ;
- ℹ️ quand les créneaux disparaissent ; ⚠️ en cas d'erreur (au plus une fois toutes les 3 h) ;
- 💓 « surveillance active » une fois par jour : plus aucun message pendant plus d'un jour = la surveillance est arrêtée.

Le script **ne réserve rien** : dès l'alerte, la réservation se fait à la main sur le site.

## Réglages

- Secrets GitHub (Settings → Secrets and variables → Actions) : `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`
  (bot créé via @BotFather ; chat_id lu via `https://api.telegram.org/bot<TOKEN>/getUpdates` après un message au bot).
- Autre consulat / démarche : variables d'environnement `KONZINFO_CONSULATE`, `KONZINFO_APPLICATION` (sous-chaînes des
  libellés du site), ou les constantes en haut de `check.py`.
- Cadence : voir « Déclenchement » ci-dessous.

## Déclenchement (toutes les 3 minutes)

Le cron intégré de GitHub Actions n'est pas fiable pour une cadence serrée : sur ce dépôt, il n'a lancé que 2 exécutions en
10 heures au lieu de 120. Le déclenchement « manuel » (`workflow_dispatch`), lui, démarre en quelques secondes. La vérification
est donc déclenchée **de l'extérieur** par le service gratuit [cron-job.org](https://cron-job.org/), qui appelle toutes les
3 minutes l'API GitHub :

```
POST https://api.github.com/repos/mohaouazan/konzinfo-rdv-bot/actions/workflows/watch.yml/dispatches
Authorization: Bearer <jeton GitHub fine-grained, limité à ce dépôt, permission Actions : lecture/écriture>
Accept: application/vnd.github+json
X-GitHub-Api-Version: 2022-11-28
corps : {"ref":"main"}
```

- Le cron GitHub reste en **roue de secours** (toutes les 15 min, s'il daigne tourner) ; le groupe `concurrency` du workflow
  empêche deux vérifications de se chevaucher.
- Le jeton expire au bout de **365 jours** : cron-job.org enverra des e-mails d'échec, puis désactivera la tâche après 25 échecs.
  Pour renouveler : nouveau jeton sur https://github.com/settings/personal-access-tokens, puis le remplacer dans l'en-tête
  `Authorization` de la tâche cron-job.org. Le jeton se révoque à tout moment au même endroit.
- Changer la cadence = modifier la tâche cron-job.org (minutes d'exécution), rien à toucher dans le dépôt.

## Lancer à la main

```bash
pip install -r requirements.txt
python -m playwright install chromium
# TELEGRAM_BOT_TOKEN et TELEGRAM_CHAT_ID dans l'environnement ou dans un fichier .env (non versionné)
python check.py
```

## À savoir

- GitHub désactive le cron d'un dépôt public après **60 jours sans commit** : pousser un petit changement de temps en
  temps, ou ré-activer dans l'onglet Actions (« Enable workflow »).
- Le dépôt est public (minutes Actions illimitées) et ne contient aucune donnée personnelle.
- Le site peut bloquer une adresse IP trop insistante : le script le détecte et le signale sur Telegram.
