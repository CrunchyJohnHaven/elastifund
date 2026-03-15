from __future__ import annotations

import logging
from typing import Any


def parse_signature_type(raw: Any, *, default: int = 1) -> int:
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def signature_type_candidates(configured_signature_type: Any) -> list[int]:
    preferred = parse_signature_type(configured_signature_type, default=1)
    ordered = [preferred, 1, 2, 0]
    return list(dict.fromkeys(ordered))


def micro_usdc_to_usd(value: Any) -> float:
    try:
        if value in (None, ""):
            return 0.0
        return round(float(value) / 1_000_000.0, 6)
    except (TypeError, ValueError):
        return 0.0


def select_signature_probe(
    probes: list[dict[str, Any]],
    *,
    configured_signature_type: Any,
) -> dict[str, Any]:
    configured = parse_signature_type(configured_signature_type, default=1)

    positive_balance = [
        probe
        for probe in probes
        if probe.get("auth_ok") and float(probe.get("balance_usd") or 0.0) > 0.0
    ]
    if positive_balance:
        positive_balance.sort(
            key=lambda probe: (
                float(probe.get("balance_usd") or 0.0),
                probe.get("signature_type") == configured,
            ),
            reverse=True,
        )
        return positive_balance[0]

    auth_ok = [probe for probe in probes if probe.get("auth_ok")]
    if auth_ok:
        auth_ok.sort(
            key=lambda probe: probe.get("signature_type") == configured,
            reverse=True,
        )
        return auth_ok[0]

    details = [
        f"sig={probe.get('signature_type')} bootstrap={probe.get('bootstrap_error')} auth={probe.get('auth_error')}"
        for probe in probes
    ]
    raise RuntimeError("no valid Polymarket CLOB signature mode: " + "; ".join(details))


def build_authenticated_clob_client(
    *,
    private_key: str,
    safe_address: str,
    configured_signature_type: Any,
    logger: logging.Logger,
    log_prefix: str = "",
):
    from py_clob_client.client import ClobClient
    from py_clob_client.clob_types import ApiCreds, AssetType, BalanceAllowanceParams

    normalized_private_key = private_key.strip()
    if normalized_private_key and not normalized_private_key.startswith("0x"):
        normalized_private_key = f"0x{normalized_private_key}"

    prefix = f"{log_prefix} " if log_prefix else ""
    probes: list[dict[str, Any]] = []
    for signature_type in signature_type_candidates(configured_signature_type):
        probe: dict[str, Any] = {
            "signature_type": signature_type,
            "auth_ok": False,
            "balance_usd": 0.0,
        }
        try:
            base_client = ClobClient(
                host="https://clob.polymarket.com",
                key=normalized_private_key,
                chain_id=137,
                signature_type=signature_type,
                funder=safe_address,
            )
            try:
                if hasattr(base_client, "create_or_derive_api_creds"):
                    derived = base_client.create_or_derive_api_creds()
                else:
                    try:
                        derived = base_client.derive_api_key()
                    except Exception:
                        derived = base_client.create_api_key()
            except Exception as exc:
                probe["bootstrap_error"] = str(exc)
                probes.append(probe)
                continue

            creds = ApiCreds(
                api_key=derived.api_key,
                api_secret=derived.api_secret,
                api_passphrase=derived.api_passphrase,
            )
            client = ClobClient(
                host="https://clob.polymarket.com",
                key=normalized_private_key,
                chain_id=137,
                creds=creds,
                signature_type=signature_type,
                funder=safe_address,
            )
            probe["client"] = client
            try:
                client.get_orders()
                probe["auth_ok"] = True
            except Exception as exc:
                probe["auth_error"] = str(exc)
            try:
                balance = client.get_balance_allowance(
                    BalanceAllowanceParams(
                        asset_type=AssetType.COLLATERAL,
                        signature_type=signature_type,
                    )
                )
                probe["balance_raw"] = balance.get("balance")
                probe["balance_usd"] = micro_usdc_to_usd(balance.get("balance"))
            except Exception as exc:
                probe["balance_error"] = str(exc)
        except Exception as exc:
            probe["bootstrap_error"] = str(exc)
        probes.append(probe)

    selected = select_signature_probe(
        probes,
        configured_signature_type=configured_signature_type,
    )
    selected_client = selected["client"]
    selected_signature_type = int(selected["signature_type"])
    configured = parse_signature_type(configured_signature_type, default=1)
    if selected_signature_type != configured:
        logger.warning(
            "%sCLOB signature_type=%s produced no usable balance; auto-selected signature_type=%s",
            prefix,
            configured,
            selected_signature_type,
        )
    logger.info(
        "%sCLOB signing mode: signature_type=%s balance_usd=%.6f",
        prefix,
        selected_signature_type,
        float(selected.get("balance_usd") or 0.0),
    )
    return selected_client, selected_signature_type, [
        {
            "signature_type": probe.get("signature_type"),
            "auth_ok": probe.get("auth_ok", False),
            "balance_usd": probe.get("balance_usd"),
            "bootstrap_error": probe.get("bootstrap_error"),
            "auth_error": probe.get("auth_error"),
            "balance_error": probe.get("balance_error"),
        }
        for probe in probes
    ]
