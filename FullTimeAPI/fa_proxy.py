#!/usr/bin/env python3
"""Reverse proxy for fulltime.thefa.com using curl_cffi (Chrome TLS impersonation).

Cloudflare blocks plain .NET/curl TLS fingerprints on fulltime.thefa.com.
This proxies those requests with a browser-impersonating client, letting the
self-hosted FullTimeAPI (.NET) scrape normally.
"""
import re
from fastapi import FastAPI, Request
from fastapi.responses import Response
from curl_cffi import requests as cr

app = FastAPI()

UPSTREAM = "https://fulltime.thefa.com"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")


@app.api_route("/{path:path}", methods=["GET"])
async def proxy(path: str, request: Request):
    qs = request.url.query
    url = f"{UPSTREAM}/{path}" + (f"?{qs}" if qs else "")
    headers = {
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-GB,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
    }
    try:
        r = cr.get(url, impersonate="chrome131", headers=headers, timeout=45)
    except Exception as e:
        return Response(content=f"proxy error: {e}", status_code=502)
    # Preserve any upstream cookies (JSESSIONID / cf_bm) for subsequent requests
    cookies = ""
    if "set-cookie" in r.headers:
        cookies = "; ".join([c.split(";")[0] for c in r.headers.get_list("set-cookie")])
    hdrs = {"Content-Type": r.headers.get("content-type", "text/html")}
    if cookies:
        hdrs["Set-Cookie"] = cookies
    return Response(content=r.content, status_code=r.status_code, headers=hdrs)
