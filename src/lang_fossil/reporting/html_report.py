"""Self-contained HTML report (data/view separation, v1.1 verdict).

Default shape: a single HTML file with the canonical JSON embedded in a
``<script type="application/json">`` block; the summary tables are rendered
server-side via Jinja2, and the embedded JSON stays independently
exportable for ``diff`` and archival. ``--no-embed`` writes a shell page
plus a sibling ``report.json`` (http preview only — ``file://`` fetch of
local JSON is blocked by browser CORS policy).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jinja2 import Environment, select_autoescape
from markupsafe import Markup

from lang_fossil.core.models import ScanResult
from lang_fossil.core.stratigraphy import StratigraphyReport
from lang_fossil.reporting.json_report import build_document


def _script_json(payload: Any) -> Markup:
    r"""Render a JSON payload safe for a ``<script>`` data block.

    Script contents are raw text: HTML autoescape would corrupt the JSON
    (quotes become ``&#34;``) and the browser does not decode entities there,
    so the payload is marked safe after neutralising the only dangerous
    sequence — ``<``, which becomes ``\u003c`` (semantically identical after
    JSON parsing but unable to close the script element).
    """
    escaped = json.dumps(payload, ensure_ascii=False).replace("<", "\\u003c")
    return Markup(escaped)  # noqa: S704 - safe by construction, see docstring


def _js_string(value: str) -> Markup:
    r"""Render a string as a safe JS/JSON string literal for ``<script>``.

    ``"`` is JSON-escaped and ``<`` is neutralised, so the value cannot
    terminate the script element.
    """
    escaped = json.dumps(value, ensure_ascii=False).replace("<", "\\u003c")
    return Markup(escaped)  # noqa: S704 - safe by construction, see docstring


_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>lang-fossil report</title>
<style>
  :root { color-scheme: light dark; }
  body { font-family: system-ui, sans-serif; margin: 2rem auto; max-width: 60rem; padding: 0 1rem; }
  h1 { border-bottom: 2px solid #8b5a2b; }
  .metrics { display: flex; gap: 1rem; flex-wrap: wrap; margin: 1rem 0; }
  .metric { border: 1px solid #ccc3; border-radius: 8px; padding: .6rem 1rem; min-width: 8rem; }
  .metric b { display: block; font-size: 1.4rem; }
  table { border-collapse: collapse; width: 100%; margin: 1rem 0; }
  th, td { border: 1px solid #ccc3; padding: .3rem .6rem; text-align: left; }
  .bar { background: #8b5a2b; height: .8rem; border-radius: 4px; min-width: 2px; }
  .sev-error { color: #c0392b; font-weight: 600; }
  .sev-warning { color: #b9770e; }
  .sev-info { color: #2471a3; }
</style>
</head>
<body>
<h1>&#9878; lang-fossil &mdash; Stratigraphy Report</h1>
<p>Root: <code>{{ root }}</code></p>
<div class="metrics">
  <div class="metric"><b>{{ summary.total_fossils }}</b>fossils</div>
  <div class="metric"><b>{{ summary.unsafe_count }}</b>unsafe findings</div>
  <div class="metric"><b>{{ "%.2f"|format(summary.fossil_index) }}</b>fossil index / kLOC</div>
  <div class="metric"><b>{{ summary.scanned_files }}</b>files scanned</div>
  <div class="metric"><b>{{ summary.clone_count }}</b>clone matches</div>
  <div class="metric"><b>{{ summary.active_fossils }}</b>active legacy fossils</div>
</div>
<h2>Era strata</h2>
<table>
  <tr><th>Era</th><th>Fossils</th><th>Top modules</th></tr>
  {% for era in eras %}
  <tr>
    <td>{{ era.era }}</td>
    <td>{{ era.fossil_count }}</td>
    <td>{% for name, count in era.top_modules %}
      <code>{{ name }}</code> ({{ count }})
    {% endfor %}</td>
  </tr>
  {% endfor %}
</table>
<h2>Fossils ({{ fossils | length }})</h2>
<table>
  <tr>
    <th>Rule</th><th>Where</th><th>Severity</th><th>Last commit</th>
    <th>Message</th><th>Provenance</th>
  </tr>
  {% for fossil in fossils %}
  <tr>
    <td><code>{{ fossil.rule_id }}</code></td>
    <td><code>{{ fossil.path }}:{{ fossil.line }}</code></td>
    <td class="sev-{{ fossil.severity }}">{{ fossil.severity }}</td>
    <td>
      {{ fossil.last_commit_year if fossil.last_commit_year is not none else "n/a" }}
    </td>
    <td>{{ fossil.message }}</td>
    <td>{{ fossil.provenance }}</td>
  </tr>
  {% endfor %}
</table>
<script type="application/json" id="lf-data">{{ embedded_json }}</script>
</body>
</html>
"""

_SHELL_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><title>lang-fossil report (shell)</title></head>
<body>
<h1>lang-fossil report (shell mode)</h1>
<p>Data file: <a href="{{ data_href }}">{{ data_href }}</a></p>
<p>This page requires an HTTP server (file:// fetch of local JSON is CORS-blocked):
<code>python -m http.server</code></p>
<script>
const href = {{ data_href_js }};
fetch(href).then(r => r.json()).then(data => {
  const pre = document.createElement("pre");
  pre.textContent = JSON.stringify(data.summary, null, 2);
  document.body.appendChild(pre);
});
</script>
</body>
</html>
"""


def _environment() -> Environment:
    """Create the Jinja2 environment with autoescaping enabled.

    Returns:
        A configured Jinja2 environment.
    """
    return Environment(autoescape=select_autoescape(["html"]), trim_blocks=True)


def write_report(
    scan_result: ScanResult,
    report: StratigraphyReport,
    root: Path,
    output: Path,
    *,
    embed_data: bool = True,
) -> Path:
    """Write the HTML report to disk.

    Args:
        scan_result: Raw scan outcome.
        report: Aggregated stratigraphy report.
        root: Scan root directory.
        output: Output file path.
        embed_data: When False, write a shell page plus sibling
            ``<stem>.json`` data file instead of a self-contained page.

    Returns:
        The written HTML path.
    """
    document = build_document(scan_result, report, root)
    output.parent.mkdir(parents=True, exist_ok=True)
    env = _environment()
    if embed_data:
        template = env.from_string(_TEMPLATE)
        rendered = template.render(
            root=str(root),
            summary=document["summary"],
            eras=document["stratigraphy"]["eras"],
            fossils=document["fossils"],
            embedded_json=_script_json(document),
        )
    else:
        data_path = output.with_suffix(".json")
        data_path.write_text(json.dumps(document, indent=2, ensure_ascii=False), encoding="utf-8")
        template = env.from_string(_SHELL_TEMPLATE)
        rendered = template.render(
            data_href=data_path.name, data_href_js=_js_string(data_path.name)
        )
    output.write_text(rendered, encoding="utf-8")
    return output
