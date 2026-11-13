"""Lancement du navigateur Playwright : Edge si present (Windows), sinon Chromium embarque.

Aucune technique de masquage de l'automatisation n'est utilisee (volontairement).
"""
from __future__ import annotations

import logging
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page, sync_playwright

log = logging.getLogger("konzinfo.browser")

CHANNELS: tuple[str | None, ...] = ("msedge", "chrome", None)
VIEWPORT = {"width": 1280, "height": 960}
DEFAULT_TIMEOUT_MS = 30_000


@contextmanager
def open_browser(*, headless: bool, user_data_dir: Path | None = None, locale: str = "en-GB",
                 record_har: Path | None = None, trace: Path | None = None,
                 channels: tuple[str | None, ...] = CHANNELS) -> Iterator[Page]:
    """Ouvre une page prete a l'emploi et ferme tout proprement a la sortie."""
    with sync_playwright() as p:
        context = None
        browser = None
        last_exc: Exception | None = None
        for channel in channels:
            try:
                ctx_kwargs = dict(locale=locale, viewport=VIEWPORT)
                if record_har is not None:
                    record_har.parent.mkdir(parents=True, exist_ok=True)
                    ctx_kwargs["record_har_path"] = str(record_har)
                if user_data_dir is not None:
                    user_data_dir.mkdir(parents=True, exist_ok=True)
                    context = p.chromium.launch_persistent_context(
                        str(user_data_dir), channel=channel, headless=headless, **ctx_kwargs)
                else:
                    browser = p.chromium.launch(channel=channel, headless=headless)
                    context = browser.new_context(**ctx_kwargs)
                log.info("navigateur lance (channel=%s, headless=%s)", channel or "chromium", headless)
                break
            except PlaywrightError as exc:
                last_exc = exc
                log.info("canal %s indisponible : %s", channel or "chromium", str(exc).splitlines()[0])
                if browser is not None:
                    browser.close()
                    browser = None
        if context is None:
            raise RuntimeError("Impossible de lancer un navigateur (Edge/Chrome/Chromium)") from last_exc

        if trace is not None:
            trace.parent.mkdir(parents=True, exist_ok=True)
            context.tracing.start(screenshots=True, snapshots=True, sources=False)

        page = context.pages[0] if context.pages else context.new_page()
        page.set_default_timeout(DEFAULT_TIMEOUT_MS)
        try:
            yield page
        finally:
            if trace is not None:
                try:
                    context.tracing.stop(path=str(trace))
                except PlaywrightError as exc:  # pragma: no cover
                    log.debug("trace non sauvegardee : %s", exc)
            try:
                context.close()  # ecrit aussi le HAR
            except PlaywrightError as exc:  # pragma: no cover
                log.debug("fermeture contexte : %s", exc)
            if browser is not None:
                try:
                    browser.close()
                except PlaywrightError:  # pragma: no cover
                    pass
