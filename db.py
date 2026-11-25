"""Database abstraction for Nexus.

Supports SQLite (default) and PostgreSQL. The goal is a small compatibility layer
so existing application code can keep using sqlite3-style `?` placeholders,
`db.execute(...).fetchone()/fetchall()/rowcount`, and dict/index row access.

PostgreSQL is enabled when NEXUS_DATABASE_URL or NEXUS_DB_URL is set to a
postgres:// or postgresql:// URL. SQLite remains the default via NEXUS_DB.
"""
from __future__ import annotations

import os
import re
import sqlite3
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

ROOT = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get('NEXUS_DB', str(ROOT / 'data' / 'nexus.sqlite3')))

# Populated when a PostgreSQL driver is available.
_pg_driver = None  # 'psycopg' | 'psycopg2' | None
_pg_errors = ()
_pg_paramstyle = '%s'


def database_url() -> str:
    return os.environ.get('NEXUS_DATABASE_URL') or os.environ.get('NEXUS_DB_URL') or ''


def is_postgres_url(url: str | None = None) -> bool:
    value = (database_url() if url is None else url).strip().lower()
    return value.startswith('postgres://') or value.startswith('postgresql://')


def is_postgres() -> bool:
    return is_postgres_url()


def backend_name() -> str:
    return 'postgres' if is_postgres() else 'sqlite'


def _load_postgres_driver():
    global _pg_driver, _pg_errors
    if _pg_driver is not None:
        return _pg_driver
    try:
        import psycopg  # type: ignore
        from psycopg.rows import dict_row  # type: ignore
        _pg_driver = ('psycopg', psycopg, dict_row)
        _pg_errors = (psycopg.Error, psycopg.IntegrityError, psycopg.OperationalError)
        return _pg_driver
    except Exception:
        pass
    try:
        import psycopg2  # type: ignore
        import psycopg2.extras  # type: ignore
        _pg_driver = ('psycopg2', psycopg2, psycopg2.extras.RealDictCursor)
        _pg_errors = (psycopg2.Error, psycopg2.IntegrityError, psycopg2.OperationalError)
        return _pg_driver
    except Exception as exc:
        raise RuntimeError(
            'PostgreSQL support requires psycopg (v3) or psycopg2. '
            'Install one of them, or unset NEXUS_DATABASE_URL/NEXUS_DB_URL to use SQLite.'
        ) from exc


def _normalize_value(value):
    # Keep application-visible behavior close to SQLite/text.
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, memoryview):
        return bytes(value)
    try:
        import decimal
        if isinstance(value, decimal.Decimal):
            if value == value.to_integral():
                return int(value)
            return float(value)
    except Exception:
        pass
    if hasattr(value, 'isoformat'):
        # datetime/date/time -> ISO string; SQLite stores TEXT.
        try:
            return value.isoformat()
        except Exception:
            return value
    return value


class Row:
    """Row supporting both key and index access, like sqlite3.Row."""

    __slots__ = ('_mapping', '_values', '_keys')

    def __init__(self, data, values=None):
        if values is not None:
            # data is columns, values is sequence
            cols = list(data)
            vals = tuple(_normalize_value(v) for v in values)
            self._keys = cols
            self._values = vals
            # For duplicate column names, last wins for key access; positional access is preserved.
            self._mapping = {k: v for k, v in zip(cols, vals)}
        elif isinstance(data, dict):
            normalized = {k: _normalize_value(v) for k, v in data.items()}
            self._mapping = normalized
            self._keys = list(normalized.keys())
            self._values = tuple(normalized.values())
        elif hasattr(data, 'keys'):
            normalized = {k: _normalize_value(v) for k, v in dict(data).items()}
            self._mapping = normalized
            self._keys = list(normalized.keys())
            self._values = tuple(normalized.values())
        else:
            # sequence of pairs
            pairs = list(data)
            self._keys = [k for k, _ in pairs]
            self._values = tuple(_normalize_value(v) for _, v in pairs)
            self._mapping = {k: v for k, v in zip(self._keys, self._values)}

    def __getitem__(self, key):
        if isinstance(key, (int, slice)):
            return self._values[key]
        return self._mapping[key]

    def __iter__(self):
        return iter(self._values)

    def __len__(self):
        return len(self._values)

    def keys(self):
        return list(self._keys)

    def items(self):
        return [(k, self._mapping.get(k)) for k in self._keys]

    def values(self):
        return list(self._values)

    def get(self, key, default=None):
        if isinstance(key, int):
            return self._values[key] if -len(self._values) <= key < len(self._values) else default
        return self._mapping.get(key, default)

    def __contains__(self, key):
        if isinstance(key, int):
            return -len(self._values) <= key < len(self._values)
        return key in self._mapping

    def __repr__(self):
        return f'Row({dict(zip(self._keys, self._values))!r})'


