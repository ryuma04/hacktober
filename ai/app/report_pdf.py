"""PDF version of the Dependency Exit Capsule (rendered from capsule.json with fpdf2)."""
from __future__ import annotations

from pathlib import Path

from fpdf import FPDF
from fpdf.enums import XPos, YPos

from . import risk
from .capsule import ai_disclosure, model_label, strip_number

INK = (23, 21, 31)
MUTED = (90, 88, 112)
LEVEL_RGB = {"critical": (214, 69, 69), "high": (242, 165, 139), "medium": (249, 213, 110),
             "low": (168, 204, 244), "none": (185, 228, 161)}
REPLACE = {"→": "->", "←": "<-", "—": "-", "–": "-", "…": "...", "·": "-", "✓": "yes", "✗": "no", "✅": "yes",
           "❌": "no", "≥": ">=", "≤": "<=", "“": '"', "”": '"', "‘": "'", "’": "'", "•": "-", "×": "x", " ": " "}


def clean(text) -> str:
    """Core PDF fonts are Latin-1: map common symbols, drop the rest (never crash on a character)."""
    s = "" if text is None else str(text)
    for a, b in REPLACE.items():
        s = s.replace(a, b)
    return s.encode("latin-1", "replace").decode("latin-1").replace("?", "?")


class Report(FPDF):
    def __init__(self, title: str):
        super().__init__(format="A4")
        self.doc_title = title
        self.set_auto_page_break(auto=True, margin=16)
        self.set_margins(15, 15, 15)
        self.alias_nb_pages()

    def header(self):
        if self.page_no() == 1:
            return
        self.set_font("Helvetica", "B", 8)
        self.set_text_color(*MUTED)
        self.cell(0, 5, clean(f"DepExit - Dependency Exit Capsule - {self.doc_title}"), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.ln(2)

    def footer(self):
        self.set_y(-12)
        self.set_font("Helvetica", "", 8)
        self.set_text_color(*MUTED)
        self.cell(0, 6, f"Page {self.page_no()}/{{nb}}", align="C")

    # --- building blocks ---
    def h1(self, text):
        self.set_font("Helvetica", "B", 18)
        self.set_text_color(*INK)
        self.multi_cell(0, 8, clean(text), align="L", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.ln(1)

    def h2(self, text, level: str | None = None):
        self.ln(3)
        if self.get_y() > 250:
            self.add_page()
        if level:
            self.set_fill_color(*LEVEL_RGB.get(level, (230, 230, 230)))
            self.rect(self.l_margin, self.get_y() + 1, 3, 6, style="F")
            self.set_x(self.l_margin + 5)
        self.set_font("Helvetica", "B", 13)
        self.set_text_color(*INK)
        self.multi_cell(0, 8, clean(text), new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    def h3(self, text):
        self.ln(1)
        self.set_font("Helvetica", "B", 10)
        self.set_text_color(*INK)
        self.cell(0, 6, clean(text), new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    def para(self, text, size=9, color=INK, style=""):
        self.set_font("Helvetica", style, size)
        self.set_text_color(*color)
        self.multi_cell(0, 4.6, clean(text), align="L", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    def bullets(self, items, size=9, mono=False):
        for it in items:
            self.set_font("Courier" if mono else "Helvetica", "", size - (1 if mono else 0))
            self.set_text_color(*INK)
            self.set_x(self.l_margin + 3)
            self.multi_cell(0, 4.6, clean(f"- {it}"), align="L", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    def grid(self, headers, rows, widths, fills=None, size=8):
        self.set_fill_color(255, 255, 255)
        self.set_font("Helvetica", "", size)
        self.set_text_color(*INK)
        with FPDF.table(self, col_widths=widths, text_align="LEFT", line_height=4.4, padding=1.2,
                        headings_style=None, first_row_as_headings=False) as t:
            hr = t.row()
            self.set_font("Helvetica", "B", size)
            for h in headers:
                hr.cell(clean(h), style=_style((243, 241, 236)))
            self.set_font("Helvetica", "", size)
            for i, r in enumerate(rows):
                row = t.row()
                for j, v in enumerate(r):
                    fill = fills[i][j] if fills and fills[i] and fills[i][j] else None
                    row.cell(clean(v), style=_style(fill if fill else (255, 255, 255)))


def _style(rgb):
    from fpdf.fonts import FontFace
    return FontFace(fill_color=rgb)


def build(capsule: dict, out: Path) -> Path:
    c = capsule
    s, t, a = c["summary"], c["target"], c["ai"]
    scan_only = t.get("verification") == "scan_only"
    repo = t.get("repo_url", "").replace("https://github.com/", "")
    pdf = Report(repo)
    pdf.add_page()

    # cover block
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_text_color(*MUTED)
    pdf.cell(0, 5, "DEPEXIT - DEPENDENCY EXIT CAPSULE", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.h1(repo or "Repository")
    eco = t.get("ecosystem", "python")
    runtime = f"Python {t.get('python_version')}" if eco == "python" else f"{eco} (scan-only)"
    pdf.para(f"Commit {t.get('commit', '')[:12]} - {runtime} - generated {c['generated_at']} - capsule {c['capsule_id']}",
             size=8, color=MUTED)
    pdf.ln(2)
    verdict_rgb = {"safe_to_migrate": (185, 228, 161), "migrate_with_care": (249, 213, 110), "blocked": (242, 165, 139)}
    pdf.set_fill_color(*verdict_rgb.get(s["verdict"], (230, 230, 230)))
    pdf.set_font("Helvetica", "B", 11)
    pdf.set_text_color(*INK)
    pdf.cell(0, 9, clean(f"  Verdict: {s['verdict'].replace('_', ' ').upper()}"), fill=True,
             new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(1)
    pdf.para(s["headline"], size=10)
    pdf.ln(2)

    tests_b = "not run (scan-only)" if scan_only else f"{s['baseline']['passed']}/{s['baseline']['total']} ({s['baseline']['status']})"
    tests_m = "not run (scan-only)" if scan_only else f"{s['migrated']['passed']}/{s['migrated']['total']} ({s['migrated']['status']})"
    gaps = "n/a" if scan_only else f"{s['gaps']['fixed']} / {s['gaps']['regressed']} / {s['gaps']['still_failing']}"
    pdf.grid(["Dependencies", "At risk", "Tests: original deps", "Tests: migrated", "Gaps fixed / regressed / failing"],
              [[s["dependencies_total"], s["at_risk"], tests_b, tests_m, gaps]], [24, 18, 40, 40, 58])

    # dependency overview
    pdf.h2("Dependencies")
    rows, fills = [], []
    for d in c["dependencies"]:
        r = d.get("replacement") or {}
        m = d.get("migration") or {}
        pin = d.get("pinned_version") or ("undeclared" if not d["declared"] else "unpinned")
        applied = "proposed" if m.get("proposed_only") else ("yes" if m.get("applied") else ("no" if m else "-"))
        rows.append([d["name"], f"{pin} -> {d.get('latest_version') or '?'}", f"{d['risk']['level']} ({d['risk']['score']})",
                     f"{r.get('strategy', '-')} {r.get('package') or ''} {r.get('version_spec') or ''}".strip(), applied])
        fills.append([None, None, LEVEL_RGB.get(d["risk"]["level"]), None, None])
    pdf.grid(["Dependency", "Version", "Risk", "Proposal", "Applied"], rows, [40, 36, 24, 62, 18], fills)

    # per at-risk dependency
    for d in c["dependencies"]:
        if not risk.at_risk(d["risk"]["level"]) and not d["compatibility_gaps"]:
            continue
        r, m = d.get("replacement") or {}, d.get("migration") or {}
        pdf.h2(f"{d['name']} - {d['risk']['level']} risk ({d['risk']['score']}/100)", d["risk"]["level"])
        decl = ", ".join(f"{x['file']}:{x['line']} ({x['spec']})" for x in d["declared"]) or "not declared"
        pdf.para(f"Installed {d.get('pinned_version') or '-'} - latest {d.get('latest_version') or '?'}"
                 f" ({d.get('latest_release_date') or 'date unknown'}) - declared in {decl}", size=8, color=MUTED)
        pdf.h3("Risk indicators")
        tag = f" [{model_label(r.get('model'))}]" if d["risk"].get("rationale_provenance") == "ai" else " [computed]"
        pdf.para(d["risk"]["rationale"] + tag)
        pdf.bullets([f"{i['code']} ({i['severity']}): {i['detail']} - evidence: "
                     + ", ".join(e.get("ref") or e.get("url") or e.get("detail") or e["source"] for e in i["evidence"][:3])
                     for i in d["risk"]["indicators"]], size=8)
        pdf.h3("Usage locations")
        locs = d["usage"]["locations"]
        pdf.bullets([f"{l['file']}:{l['line']} [{l['kind']}] {l['code']}" for l in locs[:15]] or ["not imported anywhere"],
                    mono=True)
        if len(locs) > 15:
            pdf.para(f"... and {len(locs) - 15} more locations (see capsule.json)", size=8, color=MUTED)
        br = d.get("blast_radius")
        if br:
            stt = br["stats"]
            pdf.h3("Blast radius")
            pdf.para(f"{stt['lines']} line(s) in {stt['direct_files']} file(s) use it directly; {stt['indirect_files']} more "
                     f"module(s) import those; {stt['test_files']} of {stt['total_test_files']} test file(s) reach it.")
            chains = [f"{x['file']} via {' -> '.join(x['via'][1:])}" for x in (br["indirect"] + br["tests"])[:6]]
            if chains:
                pdf.bullets(chains, size=8)
        pdf.h3("Proposed replacement")
        who = model_label(r.get("model")) if r.get("provenance") == "ai" else "computed fallback"
        pdf.para(f"{r.get('strategy', '-')} {r.get('package') or ''} {r.get('version_spec') or ''} "
                 f"(confidence {r.get('confidence', '-')}, by {who})", style="B")
        if r.get("rationale"):
            pdf.para(r["rationale"])
        if r.get("alternatives"):
            pdf.bullets([f"rejected {x['package']}: {x['reason_rejected']}" for x in r["alternatives"]], size=8)
        if m.get("steps"):
            pdf.h3("Migration steps")
            pdf.bullets([f"{n}. {strip_number(st)}" for n, st in enumerate(m["steps"], 1)], size=8)
            if m.get("proposed_only"):
                pdf.para("Proposed only - not applied (scan-only).", size=8, color=MUTED)
            else:
                pdf.para(f"Applied: {'yes' if m.get('applied') else 'no - ' + str(m.get('not_applied_reason'))}"
                         + (f" - files: {', '.join(m.get('files_changed', []))}" if m.get("files_changed") else ""),
                         size=8, color=MUTED)
        if d["suggested_tests"]:
            pdf.h3("Suggested tests")
            pdf.bullets([f"{x['name']}: {x['purpose']}" for x in d["suggested_tests"]], size=8)
        pdf.h3("Executed test results")
        tr = d.get("test_results") or {}
        pdf.para("Not run (scan-only)." if scan_only else
                 f"{tr.get('status', '-')} - affected tests: {', '.join(tr.get('affected_tests', [])) or 'none identified'}", size=8)
        if d["compatibility_gaps"]:
            pdf.h3("Compatibility gaps")
            pdf.bullets([f"{g['test_id'] or 'install'}: {g['baseline']} -> {g['migrated']} ({g['change']}, {g['severity']}): "
                         f"{g['explanation']}" for g in d["compatibility_gaps"]], size=8)
        if d["open_concerns"]:
            pdf.h3("Open concerns")
            pdf.bullets([x["text"] for x in d["open_concerns"]], size=8)

    # runs, limitations, disclosure
    pdf.h2("Test runs (Docker sandbox)")
    if scan_only or not c["runs"]:
        pdf.para("Not run: scan-only analysis (no migration, no sandbox)." if scan_only else "No sandbox runs.", size=9)
    else:
        pdf.grid(["Run", "Status", "Passed", "Failed", "Errors", "Skipped", "Duration"],
                  [[x["id"], x["status"], x["totals"]["passed"], x["totals"]["failed"], x["totals"]["errors"],
                    x["totals"]["skipped"], f"{x['duration_s']}s"] for x in c["runs"]], [28, 34, 20, 20, 20, 20, 38])
        p = c["patch"]
        pdf.para(f"Patch: {p.get('files_changed')} files changed, +{p.get('insertions')} / -{p.get('deletions')} lines.", size=8, color=MUTED)
    pdf.h2("Limitations")
    pdf.bullets(c["limitations"], size=8)
    pdf.h2("AI disclosure")
    pdf.para(ai_disclosure(a), size=8)

    out.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(out))
    return out
