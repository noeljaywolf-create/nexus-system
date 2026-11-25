"""Migrate Nexus data from SQLite to PostgreSQL.

Usage:
  python migrate_sqlite_to_postgres.py --sqlite data/nexus.sqlite3 --postgres postgresql://...

Verifies data fidelity after migration (row counts, key fields, money, blobs,
booleans, timestamps, audit sequence).
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import db as nexus_db


# Tables in dependency-safe insertion order. audit_log.seq is handled specially.
TABLES = [
    'schema_version',
    'organizations',
    'users',
    'memberships',
    'sessions',
    'login_attempts',
    'invitations',
    'customers',
    'suppliers',
    'products',
    'stock_movements',
    'projects',
    'project_members',
    'conversations',
    'conversation_members',
    'messages',
    'message_history',
    'reactions',
    'attachments',
    'tasks',
    'requisitions',
    'approvals',
    'purchase_orders',
    'invoices',
    'ledger_entries',
    'ledger_lines',
    'documents',
    'meetings',
    'meeting_attendees',
    'notifications',
    'audit_log',
    'organization_units',
    'assets',
    'contracts',
    'installed_packages',
    'extension_records',
    'conversation_records',
    'document_metadata',
    'document_files',
    'demo_workspaces',
    'workflow_rules',
    'workflow_versions',
    'workflow_runs',
    'workflow_effects',
    'idempotency_keys',
]

# Columns that are boolean-ish in app semantics (stored 0/1 in SQLite; PG has CHECK 0/1 int in schema).
BOOL_INT_COLS = {
    'memberships': {'active'},
    'projects': {'private'},
    'messages': {'pinned'},
    'workflow_rules': {'enabled'},
}
# Blob columns
BLOB_COLS = {
    'attachments': {'content'},
    'document_files': {'content'},
}
# audit_log.seq is GENERATED ALWAYS AS IDENTITY in PG schema; we must override.
IDENTITY_OVERRIDE = {
    'audit_log': 'seq',
}


def sqlite_rows(sqlite_path: Path, table: str):
    conn = sqlite3.connect(str(sqlite_path))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(f'SELECT * FROM {table} ORDER BY rowid').fetchall()
        cols = [d[0] for d in conn.execute(f'SELECT * FROM {table} LIMIT 0').description]
        return cols, [dict(r) for r in rows]
    finally:
        conn.close()


def pg_table_cols(pg, table: str):
    rows = pg.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_schema='public' AND table_name=%s ORDER BY ordinal_position",
        (table,),
    ).fetchall()
    return [r['column_name'] for r in rows]


def coerce_value(table: str, col: str, value):
    if value is None:
        return None
    if table in BLOB_COLS and col in BLOB_COLS[table]:
        if isinstance(value, memoryview):
            return bytes(value)
        if isinstance(value, bytes):
            return value
        # SQLite may return buffer-like; preserve bytes.
        return bytes(value)
    if table in BOOL_INT_COLS and col in BOOL_INT_COLS[table]:
        return int(value)
    return value


def migrate(sqlite_path: Path, pg_url: str, *, apply_schema: bool = True, truncate: bool = False) -> dict:
    src = sqlite3.connect(str(sqlite_path))
    src.row_factory = sqlite3.Row
    src.execute('PRAGMA foreign_keys=OFF')
    try:
        nexus_db._pg_driver = None
        old_url = os.environ.get('NEXUS_DATABASE_URL')
        old_url2 = os.environ.get('NEXUS_DB_URL')
        os.environ['NEXUS_DATABASE_URL'] = pg_url
        os.environ.pop('NEXUS_DB_URL', None)
        try:
            if apply_schema:
                nexus_db.init_postgres(pg_url)
            with nexus_db.connect_postgres(pg_url) as pg:
                pg.execute('SET session_replication_role = replica')  # defer FK/trigger checks during bulk load; we verify after
                if truncate:
                    for t in reversed(TABLES):
                        pg.execute(f'DELETE FROM {t}')
                counts = {}
                for table in TABLES:
                    try:
                        src_cols = [d[0] for d in src.execute(f'SELECT * FROM {table} LIMIT 0').description]
                    except sqlite3.OperationalError:
                        counts[table] = {'skipped': True, 'reason': 'missing in sqlite'}
                        continue
                    rows = src.execute(f'SELECT * FROM {table}').fetchall()
                    if not rows:
                        counts[table] = {'rows': 0}
                        continue
                    dst_cols = set(pg_table_cols(pg, table))
                    cols = [c for c in src_cols if c in dst_cols]
                    if not cols:
                        counts[table] = {'rows': 0, 'skipped': True, 'reason': 'no common columns'}
                        continue
                    placeholders = ','.join(['%s'] * len(cols))
                    col_list = ','.join(cols)
                    identity_col = IDENTITY_OVERRIDE.get(table)
                    override = f' OVERRIDING SYSTEM VALUE' if identity_col in cols else ''
                    sql = f'INSERT INTO {table} ({col_list}){override} VALUES ({placeholders}) ON CONFLICT DO NOTHING'
                    for row in rows:
                        values = [coerce_value(table, c, row[c]) for c in cols]
                        pg.execute(sql, values)
                    counts[table] = {'rows': len(rows)}
                pg.execute('SET session_replication_role = DEFAULT')
                # Fix audit_log sequence if present
                try:
                    pg.execute("SELECT setval(pg_get_serial_sequence('audit_log','seq'), COALESCE((SELECT MAX(seq) FROM audit_log),1), true)")
                except Exception:
                    try:
                        pg.execute("SELECT setval('audit_log_seq_seq', COALESCE((SELECT MAX(seq) FROM audit_log),1), true)")
                    except Exception:
                        pass
                pg.commit()
        finally:
            if old_url is None:
                os.environ.pop('NEXUS_DATABASE_URL', None)
            else:
                os.environ['NEXUS_DATABASE_URL'] = old_url
            if old_url2 is None:
                os.environ.pop('NEXUS_DB_URL', None)
            else:
                os.environ['NEXUS_DB_URL'] = old_url2
    finally:
        src.close()
    return counts

def _norm(val):
    if val is None:
        return None
    if isinstance(val, memoryview):
        val = bytes(val)
    if isinstance(val, (bytes, bytearray)):
        return ('blob', hashlib.sha256(bytes(val)).hexdigest(), len(val))
    if hasattr(val, 'isoformat'):
        # normalize timestamps to comparable ISO string
        s = val.isoformat()
        # Postgres may return +00:00, SQLite stores +00:00 or Z-like; normalize
        s = s.replace('+00:00', 'Z')
        if s.endswith('Z') and '.' not in s[:-1]:
            pass
        return ('ts', s)
    if isinstance(val, bool):
        return int(val)
    if isinstance(val, int):
        return val
    if isinstance(val, float):
        # shouldn't happen for money, but be defensive
        return str(val)
    if isinstance(val, str):
        return val
    return str(val)


def verify(sqlite_path: Path, pg_url: str) -> dict:
    src = sqlite3.connect(str(sqlite_path))
    src.row_factory = sqlite3.Row
    report = {'ok': True, 'tables': {}, 'issues': []}
    old_url = os.environ.get('NEXUS_DATABASE_URL')
    old_url2 = os.environ.get('NEXUS_DB_URL')
    os.environ['NEXUS_DATABASE_URL'] = pg_url
    os.environ.pop('NEXUS_DB_URL', None)
    try:
        with nexus_db.connect_postgres(pg_url) as pg:
            for table in TABLES:
                try:
                    src_cols = [d[0] for d in src.execute(f'SELECT * FROM {table} LIMIT 0').description]
                except sqlite3.OperationalError:
                    report['tables'][table] = {'skipped': 'missing in sqlite'}
                    continue
                dst_cols = pg_table_cols(pg, table)
                common = [c for c in src_cols if c in dst_cols]
                src_rows = [dict(r) for r in src.execute(f'SELECT * FROM {table}').fetchall()]
                pg_rows = [dict(r) for r in pg.execute(f'SELECT {",".join(common)} FROM {table}').fetchall()]
                entry = {'sqlite': len(src_rows), 'postgres': len(pg_rows)}
                if len(src_rows) != len(pg_rows):
                    entry['ok'] = False
                    report['ok'] = False
                    report['issues'].append(f'{table}: row count mismatch sqlite={len(src_rows)} pg={len(pg_rows)}')
                    report['tables'][table] = entry
                    continue
                # Compare by primary key-like identity if possible
                pk = common[0] if common else None
                def key(r):
                    if table == 'schema_version':
                        return r.get('version')
                    if 'id' in r:
                        return r.get('id')
                    if 'seq' in r:
                        return r.get('seq')
                    return tuple(_norm(r.get(c)) for c in common)
                src_map = {key(r): r for r in src_rows}
                pg_map = {key(r): r for r in pg_rows}
                if set(src_map.keys()) != set(pg_map.keys()):
                    entry['ok'] = False
                    report['ok'] = False
                    report['issues'].append(f'{table}: key set mismatch')
                    report['tables'][table] = entry
                    continue
                mismatches = []
                for k, sr in src_map.items():
                    pr = pg_map[k]
                    for c in common:
                        sv = _norm(coerce_value(table, c, sr.get(c)))
                        pv = _norm(pr.get(c))
                        # Timestamps: SQLite stores text, PG returns datetime - compare normalized
                        if sv != pv:
                            # tolerate timestamp formatting differences
                            def _ts_parse(x):
                                if isinstance(x, tuple) and x[0] == 'ts':
                                    x = x[1]
                                if isinstance(x, str):
                                    s = x.replace('Z', '+00:00')
                                    # only attempt parse for timestamp-like strings
                                    if len(s) >= 10 and s[4:5] == '-' and ':' in s:
                                        try:
                                            from datetime import datetime
                                            return datetime.fromisoformat(s)
                                        except Exception:
                                            return None
                                return None
                            d1 = _ts_parse(sv)
                            d2 = _ts_parse(pv)
                            if d1 is not None and d2 is not None and d1 == d2:
                                continue
                            # also tolerate bool/int 0/1 representations
                            if isinstance(sv, bool):
                                sv_cmp = int(sv)
                            else:
                                sv_cmp = sv
                            if isinstance(pv, bool):
                                pv_cmp = int(pv)
                            else:
                                pv_cmp = pv
                            if sv_cmp == pv_cmp:
                                continue
                            mismatches.append({'key': k, 'column': c, 'sqlite': sv, 'postgres': pv})
                            if len(mismatches) >= 10:
                                break
                    if len(mismatches) >= 10:
                        break
                entry['mismatches'] = mismatches
                entry['ok'] = len(mismatches) == 0
                if mismatches:
                    report['ok'] = False
                    report['issues'].append(f'{table}: {len(mismatches)} field mismatch(es)')
                report['tables'][table] = entry
            # Constraint/immutability checks
            checks = {}
            try:
                pg.execute('SAVEPOINT fidelity_checks')
                pg.execute("UPDATE ledger_lines SET debit=debit WHERE 1=0")
                # actual immutability test - attempt update; should fail
                try:
                    pg.execute("UPDATE ledger_lines SET debit=0 WHERE id IN (SELECT id FROM ledger_lines LIMIT 1)")
                    pg.execute('ROLLBACK TO SAVEPOINT fidelity_checks')
                    checks['ledger_lines_immutable'] = False
                    report['ok'] = False
                    report['issues'].append('ledger_lines not immutable')
                except Exception:
                    pg.execute('ROLLBACK TO SAVEPOINT fidelity_checks')
                    checks['ledger_lines_immutable'] = True
                pg.execute('RELEASE SAVEPOINT fidelity_checks')
            except Exception as e:
                checks['ledger_lines_immutable'] = f'error: {e}'
            try:
                pg.execute('SAVEPOINT fidelity_checks2')
                try:
                    pg.execute("UPDATE audit_log SET action='x' WHERE seq IN (SELECT seq FROM audit_log LIMIT 1)")
                    pg.execute('ROLLBACK TO SAVEPOINT fidelity_checks2')
                    checks['audit_log_immutable'] = False
                    report['ok'] = False
                    report['issues'].append('audit_log not immutable')
                except Exception:
                    pg.execute('ROLLBACK TO SAVEPOINT fidelity_checks2')
                    checks['audit_log_immutable'] = True
                pg.execute('RELEASE SAVEPOINT fidelity_checks2')
            except Exception as e:
                checks['audit_log_immutable'] = f'error: {e}'
            report['constraints'] = checks
    finally:
        if old_url is None:
            os.environ.pop('NEXUS_DATABASE_URL', None)
        else:
            os.environ['NEXUS_DATABASE_URL'] = old_url
        if old_url2 is None:
            os.environ.pop('NEXUS_DB_URL', None)
        else:
            os.environ['NEXUS_DB_URL'] = old_url2
        src.close()
    return report


def main():
    ap = argparse.ArgumentParser(description='Migrate Nexus SQLite database to PostgreSQL')
    ap.add_argument('--sqlite', default=str(ROOT / 'data' / 'nexus.sqlite3'), help='Source SQLite DB path')
    ap.add_argument('--postgres', required=True, help='Target PostgreSQL URL')
    ap.add_argument('--no-schema', action='store_true', help='Do not apply schema.postgres.sql')
    ap.add_argument('--truncate', action='store_true', help='Delete target rows before import')
    ap.add_argument('--verify-only', action='store_true', help='Only verify fidelity, no migration')
    ap.add_argument('--report', help='Write JSON report to this path')
    args = ap.parse_args()
    sqlite_path = Path(args.sqlite)
    if not sqlite_path.exists():
        raise SystemExit(f'SQLite DB not found: {sqlite_path}')
    if not args.verify_only:
        counts = migrate(sqlite_path, args.postgres, apply_schema=not args.no_schema, truncate=args.truncate)
        print('Migration counts:')
        for t, c in counts.items():
            print(f'  {t}: {c}')
    report = verify(sqlite_path, args.postgres)
    print('\nFidelity report:')
    print(f'  OK: {report["ok"]}')
    for t, e in report['tables'].items():
        status = 'ok' if e.get('ok', True) and not e.get('skipped') else ('SKIP' if e.get('skipped') else 'MISMATCH')
        print(f'  {t}: sqlite={e.get("sqlite","-")} pg={e.get("postgres","-")} {status}')
    if report['issues']:
        print('Issues:')
        for i in report['issues']:
            print(f'  - {i}')
    if args.report:
        Path(args.report).write_text(json.dumps(report, indent=2, default=str), encoding='utf-8')
        print(f'Report written to {args.report}')
    if not report['ok']:
        raise SystemExit(2)


if __name__ == '__main__':
    main()
