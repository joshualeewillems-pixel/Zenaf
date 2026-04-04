from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from . import storage as S


def _norm_set(values: list[str] | None) -> set[str]:
    if not values:
        return set()
    return {str(v).strip().lower() for v in values if str(v).strip()}


def _commitment_compatible(request_value: str, offer_value: str) -> bool:
    if not request_value or not offer_value:
        return True
    return request_value.strip().lower() == offer_value.strip().lower()


def _collaboration_compatible(request_value: str, offer_value: str) -> bool:
    if not request_value or not offer_value:
        return True
    return request_value.strip().lower() == offer_value.strip().lower()


def _timezone_compatible(request_value: str, offer_value: str) -> bool:
    if not request_value or not offer_value:
        return True
    return request_value.strip().lower() == offer_value.strip().lower()


def _seat_offer_score(seat_request: dict[str, Any], offer: dict[str, Any]) -> tuple[float, dict[str, Any]]:
    request_caps = _norm_set(seat_request.get("capability_tags"))
    request_roles = _norm_set(seat_request.get("role_tags"))
    offer_caps = _norm_set(offer.get("capability_tags"))
    offer_roles = _norm_set(offer.get("role_tags"))

    matched_caps = sorted(request_caps & offer_caps)
    matched_roles = sorted(request_roles & offer_roles)

    cap_score = (len(matched_caps) / len(request_caps)) if request_caps else 0.0
    role_score = (len(matched_roles) / len(request_roles)) if request_roles else 0.0
    score = round((0.7 * cap_score + 0.3 * role_score), 4)
    rationale = {
        "matched_capability_tags": matched_caps,
        "matched_role_tags": matched_roles,
        "missing_capability_tags": sorted(request_caps - offer_caps),
        "missing_role_tags": sorted(request_roles - offer_roles),
        "score_components": {
            "capability_overlap_ratio": round(cap_score, 4),
            "role_overlap_ratio": round(role_score, 4),
        },
    }
    return score, rationale


def candidate_offers_for_seat_request(seat_request: dict[str, Any], *, limit: int = 25) -> list[dict[str, Any]]:
    request_user_id = seat_request.get("user_id")
    request_commitment = (seat_request.get("commitment_type") or "").strip()
    request_collaboration = (seat_request.get("collaboration_mode") or "").strip()
    request_timezone = (seat_request.get("timezone_pref") or "").strip()
    offers = S.list_matchable_capability_offers()

    out: list[dict[str, Any]] = []
    for offer in offers:
        if offer.get("user_id") == request_user_id:
            continue
        hard_constraints = {
            "commitment_compatible": _commitment_compatible(request_commitment, offer.get("commitment_type") or ""),
            "collaboration_compatible": _collaboration_compatible(request_collaboration, offer.get("collaboration_mode") or ""),
            "timezone_compatible": _timezone_compatible(request_timezone, offer.get("timezone_pref") or ""),
        }
        if not all(hard_constraints.values()):
            continue
        score, rationale = _seat_offer_score(seat_request, offer)
        out.append(
            {
                "seat_request_id": seat_request.get("id"),
                "capability_offer_id": offer.get("id"),
                "score": score,
                "rationale": rationale,
                "hard_constraints": hard_constraints,
                "offer": {
                    "id": offer.get("id"),
                    "title": offer.get("title"),
                    "capability_tags": offer.get("capability_tags") or [],
                    "role_tags": offer.get("role_tags") or [],
                    "availability_window": offer.get("availability_window"),
                    "commitment_type": offer.get("commitment_type"),
                    "collaboration_mode": offer.get("collaboration_mode"),
                    "timezone_pref": offer.get("timezone_pref"),
                },
            }
        )
    out.sort(key=lambda x: (-x["score"], x["capability_offer_id"]))
    return out[: max(1, min(limit, 100))]


def _offer_request_score(offer: dict[str, Any], seat_request: dict[str, Any]) -> tuple[float, dict[str, Any]]:
    # Reuse the same deterministic scoring contract, inverted inputs.
    score, rationale = _seat_offer_score(seat_request, offer)
    return score, rationale


