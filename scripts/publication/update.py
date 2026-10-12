#!/usr/bin/python3

import argparse
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, time as wall_time, timezone
from email.utils import parsedate_to_datetime
import fcntl
import getpass
import hashlib
import html
import http.client
import json
import logging
import math
import os
from pathlib import Path
import random
import re
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from zoneinfo import ZoneInfo

import mysql.connector

LOG = logging.getLogger("publications")
EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
LINK_NAME = "pubmed_pubmed_citedin"
STAGES = ("known_articles", "known_citations", "citing_articles", "citation_counts")
POSTPONED = 75


# 1. Original publication workflow, with the later parsing and database fixes.
# These functions retain the original responsibilities, not untouched source.
# Flow: known article metadata -> incoming citation links -> missing citing metadata.
# Added final stage: verified counts for the remaining publication rows.


def getKnownPMIDs(conn):
    cursor = conn.cursor()
    try:
        cursor.execute("""
            SELECT DISTINCT pmid FROM valid_direct_interactions AS vdi
            JOIN interaction2externals AS i2e ON i2e.interaction_id = vdi.id
            JOIN interaction2publications AS i2p
              ON i2e.dbsource_id = i2p.dbsource_id AND i2e.external_id = i2p.external_id
            ORDER BY pmid
        """)
        return normalize_pmids(row[0] for row in cursor.fetchall())
    finally:
        cursor.close()


def getCitingPMIDs(conn):
    cursor = conn.cursor()
    try:
        cursor.execute("""
            SELECT DISTINCT citing_id FROM publication2publications AS p2p
            LEFT JOIN publications AS p ON p2p.citing_id = p.id
            WHERE p.id IS NULL ORDER BY citing_id
        """)
        return normalize_pmids(row[0] for row in cursor.fetchall())
    finally:
        cursor.close()


@dataclass(frozen=True)
class Article:
    pmid: str
    title: object
    journal: object
    pubdate: object
    authors: object
    # Retained as reference metadata only; never written to publications.citation.
    refcount: object


def parse_articles(payload, expected):
    expected = set(normalize_pmids(expected))
    unavailable = {}
    root = read_xml(payload, unavailable)
    if root.tag != "eSummaryResult":
        raise ResponseError("Unexpected ESummary response type")
    articles = {}
    for node in root.findall("./DocSum"):
        pmid = node.findtext("./Id", "").strip()
        if pmid not in expected or pmid in articles:
            raise ResponseError("ESummary returned an unexpected or duplicate PMID")
        authors_node = item(node, "AuthorList")
        authors = None if authors_node is None else tuple(dict.fromkeys(
            text_value(author) for author in authors_node.findall("./Item[@Name='Author']")
            if text_value(author)
        ))
        count = text_value(item(node, "PmcRefCount"))
        if count is not None and count != "":
            if not count.isdecimal() or int(count) > 4294967295:
                raise ResponseError("Invalid PmcRefCount")
            count = int(count)
        else:
            count = None
        articles[pmid] = Article(pmid, text_value(item(node, "Title")),
                                 text_value(item(node, "FullJournalName")),
                                 entry_date(node), authors, count)
    if set(unavailable) - expected or set(unavailable) & set(articles):
        raise ResponseError("ESummary returned an unexpected or conflicting unavailable PMID")
    if set(articles) | set(unavailable) != expected:
        missing = sorted(expected - set(articles) - set(unavailable), key=int)
        raise ResponseError("ESummary omitted requested PMIDs: %s" % ",".join(missing[:10]))
    return ArticleBatch(articles, unavailable)


def parse_citations(payload, expected):
    expected = set(normalize_pmids(expected))
    root = read_xml(payload)
    if root.tag != "eLinkResult":
        raise ResponseError("Unexpected ELink response type")
    citations = {}
    for node in root.findall("./LinkSet"):
        if any(child.tag not in ("DbFrom", "IdList", "LinkSetDb") for child in node):
            raise ResponseError("ELink returned an unexpected result structure")
        ids = [value.text.strip() if value.text else "" for value in node.findall("./IdList/Id")]
        if len(ids) != 1 or ids[0] not in expected or ids[0] in citations:
            raise ResponseError("ELink did not preserve one result per requested PMID")
        if node.findtext("./DbFrom") != "pubmed":
            raise ResponseError("ELink returned an unexpected source database")
        citing = []
        for links in node.findall("./LinkSetDb"):
            if links.findtext("./LinkName") != LINK_NAME or links.findtext("./DbTo") != "pubmed":
                raise ResponseError("ELink returned an unexpected link type")
            for link in links.findall("./Link"):
                if len(link.findall("./Id")) != 1:
                    raise ResponseError("ELink returned an incomplete citation link")
                citing.append(link.findtext("./Id", ""))
        try:
            citations[ids[0]] = normalize_pmids(citing)
        except UpdateError as exc:
            raise ResponseError("ELink returned an invalid citing PMID") from exc
    if set(citations) != expected:
        raise ResponseError("ELink omitted requested PMIDs; old citations were preserved")
    return citations


