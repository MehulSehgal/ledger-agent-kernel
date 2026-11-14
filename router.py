"""Client-side model routing, retries, reservations, and demo chaos controls."""
from contextlib import contextmanager
from contextvars import ContextVar
import hashlib
import os
import re
import threading
import time

import httpx

from policy import ConfidentialViolation


MAX_OUTPUT_TOKENS = 512
RETRY_BACKOFF_SECONDS = 0.25
_chaos = {}
_chaos_lock = threading.Lock()
_ROUTE_CONTEXT = ContextVar("ledger_route_context", default=None)


@contextmanager
def route_context(*, local_chain=None, local_providers=None, model_post=None):
    context = dict(_ROUTE_CONTEXT.get() or {})
    if local_chain is not None:
        context["local_chain"] = tuple(local_chain)
    if local_providers is not None:
        context["local_providers"] = frozenset(
            provider.casefold() for provider in local_providers
        )
    if model_post is not None:
        context["model_post"] = model_post
    token = _ROUTE_CONTEXT.set(context)
    try:
        yield
    finally:
        _ROUTE_CONTEXT.reset(token)


def _model_post(url, **kwargs):
    context = _ROUTE_CONTEXT.get() or {}
    post = context.get("model_post")
    if post is not None:
        return post(url, **kwargs)
    return httpx.post(url, **kwargs)


class _AttemptFailure(Exception):
    def __init__(self, message, retryable, status=None, simulated=False):
        super().__init__(message)
        self.retryable = retryable
        self.status = status
        self.simulated = simulated


def _chain(tier):
    configured = os.getenv(f"LEDGER_CHAIN_{tier.upper()}")
    if configured:
        models = [item.strip() for item in configured.split(",") if item.strip()]
    else:
        models = [os.getenv(
            f"LEDGER_{tier.upper()}",
            "openai/gpt-4o-mini" if tier == "cheap" else "anthropic/claude-sonnet-4-5",
        )]
    return list(dict.fromkeys(models))


def _provider(model):
    if not isinstance(model, str) or "/" not in model:
        return None
    provider, name = model.split("/", 1)
    if not provider.strip() or not name.strip():
        return None
    return provider.strip().casefold()


def _confidential_violation(run, message):
    run.emit("blocked", {
        "kind": "NETWORK",
        "reason": message,
        "source": "confidential",
    })
    raise ConfidentialViolation(message)


def _local_chain(run):
    context = _ROUTE_CONTEXT.get() or {}
    if "local_chain" in context:
        models = list(dict.fromkeys(context["local_chain"]))
    else:
        models = list(dict.fromkeys(
            item.strip()
            for item in os.getenv("LEDGER_LOCAL_CHAIN", "").split(",")
            if item.strip()
        ))
    if "local_providers" in context:
        providers = set(context["local_providers"])
    else:
        providers = {
            item.strip().casefold()
            for item in os.getenv("LOCAL_PROVIDERS", "").split(",")
            if item.strip()
        }
    if not models:
        _confidential_violation(
            run,
            "No local model is configured in LEDGER_LOCAL_CHAIN; confidential request failed closed.",
        )
    if not providers:
        _confidential_violation(
            run,
            "No local model providers are configured in LOCAL_PROVIDERS.",
        )
    for model in models:
        if _provider(model) not in providers:
            _confidential_violation(
                run,
                f"Model provider for {model!r} is not in LOCAL_PROVIDERS.",
            )
    return models, providers


def _api_key(user_id, confidential=False):
    if confidential:
        return os.getenv("BIFROST_VK_LOCAL")
    suffix = re.sub(r"[^A-Za-z0-9_]", "_", user_id).upper()
    return os.getenv(f"LEDGER_VK_{suffix}") or os.getenv("BIFROST_VK")


def configure_chaos(target, mode):
    if mode not in ("down", "slow", "429", "off"):
        raise ValueError("chaos mode must be down, slow, 429, or off")
    if os.getenv("LEDGER_DEMO") != "1":
        raise PermissionError("chaos mode requires LEDGER_DEMO=1")
    with _chaos_lock:
        if mode == "off":
            _chaos.pop(target, None)
        else:
            _chaos[target] = mode


def _chaos_mode(model):
    if os.getenv("LEDGER_DEMO") != "1":
        return None
    with _chaos_lock:
        return _chaos.get(model)


def _actual_model(payload, requested_model):
    extra_fields = payload.get("extra_fields")
    if not isinstance(extra_fields, dict):
        return requested_model
    routing_info = extra_fields.get("routing_info")
    if not isinstance(routing_info, dict):
        return requested_model
    provider = routing_info.get("provider")
    model = routing_info.get("model")
    if not isinstance(provider, str) or not provider or not isinstance(model, str) or not model:
        return requested_model
    return f"{provider}/{model}"


def _response_failure(response):
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        return _AttemptFailure(
            f"HTTP {status}",
            retryable=status == 429 or 500 <= status <= 599,
            status=status,
        )
    return None


def _simulate_chaos(mode):
    if mode == "429":
        return _AttemptFailure("HTTP 429", retryable=True, status=429, simulated=True)
    if mode == "slow":
        return _AttemptFailure("request timed out", retryable=True, status=504, simulated=True)
    return _AttemptFailure("connection unavailable", retryable=True, simulated=True)


