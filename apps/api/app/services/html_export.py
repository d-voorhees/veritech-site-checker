from pathlib import Path

from bs4 import BeautifulSoup
from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.schemas.report import ReportOut

_TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"
_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATE_DIR)),
    autoescape=select_autoescape(["html", "jinja"]),
)


def render_report_html(report: ReportOut, *, for_email: bool = False) -> str:
    """Renders the report page. `for_email=True` drops the client-side
    date-localization <script> tag — email clients strip or flag inline
    scripts (Gmail/SpamAssassin treat it as a dangerous element), and it
    doesn't run in an inbox anyway, so the UTC-formatted fallback text is
    used as-is instead.
    """
    template = _env.get_template("report.html.jinja")
    return template.render(report=report, for_email=for_email)


def render_report_text(html: str) -> str:
    """Plain-text fallback for the report email. Spam filters (and mail-tester)
    penalize HTML-only messages missing a text/plain MIME part, so this
    strips the rendered report down to readable text for that alternative.
    """
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    text = soup.get_text(separator="\n")
    lines = [line.strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)
