"""Sign in with ChatGPT and refresh its locally stored OAuth credentials."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import math
import secrets
import time
import webbrowser
from dataclasses import dataclass, replace
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx
import jwt

from convo.core.contracts import ReasoningEffort
from convo.core.exceptions import BackendNotConnected
from convo.llm.credentials import (
    AccountProfile,
    AccountProfileStore,
    CredentialStore,
)

AUTHORIZE_URL = "https://auth.openai.com/api/accounts/authorize"
TOKEN_URL = "https://auth.openai.com/api/accounts/oauth/token"
OIDC_DISCOVERY_URL = "https://auth.openai.com/.well-known/openid-configuration"
RESOURCE = "https://api.openai.com/v1"
SCOPES = "openid profile email offline_access resource.invoke chatgpt.tokens.use.direct"
DIRECT_USE_SCOPE = "chatgpt.tokens.use.direct"
CALLBACK_PATH = "/auth/callback"
TOKEN_KEY = "chatgpt.oauth.tokens"
CALLBACK_TIMEOUT_SECONDS = 180
HTTP_TIMEOUT_SECONDS = 20


@dataclass(frozen=True)
class AuthorizationResult:
    code: str
    client_id: str


class ChatGPTAuth:
    """Own the loopback OAuth flow and the local ChatGPT account connection."""

    def __init__(
        self,
        credentials: CredentialStore,
        profile_store: AccountProfileStore | None = None,
    ) -> None:
        self.credentials = credentials
        self.profiles = profile_store or AccountProfileStore()
        self._callback_future: asyncio.Future[AuthorizationResult] | None = None
        self._login_lock = asyncio.Lock()

    async def login(self) -> str:
        """Open the system browser, validate OAuth, and save the account locally."""
        async with self._login_lock:
            return await self._login()

    async def _login(self) -> str:
        try:
            profile = self._load_profile()
            old_tokens = self._load_tokens(required=False)
            result, redirect_uri, nonce, verifier = await self._authorize(profile, old_tokens)
            payload = await self._post_token(
                {
                    "grant_type": "authorization_code",
                    "client_id": result.client_id,
                    "code": result.code,
                    "redirect_uri": redirect_uri,
                    "code_verifier": verifier,
                    "resource": RESOURCE,
                }
            )
            identity, issuer = await self._verify_id_token(
                self._required_string(payload, "id_token"), result.client_id, nonce
            )
            if profile is not None and identity["sub"] != profile.subject:
                raise BackendNotConnected(
                    "This ChatGPT registration belongs to a different account. "
                    "Remove the saved Convo account before switching accounts."
                )

            scopes = _parse_scopes(payload.get("scope"))
            self._require_direct_use(scopes)
            self._validate_token_type(payload)
            expires_in = self._expires_in(payload)
            token_record = {
                "access_token": self._required_string(payload, "access_token"),
                "refresh_token": self._required_string(payload, "refresh_token"),
                "id_token": self._required_string(payload, "id_token"),
            }
            new_profile = AccountProfile(
                client_id=result.client_id,
                subject=identity["sub"],
                email=_optional_claim(identity, "email"),
                name=_optional_claim(identity, "name")
                or _optional_claim(identity, "preferred_username"),
                issuer=issuer,
                scopes=tuple(sorted(scopes)),
                expires_at=time.time() + expires_in,
                selected_model=profile.selected_model if profile else None,
                selected_model_name=profile.selected_model_name if profile else None,
                selected_reasoning_effort=profile.selected_reasoning_effort if profile else None,
            )
            self._save_connection(token_record, new_profile)
            return new_profile.email or new_profile.name or new_profile.subject
        except BackendNotConnected:
            raise
        except (httpx.HTTPError, OSError, ValueError, jwt.PyJWTError, KeyError, TypeError) as error:
            # Raw HTTP/JWT exceptions can contain request details. Keep the UI response safe.
            raise BackendNotConnected(
                "ChatGPT sign-in could not be completed. Check the connection and retry /login."
            ) from error

    async def access_token(self) -> str:
        """Return a valid, plan-enabled token, refreshing it when near expiry."""
        profile = self._load_profile()
        if profile is None:
            raise BackendNotConnected("Connect your ChatGPT account with /login")
        self._require_direct_use(set(profile.scopes))
        tokens = self._load_tokens(required=True)
        assert tokens is not None
        access_token = tokens.get("access_token")
        if not isinstance(access_token, str) or not access_token:
            raise BackendNotConnected("Saved ChatGPT credentials are incomplete. Run /login again.")
        if profile.expires_at > time.time() + 60:
            return access_token
        return await self._refresh(profile, tokens)

    def account_profile(self) -> AccountProfile | None:
        """Return the non-secret signed-in account metadata, if available."""
        return self._load_profile()

    def save_generation_preferences(
        self, model: str, display_name: str, effort: ReasoningEffort | None
    ) -> None:
        """Persist model and reasoning together without altering OAuth credentials."""
        profile = self._load_profile()
        if profile is None:
            raise BackendNotConnected("Connect your ChatGPT account with /login")
        self.profiles.save(
            replace(
                profile,
                selected_model=model,
                selected_model_name=display_name,
                selected_reasoning_effort=effort,
            )
        )

    async def _authorize(
        self,
        profile: AccountProfile | None,
        old_tokens: dict[str, str] | None,
    ) -> tuple[AuthorizationResult, str, str, str]:
        state = secrets.token_urlsafe(32)
        nonce = secrets.token_urlsafe(32)
        verifier = secrets.token_urlsafe(64)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        client_id = profile.client_id if profile else "dynamic_agent_client"
        if self._callback_future is not None:
            raise BackendNotConnected("A ChatGPT sign-in is already in progress.")

        server = await asyncio.start_server(
            lambda reader, writer: self._handle_callback(reader, writer, state, client_id),
            host="127.0.0.1",
            port=0,
            limit=16 * 1024,
        )
        try:
            socket = server.sockets[0]
            port = socket.getsockname()[1]
            redirect_uri = f"http://127.0.0.1:{port}{CALLBACK_PATH}"
            params = {
                "client_id": client_id,
                "redirect_uri": redirect_uri,
                "response_type": "code",
                "scope": SCOPES,
                "resource": RESOURCE,
                "state": state,
                "nonce": nonce,
                "code_challenge": challenge.decode("ascii").rstrip("="),
                "code_challenge_method": "S256",
                "ext_agent_host_id": self.profiles.host_id(),
            }
            if profile is None:
                params["agent_name_hint"] = "convo"
            else:
                email = profile.email
                old_id_token = old_tokens.get("id_token") if old_tokens else None
                if email:
                    params["login_hint"] = email
                if old_id_token:
                    params["id_token_hint"] = old_id_token
            authorization_url = f"{AUTHORIZE_URL}?{urlencode(params)}"
            callback_future: asyncio.Future[AuthorizationResult] = (
                asyncio.get_running_loop().create_future()
            )
            # Store the future only for the duration of this single authorization attempt.
            self._callback_future = callback_future
            opened = await asyncio.to_thread(webbrowser.open, authorization_url, 1, True)
            if not opened:
                raise BackendNotConnected(
                    "Could not open a browser for ChatGPT sign-in. Check your desktop browser and retry."
                )
            try:
                result = await asyncio.wait_for(callback_future, timeout=CALLBACK_TIMEOUT_SECONDS)
            except TimeoutError as error:
                raise BackendNotConnected(
                    "Timed out waiting for ChatGPT sign-in. Run /login and try again."
                ) from error
            if profile is None and result.client_id == "dynamic_agent_client":
                raise BackendNotConnected("ChatGPT did not return the registered client ID.")
            return AuthorizationResult(result.code, result.client_id), redirect_uri, nonce, verifier
        finally:
            self._callback_future = None
            server.close()
            await server.wait_closed()

    async def _handle_callback(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        expected_state: str,
        requested_client_id: str,
    ) -> None:
        response_status = "400 Bad Request"
        response_body = "Sign-in callback was not accepted. Return to Convo and retry /login."
        should_resolve = False
        try:
            request_line = await asyncio.wait_for(reader.readline(), timeout=10)
            try:
                method, target, _version = request_line.decode("ascii").strip().split(" ", 2)
            except (UnicodeDecodeError, ValueError):
                method, target = "", ""
            total_header_bytes = 0
            while True:
                line = await asyncio.wait_for(reader.readline(), timeout=10)
                total_header_bytes += len(line)
                if not line or line in (b"\r\n", b"\n"):
                    break
                if total_header_bytes > 16 * 1024:
                    raise ValueError("Callback headers are too large")
            parsed = urlsplit(target)
            if method != "GET" or parsed.path != CALLBACK_PATH:
                response_status = "404 Not Found"
                response_body = "Unknown Convo callback path. You may close this tab."
            else:
                query = parse_qs(parsed.query, keep_blank_values=True, strict_parsing=True)
                state_values = query.get("state", [])
                if len(state_values) != 1 or not hmac.compare_digest(
                    state_values[0], expected_state
                ):
                    response_body = "This sign-in callback did not match the pending request."
                else:
                    errors = query.get("error", [])
                    if errors:
                        response_status = "200 OK"
                        response_body = "ChatGPT sign-in was canceled. You may close this tab."
                        future = self._callback_future
                        if future is not None and not future.done():
                            future.set_exception(
                                BackendNotConnected("ChatGPT sign-in was canceled or denied.")
                            )
                        should_resolve = True
                    else:
                        codes = query.get("code", [])
                        client_ids = query.get("client_id", [])
                        if len(codes) != 1 or not codes[0]:
                            raise ValueError("Callback did not contain one authorization code")
                        if len(client_ids) > 1:
                            raise ValueError("Callback contained duplicate client IDs")
                        callback_client_id = client_ids[0] if client_ids else requested_client_id
                        if not callback_client_id or (
                            requested_client_id != "dynamic_agent_client"
                            and callback_client_id != requested_client_id
                        ):
                            raise ValueError("Callback client ID did not match the request")
                        response_status = "200 OK"
                        response_body = "ChatGPT is connected to Convo. You may close this tab."
                        future = self._callback_future
                        if future is not None and not future.done():
                            future.set_result(AuthorizationResult(codes[0], callback_client_id))
                        should_resolve = True
        except (TimeoutError, ValueError):
            response_status = "400 Bad Request"
        finally:
            body = (
                "<!doctype html><html><meta charset='utf-8'><title>Convo</title>"
                f"<body style='font:16px sans-serif;padding:2rem'>{response_body}</body></html>"
            ).encode()
            writer.write(
                f"HTTP/1.1 {response_status}\r\n"
                "Content-Type: text/html; charset=utf-8\r\n"
                f"Content-Length: {len(body)}\r\n"
                "Connection: close\r\n\r\n".encode("ascii")
                + body
            )
            try:
                await writer.drain()
            finally:
                writer.close()
                await writer.wait_closed()
        if should_resolve:
            return

    async def _post_token(self, data: dict[str, str]) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as client:
            response = await client.post(TOKEN_URL, data=data)
            response.raise_for_status()
            payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("Token endpoint returned an invalid response")
        return payload

    async def _verify_id_token(
        self, id_token: str, client_id: str, nonce: str | None
    ) -> tuple[dict[str, Any], str]:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as client:
            response = await client.get(OIDC_DISCOVERY_URL)
            response.raise_for_status()
            discovery = response.json()
            if not isinstance(discovery, dict):
                raise ValueError("OpenID discovery response is invalid")
            issuer = discovery.get("issuer")
            jwks_uri = discovery.get("jwks_uri")
            if not isinstance(issuer, str) or not isinstance(jwks_uri, str):
                raise ValueError("OpenID discovery document is missing required fields")
            jwks_url = urlsplit(jwks_uri)
            if jwks_url.scheme != "https" or jwks_url.hostname != "auth.openai.com":
                raise ValueError("OpenID discovery returned an untrusted signing-key URL")
            keys_response = await client.get(jwks_uri)
            keys_response.raise_for_status()
            key_set = keys_response.json()

        if not isinstance(key_set, dict) or not isinstance(key_set.get("keys"), list):
            raise ValueError("OpenID signing-key response is invalid")
        header = jwt.get_unverified_header(id_token)
        key_id = header.get("kid")
        if header.get("alg") != "RS256" or not isinstance(key_id, str):
            raise ValueError("ID token uses an unsupported signing key")
        jwk = next(
            (
                item
                for item in key_set["keys"]
                if isinstance(item, dict) and item.get("kid") == key_id
            ),
            None,
        )
        if jwk is None:
            raise ValueError("ID token signing key was not found")
        signing_key = jwt.PyJWK.from_dict(jwk, algorithm="RS256").key
        claims = jwt.decode(
            id_token,
            signing_key,
            algorithms=["RS256"],
            audience=client_id,
            issuer=issuer,
            options={"require": ["exp", "iat", "sub", "iss", "aud"]},
        )
        if not isinstance(claims.get("sub"), str) or not claims["sub"]:
            raise ValueError("ID token has no subject")
        if nonce is not None and not hmac.compare_digest(str(claims.get("nonce", "")), nonce):
            raise ValueError("ID token nonce did not match")
        return claims, issuer

    async def _refresh(self, profile: AccountProfile, tokens: dict[str, str]) -> str:
        refresh_token = tokens.get("refresh_token")
        if not refresh_token:
            raise BackendNotConnected("ChatGPT session expired. Run /login again.")
        try:
            payload = await self._post_token(
                {
                    "grant_type": "refresh_token",
                    "client_id": profile.client_id,
                    "refresh_token": refresh_token,
                    "resource": RESOURCE,
                }
            )
            scopes = _parse_scopes(payload.get("scope")) or set(profile.scopes)
            self._require_direct_use(scopes)
            self._validate_token_type(payload)
            expires_in = self._expires_in(payload)
            access_token = self._required_string(payload, "access_token")
            new_refresh_token = payload.get("refresh_token", refresh_token)
            if not isinstance(new_refresh_token, str) or not new_refresh_token:
                raise ValueError("Refresh endpoint returned no refresh token")
            new_id_token = payload.get("id_token", tokens.get("id_token", ""))
            if not isinstance(new_id_token, str) or not new_id_token:
                raise ValueError("Saved ID token is missing")
            if payload.get("id_token"):
                identity, issuer = await self._verify_id_token(
                    new_id_token, profile.client_id, nonce=None
                )
                if identity["sub"] != profile.subject:
                    raise ValueError("Refreshed ID token belongs to a different account")
                if issuer != profile.issuer:
                    raise ValueError("Refreshed ID token issuer changed")
            token_record = {
                "access_token": access_token,
                "refresh_token": new_refresh_token,
                "id_token": new_id_token,
            }
            updated_profile = replace(
                profile,
                scopes=tuple(sorted(scopes)),
                expires_at=time.time() + expires_in,
            )
            self._save_connection(token_record, updated_profile)
            return access_token
        except BackendNotConnected:
            raise
        except (httpx.HTTPError, ValueError, KeyError, TypeError, jwt.PyJWTError) as error:
            raise BackendNotConnected(
                "ChatGPT session expired. Run /login to reconnect your account."
            ) from error

    def _save_connection(self, tokens: dict[str, str], profile: AccountProfile) -> None:
        try:
            self.credentials.save(TOKEN_KEY, json.dumps(tokens, separators=(",", ":")))
            self.profiles.save(profile)
        except Exception as error:  # keyring backends expose platform-specific exceptions
            raise BackendNotConnected(
                "Could not securely save ChatGPT credentials. Check your operating-system keyring."
            ) from error

    def _load_profile(self) -> AccountProfile | None:
        try:
            return self.profiles.load()
        except (OSError, ValueError) as error:
            raise BackendNotConnected(
                "Saved ChatGPT profile is unreadable. Fix or remove it, then run /login again."
            ) from error

    def _load_tokens(self, *, required: bool) -> dict[str, str] | None:
        try:
            raw = self.credentials.load(TOKEN_KEY)
        except Exception as error:  # keyring backends expose platform-specific exceptions
            raise BackendNotConnected(
                "Could not access the operating-system keyring for ChatGPT credentials."
            ) from error
        if raw is None:
            if required:
                raise BackendNotConnected("Connect your ChatGPT account with /login")
            return None
        try:
            tokens = json.loads(raw)
        except json.JSONDecodeError as error:
            raise BackendNotConnected(
                "Saved ChatGPT credentials are invalid. Run /login again."
            ) from error
        if not isinstance(tokens, dict) or not all(
            isinstance(tokens.get(key), str)
            for key in ("access_token", "refresh_token", "id_token")
        ):
            raise BackendNotConnected("Saved ChatGPT credentials are incomplete. Run /login again.")
        return tokens

    @staticmethod
    def _required_string(payload: dict[str, Any], name: str) -> str:
        value = payload.get(name)
        if not isinstance(value, str) or not value:
            raise ValueError(f"Token response is missing {name}")
        return value

    @staticmethod
    def _expires_in(payload: dict[str, Any]) -> int:
        value = payload.get("expires_in")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("Token response has an invalid expiry")
        if not math.isfinite(value) or value <= 0:
            raise ValueError("Token response has an invalid expiry")
        return int(value)

    @staticmethod
    def _validate_token_type(payload: dict[str, Any]) -> None:
        token_type = payload.get("token_type", "Bearer")
        if not isinstance(token_type, str) or token_type.casefold() != "bearer":
            raise ValueError("Token endpoint returned an unsupported token type")

    @staticmethod
    def _require_direct_use(scopes: set[str]) -> None:
        if DIRECT_USE_SCOPE not in scopes:
            raise BackendNotConnected(
                "This ChatGPT account did not grant direct model access. Run /login and allow it."
            )


def _parse_scopes(value: object) -> set[str]:
    if isinstance(value, str):
        return set(value.split())
    if isinstance(value, list) and all(isinstance(scope, str) for scope in value):
        return set(value)
    return set()


def _optional_claim(claims: dict[str, Any], key: str) -> str | None:
    value = claims.get(key)
    return value if isinstance(value, str) and value else None
