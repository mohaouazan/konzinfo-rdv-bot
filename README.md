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
- Cadence : `.github/workflows/watch.yml` (cron `*/5`, minimum GitHub ; l'horaire est indicatif, souvent en retard).

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
