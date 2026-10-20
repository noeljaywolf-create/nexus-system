"""User launcher: start Nexus and open the browser after the server is listening."""
import argparse
import json
import threading
from urllib.error import URLError
from urllib.request import urlopen
import webbrowser
import os
import server

def main():
    parser=argparse.ArgumentParser(description='Start your Nexus business system')
    parser.add_argument('--port',type=int,default=4180)
    parser.add_argument('--no-browser',action='store_true')
    args=parser.parse_args();url=f'http://127.0.0.1:{args.port}'
    try:
        with urlopen(url+'/api/health',timeout=2) as response:
            result=json.load(response)
            if result.get('status')=='ok' and result.get('database')=='sqlite':
                print('Nexus is already running at '+url)
                if not args.no_browser:webbrowser.open(url)
                return
    except (URLError,TimeoutError,OSError,ValueError):pass
    server.initialize()
    host='0.0.0.0' if os.environ.get('PORT') else '127.0.0.1'
    try:http=server.ThreadingHTTPServer((host,args.port),server.Handler)
    except OSError:
        raise SystemExit(f'Port {args.port} is in use. Close the other application or use --port with another number.')
    print('\nNEXUS BUSINESS SYSTEM\n'+url+'\n')
    print('Create your organization in the browser. There are no default accounts.')
    print('Keep this window open. Press Ctrl+C to stop the server.')
    if not args.no_browser:
        threading.Thread(target=lambda:webbrowser.open(url),daemon=True).start()
    try:http.serve_forever()
    except KeyboardInterrupt:print('\nNexus stopped. Your records remain saved.')
    finally:http.server_close()

if __name__=='__main__':main()
