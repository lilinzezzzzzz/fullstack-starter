from pathlib import Path, PurePosixPath

from starlette.datastructures import Headers
from starlette.exceptions import HTTPException
from starlette.responses import Response
from starlette.staticfiles import StaticFiles
from starlette.types import Scope


def check_frontend_directory(directory: Path) -> None:
    if not (directory / "index.html").is_file():
        raise RuntimeError(
            "Frontend build missing. Run: pnpm --dir frontend build; "
            "or set serve_frontend=false in the configuration file for Vite."
        )


class FrontendFiles(StaticFiles):
    """Serve only build files; reserve API paths and constrain HTML fallback."""

    def __init__(self, directory: Path, reserved_paths: list[str]) -> None:
        self.reserved_paths = {path.strip("/") for path in reserved_paths}
        super().__init__(directory=directory, html=True, check_dir=False)

    async def get_response(self, path: str, scope: Scope) -> Response:
        parts = PurePosixPath(path).parts
        reserved = any(
            path == prefix or path.startswith(prefix + "/") for prefix in self.reserved_paths
        )
        if reserved or (parts and parts[0] == "api") or any(part.startswith(".") for part in parts):
            raise HTTPException(404)
        try:
            response = await super().get_response(path, scope)
        except HTTPException as exc:
            accepts_html = "text/html" in Headers(scope=scope).get("accept", "")
            page_path = not PurePosixPath(path).suffix and not path.startswith("assets/")
            if (
                exc.status_code != 404
                or scope["method"] not in ("GET", "HEAD")
                or not accepts_html
                or not page_path
            ):
                raise
            response = await super().get_response("index.html", scope)
            response.headers["Cache-Control"] = "no-cache"
            return response
        if path in ("", ".", "index.html"):
            response.headers["Cache-Control"] = "no-cache"
        return response
