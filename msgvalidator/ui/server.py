"""Local web UI: tiny HTTP server on 127.0.0.1 + the system browser. No external dependencies."""
from __future__ import annotations

import json
import os
import uuid
import threading
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .. import __version__
from ..profiles.loader import available
from ..report import html as html_report
from ..validate import DEFAULT_PROFILES, validate
from ..xmlval.kosit import BUILTIN as RULES
from .. import i18n
from .docs_page import DOCS, DOCS_PAGE
from . import samples_page
from ..samples import render as render_sample
from .mapper_page import MAPPER_PAGE
from . import theme
from .page import PAGE
from ..resources import data_path

MAX_UPLOAD = 50 * 1024 * 1024


class Handler(BaseHTTPRequestHandler):
    server_version = f"MsgValidator/{__version__}"

    def log_message(self, fmt, *args):  # keep the console quiet
        pass

    def _send(self, code, body: str | bytes, ctype="text/html; charset=utf-8", extra=None):
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    @property
    def lang(self) -> str:
        """UI language from the 'mv-lang' cookie (header toggle), else X-Lang, else Czech."""
        for part in (self.headers.get("Cookie") or "").split(";"):
            k, _, v = part.strip().partition("=")
            if k == "mv-lang":
                return i18n.norm(v)
        return i18n.norm(self.headers.get("X-Lang"))

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path.startswith("/assets/"):
            name = path.rsplit("/", 1)[1]
            if name in ASSETS:
                return self._send(200, data_path("ui", name).read_bytes(), ASSETS[name],
                                  extra={"Cache-Control": "max-age=86400"})
            return self._send(404, "not found", "text/plain")
        if path == "/favicon.ico":
            return self._send(200, FAVICON, "image/svg+xml", extra={"Cache-Control": "max-age=86400"})
        if path == "/mapper":
            return self._send(200, _page(MAPPER_PAGE, "mapper", self.lang))
        if path == "/docs":
            page = DOCS_PAGE.replace("__DOCS__", DOCS[self.lang]).replace(
                "__TITLE__", "Documentation" if self.lang == "en" else "Dokumentace")
            return self._send(200, _page(page, "docs", self.lang, translate=False))
        if path == "/samples":
            page = DOCS_PAGE.replace("__DOCS__", samples_page.body(self.lang)).replace(
                "__TITLE__", "Samples" if self.lang == "en" else "Vzory")
            return self._send(200, _page(page, "samples", self.lang, translate=False))
        if path == "/api/sample":
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            try:
                data, fname = render_sample(q.get("type", ["invoice"])[0], q.get("fmt", ["ubl"])[0])
            except ValueError as ex:
                return self._send(400, str(ex), "text/plain; charset=utf-8")
            ctype = "application/pdf" if fname.endswith(".pdf") else "application/xml"
            return self._send(200, data, ctype, extra={"Content-Disposition": f'attachment; filename="{fname}"'})
        if path in ("/", "/index.html"):
            return self._send(200, _page(PAGE, "check", self.lang))
        self._send(404, "not found", "text/plain")

    def do_POST(self):
        if self.headers.get("Origin") not in (None, f"http://{self.headers.get('Host')}"):
            return self._send(403, "forbidden", "text/plain")
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_UPLOAD:
            return self._send(413, "Soubor je příliš velký.", "text/plain; charset=utf-8")
        data = self.rfile.read(length)
        if self.path.startswith("/api/mapper/"):
            return self._mapper(self.path.rsplit("/", 1)[1], data)
        name = urllib.parse.unquote(self.headers.get("X-Filename") or "soubor")
        profiles = [p for p in (self.headers.get("X-Profiles") or "").split(",") if p] or None
        try:
            rep = validate(data, name, profiles)
            i18n.localize(rep, self.lang)
        except Exception as ex:  # show the error instead of a dead page
            import traceback
            return self._send(500, f"Chyba při zpracování: {ex}\n\n{traceback.format_exc()}", "text/plain; charset=utf-8")
        if self.path == "/api/validate":
            fam = rep.detection.family
            mappable = fam == "XML" or (fam == "SAP-IDOC" and rep.detection.supported)
            mapped = next((m.label.split("mapování klienta ", 1)[1] for m in rep.messages if "mapování klienta " in m.label), "")
            return self._send(200, html_report.body(rep, self.lang), extra={
                "X-Mappable": "1" if mappable else "0", "X-Family": fam, "X-Client": urllib.parse.quote(mapped)})
        if self.path == "/api/report":
            fn = urllib.parse.quote(f"report_{name}.html")
            return self._send(200, html_report.render(rep, self.lang),
                              extra={"Content-Disposition": f"attachment; filename*=UTF-8''{fn}"})
        if self.path == "/api/embedded":
            if rep.embedded_xml is None:
                return self._send(404, "Soubor neobsahuje vložené ani převedené XML.", "text/plain; charset=utf-8")
            return self._send(200, rep.embedded_xml, "application/xml")
        if self.path == "/api/ubl":
            xml = next((m.virtual_xml for m in rep.messages if m.virtual_xml), None)
            if xml is None:
                return self._send(404, "Pro tento soubor se virtuální UBL negeneruje.", "text/plain; charset=utf-8")
            return self._send(200, xml, "application/xml")
        if self.path in ("/api/print", "/api/pdf"):
            from ..report import printout
            page = printout.for_report(rep, self.lang)
            if page is None:
                return self._send(404, "Z tohoto souboru nelze sestavit fakturu (chybí sémantický model).", "text/plain; charset=utf-8")
            if self.path == "/api/print":
                return self._send(200, page)
            try:
                return self._send(200, printout.to_pdf(page), "application/pdf")
            except Exception as ex:  # no browser: the UI falls back to the print dialog
                return self._send(501, str(ex), "text/plain; charset=utf-8")
        if self.path == "/api/json":
            return self._send(200, json.dumps(html_report.to_dict(rep), ensure_ascii=False, indent=1),
                              "application/json; charset=utf-8")
        self._send(404, "not found", "text/plain")


    def _json(self, obj, code=200):
        if isinstance(obj, dict) and obj.get("error"):
            obj = {**obj, "error": i18n.tr(obj["error"], self.lang)}
        return self._send(code, json.dumps(obj, ensure_ascii=False), "application/json; charset=utf-8")

    def _mapper(self, action: str, data: bytes):
        """Mapping editor API. 'open' takes the raw file, the others JSON {token, client, profiles, ...}."""
        from ..idoc import editor
        from ..idoc import mapping as idoc_mapping
        from .. import settings
        try:
            if action == "stash":  # main page -> editor: keep the file, the editor opens it by token
                token = uuid.uuid4().hex
                SAMPLES[token] = data
                while len(SAMPLES) > 20:
                    SAMPLES.pop(next(iter(SAMPLES)))
                return self._json({"token": token})
            if action == "open":
                profiles = [p for p in (self.headers.get("X-Profiles") or "").split(",") if p] or DEFAULT_PROFILES
                token = self.headers.get("X-Token") or ""
                if token in SAMPLES and not data:
                    data = SAMPLES[token]
                else:
                    token = uuid.uuid4().hex
                    SAMPLES[token] = data
                while len(SAMPLES) > 20:
                    SAMPLES.pop(next(iter(SAMPLES)))
                out = editor.open_file(data, profiles, self.lang)
                out["token"] = token
                out["file"] = urllib.parse.unquote(self.headers.get("X-Filename") or "soubor")
                return self._json(out)
            req = json.loads(data.decode("utf-8") or "{}")
            if action == "settings":
                if req.get("mapping_dir"):
                    settings.save({"mapping_dir": req["mapping_dir"]})
                return self._json({"mapping_dir": str(settings.mapping_dir()), "clients": _clients()})
            if action == "client":
                c = idoc_mapping.get_client(req["id"])
                if c is None:
                    return self._json({"error": "Mapování nenalezeno."}, 404)
                return self._json({k: c.get(k) for k in ("id", "name", "note", "match", "terms", "groups", "aux")})
            if action == "save":
                path = idoc_mapping.save_client(req["client"], author=os.environ.get("USERNAME"))
                return self._json({"path": path, "id": idoc_mapping.slug(req["client"].get("id") or req["client"]["name"]),
                                   "clients": _clients()})
            sample = SAMPLES.get(req.get("token"))
            if sample is None:
                return self._json({"error": "Vzorek už není v paměti – nahrajte soubor znovu."}, 410)
            if action == "preview":
                return self._json(editor.preview(sample, req.get("client") or {}, req.get("profiles") or DEFAULT_PROFILES,
                                                 lang=self.lang,
                                                 rules=bool(req.get("rules"))))
        except Exception as ex:  # show the error in the editor instead of a dead page
            import traceback
            return self._json({"error": f"{ex}", "trace": traceback.format_exc()}, 500)
        return self._json({"error": "neznámá akce"}, 404)


