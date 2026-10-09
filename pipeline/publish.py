"""Opt-in YouTube and Instagram Reels publishing adapters.

Publishing is never triggered unless the caller explicitly invokes this module or
sets AUTO_PUBLISH_PLATFORMS. YouTube defaults to private; Instagram and Facebook
Reel publication is public by design. Instagram Login Reel publishing requires a
publicly reachable direct MP4 URL.
"""
from __future__ import annotations

import hashlib
import base64
import json
import mimetypes
import queue
import re
import secrets
import shutil
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from urllib.parse import parse_qs, quote, urlencode, urlparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import webbrowser

import requests

from . import config
from .models import Script
from .social_copy import build as build_social_copy
from .util import log, read_json, write_json

YOUTUBE_SCOPE = ["https://www.googleapis.com/auth/youtube.upload"]
INSTAGRAM_DRIVE_SCOPE = ["https://www.googleapis.com/auth/drive.file"]
FACEBOOK_PAGE_SCOPES = (
    "pages_show_list,pages_read_engagement,pages_manage_posts"
)
X_OAUTH_SCOPES = "tweet.read tweet.write users.read media.write offline.access"
X_API_BASE = "https://api.x.com/2"


def _youtube_credentials(interactive: bool = True):
    try:
        from google.auth.transport.requests import Request
        from google.auth.exceptions import RefreshError
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError as exc:
        raise RuntimeError("YouTube publishing dependencies are missing. Install requirements.txt in the project's .venv.") from exc
    creds = None
    if config.YOUTUBE_TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(config.YOUTUBE_TOKEN_FILE), YOUTUBE_SCOPE)
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except RefreshError as exc:
            detail = str(exc).lower()
            invalid_grant = "invalid_grant" in detail or "expired or revoked" in detail
            if not invalid_grant:
                raise
            if not interactive:
                raise RuntimeError(
                    "The saved YouTube OAuth token has expired or was revoked. "
                    "Run `python run.py connect-youtube` to sign in again."
                ) from exc
            # A stale refresh token cannot be repaired; let the interactive flow
            # obtain a fresh grant. Keep the old file until new consent succeeds.
            log("Saved YouTube refresh token expired or was revoked; starting a fresh Google sign-in.")
            creds = None
    if not creds or not creds.valid:
        if not interactive:
            raise RuntimeError("YouTube is not connected. Run `python run.py connect-youtube` first.")
        if not config.YOUTUBE_CLIENT_SECRETS.is_file():
            raise FileNotFoundError(
                "Add your Google OAuth desktop client JSON at "
                f"{config.YOUTUBE_CLIENT_SECRETS} before connecting YouTube."
            )
        flow = InstalledAppFlow.from_client_secrets_file(str(config.YOUTUBE_CLIENT_SECRETS), YOUTUBE_SCOPE)
        creds = flow.run_local_server(port=0, prompt="consent")
        config.YOUTUBE_TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
        config.YOUTUBE_TOKEN_FILE.write_text(creds.to_json(), encoding="utf-8")
    return creds


def connect_youtube() -> str:
    _youtube_credentials(interactive=True)
    return str(config.YOUTUBE_TOKEN_FILE)


def _instagram_drive_credentials(interactive: bool = True):
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError as exc:
        raise RuntimeError("Google Drive publishing dependencies are missing. Install requirements.txt.") from exc
    creds = None
    token_file = config.INSTAGRAM_DRIVE_TOKEN_FILE
    if token_file.exists():
        creds = Credentials.from_authorized_user_file(str(token_file), INSTAGRAM_DRIVE_SCOPE)
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    if not creds or not creds.valid or not creds.has_scopes(INSTAGRAM_DRIVE_SCOPE):
        if not interactive:
            raise RuntimeError("Google Drive is not connected. Run `python run.py connect-instagram-drive` first.")
        if not config.YOUTUBE_CLIENT_SECRETS.is_file():
            raise FileNotFoundError(
                "Add your Google OAuth desktop client JSON at "
                f"{config.YOUTUBE_CLIENT_SECRETS} before connecting Google Drive."
            )
        flow = InstalledAppFlow.from_client_secrets_file(
            str(config.YOUTUBE_CLIENT_SECRETS), INSTAGRAM_DRIVE_SCOPE,
        )
        creds = flow.run_local_server(port=0, prompt="consent")
        token_file.parent.mkdir(parents=True, exist_ok=True)
        token_file.write_text(creds.to_json(), encoding="utf-8")
    return creds


def connect_instagram_drive() -> str:
    _instagram_drive_credentials(interactive=True)
    return str(config.INSTAGRAM_DRIVE_TOKEN_FILE)


def _x_token_request(data: dict) -> dict:
    if not config.X_CLIENT_ID:
        raise RuntimeError("Set X_CLIENT_ID in .env from your X Developer App before connecting X.")
    form = dict(data)
    auth = None
    if config.X_CLIENT_SECRET:
        auth = (config.X_CLIENT_ID, config.X_CLIENT_SECRET)
    else:
        form["client_id"] = config.X_CLIENT_ID
    response = requests.post("https://api.x.com/2/oauth2/token", data=form,
                             auth=auth, timeout=30)
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    if not response.ok or payload.get("error"):
        message = payload.get("error_description") or payload.get("error") or "unknown OAuth error"
        raise RuntimeError(f"X OAuth token request failed ({response.status_code}): {message}")
    return payload