def write_articles(cursor, articles):
    for article in articles.values():
        # Missing optional upstream fields preserve existing data.
        fields = {"id": article.pmid, "title": column_text(article.title, article.pmid, "title"),
                  "journal": column_text(article.journal, article.pmid, "journal"),
                  "pubdate": article.pubdate}
        fields = {key: value for key, value in fields.items() if value is not None}
        columns = list(fields)
        updates = ["%s=%%s" % name for name in columns if name != "id"]
        cursor.execute("INSERT INTO publications (%s) VALUES (%s) ON DUPLICATE KEY UPDATE %s" % (
            ",".join(columns), ",".join(["%s"] * len(columns)), ",".join(updates) or "id=publications.id"
        ), tuple(fields.values()) + tuple(value for name, value in fields.items() if name != "id"))
        if article.authors is not None:
            cursor.execute("DELETE FROM publication2authors WHERE publication_id=%s", (article.pmid,))
            authors = list(dict.fromkeys(column_text(author, article.pmid, "author") for author in article.authors))
            if authors:
                cursor.executemany("""
                    INSERT INTO publication2authors (publication_id,author) VALUES (%s,%s)
                    ON DUPLICATE KEY UPDATE author=publication2authors.author
                """, [(article.pmid, author) for author in authors])


def write_citations(cursor, citations):
    for cited_id, citing_ids in citations.items():
        citing_ids = normalize_pmids(citing_ids)
        cursor.execute("DELETE FROM publication2publications WHERE cited_id=%s", (cited_id,))
        if citing_ids:
            cursor.executemany("""
                INSERT INTO publication2publications (cited_id,citing_id) VALUES (%s,%s)
            """, [(cited_id, citing_id) for citing_id in citing_ids])
    write_citation_counts(cursor, citations)


def argument_parser(stage=None):
    parser = argparse.ArgumentParser(description=__doc__)
    runtime_dir = Path(__file__).resolve().parents[2] / "severus_prod"
    parser.add_argument("-d", "--database", default=os.environ.get("PRODUCTION_DB"))
    parser.add_argument("-u", "--username", default=os.environ.get("DB_USER"))
    parser.add_argument("-p", "--password", help="Legacy option; prefer DB_PASS to avoid process-list exposure")
    parser.add_argument("--host", default=os.environ.get("DB_HOST", "localhost"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("DB_PORT", "3306")))
    parser.add_argument("--api-key-file", default=os.environ.get("NCBI_API_KEY_FILE", str(runtime_dir / ".ncbi_api_key")))
    parser.add_argument("--email", default=os.environ.get("NCBI_EMAIL", "sat362@pitt.edu"))
    parser.add_argument("--tool", default="impactpredictionanalysis")
    parser.add_argument("--stage", choices=("all",) + STAGES, default=stage or "all")
    default_state = runtime_dir / "publication_state"
    parser.add_argument("--state-dir", default=os.environ.get("PUBLICATION_STATE_DIR", str(default_state)))
    parser.add_argument("--summary-batch-size", type=int, default=100)
    parser.add_argument("--citation-batch-size", type=int, default=20)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--rate", type=int, default=8, help="Aggregate request starts/sec, including retries (maximum 10)")
    parser.add_argument("--timeout", type=float, default=45)
    parser.add_argument("--attempts", type=int, default=3)
    parser.add_argument("--no-wait", action="store_true", help="Exit 75 outside the overnight window, instead of waiting")
    parser.add_argument("--check-config", action="store_true", help="Check key, DB connectivity and table engines; no API requests or writes")
    return parser


