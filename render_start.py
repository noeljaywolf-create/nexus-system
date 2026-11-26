"""Start a disposable Render test service; local launch defaults stay unchanged."""
import os
import sys


def main():
    hostname = os.environ.get('RENDER_EXTERNAL_HOSTNAME', '').strip().lower()
    if not hostname or any(c not in 'abcdefghijklmnopqrstuvwxyz0123456789.-' for c in hostname):
        raise SystemExit('RENDER_EXTERNAL_HOSTNAME must be the Render service hostname.')
    allowed = os.environ.get('NEXUS_ALLOWED_HOSTS', '')
    os.environ['NEXUS_ALLOWED_HOSTS'] = ','.join(filter(None, (allowed, hostname)))
    os.environ.setdefault('NEXUS_SECURE_COOKIE', '1')
    os.environ.setdefault('NEXUS_DISABLE_DEMO', '1')
    port = int(os.environ.get('PORT', '10000'))
    if not 1 <= port <= 65535:
        raise SystemExit('PORT must be between 1 and 65535.')
    import server
    sys.argv = ['server.py', '--host', '0.0.0.0', '--port', str(port)]
    server.main()


if __name__ == '__main__':
    main()