def _save_x_token(payload: dict, previous: dict | None = None) -> dict:
    saved = dict(previous or {})
    saved.update({key: payload[key] for key in ("access_token", "refresh_token", "token_type", "scope")
                  if payload.get(key)})
    if payload.get("expires_in"):
        saved["expires_at"] = time.time() + int(payload["expires_in"])
    config.X_TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    write_json(config.X_TOKEN_FILE, saved)
    return saved


def _x_access_token() -> str:
    token_file = config.X_TOKEN_FILE
    if not token_file.is_file():
        if config.X_ACCESS_TOKEN:
            return config.X_ACCESS_TOKEN
        raise RuntimeError("X is not connected. Run `python run.py connect-x` first.")
    saved = read_json(token_file)
    access_token = str(saved.get("access_token") or "")
    if not access_token:
        raise RuntimeError("The saved X token is invalid. Run `python run.py connect-x` again.")
    expires_at = float(saved.get("expires_at") or 0)
    if expires_at and expires_at <= time.time() + 60:
        refresh_token = str(saved.get("refresh_token") or "")
        if not refresh_token:
            raise RuntimeError("The X access token expired. Run `python run.py connect-x` again.")
        refreshed = _x_token_request({"grant_type": "refresh_token", "refresh_token": refresh_token})
        saved = _save_x_token(refreshed, saved)
        access_token = str(saved.get("access_token") or "")
    return access_token


def connect_x() -> str:
    """Authorize an X user with OAuth 2.0 PKCE and save refreshable credentials locally."""
    if not config.X_CLIENT_ID:
        raise RuntimeError("Set X_CLIENT_ID in .env from your X Developer App before connecting X.")
    redirect = config.X_OAUTH_REDIRECT_URI
    parsed_redirect = urlparse(redirect)
    if parsed_redirect.hostname not in ("127.0.0.1", "localhost"):
        raise ValueError("X OAuth redirect URI must use localhost or 127.0.0.1 for this local desktop flow.")

    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).decode("ascii").rstrip("=")
    state_value = secrets.token_urlsafe(24)
    callback: dict[str, str] = {}
    callback_path = parsed_redirect.path or "/"

    class OAuthHandler(BaseHTTPRequestHandler):
        def log_message(self, *_args) -> None:
            pass

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            query = parse_qs(parsed.query)
            if parsed.path != callback_path:
                self.send_error(404)
                return
            if query.get("state", [""])[0] != state_value:
                callback["error"] = "OAuth state did not match. Try connecting again."
            elif query.get("error"):
                callback["error"] = query.get("error_description", query["error"])[0]
            else:
                callback["code"] = query.get("code", [""])[0]
                if not callback["code"]:
                    callback["error"] = "X returned no authorization code."
            body = ("X connection complete. You can close this tab." if "code" in callback
                    else "X connection did not complete. Return to the terminal for details.")
            payload = f"<!doctype html><title>X connection</title><p>{body}</p>".encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    server = ThreadingHTTPServer(("127.0.0.1", parsed_redirect.port or 8766), OAuthHandler)
    server.timeout = 1
    auth_url = "https://x.com/i/oauth2/authorize?" + urlencode({
        "response_type": "code", "client_id": config.X_CLIENT_ID,
        "redirect_uri": redirect, "scope": X_OAUTH_SCOPES,
        "state": state_value, "code_challenge": challenge,
        "code_challenge_method": "S256",
    })
    log("Opening X authorization in your browser …")
    try:
        webbrowser.open(auth_url)
        deadline = time.monotonic() + 240
        while time.monotonic() < deadline and not callback:
            server.handle_request()
    finally:
        server.server_close()
    if callback.get("error"):
        raise RuntimeError(f"X authorization failed: {callback['error']}")
    if not callback.get("code"):
        raise TimeoutError("X login was not completed within four minutes.")

    token = _x_token_request({
        "grant_type": "authorization_code", "code": callback["code"],
        "redirect_uri": redirect, "code_verifier": verifier,
    })
    if not token.get("access_token"):
        raise RuntimeError("X authorization completed without returning an access token.")
    _save_x_token(token)
    return str(config.X_TOKEN_FILE)


def _x_api_request(method: str, url: str, token: str, *, params: dict | None = None,
                   json_body: dict | None = None, timeout: int = 120) -> dict:
    response = requests.request(method, url, headers={"Authorization": f"Bearer {token}"},
                                params=params, json=json_body, timeout=timeout)
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    if not response.ok or payload.get("errors") or payload.get("error"):
        errors = payload.get("errors") or payload.get("error") or []
        if isinstance(errors, list):
            message = "; ".join(str(e.get("detail") or e.get("title") or e) for e in errors)
        elif isinstance(errors, dict):
            message = str(errors.get("detail") or errors.get("message") or errors)
        else:
            message = str(errors)
        raise RuntimeError(f"X API request failed ({response.status_code}): {message or 'unknown API error'}")
    return payload