def _convert_qmark(sql: str) -> str:
    """Convert sqlite qmark placeholders to psycopg %s placeholders.

    Nexus SQL is static application SQL with bound parameters, so a simple scanner
    that respects quotes, dollar-quoted strings, and comments is sufficient.
    """
    out = []
    i = 0
    n = len(sql)
    in_single = False
    in_double = False
    in_line_comment = False
    in_block_comment = False
    dollar_tag = None
    while i < n:
        ch = sql[i]
        nxt = sql[i + 1] if i + 1 < n else ''
        if in_line_comment:
            out.append(ch)
            if ch == '\n':
                in_line_comment = False
            i += 1
            continue
        if in_block_comment:
            out.append(ch)
            if ch == '*' and nxt == '/':
                out.append(nxt)
                i += 2
                in_block_comment = False
            else:
                i += 1
            continue
        if dollar_tag is not None:
            if sql.startswith(dollar_tag, i):
                out.append(dollar_tag)
                i += len(dollar_tag)
                dollar_tag = None
            else:
                out.append(ch)
                i += 1
            continue
        if in_single:
            out.append(ch)
            if ch == "'" and nxt == "'":
                out.append(nxt)
                i += 2
            elif ch == "'":
                in_single = False
                i += 1
            else:
                i += 1
            continue
        if in_double:
            out.append(ch)
            if ch == '"' and nxt == '"':
                out.append(nxt)
                i += 2
            elif ch == '"':
                in_double = False
                i += 1
            else:
                i += 1
            continue
        if ch == '-' and nxt == '-':
            out.append(ch)
            out.append(nxt)
            in_line_comment = True
            i += 2
            continue
        if ch == '/' and nxt == '*':
            out.append(ch)
            out.append(nxt)
            in_block_comment = True
            i += 2
            continue
        if ch == "'":
            in_single = True
            out.append(ch)
            i += 1
            continue
        if ch == '"':
            in_double = True
            out.append(ch)
            i += 1
            continue
        if ch == '$':
            m = re.match(r'\$[A-Za-z_0-9]*\$', sql[i:])
            if m:
                dollar_tag = m.group(0)
                out.append(dollar_tag)
                i += len(dollar_tag)
                continue
        if ch == '?':
            out.append('%s')
            i += 1
            continue
        out.append(ch)
        i += 1
    return ''.join(out)


def _normalize_sql(sql: str, postgres: bool) -> str:
    if postgres:
        original = sql
        sql = _convert_qmark(sql)
        # SQLite transaction mode not used by Postgres.
        sql = re.sub(r'^\s*BEGIN\s+IMMEDIATE\s*;?\s*$', 'BEGIN', sql, flags=re.I)
        # SQLite INSERT OR IGNORE -> Postgres ON CONFLICT DO NOTHING.
        if re.search(r'\bINSERT\s+OR\s+IGNORE\s+INTO\b', original, flags=re.I):
            sql = re.sub(r'\bINSERT\s+OR\s+IGNORE\s+INTO\b', 'INSERT INTO', sql, flags=re.I)
            if re.search(r'\bON\s+CONFLICT\b', sql, flags=re.I) is None:
                sql = sql.rstrip().rstrip(';') + ' ON CONFLICT DO NOTHING'
        return sql
    return sql


class _CompatCursor:
    def __init__(self, cursor, postgres: bool):
        self._cursor = cursor
        self._postgres = postgres

    @property
    def rowcount(self):
        return self._cursor.rowcount

    @property
    def description(self):
        return self._cursor.description

    @property
    def lastrowid(self):
        # SQLite compatibility; Postgres callers in Nexus do not rely on it.
        return getattr(self._cursor, 'lastrowid', None)

    def _row(self, row):
        if row is None:
            return None
        if isinstance(row, dict):
            return Row(row)
        if hasattr(row, 'keys'):
            try:
                return Row(dict(row))
            except Exception:
                pass
        cols = [d[0] for d in (self._cursor.description or [])]
        # Preserve positional values even when column names repeat (e.g. SUM(debit),SUM(credit)).
        try:
            return Row(cols, list(row))
        except Exception:
            return Row(dict(zip(cols, row)))

    def fetchone(self):
        row = self._cursor.fetchone()
        if row is None:
            return None
        if self._postgres:
            return self._row(row)
        return row

    def fetchall(self):
        rows = self._cursor.fetchall()
        if not self._postgres:
            return rows
        return [self._row(row) for row in rows]

    def close(self):
        try:
            self._cursor.close()
        except Exception:
            pass

    def __iter__(self):
        while True:
            row = self.fetchone()
            if row is None:
                return
            yield row


