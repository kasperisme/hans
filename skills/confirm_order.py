#!/usr/bin/env python3
"""
Format order confirmation summary.

Reads order result from stdin and outputs a human-readable summary.
Optionally marks completed items as done in Todoist.
"""

import os
import sys
import json
import argparse

# Add parent directory to path for logging_config
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from todoist_api_python.api import TodoistAPI

from logging_config import setup_logging

load_dotenv()

log = setup_logging("hans.skills.confirm")

TODOIST_API_TOKEN = os.getenv("TODOIST_API_TOKEN")


def complete_todoist_tasks(task_ids: list[str]) -> int:
    """Mark tasks as complete in Todoist."""
    if not TODOIST_API_TOKEN:
        log.warning("TODOIST_API_TOKEN not set, skipping task completion")
        return 0

    api = TodoistAPI(TODOIST_API_TOKEN)
    completed = 0

    for task_id in task_ids:
        try:
            api.close_task(task_id)
            completed += 1
            log.debug("Completed task %s", task_id)
        except Exception as e:
            log.error("Failed to complete task %s: %s", task_id, e)

    log.info("Completed %d/%d tasks in Todoist", completed, len(task_ids))
    return completed


def format_order_summary(order_result: dict, original_items: list[dict] = None) -> str:
    """Format order result into a readable summary."""
    log.debug("Formatting order summary")

    lines = []
    lines.append("=" * 40)
    lines.append("ORDRE BEKRÆFTELSE / ORDER CONFIRMATION")
    lines.append("=" * 40)
    lines.append("")

    # Ordered items
    ordered = order_result.get("ordered", [])
    if ordered:
        lines.append(f"Bestilte varer ({len(ordered)}):")
        for item in ordered:
            name = item.get("matched_product", item.get("item", "Unknown"))
            price = item.get("price", "")
            lines.append(f"  OK {name} - {price}")
        lines.append("")
        log.info("Order contains %d successfully ordered items", len(ordered))

    # Failed items
    failed = order_result.get("failed", [])
    if failed:
        lines.append(f"Kunne ikke bestilles ({len(failed)}):")
        for item in failed:
            name = item.get("item", "Unknown")
            status = item.get("status", "error")
            lines.append(f"  FEJL {name} ({status})")
        lines.append("")
        log.warning("Order contains %d failed items", len(failed))

    # Checkout status
    checkout = order_result.get("checkout", {})
    checkout_status = checkout.get("status", "unknown")

    if checkout_status == "completed":
        total = checkout.get("total", "unknown")
        lines.append(f"Status: BESTILT")
        lines.append(f"Total: {total}")
        log.info("Order completed, total: %s", total)
    elif checkout_status == "dry_run":
        note = checkout.get("note", "")
        lines.append("Status: TEST (ingen ændring af kurv)")
        if note:
            lines.append(note)
        log.info("Dry run only, basket unchanged")
    elif checkout_status == "basket":
        total = checkout.get("total", "unknown")
        note = checkout.get("note", "")
        lines.append("Status: VARER I KURV (afslut checkout på nemlig.com)")
        lines.append(f"Kurv total: {total}")
        if note:
            lines.append(note)
        log.info("Basket updated, cart total: %s", total)
    elif checkout_status == "error":
        error = checkout.get("error", "Unknown error")
        lines.append(f"Status: FEJL VED CHECKOUT")
        lines.append(f"Fejl: {error}")
        log.error("Checkout failed: %s", error)
    else:
        lines.append(f"Status: {checkout_status}")
        log.warning("Unknown checkout status: %s", checkout_status)

    lines.append("")
    lines.append("=" * 40)

    return "\n".join(lines)


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Format order confirmation")
    parser.add_argument("--complete-tasks", action="store_true",
                        help="Mark ordered items as complete in Todoist")
    parser.add_argument("--original-items", type=str,
                        help="JSON of original Todoist items (for task completion)")
    args = parser.parse_args()

    # Read order result from stdin
    try:
        order_result = json.load(sys.stdin)
        log.debug("Received order result from stdin")
    except json.JSONDecodeError as e:
        log.error("Failed to parse order result: %s", e)
        sys.exit(1)

    # Parse original items if provided
    original_items = None
    if args.original_items:
        original_items = json.loads(args.original_items)
        log.debug("Received %d original items", len(original_items))

    # Format and print summary
    summary = format_order_summary(order_result, original_items)
    print(summary)

    # Complete tasks in Todoist if requested (not after dry-run preview)
    checkout_status = order_result.get("checkout", {}).get("status")
    if (
        args.complete_tasks
        and original_items
        and checkout_status != "dry_run"
    ):
        ordered_names = {
            item.get("item", "").lower()
            for item in order_result.get("ordered", [])
        }

        task_ids_to_complete = [
            item["id"] for item in original_items
            if item.get("content", "").lower() in ordered_names
        ]

        if task_ids_to_complete:
            completed = complete_todoist_tasks(task_ids_to_complete)
            print(f"\n{completed} varer markeret som købt i Todoist.")


if __name__ == "__main__":
    main()