def publish_x(video: Path, social: dict) -> dict:
    """Upload a video in chunks, wait for processing, then create an X post."""
    token = _x_access_token()
    size = video.stat().st_size
    initialized = _x_api_request("POST", f"{X_API_BASE}/media/upload/initialize", token,
                                 json_body={"media_type": "video/mp4", "media_category": "tweet_video",
                                            "total_bytes": size})
    media_id = str((initialized.get("data") or {}).get("id") or "")
    if not media_id:
        raise RuntimeError("X did not return a media ID after initializing the video upload.")

    segment_bytes = 4 * 1024 * 1024
    with video.open("rb") as media:
        segment_index = 0
        while True:
            chunk = media.read(segment_bytes)
            if not chunk:
                break
            encoded = base64.b64encode(chunk).decode("ascii")
            _x_api_request("POST", f"{X_API_BASE}/media/upload/{media_id}/append", token,
                           json_body={"media": encoded, "segment_index": segment_index}, timeout=180)
            segment_index += 1
            log(f"X video upload {min(100, int(media.tell() * 100 / max(1, size)))}%")

    finalized = _x_api_request("POST", f"{X_API_BASE}/media/upload/{media_id}/finalize", token)
    processing = (finalized.get("data") or {}).get("processing_info") or {}
    deadline = time.monotonic() + 300
    while processing:
        state = str(processing.get("state") or "succeeded").lower()
        if state == "succeeded":
            break
        if state == "failed":
            raise RuntimeError(f"X video processing failed: {processing.get('error') or 'unknown error'}")
        if time.monotonic() >= deadline:
            raise TimeoutError("X is still processing the uploaded video after five minutes.")
        delay = max(1, int(processing.get("check_after_secs") or 2))
        time.sleep(delay)
        status = _x_api_request("GET", f"{X_API_BASE}/media/upload", token,
                                params={"media_id": media_id, "command": "STATUS"})
        processing = (status.get("data") or {}).get("processing_info") or {}

    text = str(social.get("x", {}).get("text") or "").strip()
    if not text:
        raise RuntimeError("X post text is empty. Check the X caption in the video script.")
    posted = _x_api_request("POST", f"{X_API_BASE}/tweets", token,
                            json_body={"text": text, "media": {"media_ids": [media_id]}, "made_with_ai": True})
    post_id = str((posted.get("data") or {}).get("id") or "")
    if not post_id:
        raise RuntimeError("X accepted the media but did not return a post ID.")
    result = {"id": post_id, "media_id": media_id, "url": f"https://x.com/i/status/{post_id}",
              "status": "published", "text": text}
    _record(video, "x", result)
    return result


def _facebook_page_token() -> str:
    """Use the most recently OAuth-issued Page token, falling back to .env."""
    token_file = config.FACEBOOK_PAGE_TOKEN_FILE
    if token_file.is_file():
        saved = read_json(token_file)
        saved_page_id = str(saved.get("page_id") or "")
        if saved_page_id and config.FACEBOOK_PAGE_ID and saved_page_id != config.FACEBOOK_PAGE_ID:
            raise RuntimeError(
                "The saved Facebook token belongs to a different Page. Run `python run.py connect-facebook` "
                "to authorize the Page ID currently configured in .env."
            )
        token = str(saved.get("page_access_token") or "")
        if token:
            return token
    return config.FACEBOOK_PAGE_ACCESS_TOKEN


