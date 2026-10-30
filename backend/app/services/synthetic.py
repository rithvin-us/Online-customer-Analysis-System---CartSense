"""Synthetic dataset generation.

The UCI Online Retail dataset is about 540,000 rows and roughly 45 MB, which is
small: on a cluster with a 4 MiB block size it produces a useful number of input
splits, but it cannot show how the platform behaves as data grows. This module
amplifies a real dataset into a larger one so that the benchmarking feature has
something to measure.

The generator is a structure-preserving resampler, not a random row factory.
It learns from the source:

* the product catalogue, with each product's observed price range;
* how often each product is bought, so popular products stay popular;
* the customer population and how often each customer returns;
* which country each customer buys from;
* the distribution of basket sizes and of line quantities;
* the month-by-month weighting of activity, and the real date range;
* the rate of missing CustomerID, of cancellation invoices and of exact
  duplicate rows.

It then synthesises whole invoices, so the generated data has the same shape
that the analyses depend on: an invoice has several lines, a customer has
several invoices, and some invoices reverse earlier ones. A dataset produced
this way exercises the invoice roll-up stages properly, which a file of
independent random rows would not.

Generation is seeded, so the same request produces the same dataset.
"""

from __future__ import annotations

import csv
import random
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from app.core.logging import get_logger
from app.services.profiling import (
    EXPECTED_COLUMNS,
    detect_delimiter,
    detect_encoding,
    parse_timestamp,
)

log = get_logger(__name__)

#: Source rows read to build the pools. Reading the whole 540k row file is
#: affordable, but a cap keeps generation from a one-million-row source bounded.
_MAX_SOURCE_ROWS = 400_000
_CANONICAL_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


@dataclass(slots=True)
class Product:
    stock_code: str
    description: str
    price_low: float
    price_high: float
    weight: int

    def price(self, rng: random.Random) -> float:
        if self.price_high <= self.price_low:
            return round(self.price_low, 2)
        return round(rng.uniform(self.price_low, self.price_high), 2)


@dataclass(slots=True)
class SourceProfile:
    """What the generator learned from the source dataset."""

    products: list[Product] = field(default_factory=list)
    product_weights: list[int] = field(default_factory=list)
    customers: list[str] = field(default_factory=list)
    customer_weights: list[int] = field(default_factory=list)
    customer_country: dict[str, str] = field(default_factory=dict)
    countries: list[str] = field(default_factory=list)
    country_weights: list[int] = field(default_factory=list)
    basket_sizes: list[int] = field(default_factory=list)
    quantities: list[int] = field(default_factory=list)
    month_starts: list[datetime] = field(default_factory=list)
    month_weights: list[int] = field(default_factory=list)
    missing_customer_rate: float = 0.0
    cancellation_rate: float = 0.0
    duplicate_rate: float = 0.0
    source_rows: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_rows_sampled": self.source_rows,
            "products": len(self.products),
            "customers": len(self.customers),
            "countries": len(self.countries),
            "months": len(self.month_starts),
            "median_basket_size": _median(self.basket_sizes),
            "median_line_quantity": _median(self.quantities),
            "missing_customer_rate": round(self.missing_customer_rate, 6),
            "cancellation_rate": round(self.cancellation_rate, 6),
            "duplicate_rate": round(self.duplicate_rate, 6),
        }


