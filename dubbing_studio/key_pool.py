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
import logging
import threading
from typing import List, Set, Optional, Dict, Any

logger = logging.getLogger("dubbing_studio.key_pool")

_POOL_LOCK = threading.Lock()
_RUNTIME_DEAD_GEMINI_KEYS: Set[str] = set()
_RUNTIME_DEAD_SARVAM_KEYS: Set[str] = set()
_RUNTIME_DEAD_ELEVENLABS_KEYS: Set[str] = set()


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


def get_active_elevenlabs_keys() -> List[str]:
    """Retrieve all currently active, non-exhausted ElevenLabs API keys in the runtime pool."""
    with _POOL_LOCK:
        raw = get_raw_elevenlabs_keys()
        active = [k for k in raw if k not in _RUNTIME_DEAD_ELEVENLABS_KEYS]
        return active


def mark_elevenlabs_key_dead(key: str, reason: str = "") -> None:
    """
    Evict an ElevenLabs key from the in-memory runtime pool for the entire session.
    Strictly leaves .env and os.environ untouched.
    """
    if not key:
        return
    k_clean = key.strip()
    with _POOL_LOCK:
        if k_clean not in _RUNTIME_DEAD_ELEVENLABS_KEYS:
            _RUNTIME_DEAD_ELEVENLABS_KEYS.add(k_clean)
            raw = get_raw_elevenlabs_keys()
            active_count = len([k for k in raw if k not in _RUNTIME_DEAD_ELEVENLABS_KEYS])
            msg = (
                f"[Key Pool] Evicted dead ElevenLabs key ({mask_key(k_clean)}) from runtime pool! "
                f"Reason: {reason or 'quota/subscription exhausted'}. Active keys remaining: {active_count}/{len(raw)}"
            )
            print(msg)
            logger.warning(msg)


def is_elevenlabs_dead_error(err_str: str) -> bool:
    """
    Determine if an error indicates that the ElevenLabs key should be evicted:
    - 401 Unauthorized / Invalid API Key
    - 402 / 429 Quota Exceeded / Out of character credits
    """
    if not err_str:
        return False
    err_lower = err_str.lower()
    # Library voice permission error or paid plan requirement for community voice is not a key exhaustion error
    if any(sig in err_lower for sig in ("library voice", "library_voice", "paid_plan_required")):
        return False
    dead_signals = [
        "quota_exceeded",
        "quota exceeded",
        "insufficient_credits",
        "character limit reached",
        "out of credits",
        "401",
        "invalid_api_key",
        "invalid api key",
        "unauthorized",
        "exceeded your quota",
    ]
    return any(sig in err_lower for sig in dead_signals)




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
        dead_e = len(_RUNTIME_DEAD_ELEVENLABS_KEYS)
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
                "active": max(0, len(raw_e) - dead_e),
                "dead": dead_e,
            }
        }