def cli(stage=None, argv=None):
    parser = argument_parser(stage)
    options = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if not (1 <= options.rate <= 10 and 1 <= options.workers <= 4 and
            1 <= options.summary_batch_size <= 200 and 1 <= options.citation_batch_size <= 200 and
            1 <= options.attempts <= 5 and 0 < options.timeout <= 120 and math.isfinite(options.timeout)):
        parser.error("Use rate 1–10, workers 1–4, batch sizes 1–200, attempts 1–5, timeout >0 and <=120")
    conn = None
    try:
        key = load_api_key(options.api_key_file)
        db = options.database or input("MySQL Database: ").strip()
        user = options.username or input("MySQL Username: ").strip()
        password = options.password
        if password is None:
            password = os.environ.get("DB_PASS")
        if password is None:
            password = getpass.getpass("MySQL Password: ")
        if not db or not user or not options.email or not options.tool:
            raise UpdateError("Database, username, NCBI email and tool are required")
        state_dir = Path(options.state_dir).expanduser().resolve()
        state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        identity = {"host": options.host, "port": options.port, "database": db}
        token = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[:16]
        key_token = hashlib.sha256(key.encode()).hexdigest()[:24]
        with process_lock(Path(tempfile.gettempdir()) / ("hippip_ncbi_%s.lock" % key_token)), process_lock(state_dir / ".runner.lock"):
            connection_args = dict(host=options.host, port=options.port, database=db, user=user,
                                   password=password, charset="utf8mb4", autocommit=False,
                                   connection_timeout=15, raise_on_warnings=True)
            conn = mysql.connector.connect(**connection_args)
            validate_schema(conn)
            if options.check_config:
                LOG.info("API key configured; database accessible; all publication tables are InnoDB")
                return 0
            # Avoid holding an idle database connection while waiting for 9 PM.
            conn.close()
            conn = None
            window = OvernightWindow()
            window.wait_for_open(options.no_wait)
            conn = mysql.connector.connect(**connection_args)
            validate_schema(conn)
            client = ApiClient(key, options.email, options.tool, window, rate=options.rate,
                               timeout=options.timeout, attempts=options.attempts)
            stages = STAGES if options.stage == "all" else (options.stage,)
            if options.stage == "citing_articles":
                stages += ("citation_counts",)
            prepare_citation_schema(conn)
            checkpoint = Checkpoint(state_dir / ("%s-%s.json" % (token, options.stage)))
            Runner(conn, client, checkpoint, identity, stages, options.summary_batch_size,
                   options.citation_batch_size, options.workers).run()
        return 0
    except WindowClosed:
        LOG.warning("POSTPONED: API window closed. Committed progress is saved; rerun to resume in the next window.")
        return POSTPONED
    except KeyboardInterrupt:
        LOG.warning("Interrupted; committed batches can be resumed on the next launch")
        return 130
    except Exception as exc:
        # Database and filesystem diagnostics are useful; API exceptions have
        # already been sanitized to keep the key out of logs.
        message = str(exc).replace(key, "[redacted]") if 'key' in locals() and key else str(exc)
        LOG.error("FAILED: %s", message)
        return 1
    finally:
        if conn is not None:
            try:
                conn.rollback()
            except mysql.connector.Error:
                LOG.warning("Could not roll back the closing connection; committed batches are saved")
            try:
                conn.close()
            except mysql.connector.Error:
                LOG.warning("Could not close the database connection cleanly")




class UpdateError(Exception):
    pass


class ResponseError(UpdateError):
    """An upstream error or incomplete result, never a valid empty result."""


class WindowClosed(UpdateError):
    pass


class ArticleBatch(dict):
    """Validated records plus explicit per-PMID unavailability from NCBI."""

    def __init__(self, articles, unavailable):
        super().__init__(articles)
        self.unavailable = unavailable


def normalize_pmids(values):
    result = set()
    for value in values:
        value = str(value).strip()
        if not re.fullmatch(r"[1-9][0-9]*", value):
            raise UpdateError("Invalid PMID in worklist: %r" % value)
        result.add(value)
    return sorted(result, key=int)


def read_xml(payload, unavailable=None):
    if isinstance(payload, str):
        payload = payload.encode("utf-8")
    try:
        root = ET.fromstring(payload)
    except ET.ParseError as exc:
        # NCBI can return a JSON rate-limit error despite retmode=xml.
        try:
            error = json.loads(payload).get("error")
        except (ValueError, AttributeError, TypeError):
            error = None
        if error:
            raise ResponseError("NCBI error: %s" % error) from exc
        raise ResponseError("NCBI returned an invalid XML response (possibly an API error)") from exc
    for node in root.iter():
        if node.tag.lower() in ("error", "errorlist"):
            detail = " ".join("".join(node.itertext()).split())
            match = re.fullmatch(r"UID=([1-9][0-9]*): cannot get document summary", detail)
            if unavailable is not None and node in list(root) and match:
                pmid = match.group(1)
                if pmid in unavailable:
                    raise ResponseError("ESummary returned duplicate errors for PMID %s" % pmid)
                unavailable[pmid] = detail
                continue
            raise ResponseError("NCBI error: %s; batch was not written" % (detail or "unspecified error"))
    return root