def _median(values: list[int]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return float(ordered[middle])
    return (ordered[middle - 1] + ordered[middle]) / 2.0


def learn(source: str | Path) -> SourceProfile:
    """Builds the generation pools from a real retail CSV."""
    path = Path(source)
    encoding = detect_encoding(path)
    delimiter = detect_delimiter(path, encoding)

    price_range: dict[str, list[float]] = {}
    descriptions: dict[str, str] = {}
    product_counts: Counter[str] = Counter()
    customer_invoices: dict[str, set[str]] = defaultdict(set)
    customer_country: dict[str, Counter[str]] = defaultdict(Counter)
    country_counts: Counter[str] = Counter()
    invoice_lines: Counter[str] = Counter()
    quantities: list[int] = []
    month_counts: Counter[str] = Counter()
    rows = 0
    missing_customer = 0
    cancellations = 0
    seen_rows: set[int] = set()
    duplicates = 0

    with path.open("r", encoding=encoding, errors="replace", newline="") as handle:
        reader = csv.reader(handle, delimiter=delimiter)
        next(reader, None)
        for row in reader:
            if len(row) < len(EXPECTED_COLUMNS):
                continue
            rows += 1
            if rows > _MAX_SOURCE_ROWS:
                break

            invoice_no = row[0].strip()
            stock_code = row[1].strip()
            description = row[2].strip()
            country = row[7].strip() or "Unspecified"
            customer_id = row[6].strip()
            if customer_id.endswith(".0"):
                customer_id = customer_id[:-2]

            fingerprint = hash(tuple(value.strip() for value in row[: len(EXPECTED_COLUMNS)]))
            if fingerprint in seen_rows:
                duplicates += 1
            else:
                seen_rows.add(fingerprint)

            try:
                quantity = int(row[3])
                price = float(row[5])
            except ValueError:
                continue
            if not stock_code or price <= 0 or quantity == 0:
                continue

            if invoice_no[:1].upper() == "C":
                cancellations += 1
            if not customer_id:
                missing_customer += 1
            else:
                customer_invoices[customer_id].add(invoice_no)
                customer_country[customer_id][country] += 1

            product_counts[stock_code] += 1
            descriptions.setdefault(stock_code, description)
            bounds = price_range.setdefault(stock_code, [price, price])
            bounds[0] = min(bounds[0], price)
            bounds[1] = max(bounds[1], price)

            country_counts[country] += 1
            invoice_lines[invoice_no] += 1
            quantities.append(abs(quantity))

            timestamp = parse_timestamp(row[4])
            if timestamp:
                month_counts[timestamp.strftime("%Y-%m")] += 1

    if not product_counts:
        raise ValueError("the source dataset has no usable product rows")

    profile = SourceProfile()
    for stock_code, weight in product_counts.items():
        low, high = price_range[stock_code]
        profile.products.append(
            Product(
                stock_code=stock_code,
                description=descriptions.get(stock_code, ""),
                price_low=low,
                price_high=high,
                weight=weight,
            )
        )
    profile.product_weights = [product.weight for product in profile.products]

    for customer_id, invoices in customer_invoices.items():
        profile.customers.append(customer_id)
        # Weighting by invoice count is what preserves the repeat-customer
        # structure the loyalty analysis measures.
        profile.customer_weights.append(len(invoices))
        chosen_country = customer_country[customer_id].most_common(1)
        profile.customer_country[customer_id] = chosen_country[0][0] if chosen_country else "Unspecified"

    profile.countries = list(country_counts.keys())
    profile.country_weights = [country_counts[country] for country in profile.countries]
    profile.basket_sizes = list(invoice_lines.values()) or [1]
    profile.quantities = quantities or [1]

    for month in sorted(month_counts):
        year, month_number = month.split("-")
        profile.month_starts.append(datetime(int(year), int(month_number), 1))
        profile.month_weights.append(month_counts[month])
    if not profile.month_starts:
        profile.month_starts = [datetime(2011, 1, 1)]
        profile.month_weights = [1]

    counted = max(rows, 1)
    profile.missing_customer_rate = missing_customer / counted
    profile.cancellation_rate = cancellations / counted
    profile.duplicate_rate = duplicates / counted
    profile.source_rows = rows

    log.info("learned generation profile: %s", profile.to_dict())
    return profile


def generate(
    profile: SourceProfile,
    target_path: str | Path,
    *,
    target_rows: int,
    seed: int = 20251030,
    duplicate_rate: float | None = None,
) -> dict[str, Any]:
    """Writes a synthetic dataset of approximately ``target_rows`` rows.

    The row count is approximate by design: rows are emitted a whole invoice at
    a time, so generation stops on the first invoice boundary at or past the
    target rather than truncating a basket.
    """
    if target_rows < 1:
        raise ValueError("target_rows must be positive")

    rng = random.Random(seed)
    output = Path(target_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    duplicate_probability = (
        profile.duplicate_rate if duplicate_rate is None else duplicate_rate
    )

    invoice_sequence = 600000
    written = 0
    invoices_written = 0
    cancellations_written = 0
    duplicates_written = 0
    missing_customer_written = 0
    #: Invoices kept so that a cancellation can reverse a real earlier basket.
    recent: list[tuple[str, str | None, str, list[tuple[Product, int, float]]]] = []

    with output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(EXPECTED_COLUMNS)

        while written < target_rows:
            make_cancellation = (
                recent
                and rng.random() < profile.cancellation_rate
            )

            if make_cancellation:
                original_invoice, customer_id, country, lines = rng.choice(recent)
                invoice_sequence += 1
                invoice_no = f"C{invoice_sequence}"
                timestamp = _timestamp_for(profile, rng)
                # A cancellation reverses part of the original basket.
                reversed_lines = lines[: max(1, rng.randint(1, len(lines)))]
                for product, quantity, price in reversed_lines:
                    writer.writerow(
                        [
                            invoice_no,
                            product.stock_code,
                            product.description,
                            -quantity,
                            timestamp.strftime(_CANONICAL_DATE_FORMAT),
                            f"{price:.2f}",
                            customer_id or "",
                            country,
                        ]
                    )
                    written += 1
                cancellations_written += 1
                invoices_written += 1
                continue

            invoice_sequence += 1
            invoice_no = str(invoice_sequence)
            timestamp = _timestamp_for(profile, rng)

            if profile.customers and rng.random() >= profile.missing_customer_rate:
                customer_id = rng.choices(profile.customers, weights=profile.customer_weights, k=1)[0]
                country = profile.customer_country.get(customer_id, "Unspecified")
            else:
                customer_id = None
                country = rng.choices(profile.countries, weights=profile.country_weights, k=1)[0]
                missing_customer_written += 1

            basket_size = max(1, rng.choice(profile.basket_sizes))
            chosen = rng.choices(profile.products, weights=profile.product_weights, k=basket_size)
            lines: list[tuple[Product, int, float]] = []
            seen_codes: set[str] = set()

            for product in chosen:
                if product.stock_code in seen_codes:
                    continue
                seen_codes.add(product.stock_code)
                quantity = max(1, rng.choice(profile.quantities))
                price = product.price(rng)
                lines.append((product, quantity, price))

            for product, quantity, price in lines:
                writer.writerow(
                    [
                        invoice_no,
                        product.stock_code,
                        product.description,
                        quantity,
                        timestamp.strftime(_CANONICAL_DATE_FORMAT),
                        f"{price:.2f}",
                        customer_id or "",
                        country,
                    ]
                )
                written += 1

                # Reproduce the source's duplicate rate so that the validation
                # job's de-duplication stage has real work to do.
                if duplicate_probability and rng.random() < duplicate_probability:
                    writer.writerow(
                        [
                            invoice_no,
                            product.stock_code,
                            product.description,
                            quantity,
                            timestamp.strftime(_CANONICAL_DATE_FORMAT),
                            f"{price:.2f}",
                            customer_id or "",
                            country,
                        ]
                    )
                    written += 1
                    duplicates_written += 1

            invoices_written += 1
            recent.append((invoice_no, customer_id, country, lines))
            if len(recent) > 2000:
                # Bounded memory: only recent invoices can be cancelled.
                recent.pop(rng.randrange(len(recent)))

    size_bytes = output.stat().st_size
    summary = {
        "target_rows": target_rows,
        "rows_written": written,
        "invoices_written": invoices_written,
        "cancellation_invoices": cancellations_written,
        "duplicate_rows": duplicates_written,
        "rows_without_customer_id": missing_customer_written,
        "size_bytes": size_bytes,
        "seed": seed,
        "source_profile": profile.to_dict(),
        "path": str(output),
    }
    log.info("generated synthetic dataset: %s", summary)
    return summary


def _timestamp_for(profile: SourceProfile, rng: random.Random) -> datetime:
    """A timestamp inside a month chosen with the source's monthly weighting."""
    month_start = rng.choices(profile.month_starts, weights=profile.month_weights, k=1)[0]
    return month_start + timedelta(
        days=rng.randrange(0, 28),
        hours=rng.randrange(7, 21),
        minutes=rng.randrange(0, 60),
    )
