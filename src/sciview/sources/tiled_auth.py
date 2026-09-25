"""Non-interactive Tiled login, with UI-neutral device-code notifications."""
import time


def sign_in(uri, cancel, notify, *, force=False):
    from tiled.client.context import Context
    from tiled.client.utils import handle_error
    context, _ = Context.from_any_uri(uri)
    # Existing sessions are usable without repeating MFA.
    if not force and context.use_cached_tokens():
        try:
            info = context.whoami()
            if info:
                return info
        except Exception:
            pass
    providers = context.server_info.authentication.providers
    provider = next((p for p in providers if p.mode == "external"), None)
    if provider is None:
        raise RuntimeError("This dialog supports Tiled browser/device sign-in; no external provider was advertised.")
    links = provider.links
    client = context.http_client
    client_id, token_endpoint = links.get("client_id"), links.get("token_endpoint")
    direct = bool(client_id and token_endpoint)
    data = {"client_id": client_id,
            "scope": " ".join(sorted({"openid", "offline_access"} | set(provider.extra_scopes or [])))}
    response = client.post(links["auth_endpoint"], data=data, auth=None) if direct else client.post(links["auth_endpoint"], auth=None)
    verification = handle_error(response).json()
    if direct:
        url = verification.get("verification_uri_complete") or verification.get("verification_uri") or verification.get("verification_url")
    else:
        url = verification.get("authorization_uri")
        token_endpoint = verification["verification_uri"]
    if not url:
        raise RuntimeError("Provider returned no sign-in URL")
    notify(str(url), str(verification["user_code"]))
    deadline = time.monotonic() + float(verification["expires_in"])
    interval = max(1, float(verification.get("interval", 5)))
    while time.monotonic() < deadline:
        if cancel.wait(min(interval, max(0, deadline - time.monotonic()))):
            raise RuntimeError("Sign-in cancelled")
        payload = {"device_code": verification["device_code"], "grant_type": "urn:ietf:params:oauth:grant-type:device_code"}
        response = (client.post(token_endpoint, data={**payload, "client_id": client_id}, auth=None)
                    if direct else client.post(token_endpoint, json=payload, auth=None))
        if response.status_code == 400:
            error = response.json()
            if not direct: error = error.get("detail", {})
            code = error.get("error")
            if code == "authorization_pending": continue
            if code == "slow_down": interval += 5; continue
            if code in ("expired_token", "access_denied", "authorization_declined"):
                raise RuntimeError("Sign-in expired or declined; try again")
        tokens = handle_error(response).json()
        if cancel.is_set(): raise RuntimeError("Sign-in cancelled")
        context.configure_auth(tokens, remember_me=True)
        return context.whoami()
    raise TimeoutError("Sign-in code expired; try again")
