import pytest
from src.common.http_transport import AutoTransport, BrowserTransport, FixtureTransport, build_transport
from src.inventory.collector import FetchError, FetchResponse

class Failing:
    name="http"
    def __init__(self,message): self.message=message
    def fetch(self,url): raise FetchError(self.message)

class Response:
    def __init__(self,status=200,text="ok"): self.name="proxy_http"; self.status=status; self.text=text
    def fetch(self,url): return FetchResponse(url,self.status,self.text,0,{})

def test_fixture_transport_returns_shared_response_with_metadata():
    result=FixtureTransport({"https://x":{"status_code":200,"html":"ok"}}).fetch("https://x")
    assert result.actual_transport == "fixture" and result.connection_result == "fixture"

def test_auto_falls_back_only_for_connection_layer_errors():
    result=AutoTransport([Failing("WinError 10013 connection denied"),Response()]).fetch("https://x")
    assert result.actual_transport == "proxy_http" and result.fallback_used is True

def test_auto_does_not_fallback_after_blocked_response():
    result=AutoTransport([Response(403,"blocked"),BrowserTransport(lambda url:(200,"browser",{}))]).fetch("https://x")
    assert result.actual_transport == "proxy_http" and result.connection_result == "blocked"

def test_auto_refuses_non_connection_failure():
    with pytest.raises(FetchError): AutoTransport([Failing("invalid request"),Response()]).fetch("https://x")

def test_factory_uses_auto_order_without_persisting_proxy_value():
    transport=build_transport({"transport":"auto","proxy_url_env":"WEBSITE_CHECKER_PROXY","browser_fallback":False},user_agent="x",timeout=1,max_retries=0,interval=0,max_requests=1)
    assert [x.name for x in transport.transports] == ["proxy_http","http"]