def connect_facebook_page() -> dict:
    """Run Facebook Login, exchange the code for a long-lived user token, and save the selected Page token."""
    if not config.FACEBOOK_APP_ID or not config.FACEBOOK_APP_SECRET:
        raise RuntimeError(
            "Facebook token renewal needs FACEBOOK_APP_ID and FACEBOOK_APP_SECRET in .env. "
            "Also set FACEBOOK_PAGE_ID and register FACEBOOK_OAUTH_REDIRECT_URI in your Meta app."
        )
    if not config.FACEBOOK_PAGE_ID:
        raise RuntimeError("Set FACEBOOK_PAGE_ID in .env before connecting Facebook.")

    callback_path = urlparse(config.FACEBOOK_OAUTH_REDIRECT_URI).path or "/"
    state_value = secrets.token_urlsafe(24)
    callback: dict[str, str] = {}

    class OAuthHandler(BaseHTTPRequestHandler):
        def log_message(self, *_args) -> None:
            pass

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            query = parse_qs(parsed.query)
            if parsed.path != callback_path:
                self.send_error(404)
                return
            if query.get("state", [""])[0] != state_value:
                callback["error"] = "OAuth state did not match. Try connecting again."
            elif query.get("error"):
                callback["error"] = query.get("error_description", query["error"])[0]
            else:
                callback["code"] = query.get("code", [""])[0]
                if not callback["code"]:
                    callback["error"] = "Meta returned no OAuth authorization code."
            body = ("Facebook connection complete. You can close this tab." if "code" in callback
                    else "Facebook connection did not complete. Return to the terminal for details.")
            payload = f"<!doctype html><title>Facebook connection</title><p>{body}</p>".encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    redirect = config.FACEBOOK_OAUTH_REDIRECT_URI
    server = ThreadingHTTPServer(("127.0.0.1", urlparse(redirect).port or 8765), OAuthHandler)
    server.timeout = 1
    auth_url = f"https://www.facebook.com/{config.FACEBOOK_GRAPH_VERSION}/dialog/oauth?" + urlencode({
        "client_id": config.FACEBOOK_APP_ID,
        "redirect_uri": redirect,
        "state": state_value,
        "scope": FACEBOOK_PAGE_SCOPES,
        "response_type": "code",
    })
    log("Opening Meta login to renew the Facebook Page publishing token …")
    try:
        webbrowser.open(auth_url)
        deadline = time.monotonic() + 240
        while time.monotonic() < deadline and not callback:
            server.handle_request()
    finally:
        server.server_close()
    if callback.get("error"):
        raise RuntimeError(f"Facebook authorization failed: {callback['error']}")
    if not callback.get("code"):
        raise TimeoutError("Facebook login was not completed within four minutes.")

    base = f"https://graph.facebook.com/{config.FACEBOOK_GRAPH_VERSION}"

    def graph_get(path: str, params: dict) -> dict:
        response = requests.get(f"{base}/{path.lstrip('/')}", params=params, timeout=30)
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        if not response.ok or "error" in payload:
            error = payload.get("error", {})
            message = error.get("message") if isinstance(error, dict) else str(error)
            raise RuntimeError(f"Facebook authorization API failed ({response.status_code}): {message or 'unknown API error'}")
        return payload

    short = graph_get("oauth/access_token", {
        "client_id": config.FACEBOOK_APP_ID,
        "client_secret": config.FACEBOOK_APP_SECRET,
        "redirect_uri": redirect,
        "code": callback["code"],
    })
    short_token = str(short.get("access_token") or "")
    if not short_token:
        raise RuntimeError("Meta did not return a user access token during Facebook authorization.")
    long_lived = graph_get("oauth/access_token", {
        "grant_type": "fb_exchange_token",
        "client_id": config.FACEBOOK_APP_ID,
        "client_secret": config.FACEBOOK_APP_SECRET,
        "fb_exchange_token": short_token,
    })
    user_token = str(long_lived.get("access_token") or short_token)
    pages = graph_get("me/accounts", {
        "fields": "id,name,access_token",
        "limit": 100,
        "access_token": user_token,
    }).get("data", [])
    selected = next((page for page in pages if str(page.get("id")) == config.FACEBOOK_PAGE_ID), None)
    if not selected or not selected.get("access_token"):
        available = ", ".join(str(p.get("name") or p.get("id")) for p in pages) or "none"
        raise RuntimeError(
            f"Meta did not return a Page token for FACEBOOK_PAGE_ID={config.FACEBOOK_PAGE_ID}. "
            f"Pages available to this login: {available}. Check Page access and requested permissions."
        )
    token_file = config.FACEBOOK_PAGE_TOKEN_FILE
    write_json(token_file, {
        "page_id": str(selected["id"]),
        "page_name": str(selected.get("name") or "Facebook Page"),
        "page_access_token": str(selected["access_token"]),
    })
    return {"id": str(selected["id"]), "name": str(selected.get("name") or "Facebook Page"),
            "token_file": str(token_file)}


def _record(video: Path, platform: str, result: dict) -> None:
    path = video.parent / "publishing.json"
    data = read_json(path) if path.exists() else {}
    data[platform] = {**result, "published_at": datetime.now(timezone.utc).isoformat()}
    write_json(path, data)


def publish_youtube(video: Path, social: dict, privacy_status: str = "private") -> dict:
    if privacy_status not in ("private", "unlisted", "public"):
        raise ValueError("YouTube privacy status must be private, unlisted, or public")
    try:
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaFileUpload
    except ImportError as exc:
        raise RuntimeError("YouTube publishing dependencies are missing. Install requirements.txt in the project's .venv.") from exc
    youtube = build("youtube", "v3", credentials=_youtube_credentials())
    metadata = social["youtube"]
    request = youtube.videos().insert(
        part="snippet,status",
        body={
            "snippet": {"title": metadata["title"], "description": metadata["description"],
                        "tags": metadata["tags"], "categoryId": "27"},
            "status": {"privacyStatus": privacy_status, "selfDeclaredMadeForKids": False},
        },
        media_body=MediaFileUpload(str(video), mimetype="video/mp4", chunksize=8 * 1024 * 1024, resumable=True),
    )
    response = None
    while response is None:
        progress, response = request.next_chunk()
        if progress is not None:
            log(f"YouTube upload {int(progress.progress() * 100)}%")
    video_id = response.get("id")
    if not video_id:
        raise RuntimeError("YouTube upload completed without returning a video ID")
    result = {"id": video_id, "url": f"https://youtu.be/{video_id}", "privacy_status": privacy_status,
              "title": metadata["title"]}
    _record(video, "youtube", result)
    return result


