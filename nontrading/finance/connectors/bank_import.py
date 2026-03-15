"""Bank and card import connectors for CSV and OFX inputs."""

from __future__ import annotations

import csv
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from nontrading.finance.models import FinanceAccount, FinanceGap, FinanceImportBundle, FinanceTransaction, money, utc_now

UTC = timezone.utc
TAG_RE = re.compile(r"<(?P<tag>[A-Z0-9_.]+)>(?P<value>[^<\r\n]+)", re.IGNORECASE)
STMT_BLOCK_RE = re.compile(r"<STMTTRN>(?P<body>.*?)</STMTTRN>", re.IGNORECASE | re.DOTALL)
CSV_DATE_COLUMNS = ("date", "posted_at", "posted date", "transaction date", "posting date")
CSV_AMOUNT_COLUMNS = ("amount", "transaction amount", "posted amount", "net amount")
CSV_DEBIT_COLUMNS = ("debit", "debits")
CSV_CREDIT_COLUMNS = ("credit", "credits")
CSV_DESCRIPTION_COLUMNS = ("description", "memo", "details", "name")
CSV_MERCHANT_COLUMNS = ("merchant", "payee", "counterparty")
CSV_ACCOUNT_COLUMNS = ("account_name", "account", "account name")
CSV_ACCOUNT_ID_COLUMNS = ("account_id", "account number", "account_number")
CSV_INSTITUTION_COLUMNS = ("institution", "bank", "issuer")
CSV_BALANCE_COLUMNS = ("balance", "ledger balance", "current balance")
CSV_TYPE_COLUMNS = ("account_type", "type")


def _canonical_row(row: dict[str, str]) -> dict[str, str]:
    return {str(key or "").strip().lower(): str(value or "").strip() for key, value in row.items()}


def _field(row: dict[str, str], aliases: tuple[str, ...]) -> str:
    for alias in aliases:
        value = row.get(alias)
        if value:
            return value
    return ""


def _parse_timestamp(raw: str) -> str:
    text = str(raw or "").strip()
    if not text:
        return utc_now()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%Y/%m/%d", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S"):
        try:
            parsed = datetime.strptime(text, fmt)
        except ValueError:
            continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC).replace(microsecond=0).isoformat()
    return text


def _parse_ofx_timestamp(raw: str) -> str:
    text = str(raw or "").strip()
    if not text:
        return utc_now()
    match = re.match(r"(?P<date>\d{8})(?P<time>\d{6})?(?:\.\d+)?(?:\[(?P<offset>[+-]?\d+):?.*?\])?", text)
    if not match:
        return text
    date_part = match.group("date")
    time_part = match.group("time") or "000000"
    parsed = datetime.strptime(date_part + time_part, "%Y%m%d%H%M%S")
    offset = match.group("offset")
    if offset is not None:
        parsed = parsed.replace(tzinfo=timezone(timedelta(hours=int(offset))))
    else:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).replace(microsecond=0).isoformat()


def _extract_tag(block: str, tag_name: str) -> str:
    for match in TAG_RE.finditer(block):
        if match.group("tag").upper() == tag_name.upper():
            return match.group("value").strip()
    return ""


def _parse_csv_file(path: Path) -> tuple[list[FinanceAccount], list[FinanceTransaction], list[FinanceGap]]:
    rows: list[dict[str, str]] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            return [], [], [FinanceGap("bank_imports", "missing_csv_header", "CSV file is missing headers.", source_ref=str(path))]
        rows = [_canonical_row(row) for row in reader]

    if not rows:
        return [], [], [FinanceGap("bank_imports", "empty_csv_file", "CSV import file is empty.", source_ref=str(path))]

    account_name = _field(rows[0], CSV_ACCOUNT_COLUMNS) or path.stem.replace("_", " ").title()
    institution = _field(rows[0], CSV_INSTITUTION_COLUMNS) or path.parent.name.replace("_", " ").title()
    account_id = _field(rows[0], CSV_ACCOUNT_ID_COLUMNS) or path.stem
    account_type = _field(rows[0], CSV_TYPE_COLUMNS) or ("card" if "card" in path.stem.lower() else "bank")
    transactions: list[FinanceTransaction] = []
    balance_value: float | None = None

    account = FinanceAccount(
        external_id=account_id,
        name=account_name,
        institution=institution,
        account_type=account_type,
        currency="USD",
        liquidity_tier="liquid" if str(account_type).lower() != "card" else "liability",
        source_type="csv_import",
        source_ref=str(path),
    )

    gaps: list[FinanceGap] = []
    for index, row in enumerate(rows):
        posted_at = _field(row, CSV_DATE_COLUMNS)
        amount_raw = _field(row, CSV_AMOUNT_COLUMNS)
        if not amount_raw:
            debit_raw = _field(row, CSV_DEBIT_COLUMNS)
            credit_raw = _field(row, CSV_CREDIT_COLUMNS)
            if debit_raw or credit_raw:
                amount_raw = str(money(credit_raw) - abs(money(debit_raw)))
        if not posted_at or not amount_raw:
            gaps.append(
                FinanceGap(
                    "bank_imports",
                    "csv_row_missing_required_fields",
                    f"Skipped CSV row {index + 1}: missing date or amount.",
                    source_ref=str(path),
                    metadata={"row_index": index + 1},
                )
            )
            continue
        description = _field(row, CSV_DESCRIPTION_COLUMNS)
        merchant = _field(row, CSV_MERCHANT_COLUMNS) or description
        transaction = FinanceTransaction(
            account_key=account.account_key,
            external_id=row.get("id") or row.get("transaction_id") or row.get("reference") or f"{path.stem}-{index + 1}",
            posted_at=_parse_timestamp(posted_at),
            amount_usd=money(amount_raw),
            description=description,
            merchant=merchant,
            category=row.get("category", "") or "unclassified",
            status=row.get("status", "") or "posted",
            source_type="csv_import",
            source_ref=str(path),
            merchant_confidence=0.8 if merchant else 0.3,
            metadata={"raw_row": row},
        )
        transactions.append(transaction)
        balance_raw = _field(row, CSV_BALANCE_COLUMNS)
        if balance_raw:
            balance_value = money(balance_raw)

    if balance_value is None:
        balance_value = sum(item.amount_usd for item in transactions)
    account = FinanceAccount(
        account_key=account.account_key,
        external_id=account.external_id,
        name=account.name,
        institution=account.institution,
        account_type=account.account_type,
        currency=account.currency,
        liquidity_tier=account.liquidity_tier,
        status=account.status,
        available_cash_usd=None if account.account_type == "card" else balance_value,
        current_balance_usd=balance_value,
        source_type=account.source_type,
        source_ref=account.source_ref,
        metadata={"file_kind": "csv", "file_name": path.name},
    )
    return [account], transactions, gaps


