"""Shared Jinja2 template rendering — avoids Starlette Jinja2Templates version conflict."""

from pathlib import Path
from fastapi.responses import HTMLResponse
from jinja2 import Environment, FileSystemLoader, select_autoescape

_TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"

jinja_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATE_DIR)),
    autoescape=select_autoescape(["html"]),
)


def render(request, template_name: str, **kwargs) -> HTMLResponse:
    """Render a Jinja2 template with the request in context."""
    tmpl = jinja_env.get_template(template_name)
    content = tmpl.render(request=request, **kwargs)
    return HTMLResponse(content)