SAMPLES: dict[str, bytes] = {}
FAVICON = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><rect width="32" height="32" fill="#0d101c"/>'
           '<rect x="9" y="9" width="14" height="14" fill="#0f40f7"/></svg>')
ASSETS = {"Figtree-VariableFont.ttf": "font/ttf", "grit-logo-white.svg": "image/svg+xml",
          "grit-logo-dark.svg": "image/svg+xml"}


def _page(tpl: str, active: str, lang: str = "cs", translate: bool = True) -> str:
    repl = {"__THEME_INIT__": theme.THEME_INIT, "__FONT__": theme.FONT, "__HEADER_CSS__": theme.HEADER_CSS,
            "__HEADER__": theme.header(active, __version__, lang), "__THEME_JS__": theme.THEME_JS, "__LANG__": lang,
            "__FAMILY__": theme.FAMILY, "__CSS__": html_report.CSS, "__VERSION__": __version__,
            "__PROFILES__": json.dumps(available(), ensure_ascii=False), "__DEFAULTS__": json.dumps(DEFAULT_PROFILES),
            "__RULES__": json.dumps(RULES, ensure_ascii=False)}
    for k, v in repl.items():
        tpl = tpl.replace(k, v)
    if lang == "en":
        tpl = tpl.replace('<html lang="cs">', '<html lang="en">')
        if translate:
            return i18n.tr(tpl, lang)
        # docs are written in English already – translate only the shared header
        head = theme.header(active, __version__, lang)
        return tpl.replace(head, i18n.tr(head, lang)).replace(theme.THEME_JS, i18n.tr(theme.THEME_JS, lang))
    return tpl


def _clients():
    from ..idoc import mapping as idoc_mapping
    return [{"id": c["id"], "name": c.get("name"), "match": c.get("match"), "file": c.get("file"), "error": c.get("error")}
            for c in idoc_mapping.clients()]


def serve(port: int = 0, open_browser: bool = True) -> None:
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{httpd.server_address[1]}/"
    print(f"MsgValidator {__version__} běží na {url}")
    print("Okno nechte otevřené; ukončení Ctrl+C nebo zavřením okna.")
    from .. import splash
    splash.close()
    if open_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
