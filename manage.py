"""Local database health checks and consistent online backups."""
import argparse
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
import server

def main():
    parser=argparse.ArgumentParser(description='Maintain the Nexus database')
    sub=parser.add_subparsers(dest='command',required=True)
    backup=sub.add_parser('backup');backup.add_argument('--output',type=Path)
    sub.add_parser('check')
    args=parser.parse_args()
    if not server.DB_PATH.is_file():raise SystemExit('No database exists yet. Start Nexus first.')
    with server.connect_db() as source:
        integrity=source.execute('PRAGMA integrity_check').fetchone()[0]
        foreign_keys=list(source.execute('PRAGMA foreign_key_check'))
        unbalanced=list(source.execute('SELECT e.id FROM ledger_entries e LEFT JOIN ledger_lines l ON l.entry_id=e.id GROUP BY e.id HAVING COALESCE(SUM(l.debit),0)!=COALESCE(SUM(l.credit),0) OR COUNT(l.id)!=2'))
        if integrity!='ok' or foreign_keys or unbalanced:
            raise SystemExit(f'Health check failed: integrity={integrity}, foreign-key violations={len(foreign_keys)}, unbalanced entries={len(unbalanced)}')
        print('Database integrity, foreign keys, and journal balances: OK')
        if args.command=='backup':
            output=args.output or server.ROOT/'backups'/('nexus-'+datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')+'.sqlite3')
            output=output.resolve()
            if output==server.DB_PATH.resolve():raise SystemExit('Backup destination must differ from the live database.')
            output.parent.mkdir(parents=True,exist_ok=True)
            # Exclusive creation prevents accidental replacement of any existing file.
            with output.open('xb'):pass
            try:
                with sqlite3.connect(output) as destination:
                    source.backup(destination)
                    check=destination.execute('PRAGMA integrity_check').fetchone()[0]
                    if check!='ok':raise RuntimeError('Backup verification failed')
            except Exception:
                print('Backup did not finish. Retain the original live database.')
                raise
            print('Verified backup saved to '+str(output))

if __name__=='__main__':main()
