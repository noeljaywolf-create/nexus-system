#!/usr/bin/env python3
"""Run Nexus test suite on SQLite and optionally PostgreSQL."""
from __future__ import annotations
import argparse, os, subprocess, sys

def run(cmd, env, label):
    print(f"\n=== {label} ===")
    p = subprocess.run(cmd, env=env)
    return p.returncode == 0

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--postgres-url", default=os.environ.get("NEXUS_TEST_DATABASE_URL", ""))
    ap.add_argument("--skip-postgres", action="store_true")
    args = ap.parse_args()
    root = os.path.dirname(os.path.abspath(__file__))
    py = sys.executable
    cmd = [py, "-m", "unittest", "discover", "-s", "tests", "-v"]
    ok = True
    env = os.environ.copy()
    for k in ("NEXUS_TEST_DATABASE_URL", "NEXUS_DATABASE_URL", "NEXUS_DB_URL"):
        env.pop(k, None)
    ok &= run(cmd, env, "SQLite")
    if not args.skip_postgres and args.postgres_url:
        env2 = os.environ.copy()
        env2["NEXUS_TEST_DATABASE_URL"] = args.postgres_url
        ok &= run(cmd, env2, "PostgreSQL")
    elif not args.skip_postgres:
        print("\n=== PostgreSQL skipped (no --postgres-url / NEXUS_TEST_DATABASE_URL) ===")
    print("\nRESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1

if __name__ == "__main__":
    raise SystemExit(main())
