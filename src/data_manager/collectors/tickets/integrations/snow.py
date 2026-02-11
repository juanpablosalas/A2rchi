from threading import Lock
from typing import Any, Dict, Iterator, Optional, List
from time import perf_counter
from datetime import datetime

import requests
from requests.auth import HTTPBasicAuth

from src.data_manager.collectors.tickets.ticket_resource import TicketResource
from src.data_manager.collectors.utils.anonymizer import Anonymizer
from src.utils.env import read_secret
from src.utils.logging import get_logger

logger = get_logger(__name__)


class ServiceNowClient:
    """Client for fetching tickets from ServiceNow."""

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        self.client: Optional[requests.Session] = None
        self.snow_url: Optional[str] = None
        self.snow_projects: list = []
        self.anonymize_data = True
        self.anonymizer: Optional[Anonymizer] = None
        self.visible: bool = True
        self.cutoff_date: Optional[str] = None

        snow_config: Dict[str, Any] = dict(config or {})

        if not snow_config.get("enabled", False):
            logger.debug("ServiceNow source disabled; skipping data fetching from ServiceNow")
            return

        self.snow_config = snow_config
        self.snow_url = snow_config.get("url") or snow_config.get("SNOW_URL")
        if not self.snow_url:
            logger.info(
                "ServiceNow configs couldn't be found. archi will skip data fetching from ServiceNow"
            )
            return

        try:
            self.snow_user = read_secret("SNOW_USER")
            self.snow_password = read_secret("SNOW_PASSWORD")
        except FileNotFoundError as error:
            logger.warning(
                "ServiceNow credentials (SNOW_USER/SNOW_PASSWORD) not found. Skipping ServiceNow collection.",
                exc_info=error,
            )
            return

        self.anonymize_data = snow_config.get("anonymize_data", False)
        self.max_tickets = int(snow_config.get("max_tickets", 1e10))
        self.cutoff_date = snow_config.get("cutoff_date") or snow_config.get("cut_off_date")

        client = self._initialize_session()
        if not client:
            logger.warning("Could not establish ServiceNow connection; skipping ServiceNow collection.")
            return

        self.client = client
        if self.anonymize_data:
            try:
                self.anonymizer = Anonymizer()
            except Exception as error:
                logger.warning(
                    "Failed to initialise ServiceNow anonymizer; continuing without anonymization.",
                    exc_info=error,
                )
                self.anonymize_data = False

    def _initialize_session(self) -> Optional[requests.Session]:
        """Initialize and authenticate ServiceNow session."""
        try:
            session = requests.Session()
            session.auth = HTTPBasicAuth(self.snow_user, self.snow_password)
            session.headers.update({"Accept": "application/json", "Content-Type": "application/json"})

            # Test connection
            url = f"{self.snow_url.rstrip('/')}/api/now/table/incident"
            params = {"sysparm_limit": 1}
            response = session.get(url, params=params, timeout=30)
            response.raise_for_status()
            logger.debug("ServiceNow authentication successful")
            return session
        except Exception as error:
            logger.error(f"Failed to initialize ServiceNow session: {error}")
            return None

    def collect(
        self,
        projects: List[str],
        since_iso: Optional[str] = None,
    ) -> Iterator[TicketResource]:
        """Return an iterator of tickets pulled from ServiceNow."""
        if not self.client:
            logger.warning("Skipping ServiceNow collection; client not initialized.")
            return iter(())
        if not projects:
            logger.warning("Skipping ServiceNow collection; projects missing.")
            return iter(())
        for project in projects:
            yield from self._fetch_ticket_resources(project, since_iso=since_iso)

    def _fetch_ticket_resources(
        self,
        project: str,
        since_iso: Optional[str] = None,
    ) -> Iterator[TicketResource]:
        """Fetch tickets from ServiceNow for a specific project/assignment group."""
        trimmed_url = self.snow_url.rstrip("/") if self.snow_url else None

        for ticket in self._get_project_tickets(project, since_iso=since_iso):
            sys_id = ticket.get("sys_id", "")
            number = ticket.get("number", str(sys_id))
            short_description = ticket.get("short_description", "")
            description = ticket.get("description", "")
            state = ticket.get("state", "")
            priority = ticket.get("priority", "")
            assignment_group = ticket.get("assignment_group", {})
            created_on = ticket.get("sys_created_on", "")
            opened_by = ticket.get("opened_by", {})

            # Build content
            content_parts = []
            if created_on:
                content_parts.append(f"Created: {created_on}")
            if number:
                content_parts.append(f"Ticket: {number}")
            if short_description:
                content_parts.append(f"Summary: {short_description}")
            if description:
                content_parts.append(f"Description: {description}")
            if state:
                content_parts.append(f"State: {state}")
            if priority:
                content_parts.append(f"Priority: {priority}")

            # Add comments/work notes
            comments = self._get_ticket_comments(sys_id)
            if comments:
                content_parts.append("Comments/Work Notes:")
                for comment in comments:
                    comment_text = comment.get("value", "")
                    if comment_text:
                        content_parts.append(f"  - {comment_text}")

            content = "\n".join(part for part in content_parts if part)

            # Anonymize if configured
            if self.anonymize_data and self.anonymizer:
                content = self.anonymizer.anonymize(content)

            metadata = {
                "ticket_number": number,
                "ticket_provider": "servicenow",
                "url": f"{trimmed_url}/nav_to.do?uri=incident.do?sys_id={sys_id}" if trimmed_url else None,
                "project": project,
                "state": state,
                "priority": priority,
            }

            record = TicketResource(
                ticket_id=str(number),
                content=content,
                source_type="ticket",
                created_at=created_on or None,
                metadata={k: v for k, v in metadata.items() if v},
            )

            logger.debug(f"Collected ServiceNow ticket {number}")
            yield record

    def _get_project_tickets(
        self,
        project: str,
        since_iso: Optional[str] = None,
    ) -> Iterator[Dict[str, Any]]:
        """Fetch all tickets from ServiceNow for the specified project/assignment group."""
        if not self.client:
            return

        max_batch_results = min(100, self.max_tickets)
        logger.info(f"Fetching tickets for ServiceNow project: {project}")
        logger.debug(
            f"Fetching maximum of {int(self.max_tickets)} tickets in batches of {max_batch_results} "
            f"for project: {project}"
        )

        # Build query filters
        query_parts = []

        # Filter by assignment group (project)
        if project:
            query_parts.append(f"assignment_groupLIKE{project}")

        # Add cutoff date filter
        cutoff_formatted = self._format_snow_datetime(self.cutoff_date, "cutoff_date")
        if cutoff_formatted:
            query_parts.append(f"sys_created_on>={cutoff_formatted}")

        # Add since_iso filter
        since_formatted = self._format_snow_datetime(since_iso, "since_iso")
        if since_formatted:
            query_parts.append(f"sys_updated_on>={since_formatted}")

        query = "^".join(query_parts)  # ServiceNow uses ^ as AND operator in queries
        logger.debug(f"Fetching ServiceNow tickets with query: {query}")

        url = f"{self.snow_url.rstrip('/')}/api/now/table/incident"
        offset = 0
        project_start = perf_counter()

        while True:
            fetch_start = perf_counter()
            params = {
                "sysparm_query": query,
                "sysparm_limit": max_batch_results,
                "sysparm_offset": offset,
                "sysparm_fields": "sys_id,number,short_description,description,state,priority,"
                "assignment_group,sys_created_on,opened_by,sys_updated_on",
            }

            try:
                response = self.client.get(url, params=params, timeout=30)
                response.raise_for_status()
                data = response.json()
                records = data.get("result", [])
                fetch_duration = perf_counter() - fetch_start

                if not records:
                    logger.info(
                        "ServiceNow search returned 0 tickets | project=%s offset=%d duration=%.2fs",
                        project,
                        offset,
                        fetch_duration,
                    )
                    break

                logger.info(
                    "Fetched %d ServiceNow tickets | project=%s offset=%d duration=%.2fs",
                    len(records),
                    project,
                    offset,
                    fetch_duration,
                )

                yield from records

                if len(records) < max_batch_results:
                    break

                offset += max_batch_results
                if offset > self.max_tickets:
                    logger.warning(f"Reached max ticket limit of {self.max_tickets}. Stopping further fetch.")
                    break

            except requests.RequestException as error:
                logger.error(f"Error fetching ServiceNow tickets: {error}")
                break

        project_duration = perf_counter() - project_start
        logger.info("Completed ServiceNow fetch for project=%s in %.2fs", project, project_duration)

    def _get_ticket_comments(self, sys_id: str) -> List[Dict[str, Any]]:
        """Fetch comments and work notes for a specific ticket."""
        if not self.client or not sys_id:
            return []

        try:
            # Fetch activity stream or comments from journal table
            url = f"{self.snow_url.rstrip('/')}/api/now/table/sys_journal_field"
            params = {
                "sysparm_query": f"element_idLIKE{sys_id}^elementLIKEcomments",
                "sysparm_fields": "value",
                "sysparm_limit": 50,
            }
            response = self.client.get(url, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()
            return data.get("result", [])
        except requests.RequestException as error:
            logger.debug(f"Error fetching comments for ticket {sys_id}: {error}")
            return []

    @staticmethod
    def _format_snow_datetime(date_iso: Optional[str], label: str) -> Optional[str]:
        """Convert ISO-8601 datetime to ServiceNow format (YYYY-MM-DD HH:MM:SS)."""
        if not date_iso:
            return None
        try:
            dt = datetime.fromisoformat(date_iso)
        except (TypeError, ValueError) as error:
            logger.warning(
                "Invalid %s %r; expected ISO-8601. Skipping ServiceNow date filter.",
                label,
                date_iso,
                exc_info=error,
            )
            return None
        return dt.strftime("%Y-%m-%d %H:%M:%S")