def item(node, name):
    return node.find("./Item[@Name='%s']" % name)


def text_value(node):
    if node is None:
        return None
    text = "".join(node.itertext())
    # ESummary XML sometimes embeds escaped HTML markup in the Title field.
    return html.unescape(re.sub(r"</?[A-Za-z][^>]*>", "", text)).strip()


def entry_date(node):
    history = item(node, "History")
    raw = text_value(item(history, "pubmed")) if history is not None else None
    if not raw:
        return None
    try:
        value = datetime.fromisoformat(raw.replace("/", "-").replace("Z", "+00:00"))
        if value.tzinfo is not None:
            value = value.astimezone(timezone.utc).replace(tzinfo=None)
    except ValueError as exc:
        raise ResponseError("Invalid PubMed entry date") from exc
    # Existing schema uses a MySQL TIMESTAMP, which cannot hold dates before
    # 1970 or after January 2038. Preserve an existing value when unavailable.
    if value < datetime(1970, 1, 1, 0, 0, 1) or value > datetime(2038, 1, 19, 3, 14, 7):
        LOG.warning("PubMed entry date is outside the legacy TIMESTAMP range; preserving stored date")
        return None
    return value


def column_text(value, pmid, name):
    if value is not None and len(value) > 255:
        LOG.warning("PMID %s: %s shortened to the schema's 255-character limit", pmid, name)
        return value[:255]
    return value


def commit_batch(conn, stage, result):
    cursor = conn.cursor()
    try:
        if stage == "known_citations":
            if getattr(result, "articles", None) is not None:
                write_articles(cursor, result.articles)
            write_citations(cursor, result)
        elif stage == "citation_counts":
            write_citation_counts(cursor, result)
        else:
            write_articles(cursor, result)
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        cursor.close()


def validate_schema(conn):
    cursor = conn.cursor()
    try:
        cursor.execute("""
            SELECT TABLE_NAME, ENGINE FROM information_schema.TABLES
            WHERE TABLE_SCHEMA=DATABASE()
              AND TABLE_NAME IN ('publications','publication2authors','publication2publications')
        """)
        tables = dict(cursor.fetchall())
        required = {"publications", "publication2authors", "publication2publications"}
        if set(tables) != required or any(str(engine).lower() != "innodb" for engine in tables.values()):
            raise UpdateError("Publication tables must exist and use InnoDB for safe batch transactions")
        conn.commit()
    finally:
        cursor.close()


