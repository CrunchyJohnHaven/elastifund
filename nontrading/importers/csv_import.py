"""Manual CSV importer for non-trading leads."""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from pathlib import Path

from nontrading.config import RevenueAgentSettings
from nontrading.models import Lead, normalize_country, normalize_email, utc_now
from nontrading.store import RevenueStore


def _parse_bool(raw: str | None) -> bool:
    if raw is None:
        return False
    return raw.strip().lower() in {"1", "true", "yes", "y"}


@dataclass(frozen=True)
class CsvImportSummary:
    inserted: int = 0
    updated: int = 0
    skipped: int = 0


def import_csv(
    csv_path: str | Path,
    store: RevenueStore,
    default_country: str = "US",
    default_source: str = "manual_csv",
) -> CsvImportSummary:
    path = Path(csv_path)
    inserted = 0
    updated = 0
    skipped = 0
    seen_in_file: set[str] = set()

    with path.open(newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            email = (row.get("email") or "").strip()
            if not email:
                skipped += 1
                continue
            normalized = normalize_email(email)
            if normalized in seen_in_file:
                skipped += 1
                continue
            seen_in_file.add(normalized)

            explicit_opt_in = _parse_bool(row.get("explicit_opt_in"))
            lead = Lead(
                email=email,
                company_name=(row.get("company_name") or "").strip(),
                country_code=normalize_country(row.get("country_code") or default_country),
                source=(row.get("source") or default_source).strip(),
                explicit_opt_in=explicit_opt_in,
                opt_in_recorded_at=(row.get("opt_in_recorded_at") or utc_now()) if explicit_opt_in else None,
            )
            _, was_inserted = store.upsert_lead(lead)
            if was_inserted:
                inserted += 1
            else:
                updated += 1

    return CsvImportSummary(inserted=inserted, updated=updated, skipped=skipped)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Import leads into the non-trading revenue agent store.")
    parser.add_argument("csv_path", help="Path to a CSV file with an email column.")
    parser.add_argument("--db-path", help="Override JJ_REVENUE_DB_PATH for this import.")
    args = parser.parse_args(argv)

    settings = RevenueAgentSettings.from_env()
    db_path = Path(args.db_path) if args.db_path else settings.db_path
    store = RevenueStore(db_path)
    summary = import_csv(args.csv_path, store)
    print(
        "csv-import "
        f"inserted={summary.inserted} "
        f"updated={summary.updated} "
        f"skipped={summary.skipped} "
        f"db={db_path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

