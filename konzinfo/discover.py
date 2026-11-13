"""Decouverte du DOM : charge le site, attend le rendu Blazor, exporte inventaire + HTML + captures.

N'effectue aucune reservation. Sert a figer les selecteurs de selectors.py.
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path

from playwright.sync_api import Page

log = logging.getLogger("konzinfo.discover")

JS_INVENTORY = r"""
() => {
  const txt = e => (e ? (e.innerText || e.textContent || '') : '').trim().replace(/\s+/g, ' ').slice(0, 160);
  const vis = e => !!(e.offsetWidth || e.offsetHeight || e.getClientRects().length);
  const labelFor = el => {
    if (el.id) { const l = document.querySelector('label[for="' + CSS.escape(el.id) + '"]'); if (l) return txt(l); }
    const p = el.closest('label'); return p ? txt(p) : null;
  };
  return {
    title: document.title,
    selects: [...document.querySelectorAll('select')].map(s => ({id: s.id, name: s.name, multiple: s.multiple,
      cls: s.className, visible: vis(s), options: [...s.options].map(o => ({value: o.value, text: txt(o)}))})),
    inputs: [...document.querySelectorAll('input,textarea')].map(i => ({id: i.id, type: i.type, name: i.name,
      placeholder: i.placeholder, cls: i.className, label: labelFor(i), visible: vis(i), value: i.value})),
    buttons: [...document.querySelectorAll('button,a.btn,[role=button]')].map(b => ({id: b.id, cls: b.className,
      text: txt(b), disabled: !!b.disabled, visible: vis(b), dataTarget: b.getAttribute('data-target')})),
    duet: [...document.querySelectorAll('duet-date-picker')].map(d => ({id: d.id, identifier: d.identifier,
      value: d.value, cls: d.className, name: d.getAttribute('name')})),
    modals: [...document.querySelectorAll('.modal')].map(m => ({id: m.id, cls: m.className,
      title: txt(m.querySelector('.modal-title')), visible: vis(m)})),
    bootstrapSelect: [...document.querySelectorAll('.bootstrap-select')].map(b => ({cls: b.className,
      button: txt(b.querySelector('button')), selectId: (b.querySelector('select') || {}).id})),
    tabs: [...document.querySelectorAll('[role=tab], .nav-link, nav a')].map(t => ({id: t.id, cls: t.className, text: txt(t)})),
    captcha: {recaptchaScript: !!document.querySelector('script[src*="recaptcha"]'),
              hcaptcha: !!document.querySelector('.h-captcha, iframe[src*="hcaptcha"]')},
    blazorError: vis(document.querySelector('#blazor-error-ui') || {offsetWidth: 0, getClientRects: () => []}),
    bodyText: txt(document.body).slice(0, 4000),
  };
}
"""


def wait_blazor(page: Page, timeout_ms: int = 90_000) -> None:
    """Attend la fin du chargement WebAssembly : un <select> ou le texte d'accueil apparait."""
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        if page.locator("select").count() > 0:
            return
        if page.get_by_text("I wish to book an appointment").count() > 0:
            return
        if page.locator("#blazor-error-ui").is_visible():
            raise RuntimeError("Blazor a leve une erreur non geree au chargement")
        page.wait_for_timeout(500)
    raise TimeoutError("Le site ne s'est pas charge (WebAssembly) dans le delai imparti")


def dump(page: Page, out_dir: Path, name: str) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{name}.html").write_text(page.content(), encoding="utf-8")
    page.screenshot(path=str(out_dir / f"{name}.png"), full_page=True)
    inv = page.evaluate(JS_INVENTORY)
    (out_dir / f"{name}.json").write_text(json.dumps(inv, indent=2, ensure_ascii=False), encoding="utf-8")
    log.info("dump %s : %d selects, %d inputs, %d boutons, %d duet, %d modals", name,
             len(inv["selects"]), len(inv["inputs"]), len(inv["buttons"]), len(inv["duet"]), len(inv["modals"]))
    return inv


def run_discovery(page: Page, out_dir: Path, site_url: str, consulate: str | None = None) -> dict:
    page.goto(site_url, wait_until="domcontentloaded")
    wait_blazor(page)
    page.wait_for_timeout(1500)
    inv = dump(page, out_dir, "01_loaded")
    if consulate:
        for sel in inv["selects"]:
            match = [o for o in sel["options"] if consulate.lower() in o["text"].lower()]
            if match and sel["id"]:
                log.info("consulat %r trouve dans select #%s -> option %r", consulate, sel["id"], match[0]["text"])
                page.select_option(f"#{sel['id']}", value=match[0]["value"])
                page.wait_for_timeout(3000)
                inv = dump(page, out_dir, "02_consulate")
                break
        else:
            log.warning("consulat %r introuvable dans les selects", consulate)
    return inv
