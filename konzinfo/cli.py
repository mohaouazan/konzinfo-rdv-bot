"""Point d'entree : python -m konzinfo <commande> [options]."""
from __future__ import annotations

import argparse
import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from konzinfo import __version__
from konzinfo.config import ConfigError, load_config


def setup_logging(logs_dir: Path, verbose: bool) -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except Exception:  # noqa: BLE001
        pass
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s", "%H:%M:%S")
    root = logging.getLogger()
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    root.handlers.clear()
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)
    root.addHandler(console)
    try:
        logs_dir.mkdir(parents=True, exist_ok=True)
        fileh = RotatingFileHandler(logs_dir / "konzinfo.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8")
        fileh.setFormatter(fmt)
        root.addHandler(fileh)
    except OSError:
        pass
    logging.getLogger("urllib3").setLevel(logging.WARNING)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="konzinfo",
                                description="Surveillance et reservation semi-automatique de rendez-vous "
                                            "sur konzinfobooking.mfa.gov.hu")
    p.add_argument("--config", help="fichier YAML (defaut : config.yaml, sinon config.watch.yaml)")
    p.add_argument("--root", default=".", help="dossier du projet (state/, screenshots/, logs/)")
    p.add_argument("-v", "--verbose", action="store_true", help="logs detailles")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="cmd", required=True)

    w = sub.add_parser("watch", help="surveille la disponibilite et alerte sur Telegram (ne reserve jamais)")
    w.add_argument("--once", action="store_true", help="une seule verification puis sortie (GitHub Actions)")
    w.add_argument("--show", action="store_true", help="navigateur visible (defaut : headless)")
    w.add_argument("--no-deep", action="store_true", help="ne lister que les jours, pas les horaires")
    w.add_argument("--notify-always", action="store_true", help="envoyer un message meme sans creneau (test)")

    b = sub.add_parser("book", help="reservation semi-automatique dans un navigateur visible")
    b.add_argument("--loop", action="store_true", help="reessayer jusqu'a trouver un creneau")
    b.add_argument("--dry-run", action="store_true", help="remplir l'etape 1 puis s'arreter (aucun creneau touche)")
    b.add_argument("--force", action="store_true", help="ignorer le marqueur state/BOOKED")
    b.add_argument("--headless", action="store_true", help="(tests) navigateur invisible")

    d = sub.add_parser("discover", help="exporte le DOM du site dans discovery/ (maintenance des selecteurs)")
    d.add_argument("--show", action="store_true", help="navigateur visible")

    sub.add_parser("notify-test", help="envoie un message Telegram de test")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = Path(args.root).resolve()
    setup_logging(root / "logs", args.verbose)
    log = logging.getLogger("konzinfo")
    try:
        cfg = load_config(args.config, root=root, require_person=args.cmd in ("book", "watch"))
    except ConfigError as exc:
        log.error("configuration invalide : %s", exc)
        return 2

    try:
        if args.cmd == "notify-test":
            from konzinfo.notify import Notifier

            notifier = Notifier(cfg.telegram.token, cfg.telegram.chat_id, beep=cfg.human.beep)
            if not notifier.enabled:
                log.error("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID absents du .env")
                return 1
            ok = notifier.send(f"✅ konzinfo-rdv-bot v{__version__} : notifications Telegram operationnelles.", beep=True)
            log.info("envoi Telegram : %s", "OK" if ok else "ECHEC")
            return 0 if ok else 1

        if args.cmd == "discover":
            from konzinfo.browser import open_browser
            from konzinfo.discover import run_discovery

            out = cfg.discovery_dir
            with open_browser(headless=not args.show, record_har=out / "session.har", trace=out / "trace.zip") as page:
                run_discovery(page, out, cfg.site_url)
            log.info("exports ecrits dans %s", out)
            return 0

        if args.cmd == "watch":
            from konzinfo import watcher

            result = watcher.run(cfg, once=args.once, headless=not args.show, deep=not args.no_deep,
                                 notify_always=args.notify_always)
            return 1 if result.get("error") else 0

        if args.cmd == "book":
            from konzinfo import booker

            return booker.run(cfg, loop=args.loop, headless=args.headless, dry_run=args.dry_run, force=args.force)
    except KeyboardInterrupt:
        log.info("arret demande par l'utilisateur")
        return 130
    return 0