def candidate_requests_for_capability_offer(offer: dict[str, Any], *, limit: int = 25) -> list[dict[str, Any]]:
    offer_user_id = offer.get("user_id")
    offer_commitment = (offer.get("commitment_type") or "").strip()
    offer_collaboration = (offer.get("collaboration_mode") or "").strip()
    offer_timezone = (offer.get("timezone_pref") or "").strip()
    requests = S.list_matchable_seat_requests()

    out: list[dict[str, Any]] = []
    for seat_request in requests:
        if seat_request.get("user_id") == offer_user_id:
            continue
        hard_constraints = {
            "commitment_compatible": _commitment_compatible(seat_request.get("commitment_type") or "", offer_commitment),
            "collaboration_compatible": _collaboration_compatible(seat_request.get("collaboration_mode") or "", offer_collaboration),
            "timezone_compatible": _timezone_compatible(seat_request.get("timezone_pref") or "", offer_timezone),
        }
        if not all(hard_constraints.values()):
            continue
        score, rationale = _offer_request_score(offer, seat_request)
        out.append(
            {
                "capability_offer_id": offer.get("id"),
                "seat_request_id": seat_request.get("id"),
                "score": score,
                "rationale": rationale,
                "hard_constraints": hard_constraints,
                "seat_request": {
                    "id": seat_request.get("id"),
                    "title": seat_request.get("title"),
                    "context_type": seat_request.get("context_type"),
                    "capability_tags": seat_request.get("capability_tags") or [],
                    "role_tags": seat_request.get("role_tags") or [],
                    "availability_window": seat_request.get("availability_window"),
                    "commitment_type": seat_request.get("commitment_type"),
                    "collaboration_mode": seat_request.get("collaboration_mode"),
                    "timezone_pref": seat_request.get("timezone_pref"),
                },
            }
        )
    out.sort(key=lambda x: (-x["score"], x["seat_request_id"]))
    return out[: max(1, min(limit, 100))]


_CONDITION_ORDER = ["any", "poor", "fair", "good", "very_good", "excellent", "new"]
_CONDITION_INDEX = {v: i for i, v in enumerate(_CONDITION_ORDER)}
_COST_BAND_ORDER = ["free", "low", "medium", "high", "premium", "enterprise"]
_COST_BAND_INDEX = {v: i for i, v in enumerate(_COST_BAND_ORDER)}


def _norm_str(value: Any) -> str:
    return str(value or "").strip().lower()


def _parse_iso(value: str | None) -> datetime | None:
    raw = _norm_str(value)
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("z", "+00:00"))
    except Exception:
        return None
    # Policy: coerce naive datetimes to UTC to avoid naive/aware comparison failures.
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _availability_overlap(
    req_start: str | None, req_end: str | None, off_start: str | None, off_end: str | None
) -> bool:
    rs = _parse_iso(req_start)
    re = _parse_iso(req_end)
    os = _parse_iso(off_start)
    oe = _parse_iso(off_end)
    if rs is None and re is None:
        return True
    if os is None and oe is None:
        return True
    rs = rs or datetime.min.replace(tzinfo=timezone.utc)
    re = re or datetime.max.replace(tzinfo=timezone.utc)
    os = os or datetime.min.replace(tzinfo=timezone.utc)
    oe = oe or datetime.max.replace(tzinfo=timezone.utc)
    return max(rs, os) <= min(re, oe)


def _condition_compatible(condition_min: str, condition_state: str) -> bool:
    req = _CONDITION_INDEX.get(_norm_str(condition_min))
    off = _CONDITION_INDEX.get(_norm_str(condition_state))
    if req is None or off is None:
        return False
    return off >= req


def _cost_compatible(cost_band_max: str, cost_band: str) -> bool:
    req = _norm_str(cost_band_max)
    off = _norm_str(cost_band)
    if not req:
        return True
    if not off:
        return False
    req_idx = _COST_BAND_INDEX.get(req)
    off_idx = _COST_BAND_INDEX.get(off)
    if req_idx is None or off_idx is None:
        return False
    return off_idx <= req_idx


def _location_compatible(request: dict[str, Any], offer: dict[str, Any]) -> bool:
    req_region = _norm_str(request.get("location_region"))
    off_region = _norm_str(offer.get("location_region"))
    if req_region and off_region and req_region != off_region:
        return False
    max_distance = request.get("max_distance_km")
    service_area = offer.get("service_area_km")
    if max_distance is not None and service_area is not None:
        try:
            return float(service_area) >= float(max_distance)
        except Exception:
            return False
    return True


def _usage_constraints_compatible(request: dict[str, Any], offer: dict[str, Any]) -> bool:
    req = _norm_set(request.get("usage_constraints"))
    off = _norm_set(offer.get("usage_constraints"))
    if not req:
        return True
    return req.issubset(off)


def _material_score(request: dict[str, Any], offer: dict[str, Any]) -> tuple[float, dict[str, Any]]:
    req_tags = _norm_set(request.get("category_tags"))
    off_tags = _norm_set(offer.get("category_tags"))
    matched_tags = sorted(req_tags & off_tags)
    tag_overlap = (len(matched_tags) / len(req_tags)) if req_tags else 0.0
    score = round(tag_overlap, 4)
    rationale = {
        "matched_category_tags": matched_tags,
        "missing_category_tags": sorted(req_tags - off_tags),
        "score_components": {"category_overlap_ratio": round(tag_overlap, 4)},
    }
    return score, rationale


