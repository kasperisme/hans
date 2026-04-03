#!/usr/bin/env python3
"""
Read shopping list from Todoist project "Indkøb".

Outputs JSON array of items with task IDs for later completion.
"""

import os
import json
import sys

# Add parent directory to path for logging_config
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from todoist_api_python.api import TodoistAPI

from logging_config import setup_logging

load_dotenv()

log = setup_logging("hans.skills.todoist")

TODOIST_API_TOKEN = os.getenv("TODOIST_API_TOKEN")
PROJECT_NAME = "Indkøb"


def find_project_id(api: TodoistAPI, project_name: str) -> str | None:
    """Find project ID by name."""
    log.debug("Searching for project: %s", project_name)
    try:
        # todoist-api-python returns pages: Iterator[list[Project]]
        for page in api.get_projects():
            for project in page:
                if project.name.lower() == project_name.lower():
                    log.debug("Found project %s with ID %s", project_name, project.id)
                    return project.id
        log.warning("Project '%s' not found", project_name)
    except Exception as e:
        log.exception("Error fetching projects")
    return None


def get_shopping_list() -> list[dict]:
    """Fetch all open tasks from the Indkøb project."""
    if not TODOIST_API_TOKEN:
        log.error("TODOIST_API_TOKEN not set")
        return []

    log.info("Fetching shopping list from Todoist")
    api = TodoistAPI(TODOIST_API_TOKEN)

    project_id = find_project_id(api, PROJECT_NAME)
    if not project_id:
        log.error("Project '%s' not found", PROJECT_NAME)
        return []

    try:
        # todoist-api-python returns pages: Iterator[list[Task]]
        items = []
        for page in api.get_tasks(project_id=project_id):
            for task in page:
                items.append({
                    "id": task.id,
                    "content": task.content,
                    "description": task.description or "",
                    "priority": task.priority,
                    "labels": task.labels,
                })
        log.info("Found %d items in shopping list", len(items))
        return items
    except Exception as e:
        log.exception("Error fetching tasks")
        return []


def main():
    """Main entry point."""
    items = get_shopping_list()
    print(json.dumps(items, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