def _parse_ofx_file(path: Path) -> tuple[list[FinanceAccount], list[FinanceTransaction], list[FinanceGap]]:
    text = path.read_text(encoding="utf-8", errors="ignore")
    account_type = _extract_tag(text, "ACCTTYPE")
    if not account_type:
        account_type = "card" if "CCSTMTTRNRS" in text.upper() else "bank"
    institution = _extract_tag(text, "ORG") or path.parent.name.replace("_", " ").title()
    account_id = _extract_tag(text, "ACCTID") or path.stem
    currency = _extract_tag(text, "CURDEF") or "USD"
    balance_raw = _extract_tag(text, "BALAMT")
    balance_value = money(balance_raw) if balance_raw else 0.0

    account = FinanceAccount(
        external_id=account_id,
        name=f"{institution or 'Imported'} {account_type.title()}",
        institution=institution,
        account_type=account_type,
        currency=currency,
        liquidity_tier="liquid" if str(account_type).lower() != "card" else "liability",
        available_cash_usd=None if str(account_type).lower() == "card" else balance_value,
        current_balance_usd=balance_value,
        source_type="ofx_import",
        source_ref=str(path),
        metadata={"file_kind": "ofx", "file_name": path.name},
    )
    transactions: list[FinanceTransaction] = []

    blocks = STMT_BLOCK_RE.findall(text)
    if not blocks:
        return [account], [], [FinanceGap("bank_imports", "no_ofx_transactions", "OFX file contained no STMTTRN blocks.", source_ref=str(path))]

    for index, block in enumerate(blocks):
        posted_at = _parse_ofx_timestamp(_extract_tag(block, "DTPOSTED"))
        amount_usd = money(_extract_tag(block, "TRNAMT"))
        name = _extract_tag(block, "NAME")
        memo = _extract_tag(block, "MEMO")
        description = memo or name or _extract_tag(block, "TRNTYPE")
        transactions.append(
            FinanceTransaction(
                account_key=account.account_key,
                external_id=_extract_tag(block, "FITID") or f"{path.stem}-{index + 1}",
                posted_at=posted_at,
                amount_usd=amount_usd,
                description=description,
                merchant=name or description,
                category="unclassified",
                source_type="ofx_import",
                source_ref=str(path),
                merchant_confidence=0.75 if name else 0.35,
                metadata={
                    "name": name,
                    "memo": memo,
                    "trn_type": _extract_tag(block, "TRNTYPE"),
                },
            )
        )
    return [account], transactions, []


def load_bank_folder_bundle(import_dir: str | Path, *, observed_at: str | None = None) -> FinanceImportBundle:
    root = Path(import_dir)
    observed = observed_at or utc_now()
    if not root.exists():
        return FinanceImportBundle(
            source_name="bank_imports",
            observed_at=observed,
            gaps=(
                FinanceGap(
                    "bank_imports",
                    "missing_bank_import_dir",
                    "Bank import directory does not exist.",
                    source_ref=str(root),
                ),
            ),
        )

    files = sorted(path for path in root.rglob("*") if path.is_file() and path.suffix.lower() in {".csv", ".ofx", ".qfx"})
    if not files:
        return FinanceImportBundle(
            source_name="bank_imports",
            observed_at=observed,
            gaps=(
                FinanceGap(
                    "bank_imports",
                    "no_bank_import_files",
                    "No CSV or OFX files were found under the bank import directory.",
                    source_ref=str(root),
                ),
            ),
        )

    accounts_by_key: dict[str, FinanceAccount] = {}
    transactions: list[FinanceTransaction] = []
    gaps: list[FinanceGap] = []
    for path in files:
        if path.suffix.lower() == ".csv":
            file_accounts, file_transactions, file_gaps = _parse_csv_file(path)
        else:
            file_accounts, file_transactions, file_gaps = _parse_ofx_file(path)
        for account in file_accounts:
            accounts_by_key[account.account_key] = account
        transactions.extend(file_transactions)
        gaps.extend(file_gaps)

    return FinanceImportBundle(
        source_name="bank_imports",
        observed_at=observed,
        accounts=tuple(accounts_by_key.values()),
        transactions=tuple(transactions),
        gaps=tuple(gaps),
        metadata={"import_root": str(root), "files": [str(path) for path in files]},
    )