class PostgresConnection:
    backend = 'postgres'
    is_postgres = True

    def __init__(self, conn):
        self._conn = conn
        self._closed = False

    def _in_transaction(self):
        try:
            status = self._conn.info.transaction_status
            # psycopg3: IDLE=0, ACTIVE=1, INTRANS=2, INERROR=3, UNKNOWN=4
            return int(status) != 0
        except Exception:
            pass
        try:
            # psycopg2
            import psycopg2.extensions as ext
            return self._conn.status != ext.STATUS_READY
        except Exception:
            return False

    def execute(self, sql, params=()):
        normalized = _normalize_sql(sql, True)
        if re.match(r'^\s*BEGIN\b', normalized, flags=re.I) and self._in_transaction():
            cur = self._conn.cursor()
            return _CompatCursor(cur, True)
        cur = self._conn.execute(normalized, params)
        return _CompatCursor(cur, True)

    def executemany(self, sql, params_seq):
        sql = _normalize_sql(sql, True)
        cur = self._conn.cursor()
        cur.executemany(sql, list(params_seq))
        return _CompatCursor(cur, True)

    def executescript(self, sql):
        # psycopg3 supports multi-statement execute in autocommit blocks sometimes,
        # but we keep it simple: split on semicolons at top level.
        cur = self._conn.cursor()
        for statement in _split_sql_statements(sql):
            stmt = statement.strip()
            if stmt:
                cur.execute(stmt)
        return _CompatCursor(cur, True)

    def commit(self):
        self._conn.commit()

    def rollback(self):
        try:
            self._conn.rollback()
        except Exception:
            pass

    def close(self):
        if not self._closed:
            self._closed = True
            try:
                self._conn.close()
            except Exception:
                pass

    @property
    def closed(self):
        return self._closed

    def cursor(self):
        return _CompatCursor(self._conn.cursor(), True)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        try:
            if exc_type is None:
                self.commit()
            else:
                self.rollback()
        finally:
            self.close()
        return False


class SQLiteConnection(sqlite3.Connection):
    backend = 'sqlite'
    is_postgres = False

    def __exit__(self, exc_type, exc, tb):
        try:
            return super().__exit__(exc_type, exc, tb)
        finally:
            self.close()


def _split_sql_statements(sql: str):
    # Simple statement splitter for schema scripts. Handles quotes and dollar quotes.
    statements = []
    buff = []
    i = 0
    n = len(sql)
    in_single = in_double = in_line_comment = in_block_comment = False
    dollar_tag = None
    while i < n:
        ch = sql[i]
        nxt = sql[i + 1] if i + 1 < n else ''
        if in_line_comment:
            buff.append(ch)
            if ch == '\n':
                in_line_comment = False
            i += 1
            continue
        if in_block_comment:
            buff.append(ch)
            if ch == '*' and nxt == '/':
                buff.append(nxt)
                i += 2
                in_block_comment = False
            else:
                i += 1
            continue
        if dollar_tag is not None:
            buff.append(ch)
            if sql.startswith(dollar_tag, i):
                buff.extend(dollar_tag[1:])
                i += len(dollar_tag)
                dollar_tag = None
            else:
                i += 1
            continue
        if in_single:
            buff.append(ch)
            if ch == "'" and nxt == "'":
                buff.append(nxt)
                i += 2
            elif ch == "'":
                in_single = False
                i += 1
            else:
                i += 1
            continue
        if in_double:
            buff.append(ch)
            if ch == '"' and nxt == '"':
                buff.append(nxt)
                i += 2
            elif ch == '"':
                in_double = False
                i += 1
            else:
                i += 1
            continue
        if ch == '-' and nxt == '-':
            buff.append(ch); buff.append(nxt); in_line_comment = True; i += 2; continue
        if ch == '/' and nxt == '*':
            buff.append(ch); buff.append(nxt); in_block_comment = True; i += 2; continue
        if ch == "'":
            in_single = True; buff.append(ch); i += 1; continue
        if ch == '"':
            in_double = True; buff.append(ch); i += 1; continue
        if ch == '$':
            m = re.match(r'\$[A-Za-z_0-9]*\$', sql[i:])
            if m:
                dollar_tag = m.group(0)
                buff.append(dollar_tag)
                i += len(dollar_tag)
                continue
        if ch == ';':
            stmt = ''.join(buff).strip()
            if stmt:
                statements.append(stmt)
            buff = []
            i += 1
            continue
        buff.append(ch)
        i += 1
    tail = ''.join(buff).strip()
    if tail:
        statements.append(tail)
    return statements


