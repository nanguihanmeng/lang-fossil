"""自包含 HTML 报告（数据/视图分离，v1.1 结论）.

默认形态：单个 HTML 文件，规范 JSON 内嵌在
``<script type="application/json">`` 块中；汇总表格由 Jinja2 在服务端
渲染，内嵌 JSON 保持独立可导出（供 ``diff`` 与归档）。``--no-embed``
写外壳页加同级 ``report.json``（仅限 http 预览——``file://`` 读取本地
JSON 会被浏览器 CORS 拦截）.
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
    r"""把 JSON 载荷渲染为 ``<script>`` 数据块安全的内容.

    script 内容是原始文本：HTML autoescape 会破坏 JSON（引号变
    ``&#34;``）且浏览器不做实体解码，因此在中和唯一危险序列——``<`` 变
    ``\u003c``（JSON 解析后语义等价，但无法闭合 script 元素）——后标记
    为安全.
    """
    escaped = json.dumps(payload, ensure_ascii=False).replace("<", "\\u003c")
    return Markup(escaped)  # noqa: S704 - 构造上安全，见 docstring


def _js_string(value: str) -> Markup:
    r"""把字符串渲染为 ``<script>`` 内安全的 JS/JSON 字符串字面量.

    ``"`` 做 JSON 转义、``<`` 被中和，值不可能终止 script 元素.
    """
    escaped = json.dumps(value, ensure_ascii=False).replace("<", "\\u003c")
    return Markup(escaped)  # noqa: S704 - 构造上安全，见 docstring


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
    """创建开启 autoescape 的 Jinja2 环境.

    Returns:
        配置好的 Jinja2 环境.
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
    """把 HTML 报告写入磁盘.

    Args:
        scan_result: 原始扫描产物.
        report: 聚合的地层报告.
        root: 扫描根目录.
        output: 输出文件路径.
        embed_data: False 时写外壳页加同级 ``<stem>.json`` 数据文件，
            而非自包含页面.

    Returns:
        写入的 HTML 路径.
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