def candidate_offers_for_material_request(request: dict[str, Any], *, limit: int = 25) -> list[dict[str, Any]]:
    offers = S.list_matchable_material_offers()
    request_user_id = request.get("user_id")
    req_qty = float(request.get("quantity_needed") or 0)
    req_unit = _norm_str(request.get("quantity_unit"))

    out: list[dict[str, Any]] = []
    for offer in offers:
        if offer.get("user_id") == request_user_id:
            continue
        off_qty = float(offer.get("quantity_available") or 0)
        off_unit = _norm_str(offer.get("quantity_unit"))
        hard_constraints = {
            "material_type_compatible": _norm_str(request.get("material_type")) == _norm_str(offer.get("material_type")),
            "resource_nature_compatible": _norm_str(request.get("resource_nature")) == _norm_str(offer.get("resource_nature")),
            "quantity_full_fit": off_qty >= req_qty,
            "quantity_unit_compatible": req_unit == off_unit,
            "availability_overlap": _availability_overlap(
                request.get("availability_start"),
                request.get("availability_end"),
                offer.get("availability_start"),
                offer.get("availability_end"),
            ),
            "condition_compatible": _condition_compatible(
                request.get("condition_min") or "any",
                offer.get("condition_state") or "any",
            ),
            "access_mode_compatible": not _norm_str(request.get("access_mode")) or _norm_str(request.get("access_mode")) == _norm_str(offer.get("access_mode")),
            "location_compatible": _location_compatible(request, offer),
            "cost_compatible": _cost_compatible(request.get("cost_band_max") or "", offer.get("cost_band") or ""),
            "usage_constraints_compatible": _usage_constraints_compatible(request, offer),
        }
        if not all(hard_constraints.values()):
            continue
        score, rationale = _material_score(request, offer)
        out.append(
            {
                "material_request_id": request.get("id"),
                "material_offer_id": offer.get("id"),
                "score": score,
                "rationale": rationale,
                "hard_constraints": hard_constraints,
                "offer": {
                    "id": offer.get("id"),
                    "title": offer.get("title"),
                    "material_type": offer.get("material_type"),
                    "resource_nature": offer.get("resource_nature"),
                    "category_tags": offer.get("category_tags") or [],
                    "quantity_available": offer.get("quantity_available"),
                    "quantity_unit": offer.get("quantity_unit"),
                    "availability_start": offer.get("availability_start"),
                    "availability_end": offer.get("availability_end"),
                    "condition_state": offer.get("condition_state"),
                    "access_mode": offer.get("access_mode"),
                    "location_region": offer.get("location_region"),
                    "cost_band": offer.get("cost_band"),
                },
            }
        )
    out.sort(key=lambda x: (-x["score"], x["material_offer_id"]))
    return out[: max(1, min(limit, 100))]


def candidate_requests_for_material_offer(offer: dict[str, Any], *, limit: int = 25) -> list[dict[str, Any]]:
    requests = S.list_matchable_material_requests()
    offer_user_id = offer.get("user_id")

    out: list[dict[str, Any]] = []
    for request in requests:
        if request.get("user_id") == offer_user_id:
            continue
        hard_constraints = {
            "material_type_compatible": _norm_str(request.get("material_type")) == _norm_str(offer.get("material_type")),
            "resource_nature_compatible": _norm_str(request.get("resource_nature")) == _norm_str(offer.get("resource_nature")),
            "quantity_full_fit": float(offer.get("quantity_available") or 0) >= float(request.get("quantity_needed") or 0),
            "quantity_unit_compatible": _norm_str(request.get("quantity_unit")) == _norm_str(offer.get("quantity_unit")),
            "availability_overlap": _availability_overlap(
                request.get("availability_start"),
                request.get("availability_end"),
                offer.get("availability_start"),
                offer.get("availability_end"),
            ),
            "condition_compatible": _condition_compatible(
                request.get("condition_min") or "any",
                offer.get("condition_state") or "any",
            ),
            "access_mode_compatible": not _norm_str(request.get("access_mode")) or _norm_str(request.get("access_mode")) == _norm_str(offer.get("access_mode")),
            "location_compatible": _location_compatible(request, offer),
            "cost_compatible": _cost_compatible(request.get("cost_band_max") or "", offer.get("cost_band") or ""),
            "usage_constraints_compatible": _usage_constraints_compatible(request, offer),
        }
        if not all(hard_constraints.values()):
            continue
        score, rationale = _material_score(request, offer)
        out.append(
            {
                "material_offer_id": offer.get("id"),
                "material_request_id": request.get("id"),
                "score": score,
                "rationale": rationale,
                "hard_constraints": hard_constraints,
                "request": {
                    "id": request.get("id"),
                    "title": request.get("title"),
                    "material_type": request.get("material_type"),
                    "resource_nature": request.get("resource_nature"),
                    "category_tags": request.get("category_tags") or [],
                    "quantity_needed": request.get("quantity_needed"),
                    "quantity_unit": request.get("quantity_unit"),
                    "availability_start": request.get("availability_start"),
                    "availability_end": request.get("availability_end"),
                    "condition_min": request.get("condition_min"),
                    "access_mode": request.get("access_mode"),
                    "location_region": request.get("location_region"),
                    "cost_band_max": request.get("cost_band_max"),
                },
            }
        )
    out.sort(key=lambda x: (-x["score"], x["material_request_id"]))
    return out[: max(1, min(limit, 100))]
