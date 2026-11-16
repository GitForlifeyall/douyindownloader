#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
dubbing_studio/key_pool.py
==========================
Centralized Thread-Safe Runtime Key Pool & Eviction Manager.

Features:
- Instant runtime eviction of dead or quota-exhausted keys (Gemini 429/400/403, Sarvam 402/401).
- Strictly preserves .env and OS environment variables (zero file modifications).
- Prevents infinite loops and wasted retry cycles across all pipeline stages.
- Shared across all workers, threads, and modules for the entire process lifetime.
"""

import os
import re
import json
import hashlib
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Set, Optional, Dict, Any

logger = logging.getLogger("dubbing_studio.key_pool")

_POOL_LOCK = threading.Lock()
_RUNTIME_DEAD_GEMINI_KEYS: Set[str] = set()
_RUNTIME_DEAD_SARVAM_KEYS: Set[str] = set()
_RUNTIME_DEAD_ELEVENLABS_KEYS: Set[str] = set()
_RUNTIME_DEAD_ELEVENLABS_HASHES: Dict[str, Dict[str, str]] = {}

_EXHAUSTED_ELEVENLABS_STORE = Path(__file__).resolve().parent.parent / "config" / "exhausted_elevenlabs_keys.json"


def _hash_key(key: str) -> str:
    """Return stable SHA-256 hex digest of an API key so secrets are never stored in cache files."""
    return hashlib.sha256(key.strip().encode("utf-8")).hexdigest()


def _load_exhausted_elevenlabs_store() -> None:
    """Load persisted exhausted ElevenLabs key hashes without modifying .env."""
    if not _EXHAUSTED_ELEVENLABS_STORE.is_file():
        return
    try:
        data = json.loads(_EXHAUSTED_ELEVENLABS_STORE.read_text(encoding="utf-8"))
        entries = data.get("exhausted_keys", data) if isinstance(data, dict) else {}
        if isinstance(entries, dict):
            for h, meta in entries.items():
                if isinstance(h, str) and len(h) == 64:
                    _RUNTIME_DEAD_ELEVENLABS_HASHES[h] = meta if isinstance(meta, dict) else {}
    except Exception as e:
        logger.debug(f"[Key Pool] Could not load exhausted ElevenLabs store: {e}")


def _save_exhausted_elevenlabs_store() -> None:
    """Persist exhausted ElevenLabs key hashes atomically while leaving .env untouched."""
    try:
        _EXHAUSTED_ELEVENLABS_STORE.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "note": "Persisted local blocklist of exhausted ElevenLabs keys (SHA-256 hashes). .env is never modified.",
            "exhausted_keys": _RUNTIME_DEAD_ELEVENLABS_HASHES,
        }
        tmp = _EXHAUSTED_ELEVENLABS_STORE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp.replace(_EXHAUSTED_ELEVENLABS_STORE)
    except Exception as e:
        logger.debug(f"[Key Pool] Could not save exhausted ElevenLabs store: {e}")


_load_exhausted_elevenlabs_store()


def mask_key(key: str) -> str:
    """Mask key for safe logging (e.g., AIzaSy...3F2a)."""
    if not key:
        return "<none>"
    k = key.strip()
    if len(k) <= 8:
        return "..." + k[-3:]
    return f"{k[:7]}...{k[-4:]}"


# =====================================================================
#  GEMINI KEY MANAGEMENT
# =====================================================================

def get_raw_gemini_keys() -> List[str]:
    """Retrieve all declared Gemini API keys from environment without filtering."""
    keys: List[str] = []
    env_keys = os.environ.get("GEMINI_API_KEYS", "")
    for k in env_keys.split(","):
        k = k.strip()
        if k and k not in keys:
            keys.append(k)
    single_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if single_key and single_key not in keys:
        keys.insert(0, single_key)
    return keys


def get_active_gemini_keys() -> List[str]:
    """Retrieve all currently active, non-exhausted Gemini API keys in the runtime pool."""
    with _POOL_LOCK:
        raw = get_raw_gemini_keys()
        active = [k for k in raw if k not in _RUNTIME_DEAD_GEMINI_KEYS]
        return active


def mark_gemini_key_dead(key: str, reason: str = "") -> None:
    """
    Evict a Gemini key from the in-memory runtime pool for the entire session.
    Strictly leaves .env and os.environ untouched.
    """
    if not key:
        return
    k_clean = key.strip()
    with _POOL_LOCK:
        if k_clean not in _RUNTIME_DEAD_GEMINI_KEYS:
            _RUNTIME_DEAD_GEMINI_KEYS.add(k_clean)
            raw = get_raw_gemini_keys()
            active_count = len([k for k in raw if k not in _RUNTIME_DEAD_GEMINI_KEYS])
            msg = (
                f"[Key Pool] Evicted dead Gemini key ({mask_key(k_clean)}) from runtime pool! "
                f"Reason: {reason or 'quota/exhaustion'}. Active keys remaining: {active_count}/{len(raw)}"
            )
            print(msg)
            logger.warning(msg)


def is_gemini_dead_error(err_str: str) -> bool:
    """
    Determine if an error indicates that the Gemini key should be evicted:
    - 429 RESOURCE_EXHAUSTED (Quota / Plan limit reached)
    - 400 API_KEY_INVALID (Invalid or malformed key)
    - 403 PERMISSION_DENIED / CONSUMER_SUSPENDED
    """
    if not err_str:
        return False
    err_lower = err_str.lower()
    quota_signals = [
        "resource_exhausted",
        "quota exceeded",
        "exceeded your current quota",
        "billing details",
        "check your plan",
        "api_key_invalid",
        "api key not valid",
        "invalid api key",
        "permission_denied",
        "consumer_suspended",
    ]
    if any(sig in err_lower for sig in quota_signals):
        return True
    if "429" in err_str and ("quota" in err_lower or "plan" in err_lower or "limit" in err_lower or "resource" in err_lower):
        return True
    if "400" in err_str and ("api_key_invalid" in err_lower or "api key not valid" in err_lower or "invalid api key" in err_lower):
        return True
    if "403" in err_str:
        return True
    return False


# =====================================================================
#  SARVAM KEY MANAGEMENT
# =====================================================================

def get_raw_sarvam_keys() -> List[str]:
    """Retrieve all declared Sarvam API keys from environment without filtering."""
    keys: List[str] = []
    env_keys = os.getenv("SARVAM_API_KEYS", "")
    for k in env_keys.split(","):
        k = k.strip()
        if k and k not in keys:
            keys.append(k)
    single_key = os.getenv("SARVAM_API_KEY", "").strip()
    if single_key and single_key not in keys:
        keys.append(single_key)
    return keys


def get_active_sarvam_keys() -> List[str]:
    """Retrieve all currently active, non-exhausted Sarvam API keys in the runtime pool."""
    with _POOL_LOCK:
        raw = get_raw_sarvam_keys()
        active = [k for k in raw if k not in _RUNTIME_DEAD_SARVAM_KEYS]
        return active


def mark_sarvam_key_dead(key: str, reason: str = "") -> None:
    """
    Evict a Sarvam key from the in-memory runtime pool for the entire session.
    Strictly leaves .env and os.environ untouched.
    """
    if not key:
        return
    k_clean = key.strip()
    with _POOL_LOCK:
        if k_clean not in _RUNTIME_DEAD_SARVAM_KEYS:
            _RUNTIME_DEAD_SARVAM_KEYS.add(k_clean)
            raw = get_raw_sarvam_keys()
            active_count = len([k for k in raw if k not in _RUNTIME_DEAD_SARVAM_KEYS])
            msg = (
                f"[Key Pool] Evicted dead Sarvam key ({mask_key(k_clean)}) from runtime pool! "
                f"Reason: {reason or 'insufficient quota/credits'}. Active keys remaining: {active_count}/{len(raw)}"
            )
            print(msg)
            logger.warning(msg)


def is_sarvam_dead_error(err_str: str) -> bool:
    """
    Determine if an error indicates that the Sarvam key should be evicted:
    - 402 Insufficient Quota / No credits
    - 401 Unauthorized / Invalid subscription key
    - 403 Forbidden
    """
    if not err_str:
        return False
    err_lower = err_str.lower()
    dead_signals = [
        "402",
        "insufficient_quota",
        "insufficient credits",
        "no credits available",
        "recharge your balance",
        "invalid subscription key",
        "unauthorized",
        "401",
        "forbidden",
        "403",
    ]
    return any(sig in err_lower for sig in dead_signals)


# =====================================================================
#  ELEVENLABS KEY MANAGEMENT
# =====================================================================

def get_raw_elevenlabs_keys() -> List[str]:
    """Retrieve all declared ElevenLabs API keys from environment without filtering."""
    keys: List[str] = []
    env_keys = os.getenv("ELEVENLABS_API_KEYS", "")
    for k in env_keys.split(","):
        k = k.strip()
        if k and k not in keys:
            keys.append(k)
    single_key = os.getenv("ELEVENLABS_API_KEY", "").strip()
    if single_key and single_key not in keys:
        keys.append(single_key)
    return keys


def _is_elevenlabs_key_dead_unlocked(key: str) -> bool:
    k_clean = key.strip()
    if k_clean in _RUNTIME_DEAD_ELEVENLABS_KEYS:
        return True
    return _hash_key(k_clean) in _RUNTIME_DEAD_ELEVENLABS_HASHES


def get_active_elevenlabs_keys() -> List[str]:
    """Retrieve all currently active, non-exhausted ElevenLabs API keys in the local pool."""
    with _POOL_LOCK:
        raw = get_raw_elevenlabs_keys()
        active = [k for k in raw if not _is_elevenlabs_key_dead_unlocked(k)]
        return active


def mark_elevenlabs_key_dead(key: str, reason: str = "") -> None:
    """
    Evict an ElevenLabs key from the local runtime & persisted pool so it is
    never re-read for subsequent blocks or videos. Strictly leaves .env untouched.
    """
    if not key:
        return
    k_clean = key.strip()
    k_hash = _hash_key(k_clean)
    with _POOL_LOCK:
        is_new = (k_clean not in _RUNTIME_DEAD_ELEVENLABS_KEYS) and (k_hash not in _RUNTIME_DEAD_ELEVENLABS_HASHES)
        _RUNTIME_DEAD_ELEVENLABS_KEYS.add(k_clean)
        if k_hash not in _RUNTIME_DEAD_ELEVENLABS_HASHES:
            _RUNTIME_DEAD_ELEVENLABS_HASHES[k_hash] = {
                "masked": mask_key(k_clean),
                "reason": (reason or "quota/subscription exhausted")[:200],
                "evicted_at": datetime.now(timezone.utc).isoformat(),
            }
            _save_exhausted_elevenlabs_store()
        if is_new:
            raw = get_raw_elevenlabs_keys()
            active_count = len([k for k in raw if not _is_elevenlabs_key_dead_unlocked(k)])
            msg = (
                f"[Key Pool] Removed exhausted ElevenLabs key ({mask_key(k_clean)}) from local pool "
                f"(.env untouched). Reason: {reason or 'quota/subscription exhausted'}. "
                f"Active keys remaining: {active_count}/{len(raw)}"
            )
            print(msg)
            logger.warning(msg)


def reset_exhausted_elevenlabs_keys() -> int:
    """Clear the local persisted blocklist of exhausted ElevenLabs keys (e.g., after billing reset)."""
    with _POOL_LOCK:
        cleared = len(_RUNTIME_DEAD_ELEVENLABS_HASHES) + len(_RUNTIME_DEAD_ELEVENLABS_KEYS)
        _RUNTIME_DEAD_ELEVENLABS_KEYS.clear()
        _RUNTIME_DEAD_ELEVENLABS_HASHES.clear()
        if _EXHAUSTED_ELEVENLABS_STORE.exists():
            try:
                _EXHAUSTED_ELEVENLABS_STORE.unlink()
            except Exception:
                pass
        return cleared


def is_elevenlabs_dead_error(
    err_str: str,
    status_code: Optional[int] = None,
    body: Any = None,
) -> bool:
    """
    Determine if an ElevenLabs error indicates that the key is exhausted/invalid
    and should be removed from the local pool (while ignoring transient concurrency limits).
    """
    parts = [str(err_str or "")]
    if status_code is not None:
        parts.append(f"status_code={status_code}")
    if body is not None:
        parts.append(str(body))
    combined_lower = " ".join(parts).lower()
    if not combined_lower.strip():
        return False

    # Library voice permission error or paid plan requirement for community voice is not a key exhaustion error
    if any(sig in combined_lower for sig in ("library voice", "library_voice", "paid_plan_required")):
        return False
    # Transient concurrency / server busy errors should rotate without killing the key
    if any(sig in combined_lower for sig in ("too_many_concurrent_requests", "system_busy", "concurrent requests")):
        return False

    if status_code in (401, 402):
        return True

    dead_signals = [
        "quota_exceeded",
        "quota exceeded",
        "insufficient_credits",
        "character limit reached",
        "out of credits",
        "status_code: 401",
        "status_code: 402",
        "401",
        "402",
        "invalid_api_key",
        "invalid api key",
        "unauthorized",
        "exceeded your quota",
        "detected_unusual_activity",
        "free tier access has been disabled",
        "subscription_not_active",
    ]
    return any(sig in combined_lower for sig in dead_signals)




# =====================================================================
#  POOL STATUS & DIAGNOSTICS
# =====================================================================

def get_pool_status() -> Dict[str, Any]:
    """Get active key counts and dead key stats for Gemini, Sarvam, and ElevenLabs."""
    with _POOL_LOCK:
        raw_g = get_raw_gemini_keys()
        dead_g = len(_RUNTIME_DEAD_GEMINI_KEYS)
        raw_s = get_raw_sarvam_keys()
        dead_s = len(_RUNTIME_DEAD_SARVAM_KEYS)
        raw_e = get_raw_elevenlabs_keys()
        active_e = len([k for k in raw_e if not _is_elevenlabs_key_dead_unlocked(k)])
        dead_e = max(0, len(raw_e) - active_e)
        return {
            "gemini": {
                "total": len(raw_g),
                "active": max(0, len(raw_g) - dead_g),
                "dead": dead_g,
            },
            "sarvam": {
                "total": len(raw_s),
                "active": max(0, len(raw_s) - dead_s),
                "dead": dead_s,
            },
            "elevenlabs": {
                "total": len(raw_e),
                "active": active_e,
                "dead": dead_e,
            }
        }