def connect_sqlite(path: Path | None = None, timeout: float = 15):
    db_path = Path(path) if path is not None else DB_PATH
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), timeout=timeout, factory=SQLiteConnection)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')
    conn.execute(f'PRAGMA busy_timeout={int(timeout * 1000)}')
    return conn


def connect_postgres(url: str | None = None):
    url = (url or database_url()).strip()
    driver_name, driver, row_factory = _load_postgres_driver()
    # Sensible defaults; allow URL to override via query params.
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    connect_timeout = int(os.environ.get('NEXUS_PG_CONNECT_TIMEOUT', query.pop('connect_timeout', '10')))
    app_name = os.environ.get('NEXUS_PG_APPNAME', query.pop('application_name', 'nexus'))
    clean_url = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))
    if driver_name == 'psycopg':
        conn = driver.connect(clean_url, connect_timeout=connect_timeout, application_name=app_name, autocommit=False)
    else:
        conn = driver.connect(clean_url, connect_timeout=connect_timeout, application_name=app_name)
        conn.autocommit = False
    with conn.cursor() as cur:
        cur.execute("SET TIME ZONE 'UTC'")
        cur.execute("SELECT set_config('statement_timeout', %s, false)", (str(int(os.environ.get('NEXUS_PG_STATEMENT_TIMEOUT_MS', '15000'))),))
        cur.execute("SELECT set_config('lock_timeout', %s, false)", (str(int(os.environ.get('NEXUS_PG_LOCK_TIMEOUT_MS', '5000'))),))
        cur.execute("SELECT set_config('idle_in_transaction_session_timeout', %s, false)", (str(int(os.environ.get('NEXUS_PG_IDLE_TX_TIMEOUT_MS', '30000'))),))
    conn.commit()
    return PostgresConnection(conn)


def connect_db(path: Path | None = None, timeout: float = 15):
    if is_postgres():
        return connect_postgres()
    return connect_sqlite(path, timeout)


def init_sqlite(path: Path | None = None):
    db_path = Path(path) if path is not None else DB_PATH
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with connect_sqlite(db_path) as db:
        db.execute('PRAGMA journal_mode=WAL')
        db.executescript((ROOT / 'schema.sql').read_text('utf-8'))
        cols = {r['name'] for r in db.execute("PRAGMA table_info(idempotency_keys)")}
        if 'fingerprint' not in cols:
            db.execute("ALTER TABLE idempotency_keys ADD COLUMN fingerprint TEXT NOT NULL DEFAULT ''")


def init_postgres(url: str | None = None):
    schema = (ROOT / 'schema.postgres.sql').read_text('utf-8')
    with connect_postgres(url) as db:
        db.executescript(schema)
        # Ensure idempotency fingerprint exists for older DBs.
        row = db.execute(
            "SELECT 1 FROM information_schema.columns WHERE table_name='idempotency_keys' AND column_name='fingerprint'"
        ).fetchone()
        if not row:
            db.execute("ALTER TABLE idempotency_keys ADD COLUMN fingerprint TEXT NOT NULL DEFAULT ''")


def initialize(path: Path | None = None):
    if is_postgres():
        init_postgres()
    else:
        init_sqlite(path)


# Exception compatibility. SQLite callers/tests may catch sqlite3.IntegrityError.
IntegrityError = sqlite3.IntegrityError
OperationalError = sqlite3.OperationalError
DatabaseError = sqlite3.DatabaseError


def postgres_exception_types():
    if not is_postgres():
        return ()
    try:
        name, driver, _ = _load_postgres_driver()
        return (driver.IntegrityError, driver.OperationalError, driver.Error)
    except Exception:
        return ()
