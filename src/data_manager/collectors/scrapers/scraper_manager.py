import os
import importlib
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from src.data_manager.collectors.persistence import PersistenceService
from src.data_manager.collectors.scrapers.scraped_resource import \
    ScrapedResource
from src.data_manager.collectors.scrapers.scraper import LinkScraper
from src.utils.config_loader import load_global_config
from src.utils.logging import get_logger

logger = get_logger(__name__)

if TYPE_CHECKING:
    from src.data_manager.collectors.scrapers.integrations.git_scraper import \
        GitScraper


class ScraperManager:
    """Coordinates scraper integrations and centralises persistence logic."""

    def __init__(self, dm_config: Optional[Dict[str, Any]] = None) -> None:
        global_config = load_global_config()

        sources_config = (dm_config or {}).get("sources", {}) or {}
        links_config = sources_config.get("links", {}) if isinstance(sources_config, dict) else {}
        selenium_config = links_config.get("selenium_scraper", {}) if isinstance(sources_config, dict) else {}

        git_config = sources_config.get("git", {}) if isinstance(sources_config, dict) else {}
        self.base_depth = links_config.get('base_source_depth', 5)
        logger.debug(f"Using base depth of {self.base_depth} for weblist URLs")

        scraper_config = {}
        if isinstance(links_config, dict):
            scraper_config = links_config.get("html_scraper", {}) or {}
        if not scraper_config:
            scraper_config = utils_config.get("html_scraper", {}) or {}
        self.config = scraper_config
        raw_max_pages = links_config.get("max_pages")
        self.max_pages = None
        if raw_max_pages not in (None, ""):
            try:
                self.max_pages = int(raw_max_pages)
            except (TypeError, ValueError):
                logger.warning(f"Invalid max_pages value {raw_max_pages}; ignoring.")

        self.links_enabled = links_config.get("enabled", True)
        self.git_enabled = git_config.get("enabled", False) if isinstance(git_config, dict) else True
        self.git_config = git_config if isinstance(git_config, dict) else {}
        self.selenium_config = selenium_config or {}
        self.selenium_enabled = self.selenium_config.get("enabled", False)
        self.scrape_with_selenium = self.selenium_config.get("use_for_scraping", False)

        self.data_path = Path(global_config["DATA_PATH"])
        self.input_lists = links_config.get("input_lists", [])
        self.git_dir = self.data_path / "git"

        self.data_path.mkdir(parents=True, exist_ok=True)

        self.web_scraper = LinkScraper(
            verify_urls=self.config.get("verify_urls", True),
            enable_warnings=self.config.get("enable_warnings", True),
        )
        self._git_scraper: Optional["GitScraper"] = None
          
    def collect_all_from_config(
        self, persistence: PersistenceService
    ) -> None:
        """Run the configured scrapers and persist their output."""
        input_lists = self.config.get("input_lists", [])
        link_urls, git_urls, sso_urls = self._collect_urls_from_lists_by_type(input_lists)

        self.collect_links(persistence, link_urls=link_urls)
        self.collect_sso(persistence, sso_urls=sso_urls)
        self.collect_git(persistence, git_urls=git_urls)

        logger.info("Web scraping was completed successfully")

    def collect_links(
        self,
        persistence: PersistenceService,
        link_urls: List[str] = [],
    ) -> None:
        """Collect only standard link sources."""
        if not self.links_enabled:
            logger.info("Links disabled, skipping link scraping")
            return
        if not link_urls:
            return
        websites_dir = persistence.data_path / "websites"
        if not os.path.exists(websites_dir):
            os.makedirs(websites_dir, exist_ok=True)
        self._collect_links_from_urls(link_urls, persistence, websites_dir)

    def collect_git(
        self,
        persistence: PersistenceService,
        git_urls: Optional[List[str]] = None,
    ) -> None:
        """Collect only git sources."""
        if not self.git_enabled:
            logger.info("Git disabled, skipping git scraping")
            return
        if not git_urls:
            return
        git_dir = persistence.data_path / "git"
        if not os.path.exists(git_dir):
            os.makedirs(git_dir, exist_ok=True)
        self._collect_git_resources(git_urls, persistence, git_dir)

    def collect_sso(
        self,
        persistence: PersistenceService,
        sso_urls: Optional[List[str]] = None,
    ) -> None:
        """Collect only SSO sources."""
        if not self.sso_enabled:
            logger.info("SSO disabled, skipping SSO scraping")
            return
        if not sso_urls:
            return
        sso_dir = persistence.data_path / "sso"
        if not os.path.exists(sso_dir):
            os.makedirs(sso_dir, exist_ok=True)
        self._collect_sso_from_urls(sso_urls, persistence, sso_dir)

    def schedule_collect_links(self, persistence: PersistenceService, last_run: Optional[str] = None) -> None:
        """
        Scheduled collection of link sources.
        For now, this behaves the same as a full collection, overriding last_run depending on the persistence layer.
        """
        metadata = self.persistence.catalog.get_metadata_by_filter("source_type", source_type="links", metadata_keys=["url"])
        catalog_urls = [m[1].get("url", "") for m in metadata]
        self.collect_links(persistence, link_urls=catalog_urls)

    def schedule_collect_git(self, persistence: PersistenceService, last_run: Optional[str] = None) -> None:
        metadata = self.persistence.catalog.get_metadata_by_filter("source_type", source_type="git", metadata_keys=["url"])
        catalog_urls = [m[1].get("url", "") for m in metadata]
        self.collect_git(persistence, git_urls=catalog_urls)

    def schedule_collect_sso(self, persistence: PersistenceService, last_run: Optional[str] = None) -> None:
        metadata = self.persistence.catalog.get_metadata_by_filter("source_type", source_type="sso", metadata_keys=["url"])
        catalog_urls = [m[1].get("url", "") for m in metadata]
        self.collect_sso(persistence, sso_urls=catalog_urls)

    def _collect_links_from_urls(
        self,
        urls: List[str],
        persistence: PersistenceService,
        websites_dir: Path,
    ) -> None:
        for url in urls:
            self._handle_standard_url(url, persistence, websites_dir)

        # authenticator is not made a class variable here because we mgiht want to use multiple in the future
        # initialize only once and use it for all scrapes in a batch 
        authenticator = None
        if self.selenium_enabled:
            authenticator_class, kwargs = self._resolve_scraper()
            authenticator = authenticator_class(**kwargs)

        for raw_url, depth in self.collect_urls_from_lists():
            if raw_url.startswith("git-"):
                git_urls.append(raw_url.split("git-", 1)[1])
                continue

            selenium_client = authenticator if self.scrape_with_selenium else None

            url = raw_url
            if raw_url.startswith("sso-"):
                url = raw_url.split("sso-", 1)[1]

                # Now the selenium client is still necessary for the auth regardless
                selenium_client = authenticator

            self._handle_standard_url(url, persistence, websites_dir, depth, selenium_client, self.scrape_with_selenium)

        if authenticator is not None: 
            authenticator.close() # close the authenticator properly and free the resources

        if self.git_enabled and git_urls:
            if self.config.get("reset_data", False):
                persistence.reset_directory(self.git_dir)
            git_resources = self._collect_git_resources(
                git_urls, persistence
            )
            logger.debug(f"Git scraping produced {len(git_resources)} resources")
        elif git_urls:
            logger.warning("Git URLs detected but git source is disabled; skipping git scraping")

    def _collect_sso_resources(self, urls: List[str]) -> List[ScrapedResource]:
        resources: List[ScrapedResource] = []
        for url in urls:
            resources.extend(self.sso_collector.collect(url))
        return resources

    def _collect_urls_from_lists(self, input_lists) -> List[tuple[str, int]]:
        """Collect URLs from the configured weblists."""
        # Handle case where input_lists might be None
        urls: List[tuple[str, int]] = []
        if not self.input_lists:
            return urls
        for list_name in input_lists:
            list_path = Path("weblists") / Path(list_name).name
            if not list_path.exists():
                logger.warning(f"Input list {list_path} not found.")
                continue

            urls.extend(self._extract_urls_from_file(list_path))

        return urls

    def _collect_urls_from_lists_by_type(self, input_lists: List[str]) -> tuple[List[str], List[str], List[str]]:
        """All types of URLs are in the same input lists, separate them via prefixes"""
        link_urls: List[str] = []
        git_urls: List[str] = []
        sso_urls: List[str] = []
        for raw_url in self._collect_urls_from_lists(input_lists):
            if raw_url.startswith("git-"):
                git_urls.append(raw_url.split("git-", 1)[1])
                continue
            if raw_url.startswith("sso-"):
                sso_urls.append(raw_url.split("sso-", 1)[1])
                continue
            link_urls.append(raw_url)
        return link_urls, git_urls, sso_urls
    def _resolve_scraper(self):
        class_name = self.selenium_config.get("selenium_class")
        class_map = self.selenium_config.get("selenium_class_map", "")

        entry = class_map.get(class_name)

        if not entry: 
            logger.error("Selenium class {class_name} is not defined in the configuration")
            return None, {}

        scraper_class = entry.get("class")
        if isinstance(scraper_class, str):
            module_name = entry.get(
                    "module", 
                    "src.data_manager.collectors.scrapers.links.selenium_scraper",
                    )
            module = importlib.import_module(module_name)
            scraper_class = getattr(module, scraper_class)
        scraper_kwargs = entry.get("kwargs", {})
        return scraper_class, scraper_kwargs

    def _handle_standard_url(
            self, 
            url: str, 
            persistence: PersistenceService, 
            websites_dir: Path, 
            max_depth: int, 
            client=None, 
            use_client_for_scraping: bool = False,
    ) -> None:
        try:
            for resource in self.web_scraper.crawl_iter(
                url,
                browserclient=client,
                max_depth=max_depth,
                selenium_scrape=use_client_for_scraping,
                max_pages=self.max_pages,
            ):
                persistence.persist_resource(
                    resource, websites_dir
                )
        except Exception as exc:
            logger.error(f"Failed to scrape {url}: {exc}")

    def _extract_urls_from_file(self, path: Path) -> List[tuple[str, int]]:
        urls: List[str] = []
        with path.open("r") as file:
            for line in file:
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                # check if a depth was specified  for crawling if not make it 1
                url_depth = stripped.split(",")

                depth = self.base_depth # default
                if len(url_depth) == 2 : 
                    stripped = url_depth[0]
                    depth = url_depth[1]
                urls.append((stripped, depth))
        return urls

    def _collect_git_resources(
        self,
        git_urls: List[str],
        persistence: PersistenceService,
        git_dir: Path,
    ) -> List[ScrapedResource]:
        git_scraper = self._get_git_scraper()
        resources = git_scraper.collect(git_urls)
        for resource in resources:
            persistence.persist_resource(resource, git_dir)
        return resources

    def _get_git_scraper(self) -> "GitScraper":
        if self._git_scraper is None:
            from src.data_manager.collectors.scrapers.integrations.git_scraper import \
                    GitScraper

            self._git_scraper = GitScraper(manager=self, git_config=self.git_config)
        return self._git_scraper