def complete(run, meter, label, tier, system, user, user_id=None):
    from kernel import GatewayError, tok

    if meter.run is not run:
        meter.run = run
    confidential = meter.refresh_confidential()
    local_models, local_providers = _local_chain(run) if confidential else (None, None)
    user_id = user_id or meter.user_id or "default"
    if meter.user_id is None:
        meter.user_id = user_id
        if meter.user_cap is None:
            try:
                meter.user_cap = int(os.getenv("LEDGER_USER_CAP", "12000"))
            except ValueError as exc:
                raise ValueError("LEDGER_USER_CAP must be a positive integer") from exc
        if meter.user_cap <= 0:
            raise ValueError("LEDGER_USER_CAP must be a positive integer")

    cache_key = hashlib.sha256(
        f"{int(confidential)}\0{label}\0{system}\0{user}".encode("utf-8")
    ).hexdigest()
    cached = run.get_cached(cache_key)
    if cached is not None:
        if confidential and _provider(cached["model"]) not in local_providers:
            _confidential_violation(
                run,
                "A non-local cached model response is blocked for this confidential request.",
            )
        meter.log(
            label,
            cached["tier"],
            0,
            0,
            model=cached["model"],
            cached=True,
        )
        return cached["content"]

    reservation = meter.reserve(
        est_in=tok(system + user),
        max_out=MAX_OUTPUT_TOKENS,
        tier=tier,
    )
    models = local_models if confidential else _chain(reservation.tier)
    if not models:
        meter.release(reservation)
        raise GatewayError("No Bifrost models are configured for this tier.")

    key = _api_key(user_id, confidential=confidential)
    if confidential and not key:
        meter.release(reservation)
        _confidential_violation(
            run,
            "BIFROST_VK_LOCAL is not configured for confidential local-model routing.",
        )
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    base_url = os.getenv("BIFROST_URL", "").rstrip("/")
    if not base_url:
        meter.release(reservation)
        if confidential:
            _confidential_violation(
                run,
                "BIFROST_URL is not configured for confidential local-model routing.",
            )
        raise GatewayError("BIFROST_URL is not configured.")

    requested_model = models[0]
    last_error = None
    last_failure_reason = None
    chaos_failed = False
    answer = None
    actual_model = requested_model
    usage = {}
    stop_chain = False
    for model_index, model in enumerate(models):
        if confidential and _provider(model) not in local_providers:
            meter.release(reservation)
            _confidential_violation(
                run,
                f"Model provider for {model!r} is not in LOCAL_PROVIDERS.",
            )
        for attempt in range(2):
            simulated_mode = _chaos_mode(model)
            if simulated_mode:
                failure = _simulate_chaos(simulated_mode)
            else:
                request_body = {
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    "fallbacks": models[model_index + 1:],
                    "max_tokens": reservation.max_tokens,
                }
                try:
                    response = _model_post(
                        base_url + "/v1/chat/completions",
                        timeout=90,
                        headers=headers,
                        json=request_body,
                    )
                except httpx.HTTPStatusError as exc:
                    status = exc.response.status_code
                    failure = _AttemptFailure(
                        f"HTTP {status}",
                        retryable=status == 429 or 500 <= status <= 599,
                        status=status,
                    )
                    last_error = exc
                except (httpx.TimeoutException, httpx.TransportError) as exc:
                    failure = _AttemptFailure(str(exc), retryable=True)
                    last_error = exc
                except GatewayError as exc:
                    failure = _AttemptFailure(str(exc), retryable=True)
                    last_error = exc
                else:
                    failure = _response_failure(response)
                    if failure is None:
                        try:
                            payload = response.json()
                            if not isinstance(payload, dict):
                                raise ValueError("response must be an object")
                            candidate_answer = payload["choices"][0]["message"]["content"]
                            if not isinstance(candidate_answer, str):
                                raise TypeError("response content must be text")
                            candidate_model = _actual_model(payload, model)
                            if confidential and _provider(candidate_model) not in local_providers:
                                meter.release(reservation)
                                _confidential_violation(
                                    run,
                                    f"Actual model provider for {candidate_model!r} is not local.",
                                )
                            answer = candidate_answer
                            actual_model = candidate_model
                            usage = payload.get("usage", {})
                            if not isinstance(usage, dict):
                                usage = {}
                        except (ValueError, KeyError, IndexError, TypeError) as exc:
                            failure = _AttemptFailure(str(exc), retryable=True)
                            last_error = exc
                        else:
                            break
                    else:
                        last_error = failure

            last_failure_reason = str(failure)
            chaos_failed = chaos_failed or failure.simulated
            if failure.retryable and attempt == 0:
                time.sleep(RETRY_BACKOFF_SECONDS)
                continue
            if not failure.retryable:
                stop_chain = True
                break
            break
        if answer is not None:
            break
        if stop_chain:
            break
        last_error = last_error or failure
    if answer is None:
        meter.release(reservation)
        if confidential:
            _confidential_violation(
                run,
                "No configured local model answered; confidential request failed closed.",
            )
        detail = str(last_error or last_failure_reason or "no model succeeded")
        raise GatewayError(f"Bifrost request failed after retries: {detail}") from last_error

    if actual_model != requested_model:
        reason = "chaos (simulated)" if chaos_failed else (
            last_failure_reason or "Bifrost fallback"
        )
        run.emit("failover", {
            "from": requested_model,
            "to": actual_model,
            "reason": reason,
        })
    tokens_in = usage.get("prompt_tokens", tok(system + user))
    tokens_out = usage.get("completion_tokens", tok(answer))
    meter.log(
        label,
        reservation.tier,
        tokens_in,
        tokens_out,
        model=actual_model,
        reservation=reservation,
    )
    run.set_cached(cache_key, {
        "content": answer,
        "tier": reservation.tier,
        "model": actual_model,
    })
    return answer
