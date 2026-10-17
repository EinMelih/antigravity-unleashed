"""Typed aiohttp application keys shared by proxy components."""

from typing import Optional

from aiohttp import web


BACKEND_PORT_KEY = web.AppKey("backend_port", Optional[int])
CODE_SERVER_PORT_KEY = web.AppKey("code_server_port", int)
