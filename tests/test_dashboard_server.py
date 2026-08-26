import json, threading
import socket
from urllib.request import urlopen
from http.server import ThreadingHTTPServer
from src.dashboard import make_handler
from src.dashboard import main

def test_localhost_server_serves_health_and_assets(tmp_path):
    server=ThreadingHTTPServer(("127.0.0.1",0),make_handler(tmp_path/"state",tmp_path/"output")); thread=threading.Thread(target=server.serve_forever); thread.start()
    try:
        base=f"http://127.0.0.1:{server.server_port}"
        assert json.loads(urlopen(base+"/api/health",timeout=2).read())["bind"] == "127.0.0.1"
        assert b"NIHHS" in urlopen(base+"/",timeout=2).read()
    finally:
        server.shutdown(); thread.join(); server.server_close()

def test_port_collision_returns_clear_failure(tmp_path, capsys):
    held=socket.socket(); held.bind(("127.0.0.1",0)); held.listen()
    try:
        assert main(["--port",str(held.getsockname()[1]),"--state-dir",str(tmp_path/"state")]) == 1
        assert "already in use" in capsys.readouterr().out
    finally: held.close()