def _instagram_access_token() -> str:
    """Load a long-lived Instagram Login token and refresh it before expiry when eligible.

    Instagram Login refresh requires a still-valid long-lived token that is at least
    24 hours old. A token file written after refresh takes precedence over .env until
    the configured environment token is changed.
    """
    token_file = config.INSTAGRAM_TOKEN_FILE
    saved = read_json(token_file) if token_file.is_file() else {}
    env_token = str(config.INSTAGRAM_ACCESS_TOKEN or "").strip()
    env_fingerprint = hashlib.sha256(env_token.encode("utf-8")).hexdigest() if env_token else ""
    saved_fingerprint = str(saved.get("env_token_fingerprint") or "")
    saved_token = str(saved.get("access_token") or "").strip()

    # If .env was edited to replace a token, prefer that value over an older
    # persisted refresh result.
    if env_token and env_fingerprint != saved_fingerprint:
        token = env_token
        has_fresh_token_from_env = True
    else:
        token = saved_token or env_token
        has_fresh_token_from_env = bool(env_token and not saved_token)

    if not token:
        raise RuntimeError(
            "Set INSTAGRAM_ACCESS_TOKEN to an Instagram Login long-lived access token in .env."
        )

    refreshed_at = float(saved.get("refreshed_at") or 0)
    refresh_interval = 7 * 24 * 60 * 60
    should_refresh = has_fresh_token_from_env or not saved_token or time.time() - refreshed_at >= refresh_interval
    if not should_refresh:
        return token

    try:
        response = requests.get(
            "https://graph.instagram.com/refresh_access_token",
            params={"grant_type": "ig_refresh_token", "access_token": token},
            timeout=30,
        )
        try:
            payload = response.json()
        except ValueError:
            payload = {}
    except requests.RequestException as exc:
        log(f"Instagram token refresh request failed ({type(exc).__name__}); continuing with the saved token.")
        return token

    new_token = str(payload.get("access_token") or "").strip()
    if response.ok and new_token:
        token_record = {
            "access_token": new_token,
            "refreshed_at": time.time(),
            "expires_in": int(payload.get("expires_in") or 0),
            "env_token_fingerprint": env_fingerprint,
        }
        try:
            write_json(token_file, token_record)
        except OSError as exc:
            log(f"Instagram token refreshed but could not be saved locally ({type(exc).__name__}); using it for this publish.")
        else:
            log("Instagram long-lived access token refreshed and saved locally.")
        return new_token

    error = payload.get("error", {})
    if not isinstance(error, dict):
        error = {}
    message = str(error.get("message") or payload.get("error_description") or "unknown refresh error")
    code = error.get("code")
    lower_message = message.lower()

    # Tokens less than 24 hours old cannot be refreshed yet; use the current token.
    too_new = (
        "24 hour" in lower_message
        or "24-hour" in lower_message
        or "at least 24" in lower_message
        or "must be at least" in lower_message
    )
    if too_new:
        log("Instagram token is not eligible for refresh yet; continuing with the current token.")
        return token

    expired_or_invalid = (
        "expired" in lower_message
        or "revoked" in lower_message
        or ("invalid" in lower_message and "token" in lower_message)
        or "not valid" in lower_message
    )
    if expired_or_invalid:
        log("Instagram token refresh reports that the current token may be invalid; checking it with the publish API.")
    else:
        # This includes ambiguous OAuth errors such as code 190. A token that is
        # too new to refresh may receive an OAuth error too, so don't block a valid
        # token based on the refresh endpoint alone.
        log(f"Instagram token refresh was unavailable ({response.status_code}: {message}); continuing with current token.")
    return token


def _instagram_request(method: str, url: str, **kwargs) -> dict:
    response = requests.request(method, url, timeout=60, **kwargs)
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    if not response.ok or "error" in payload:
        err = payload.get("error", {})
        message = err.get("message") if isinstance(err, dict) else str(err)
        code = err.get("code") if isinstance(err, dict) else None
        message_text = str(message or "unknown API error")
        if str(code) == "190" or response.status_code == 401 or "access token has expired" in message_text.lower():
            raise RuntimeError(
                "Instagram rejected the access token as expired or invalid. "
                "The automatic refresh was unable to recover it; generate a new Instagram Login "
                "long-lived token and replace INSTAGRAM_ACCESS_TOKEN in .env."
            )
        raise RuntimeError(f"Instagram Graph API request failed ({response.status_code}): {message_text}")
    return payload


def _instagram_video_url(video: Path, explicit_url: str = "") -> tuple[str, Callable[[], None] | None]:
    if explicit_url:
        url = explicit_url
    else:
        template = config.INSTAGRAM_VIDEO_URL_TEMPLATE
        if not template:
            mode = config.INSTAGRAM_UPLOAD_MODE
            if mode == "drive":
                return _upload_instagram_drive(video)
            if mode == "r2":
                return _upload_instagram_video(video)
            if mode == "tunnel":
                return _tunnel_instagram_video(video)
            raise RuntimeError("Set INSTAGRAM_UPLOAD_MODE to 'tunnel' or 'r2', or configure a direct video URL.")
        url = template.format(filename=quote(video.name), video_id=quote(video.stem))
    host = (urlparse(url).hostname or "").lower()
    if host == "facebook.com" or host.endswith(".facebook.com"):
        raise ValueError(
            "A Facebook Page/Reel link is a webpage, not the MP4 file. Supply a "
            "publicly reachable direct MP4 URL for Instagram Login publishing."
        )
    return url, None


