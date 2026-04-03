#!/usr/bin/env python3
"""
Add Todoist shopping items to nemlig.com basket via the unofficial web API.

Reads Todoist-style JSON (from read_todoist.py), searches each line, picks the
first in-stock hit, adds the requested quantity, then prints a JSON result for
confirm_order.py on stdout. Logs go to stderr.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys

# Repo root for nemlig_api package
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

from logging_config import setup_logging
from nemlig_api import NemligAPI, NemligAPIError

load_dotenv()

log = setup_logging("hans.skills.nemlig")

NEMLIG_EMAIL = os.getenv("NEMLIG_EMAIL") or os.getenv("NEMLIG_USERNAME")
NEMLIG_PASSWORD = os.getenv("NEMLIG_PASSWORD")


def parse_shopping_line(text: str) -> tuple[str, int]:
    """
    Parse task text into (search_query, quantity).

    Supports: 2x mælk, mælk 2x, 2× ost, 2 stk mælk, mælk (2), 2 mælk (leading number + name).
    Default quantity is 1.
    """
    raw = (text or "").strip()
    if not raw:
        return "", 0

    raw = re.sub(r"^\s*[-*]\s+\[[x ]?\]\s*", "", raw, flags=re.IGNORECASE)

    m = re.match(r"^(\d+)\s*[x×]\s*(.+)$", raw, re.IGNORECASE)
    if m:
        return m.group(2).strip(), max(1, int(m.group(1)))

    m = re.match(r"^(.+?)\s+(\d+)\s*[x×]\s*$", raw, re.IGNORECASE)
    if m:
        return m.group(1).strip(), max(1, int(m.group(2)))

    m = re.match(r"^(\d+)\s+stk\.?\s+(.+)$", raw, re.IGNORECASE)
    if m:
        return m.group(2).strip(), max(1, int(m.group(1)))

    m = re.match(r"^(.+?)\s*\((\d+)\)\s*$", raw)
    if m:
        return m.group(1).strip(), max(1, int(m.group(2)))

    m = re.match(r"^(\d+)\s+(.+)$", raw)
    if m and 1 <= int(m.group(1)) <= 99:
        rest = m.group(2).strip()
        if re.search(r"[a-zA-ZæøåÆØÅ]", rest):
            return rest, int(m.group(1))

    return raw, 1


def pick_product(products: list[dict]) -> dict | None:
    """First product with id and available; else first with id."""
    for p in products:
        if p.get("id") is None:
            continue
        if p.get("available", True):
            return p
    for p in products:
        if p.get("id") is not None:
            return p
    return None


def extract_cart_total(cart: dict) -> str | None:
    """Best-effort total from GetBasket payload."""
    if not isinstance(cart, dict):
        return None
    for key in (
        "TotalPrice",
        "TotalPriceIncVat",
        "TotalPriceInclVat",
        "TotalForPayment",
        "Total",
        "totalPrice",
    ):
        v = cart.get(key)
        if v is not None and v != "":
            return str(v)
    return None


def build_order_result(
    ordered: list[dict],
    failed: list[dict],
    cart: dict | None,
    error: str | None = None,
) -> dict:
    checkout: dict = {"status": "basket"}
    if error:
        checkout["status"] = "error"
        checkout["error"] = error
    elif cart is not None:
        total = extract_cart_total(cart)
        checkout["total"] = total or "unknown"
        checkout["note"] = (
            "Varer ligger i kurven på nemlig.com. Åbn siden og gennemfør checkout."
        )
    else:
        checkout["status"] = "unknown"
        checkout["note"] = "Kunne ikke hente kurv efter tilføjelse."
    return {"ordered": ordered, "failed": failed, "checkout": checkout}


def add_items_to_basket(
    items: list[dict],
    *,
    dry_run: bool,
    search_limit: int,
) -> dict:
    if not NEMLIG_EMAIL or not NEMLIG_PASSWORD:
        log.error("NEMLIG_EMAIL (or NEMLIG_USERNAME) and NEMLIG_PASSWORD must be set")
        return build_order_result([], [], None, error="Missing credentials")

    api = NemligAPI()
    ordered: list[dict] = []
    failed: list[dict] = []

    if not dry_run:
        try:
            api.login(NEMLIG_EMAIL, NEMLIG_PASSWORD)
        except NemligAPIError as e:
            log.error("Login failed: %s", e)
            return build_order_result([], [], None, error=str(e))

    for task in items:
        content = task.get("content", "")
        task_id = task.get("id")
        query, qty = parse_shopping_line(content)
        if not query:
            failed.append(
                {
                    "item": content,
                    "task_id": task_id,
                    "status": "empty_line",
                }
            )
            continue

        log.info("Search: %r q=%d", query, qty)
        products = api.search_products(query, limit=search_limit)
        product = pick_product(products) if products else None

        if not product:
            failed.append(
                {
                    "item": content,
                    "task_id": task_id,
                    "status": "no_search_results",
                    "query": query,
                }
            )
            log.warning("No product for: %s", query)
            continue

        pid = product["id"]
        name = product.get("name") or str(pid)
        price = product.get("price")

        if dry_run:
            ordered.append(
                {
                    "item": content,
                    "task_id": task_id,
                    "matched_product": name,
                    "product_id": pid,
                    "quantity": qty,
                    "price": price,
                }
            )
            continue

        try:
            api.add_to_cart(pid, qty)
            ordered.append(
                {
                    "item": content,
                    "task_id": task_id,
                    "matched_product": name,
                    "product_id": pid,
                    "quantity": qty,
                    "price": price,
                }
            )
            log.info("Added %s x %s", qty, name)
        except NemligAPIError as e:
            failed.append(
                {
                    "item": content,
                    "task_id": task_id,
                    "status": "add_to_cart_failed",
                    "matched_product": name,
                    "product_id": pid,
                    "error": str(e),
                }
            )
            log.error("Add failed for %s: %s", name, e)

    if dry_run:
        return {
            "ordered": ordered,
            "failed": failed,
            "checkout": {
                "status": "dry_run",
                "note": "Kør uden --dry-run for at tilføje varer til kurven.",
            },
        }

    cart = None
    if api.is_logged_in():
        try:
            cart = api.get_cart()
        except NemligAPIError as e:
            log.warning("get_cart: %s", e)

    return build_order_result(ordered, failed, cart)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Add Todoist shopping items to nemlig.com basket via the web API"
    )
    parser.add_argument("--items", type=str, help="JSON array of Todoist tasks")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse lines and resolve searches only; do not log in or add to basket",
    )
    parser.add_argument(
        "--search-limit",
        type=int,
        default=10,
        help="Max search results per line (default 10)",
    )
    args = parser.parse_args()

    if args.items:
        items = json.loads(args.items)
    else:
        items = json.load(sys.stdin)

    if not items:
        log.warning("No items to order")
        print(json.dumps(build_order_result([], [], None, error="No items")))
        sys.exit(0)

    result = add_items_to_basket(
        items,
        dry_run=args.dry_run,
        search_limit=args.search_limit,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