@contextmanager
def process_lock(path):
    descriptor = os.open(str(path), os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise UpdateError("Another publication job is already using this API key or state directory") from exc
        yield
    finally:
        os.close(descriptor)


def load_api_key(path=None):
    key = os.environ.get("NCBI_API_KEY", "").strip()
    if not key and path:
        path = Path(path).expanduser()
        if path.stat().st_mode & 0o077:
            raise UpdateError("API key file must be private (chmod 600)")
        key = path.read_text().strip()
    if not key:
        raise UpdateError("Configure NCBI_API_KEY or NCBI_API_KEY_FILE before running")
    return key


# API scheduling and retries added to the original workflow.
# Every worker and retry uses the same request budget and overnight window.


class OvernightWindow:
    def __init__(self, now=None, sleep=time.sleep):
        self.zone = ZoneInfo("America/New_York")
        self.now = now or (lambda: datetime.now(self.zone))
        self.sleep = sleep

    def bounds(self):
        now = self.now().astimezone(self.zone)
        day = now.date()
        if now.hour < 5:
            start_day, end_day = day - timedelta(days=1), day
        else:
            start_day, end_day = day, day + timedelta(days=1)
        start = datetime.combine(start_day, wall_time(21), self.zone)
        end = datetime.combine(end_day, wall_time(5), self.zone)
        return now, start, end

    def remaining(self):
        now, start, end = self.bounds()
        if now < start or now >= end:
            raise WindowClosed("Outside the 9 PM–5 AM America/New_York API window")
        # Timestamps account for the DST transition in an overnight window.
        return end.timestamp() - now.timestamp()

    def wait_for_open(self, no_wait=False):
        now, start, _ = self.bounds()
        if now < start:
            if no_wait:
                self.remaining()
            LOG.info("Waiting until %s; API requests are allowed 9 PM–5 AM Eastern", start.isoformat())
            while self.now().timestamp() < start.timestamp():
                self.sleep(min(30, start.timestamp() - self.now().timestamp()))
        self.remaining()


class RateLimiter:
    """One rolling-second request-start budget shared by workers and retries."""

    def __init__(self, rate=8, clock=time.monotonic, sleep=time.sleep):
        self.rate = rate
        self.clock = clock
        self.sleep = sleep
        self.starts = deque()
        self.lock = threading.Lock()

    def acquire(self, window, stopped):
        # Reserve immediately before urlopen. The small timing margin avoids
        # bursts at a rolling-window boundary; every retry reserves a new slot.
        while True:
            with self.lock:
                if stopped.is_set():
                    raise WindowClosed("Request scheduling stopped")
                remaining = window.remaining()
                now = self.clock()
                while self.starts and now - self.starts[0] >= 1.01:
                    self.starts.popleft()
                if len(self.starts) < self.rate:
                    self.starts.append(now)
                    return remaining
                delay = self.starts[0] + 1.01 - now
            if delay >= remaining:
                raise WindowClosed("The API window closes before the next request slot")
            self.sleep(min(delay, 0.1))


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        # A redirect would be a second HTTP request outside the shared limiter.
        return None


HTTP_OPEN = urllib.request.build_opener(NoRedirect()).open


class ApiClient:
    def __init__(self, api_key, email, tool, window, rate=8, timeout=45, attempts=3,
                 opener=HTTP_OPEN, limiter=None):
        self.api_key, self.email, self.tool = api_key, email, tool
        self.window, self.timeout, self.attempts = window, timeout, attempts
        self.opener = opener
        self.limiter = limiter or RateLimiter(rate)
        self.stopped = threading.Event()

    def pause(self, seconds):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            if self.stopped.is_set() or end - time.monotonic() >= self.window.remaining():
                raise WindowClosed("Retry deferred until the next API window")
            self.stopped.wait(min(0.1, end - time.monotonic()))

    def fetch(self, stage, pmids):
        if stage == "citation_counts":
            return fetch_verified_citations(self, pmids)
        endpoint = "elink" if stage == "known_citations" else "esummary"
        params = [("retmode", "xml"), ("tool", self.tool), ("email", self.email),
                  ("api_key", self.api_key)]
        if endpoint == "elink":
            params += [("dbfrom", "pubmed"), ("db", "pubmed"), ("cmd", "neighbor"),
                       ("linkname", LINK_NAME)] + [("id", pmid) for pmid in pmids]
            parser = parse_citations
        else:
            params += [("db", "pubmed"), ("id", ",".join(pmids))]
            parser = parse_articles
        request = urllib.request.Request(EUTILS + endpoint + ".fcgi",
                                         data=urllib.parse.urlencode(params).encode("ascii"),
                                         headers={"Content-Type": "application/x-www-form-urlencoded",
                                                  "User-Agent": self.tool}, method="POST")
        last_error = "request failed"
        for attempt in range(self.attempts):
            retry_after = 0
            try:
                timeout = min(self.timeout, self.limiter.acquire(self.window, self.stopped))
                self.window.remaining()
                deadline = time.monotonic() + timeout
                with self.opener(request, timeout=timeout) as response:
                    parts = []
                    while True:
                        if time.monotonic() >= deadline:
                            raise TimeoutError("Response download timed out")
                        part = response.read(65536)
                        if not part:
                            break
                        parts.append(part)
                    return parser(b"".join(parts), pmids)
            except WindowClosed:
                raise
            except urllib.error.HTTPError as exc:
                status = exc.code
                raw_retry = exc.headers.get("Retry-After", "") if exc.headers else ""
                exc.close()
                if status not in (408, 429, 500, 502, 503, 504):
                    raise UpdateError("NCBI HTTP %s; batch was not written" % status) from None
                last_error = "HTTP %s" % status
                try:
                    retry_after = max(0, float(raw_retry))
                    if not math.isfinite(retry_after):
                        retry_after = 0
                except ValueError:
                    try:
                        retry_after = max(0, parsedate_to_datetime(raw_retry).timestamp() - time.time())
                    except (ValueError, TypeError, OverflowError):
                        retry_after = 0
            except (urllib.error.URLError, OSError, TimeoutError, http.client.HTTPException, ResponseError) as exc:
                # Never print request bodies, URLs from exceptions, or the key.
                last_error = str(exc) if isinstance(exc, ResponseError) else type(exc).__name__
                last_error = re.sub(re.escape(self.api_key), "[redacted]", last_error, flags=re.IGNORECASE)
                last_error = " ".join(last_error.split())[:600]
            if attempt + 1 == self.attempts:
                break
            delay = max(retry_after, min(60, 2 ** (attempt + 1)) + random.uniform(0, 1))
            LOG.warning("%s batch (%d PMIDs): %s; retry %d/%d in %.1fs", endpoint,
                        len(pmids), last_error, attempt + 2, self.attempts, delay)
            self.pause(delay)
        raise UpdateError("%s batch failed after %d attempts: %s" % (endpoint, self.attempts, last_error))


# Workers only fetch and parse API responses. The main thread writes to MySQL
# and saves checkpoints after commits, in worklist order.
# Runner.run() manages stages; Runner.run_stage() manages the worker pool.


class Checkpoint:
    def __init__(self, path):
        self.path = Path(path)

    def load(self):
        if not self.path.exists():
            return None
        with self.path.open() as handle:
            return json.load(handle)

    def worklist_path(self, name):
        if name not in ("known", "citing", "counts"):
            raise UpdateError("Invalid checkpoint worklist name")
        return self.path.with_name(self.path.stem + "-" + name + "-pmids.json")

    def save_worklist(self, name, pmids):
        self.atomic_write(self.worklist_path(name), pmids)

    def load_worklist(self, name):
        with self.worklist_path(name).open() as handle:
            return json.load(handle)

    def save(self, state):
        self.atomic_write(self.path, state)

    def atomic_write(self, path, value):
        descriptor, name = tempfile.mkstemp(prefix=".checkpoint-", dir=str(self.path.parent))
        try:
            with os.fdopen(descriptor, "w") as handle:
                json.dump(value, handle, ensure_ascii=False)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(name, path)
            directory = os.open(str(self.path.parent), os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            if os.path.exists(name):
                os.unlink(name)


# Citation-count correction helpers added to the original workflow.
# Counts describe NCBI's incoming PMID links, not a complete literature census.
CITATION_SOURCE = "ncbi_pubmed_citedin"
CHECKPOINT_VERSION = 2
LEGACY_STAGES = ("known_articles", "known_citations", "citing_articles")


class CitationBatch(dict):
    def __init__(self, citations, unavailable=None, articles=None):
        super().__init__(citations)
        self.unavailable = unavailable or {}
        self.articles = articles


def prepare_citation_schema(conn):
    """Migrate legacy reference counts to unknown; normal runs only, never --check-config."""
    cursor = conn.cursor()
    try:
        cursor.execute("""
            SELECT COLUMN_NAME, COLUMN_TYPE, IS_NULLABLE, COLUMN_DEFAULT
            FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='publications'
              AND COLUMN_NAME IN ('citation','citation_source','citation_checked_at')
        """)
        columns = {row[0]: row[1:] for row in cursor.fetchall()}
        citation = columns.get("citation")
        if citation is None or not re.fullmatch(r"int(?:\(\d+\))? unsigned", citation[0].lower()):
            raise UpdateError("publications.citation must be an unsigned INT")
        changes = []
        if citation[1] != "YES" or citation[2] is not None:
            changes.append("MODIFY COLUMN citation INT UNSIGNED NULL DEFAULT NULL")
        if "citation_source" not in columns:
            changes.append("ADD COLUMN citation_source VARCHAR(32) NULL DEFAULT NULL")
        if "citation_checked_at" not in columns:
            changes.append("ADD COLUMN citation_checked_at DATETIME(6) NULL DEFAULT NULL")
        if changes:
            LOG.info("Preparing citation columns; counts without verification will become unknown")
            # The legacy pubdate default is zero. Permit that unchanged default
            # only for this DDL, then restore the original session SQL mode.
            cursor.execute("SELECT @@SESSION.sql_mode")
            sql_mode = cursor.fetchone()[0]
            ddl_mode = ",".join(mode for mode in sql_mode.split(",")
                                if mode not in {"NO_ZERO_DATE", "NO_ZERO_IN_DATE"})
            try:
                set_citation_ddl_mode(cursor, ddl_mode)
                cursor.execute("ALTER TABLE publications " + ", ".join(changes))
            finally:
                set_citation_ddl_mode(cursor, sql_mode)
        cursor.execute("""
            UPDATE publications SET citation=NULL
            WHERE citation IS NOT NULL
              AND (citation_source IS NULL OR citation_checked_at IS NULL)
        """)
        cleared = cursor.rowcount
        conn.commit()
        if cleared:
            LOG.info("Marked %d unverified legacy reference counts unknown pending ELink retrieval", cleared)
    except BaseException:
        conn.rollback()
        raise
    finally:
        cursor.close()


def set_citation_ddl_mode(cursor, mode):
    try:
        cursor.execute("SET SESSION sql_mode=%s", (mode,))
    except mysql.connector.Error as exc:
        # MySQL 8 applies SET, then emits this deprecation warning; the connector
        # raises warnings as errors. Only this known warning may be ignored.
        if exc.errno != 3135:
            raise


def write_citation_counts(cursor, citations):
    for cited_id, citing_ids in citations.items():
        # Normalize again so direct callers cannot count duplicate links.
        count = len(normalize_pmids(citing_ids))
        cursor.execute("""
            UPDATE publications
            SET citation=%s, citation_source=%s, citation_checked_at=UTC_TIMESTAMP(6)
            WHERE id=%s
        """, (count, CITATION_SOURCE, cited_id))
        if cursor.rowcount == 0:
            cursor.execute("SELECT id FROM publications WHERE id=%s", (cited_id,))
            if cursor.fetchone() is None:
                raise UpdateError("Missing metadata for PMID %s; retrieve known_articles first" % cited_id)


def getCitationCountPMIDs(conn):
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT id FROM publications ORDER BY id")
        return normalize_pmids(row[0] for row in cursor.fetchall())
    finally:
        cursor.close()


def fetch_verified_citations(client, pmids, include_metadata=False):
    # ELink can return an empty LinkSet for an invalid PMID. ESummary establishes
    # that each source exists before an empty citation list can become zero.
    articles = client.fetch("citing_articles", pmids)
    valid = list(articles)
    citations = client.fetch("known_citations", valid) if valid else {}
    return CitationBatch(citations, articles.unavailable,
                         articles if include_metadata else None)


def upgrade_citation_checkpoint(state, checkpoint, stages):
    """Keep metadata progress, but replay citation writes under the new meaning."""
    if state.get("version") != 1:
        raise UpdateError("Unsupported publication checkpoint version")
    legacy_stages = list(LEGACY_STAGES) if stages == STAGES else [stages[0]]
    if state.get("stages") != legacy_stages:
        raise UpdateError("Checkpoint belongs to another workflow; use its original configuration")
    index = state.get("stage_index")
    if not isinstance(index, int) or not 0 <= index <= len(legacy_stages):
        raise UpdateError("Invalid legacy checkpoint stage index")
    if "known_citations" in legacy_stages and index >= legacy_stages.index("known_citations"):
        index = legacy_stages.index("known_citations")
        state["work"] = None
    state.update(version=CHECKPOINT_VERSION, stages=list(stages), stage_index=index)
    checkpoint.save(state)
    LOG.info("Upgraded citation checkpoint; metadata progress retained and incoming counts will be refreshed")
    return state


class Runner:
    def __init__(self, conn, client, checkpoint, identity, stages=STAGES,
                 summary_batch=100, citation_batch=20, workers=4):
        self.conn, self.client, self.checkpoint, self.identity = conn, client, checkpoint, identity
        self.stages = tuple(stages)
        self.summary_batch, self.citation_batch, self.workers = summary_batch, citation_batch, workers

    def run(self):
        state = self.checkpoint.load()
        if state and not state.get("completed"):
            if state.get("identity") != self.identity:
                raise UpdateError("Checkpoint belongs to another database/workflow; use its original configuration")
            if state.get("version") == 1:
                state = upgrade_citation_checkpoint(state, self.checkpoint, self.stages)
            if state.get("version") != CHECKPOINT_VERSION or state.get("stages") != list(self.stages):
                raise UpdateError("Checkpoint belongs to another database/workflow; use its original configuration")
            if not isinstance(state.get("stage_index"), int) or not 0 <= state["stage_index"] <= len(self.stages):
                raise UpdateError("Invalid checkpoint stage index")
            LOG.info("Resuming checkpoint %s", self.checkpoint.path)
        else:
            state = {"version": CHECKPOINT_VERSION, "identity": self.identity, "stages": list(self.stages),
                     "stage_index": 0, "known_loaded": False, "work": None, "completed": False,
                     "started_at": datetime.now().astimezone().isoformat()}
            self.checkpoint.save(state)
        state.setdefault("unavailable_articles", {})
        while state["stage_index"] < len(self.stages):
            stage = self.stages[state["stage_index"]]
            if state["work"] is None:
                self.client.window.remaining()
                if stage == "citing_articles":
                    pmids = getCitingPMIDs(self.conn)
                    name = "citing"
                    self.checkpoint.save_worklist(name, pmids)
                elif stage == "citation_counts":
                    pmids = getCitationCountPMIDs(self.conn)
                    # Known papers already got their count and links in one transaction.
                    # Other existing/new citing rows receive counts only, without growing
                    # the citation graph or retrieving another generation of papers.
                    if "known_citations" in self.stages and state["stage_index"] > self.stages.index("known_citations"):
                        known = set(self.checkpoint.load_worklist("known"))
                        pmids = [pmid for pmid in pmids if pmid not in known]
                    unavailable = set(state["unavailable_articles"])
                    pmids = [pmid for pmid in pmids if pmid not in unavailable]
                    name = "counts"
                    self.checkpoint.save_worklist(name, pmids)
                else:
                    name = "known"
                    if not state["known_loaded"]:
                        pmids = getKnownPMIDs(self.conn)
                        self.checkpoint.save_worklist(name, pmids)
                        state["known_loaded"] = True
                self.conn.commit()  # End the read transaction before fetching.
                state["work"] = {"list": name, "next_index": 0}
                self.checkpoint.save(state)
            work = state["work"]
            pmids = self.checkpoint.load_worklist(work["list"])
            if normalize_pmids(pmids) != pmids or not isinstance(work["next_index"], int) or not 0 <= work["next_index"] <= len(pmids):
                raise UpdateError("Invalid checkpoint worklist or offset")
            LOG.info("%s: %d/%d PMIDs already processed", stage, work["next_index"], len(pmids))
            self.run_stage(stage, state, pmids)
            state["stage_index"] += 1
            state["work"] = None
            self.checkpoint.save(state)
        state["completed"] = True
        state["finished_at"] = datetime.now().astimezone().isoformat()
        self.checkpoint.save(state)
        unavailable = state["unavailable_articles"]
        if unavailable:
            LOG.warning("COMPLETED WITH WARNINGS: %d unavailable PMIDs retained their existing data. Details: %s",
                        len(unavailable), self.checkpoint.path)
        else:
            LOG.info("All requested publication stages completed successfully")

    def run_stage(self, stage, state, pmids):
        work = state["work"]
        batch_size = self.citation_batch if stage in ("known_citations", "citation_counts") else self.summary_batch
        submit_index = work["next_index"]
        if submit_index == len(pmids):
            return
        executor = ThreadPoolExecutor(max_workers=self.workers)
        pending = deque()
        failed = True
        unavailable_known = set(state.get("unavailable_articles", {}))
        try:
            while submit_index < len(pmids) or pending:
                while len(pending) < self.workers and submit_index < len(pmids):
                    end = min(submit_index + batch_size, len(pmids))
                    batch = pmids[submit_index:end]
                    if stage in ("known_citations", "citation_counts"):
                        batch = [pmid for pmid in batch if pmid not in unavailable_known]
                    if batch and stage == "known_citations" and "known_articles" not in self.stages:
                        future = executor.submit(fetch_verified_citations, self.client, batch, True)
                    else:
                        future = executor.submit(self.client.fetch, stage, batch) if batch else executor.submit(dict)
                    pending.append((end, future))
                    submit_index = end
                end, future = pending.popleft()
                result = future.result()
                # Commit in submission order so a single contiguous offset is
                # sufficient even when responses arrive out of order.
                commit_batch(self.conn, stage, result)
                for pmid, reason in getattr(result, "unavailable", {}).items():
                    state["unavailable_articles"][pmid] = {"stage": stage, "reason": reason}
                    LOG.warning("%s: PMID %s unavailable (%s); existing metadata and citation links preserved",
                                stage, pmid, reason)
                work["next_index"] = end
                self.checkpoint.save(state)  # Always AFTER the database commit.
                LOG.info("%s: processed %d/%d PMIDs", stage, end, len(pmids))
            failed = False
        finally:
            if failed:
                self.client.stopped.set()
                for _, future in pending:
                    future.cancel()
            executor.shutdown(wait=True, cancel_futures=True)


if __name__ == "__main__":
    sys.exit(cli())
