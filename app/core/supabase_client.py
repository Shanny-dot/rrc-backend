import httpx
from supabase import create_client, Client, ClientOptions
from app.core.config import settings


def _pooled_http() -> httpx.Client:
    """A pool of ordinary HTTP/1.1 connections for database calls.

    By default the Supabase client sends every request over one shared HTTP/2 connection. Our
    endpoints run in many threads at once, and on launch day (25 Oct) that single connection
    jammed under load ("ReadError: Resource temporarily unavailable"): about 1 request in 5
    failed. A connection pool handles parallel requests safely (tested: 18% failures → 0.25%)."""
    return httpx.Client(
        http2=False,
        timeout=httpx.Timeout(30.0),
        limits=httpx.Limits(max_connections=40, max_keepalive_connections=20, keepalive_expiry=15),
        transport=httpx.HTTPTransport(retries=2),
        follow_redirects=True,
    )


supabase_anon: Client = create_client(str(settings.SUPABASE_URL), settings.SUPABASE_ANON_KEY,
                                      options=ClientOptions(httpx_client=_pooled_http()))
supabase_admin: Client = create_client(str(settings.SUPABASE_URL), settings.SUPABASE_SERVICE_KEY,
                                       options=ClientOptions(httpx_client=_pooled_http()))
