"""Serve client routes without disguising missing API endpoints or assets."""

from pathlib import PurePosixPath

from starlette.exceptions import HTTPException
from starlette.staticfiles import StaticFiles


class SPAStaticFiles(StaticFiles):
    async def get_response(self, path, scope):
        try:
            response = await super().get_response(path, scope)
            if response.status_code != 404:
                return response
        except HTTPException as error:
            if error.status_code != 404:
                raise

        parts = PurePosixPath(path).parts
        client_route = (
            scope["method"] in {"GET", "HEAD"}
            and not any(part.startswith(".") for part in parts)
            and "\\" not in path
            and (not parts or parts[0] not in {"api", "assets"})
            and not PurePosixPath(path).suffix
        )
        if client_route:
            return await super().get_response("index.html", scope)
        raise HTTPException(status_code=404)