def _upload_instagram_video(video: Path) -> tuple[str, Callable[[], None]]:
    """Stage a local MP4 in configured public S3-compatible storage for Meta to fetch."""
    required = {
        "INSTAGRAM_STORAGE_ENDPOINT_URL": config.INSTAGRAM_STORAGE_ENDPOINT_URL,
        "INSTAGRAM_STORAGE_ACCESS_KEY_ID": config.INSTAGRAM_STORAGE_ACCESS_KEY_ID,
        "INSTAGRAM_STORAGE_SECRET_ACCESS_KEY": config.INSTAGRAM_STORAGE_SECRET_ACCESS_KEY,
        "INSTAGRAM_STORAGE_BUCKET": config.INSTAGRAM_STORAGE_BUCKET,
        "INSTAGRAM_STORAGE_PUBLIC_BASE_URL": config.INSTAGRAM_STORAGE_PUBLIC_BASE_URL,
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        raise RuntimeError(
            "Instagram Login needs a public MP4 URL. To have the project stage it "
            "automatically, configure these one-time .env values: " + ", ".join(missing)
        )
    try:
        import boto3
    except ImportError as exc:
        raise RuntimeError("Install the project's dependencies to enable automatic Instagram video staging.") from exc

    digest = hashlib.sha256()
    with video.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    suffix = video.suffix.lower() or ".mp4"
    key = "/".join(part for part in (config.INSTAGRAM_STORAGE_PREFIX, f"{digest.hexdigest()}{suffix}") if part)
    client = boto3.client(
        "s3",
        endpoint_url=config.INSTAGRAM_STORAGE_ENDPOINT_URL,
        aws_access_key_id=config.INSTAGRAM_STORAGE_ACCESS_KEY_ID,
        aws_secret_access_key=config.INSTAGRAM_STORAGE_SECRET_ACCESS_KEY,
        region_name=config.INSTAGRAM_STORAGE_REGION,
    )
    client.upload_file(
        str(video), config.INSTAGRAM_STORAGE_BUCKET, key,
        ExtraArgs={"ContentType": mimetypes.guess_type(video.name)[0] or "video/mp4"},
    )

    def delete_staged_video() -> None:
        client.delete_object(Bucket=config.INSTAGRAM_STORAGE_BUCKET, Key=key)

    return f"{config.INSTAGRAM_STORAGE_PUBLIC_BASE_URL}/{quote(key, safe='/')}", delete_staged_video


def _upload_instagram_drive(video: Path) -> tuple[str, Callable[[], None]]:
    """Upload the Reel to Drive, expose a temporary viewer link, and return cleanup."""
    try:
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaFileUpload
    except ImportError as exc:
        raise RuntimeError("Google Drive publishing dependencies are missing. Install requirements.txt.") from exc
    drive = build("drive", "v3", credentials=_instagram_drive_credentials(interactive=False))
    uploaded = drive.files().create(
        body={"name": video.name, "mimeType": "video/mp4"},
        media_body=MediaFileUpload(str(video), mimetype="video/mp4", resumable=True),
        fields="id",
    ).execute()
    file_id = uploaded.get("id")
    if not file_id:
        raise RuntimeError("Google Drive upload completed without returning a file ID")
    try:
        drive.permissions().create(
            fileId=file_id,
            body={"type": "anyone", "role": "reader"},
            fields="id",
        ).execute()
        metadata = drive.files().get(
            fileId=file_id, fields="webContentLink,resourceKey",
        ).execute()
        video_url = metadata.get("webContentLink")
        if not video_url:
            raise RuntimeError("Google Drive did not return a direct download URL for the uploaded video")
        resource_key = metadata.get("resourceKey")
        if resource_key:
            separator = "&" if "?" in video_url else "?"
            video_url = f"{video_url}{separator}resourcekey={quote(resource_key)}"
    except Exception:
        drive.files().delete(fileId=file_id).execute()
        raise

    def delete_staged_video() -> None:
        drive.files().delete(fileId=file_id).execute()

    return video_url, delete_staged_video


def _tunnel_instagram_video(video: Path) -> tuple[str, Callable[[], None]]:
    """Serve only this video over an ephemeral Cloudflare Quick Tunnel."""
    cloudflared = shutil.which("cloudflared")
    if not cloudflared:
        raise RuntimeError(
            "Instagram no-card upload needs cloudflared installed and available on PATH. "
            "On Windows, install it with `winget install --id Cloudflare.cloudflared`."
        )

    route = "/" + secrets.token_urlsafe(24) + (video.suffix.lower() or ".mp4")

    class VideoHandler(BaseHTTPRequestHandler):
        def log_message(self, *_args) -> None:
            pass

        def _send_video(self, include_body: bool) -> None:
            if self.path.split("?", 1)[0] != route:
                self.send_error(404)
                return
            size = video.stat().st_size
            start, end, status_code = 0, size - 1, 200
            range_header = self.headers.get("Range", "")
            match = re.fullmatch(r"bytes=(\d*)-(\d*)", range_header.strip()) if range_header else None
            if match:
                left, right = match.groups()
                if left:
                    start = int(left)
                    end = min(int(right), size - 1) if right else size - 1
                elif right:
                    start = max(0, size - int(right))
                if start >= size or start > end:
                    self.send_response(416)
                    self.send_header("Content-Range", f"bytes */{size}")
                    self.end_headers()
                    return
                status_code = 206
            length = end - start + 1
            self.send_response(status_code)
            self.send_header("Content-Type", mimetypes.guess_type(video.name)[0] or "video/mp4")
            self.send_header("Content-Length", str(length))
            self.send_header("Accept-Ranges", "bytes")
            if status_code == 206:
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.end_headers()
            if include_body:
                with video.open("rb") as source:
                    source.seek(start)
                    remaining = length
                    while remaining:
                        chunk = source.read(min(1024 * 1024, remaining))
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                        remaining -= len(chunk)

        def do_GET(self) -> None:
            self._send_video(True)

        def do_HEAD(self) -> None:
            self._send_video(False)

    server = ThreadingHTTPServer(("127.0.0.1", 0), VideoHandler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    local_url = f"http://127.0.0.1:{server.server_port}"
    try:
        process = subprocess.Popen(
            [cloudflared, "tunnel", "--no-autoupdate", "--url", local_url],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            encoding="utf-8", errors="replace", bufsize=1,
            **({"creationflags": subprocess.CREATE_NO_WINDOW} if hasattr(subprocess, "CREATE_NO_WINDOW") else {}),
        )
    except Exception:
        server.shutdown()
        server.server_close()
        raise

    def stop_tunnel() -> None:
        server.shutdown()
        server.server_close()
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)

    lines: queue.Queue[str | None] = queue.Queue()

    def read_output() -> None:
        try:
            for line in process.stdout or ():
                lines.put(line.rstrip())
        finally:
            lines.put(None)

    threading.Thread(target=read_output, daemon=True).start()
    deadline = time.monotonic() + 45
    public_url = ""
    while time.monotonic() < deadline:
        if process.poll() is not None:
            break
        try:
            line = lines.get(timeout=min(1.0, max(0.05, deadline - time.monotonic())))
        except queue.Empty:
            continue
        if line is None:
            break
        match = re.search(r"https://[a-z0-9-]+\.trycloudflare\.com", line, re.IGNORECASE)
        if match:
            public_url = match.group(0)
            break
    if not public_url:
        stop_tunnel()
        raise RuntimeError("Cloudflare Quick Tunnel did not provide a public URL within 45 seconds.")

    # A generated tunnel hostname can exist before DNS and ingress are ready.
    # Verify the exact one-byte media response before asking Instagram to fetch it.
    ready_deadline = time.monotonic() + 90
    last_error = "tunnel is not reachable yet"
    while time.monotonic() < ready_deadline:
        try:
            response = requests.get(
                public_url + route,
                headers={"Range": "bytes=0-0"},
                timeout=(3, 6),
                stream=True,
            )
            content_type = response.headers.get("Content-Type", "").lower()
            if response.status_code == 206 and content_type.startswith("video/"):
                response.close()
                break
            last_error = f"tunnel returned HTTP {response.status_code} with content type {content_type or 'unknown'}"
            response.close()
        except requests.RequestException as exc:
            last_error = f"{type(exc).__name__}: {exc}"
        time.sleep(1)
    else:
        stop_tunnel()
        raise RuntimeError(f"Cloudflare Quick Tunnel did not become reachable for the MP4: {last_error}")

    return public_url + route, stop_tunnel


def publish_instagram(video: Path, social: dict, explicit_video_url: str = "") -> dict:
    ig_user_id = config.INSTAGRAM_BUSINESS_ACCOUNT_ID
    if not ig_user_id:
        raise RuntimeError("Set INSTAGRAM_BUSINESS_ACCOUNT_ID in .env to your Instagram account ID.")
    token = _instagram_access_token()

    video_url, delete_staged_video = _instagram_video_url(video, explicit_video_url)
    try:
        base = f"https://graph.instagram.com/{config.INSTAGRAM_GRAPH_VERSION}"
        created = _instagram_request("POST", f"{base}/{ig_user_id}/media", data={
            "media_type": "REELS",
            "video_url": video_url,
            "caption": social["instagram"]["caption"],
            "share_to_feed": "true",
            "access_token": token,
        })
        container_id = created.get("id") or created.get("container_id")
        if not container_id:
            raise RuntimeError("Instagram did not return a Reel container ID")

        deadline = time.monotonic() + 300
        while time.monotonic() < deadline:
            status = _instagram_request("GET", f"{base}/{container_id}", params={
                "fields": "status_code,status", "access_token": token,
            })
            state = status.get("status_code", "").upper()
            if state == "FINISHED":
                break
            if state == "ERROR":
                detail = status.get("video_status") or status.get("status") or status
                raise RuntimeError(f"Instagram Reel processing failed: {detail}")
            time.sleep(5)
        else:
            raise TimeoutError("Instagram Reel is still processing after five minutes; retry after checking the container status")
        published = _instagram_request("POST", f"{base}/{ig_user_id}/media_publish", data={
            "creation_id": container_id, "access_token": token,
        })
        media_id = published.get("id")
        if not media_id:
            raise RuntimeError("Instagram publish completed without returning a media ID")
        result = {"id": media_id, "container_id": container_id, "status": "published"}
        _record(video, "instagram", result)
        return result
    finally:
        if delete_staged_video:
            try:
                delete_staged_video()
            except Exception:
                log("Instagram publishing ended, but temporary upload cleanup failed. Check the tunnel process or storage bucket.")


def _facebook_token_expired(payload: dict) -> bool:
    error = payload.get("error", {}) if isinstance(payload, dict) else {}
    if not isinstance(error, dict):
        return False
    code = error.get("code")
    message = str(error.get("message") or "").lower()
    return code == 190 or "session has expired" in message or "access token has expired" in message


def _reauthorize_and_retry_facebook(video: Path, social: dict, payload: dict,
                                    status_code: int, stage: str, retry: bool) -> dict:
    if not _facebook_token_expired(payload):
        error = payload.get("error", {}) if isinstance(payload, dict) else {}
        message = error.get("message") if isinstance(error, dict) else str(error)
        raise RuntimeError(f"Facebook Reel {stage} failed ({status_code}): {message or 'unknown API error'}")
    if not retry:
        raise RuntimeError(
            f"Facebook token renewal did not resolve the expired token during {stage}. "
            "Check app permissions and Page access, then run `python run.py connect-facebook`."
        )
    log("Facebook Page token expired; opening Meta login to renew it before retrying the Reel upload …")
    connect_facebook_page()
    return publish_facebook(video, social, _auth_retry=False)


def publish_facebook(video: Path, social: dict, _auth_retry: bool = True) -> dict:
    """Upload a local MP4 and publish it as a Facebook Page Reel."""
    token = _facebook_page_token()
    if not token or not config.FACEBOOK_PAGE_ID:
        raise RuntimeError(
            "Set FACEBOOK_PAGE_ID and a Page token in .env, or configure FACEBOOK_APP_ID/FACEBOOK_APP_SECRET "
            "and run `python run.py connect-facebook` to authorize the Page."
        )
    base = f"https://graph.facebook.com/{config.FACEBOOK_GRAPH_VERSION}"
    started = requests.post(f"{base}/{config.FACEBOOK_PAGE_ID}/video_reels", data={
        "upload_phase": "start", "access_token": token,
    }, timeout=60)
    try:
        session = started.json()
    except ValueError:
        session = {}
    if not started.ok or "error" in session:
        return _reauthorize_and_retry_facebook(video, social, session, started.status_code,
                                               "upload initialization", _auth_retry)
    video_id = session.get("video_id")
    upload_url = session.get("upload_url")
    if not video_id or not upload_url:
        raise RuntimeError("Facebook did not return the Reel upload session details")

    size = video.stat().st_size
    with video.open("rb") as media:
        uploaded = requests.post(upload_url, headers={
            "Authorization": f"OAuth {token}",
            "offset": "0",
            "file_size": str(size),
            "Content-Type": "application/octet-stream",
        }, data=media, timeout=(60, 900))
    try:
        upload_result = uploaded.json()
    except ValueError:
        upload_result = {}
    if not uploaded.ok or upload_result.get("success") is not True:
        return _reauthorize_and_retry_facebook(video, social, upload_result, uploaded.status_code,
                                               "media upload", _auth_retry)

    metadata = social["facebook"]
    finished = requests.post(f"{base}/{config.FACEBOOK_PAGE_ID}/video_reels", data={
        "upload_phase": "finish",
        "video_state": "PUBLISHED",
        "video_id": video_id,
        "title": metadata["title"],
        "description": metadata["description"],
        "access_token": token,
    }, timeout=60)
    try:
        finish_result = finished.json()
    except ValueError:
        finish_result = {}
    if not finished.ok or finish_result.get("success") is not True or "error" in finish_result:
        return _reauthorize_and_retry_facebook(video, social, finish_result, finished.status_code,
                                               "publishing", _auth_retry)
    result = {"id": video_id, "status": "published", "title": metadata["title"]}
    _record(video, "facebook", result)
    return result


def publish(video_path: Path, script_path: Path | None = None, article_path: Path | None = None,
            platforms: tuple[str, ...] = ("youtube", "instagram"), privacy_status: str = "private",
            instagram_video_url: str = "", confirm: bool = False) -> dict:
    video = video_path.resolve()
    if video.is_dir():
        video = video / "final.mp4"
    if not video.is_file():
        raise FileNotFoundError(f"Video file not found: {video}")
    if not confirm:
        raise RuntimeError("Publishing requires --confirm. Review the platform copy with --dry-run first.")
    if any(p not in ("youtube", "instagram", "facebook", "x") for p in platforms):
        raise ValueError("Platforms must be youtube, instagram, facebook, and/or x")
    script_file = script_path or video.parent / "script.json"
    if not script_file.is_file():
        raise FileNotFoundError(f"Script metadata not found next to video: {script_file}")
    manifest_path = video.parent / "manifest.json"
    manifest = read_json(manifest_path) if manifest_path.exists() else {}
    script = Script.model_validate(read_json(script_file), context={
        "allow_extended_storyboard": bool(manifest.get("extended_storyboard"))})
    article_file = article_path or video.parent / "article.json"
    article = read_json(article_file) if article_file.is_file() else {}
    social = build_social_copy(script, article)
    results = {}
    for platform in platforms:
        if platform == "youtube":
            results[platform] = publish_youtube(video, social, privacy_status)
        elif platform == "instagram":
            results[platform] = publish_instagram(video, social, instagram_video_url)
        elif platform == "x":
            results[platform] = publish_x(video, social)
        else:
            results[platform] = publish_facebook(video, social)
    return results


def auto_publish(video_path: Path) -> dict:
    """Publish automatically only for explicitly enabled platform names in .env."""
    platforms = tuple(p for p in ("youtube", "instagram", "facebook", "x") if p in config.AUTO_PUBLISH_PLATFORMS)
    if not platforms:
        return {}
    unknown = config.AUTO_PUBLISH_PLATFORMS - {"youtube", "instagram", "facebook", "x"}
    if unknown:
        raise ValueError(f"Unsupported AUTO_PUBLISH_PLATFORMS values: {', '.join(sorted(unknown))}")
    return publish(video_path, platforms=platforms,
                   privacy_status=config.AUTO_PUBLISH_YOUTUBE_PRIVACY, confirm=True)
