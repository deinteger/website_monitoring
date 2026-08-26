"""Replaceable fetch transports sharing InventoryCollector's FetchResponse model."""
from __future__ import annotations
import os, time
from typing import Callable
import requests
from src.inventory.collector import FetchError, FetchResponse, RequestLimitError

def connection_error(exc):
    text=str(exc).lower()
    return any(x in text for x in ("winerror 10013","connection","dns","ssl","proxy","network access denied"))

def blocked_status(response):
    return response.status_code in (401,403,429) or any(x in response.text[:4000].lower() for x in ("captcha","waf","web application firewall"))

def traced(response, *, requested, actual, proxy_used=False, fallback=False, reason="", result="success"):
    return FetchResponse(response.url,response.status_code,response.text,response.elapsed_seconds,dict(response.headers),requested,actual,proxy_used,fallback,reason,result)

class HttpTransport:
    name="http"
    def __init__(self, *, user_agent="NIHHS-QA-Bot/1.0", timeout=15, max_retries=1, interval=1, max_requests=10, trust_env=False, session=None):
        self.session=session or requests.Session(); self.session.trust_env=trust_env; self.session.headers.update({"User-Agent":user_agent,"Accept":"text/html,application/xml,text/xml"})
        self.timeout,self.max_retries,self.interval,self.max_requests=timeout,max_retries,interval,max_requests; self.request_count=0; self._last_request_at=None
    def fetch(self,url):
        if self.request_count >= self.max_requests: raise RequestLimitError(f"request limit {self.max_requests}")
        if self._last_request_at is not None: time.sleep(max(0,self.interval-(time.monotonic()-self._last_request_at)))
        self._last_request_at=time.monotonic(); self.request_count+=1; last=None
        for attempt in range(self.max_retries+1):
            try:
                started=time.monotonic(); r=self.session.get(url,timeout=self.timeout,allow_redirects=False)
                return FetchResponse(url,r.status_code,r.text,time.monotonic()-started,dict(r.headers),self.name,self.name,False,False,"","success")
            except requests.RequestException as exc:
                last=exc
                if attempt == self.max_retries: raise FetchError(f"request failed: {exc}") from exc

class ProxyHttpTransport(HttpTransport):
    name="proxy_http"
    def __init__(self, *, proxy_url=None, proxy_env="WEBSITE_CHECKER_PROXY", **kwargs):
        super().__init__(trust_env=True,**kwargs); value=proxy_url or os.environ.get(proxy_env)
        if value: self.session.proxies.update({"http":value,"https":value}); self.proxy_used=True
        else: self.proxy_used=False
    def fetch(self,url):
        response=super().fetch(url)
        return traced(response,requested=self.name,actual=self.name,proxy_used=self.proxy_used,result=response.connection_result)

class FixtureTransport:
    name="fixture"
    def __init__(self,responses): self.responses=responses; self.request_count=0
    def fetch(self,url):
        self.request_count+=1; v=self.responses.get(url,self.responses.get(url.rstrip("/"),{}))
        return FetchResponse(url,int(v.get("status_code",200)),v.get("html",v.get("text","")),float(v.get("elapsed_seconds",0)),v.get("headers",{}),self.name,self.name,False,False,"","fixture")

class BrowserTransport:
    name="browser"
    def __init__(self, loader: Callable[[str],tuple[int,str,dict]]|None=None): self.loader=loader; self.request_count=0
    def fetch(self,url):
        self.request_count+=1
        if self.loader: status,text,headers=self.loader(url); return FetchResponse(url,status,text,0,headers,self.name,self.name,False,False,"","success")
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                b=p.chromium.launch(headless=True); page=b.new_page(); response=page.goto(url,wait_until="domcontentloaded",timeout=15000); text=page.content(); b.close()
            return FetchResponse(url,response.status if response else 0,text,0,{},self.name,self.name,False,False,"","success")
        except Exception as exc: raise FetchError(f"browser failed: {exc}") from exc

class AutoTransport:
    name="auto"
    def __init__(self, transports): self.transports=list(transports); self.request_count=0
    def fetch(self,url):
        errors=[]
        for index,transport in enumerate(self.transports):
            try:
                response=transport.fetch(url); self.request_count+=1
                if blocked_status(response): return traced(response,requested=self.name,actual=transport.name,proxy_used=getattr(transport,"proxy_used",False),fallback=index>0,result="blocked")
                return traced(response,requested=self.name,actual=transport.name,proxy_used=getattr(transport,"proxy_used",False),fallback=index>0,reason="; ".join(errors),result="success")
            except FetchError as exc:
                if not connection_error(exc): raise
                errors.append(str(exc))
        raise FetchError("all transports failed: " + "; ".join(errors))

def build_transport(network, *, user_agent, timeout, max_retries, interval, max_requests):
    """Build configured transports without persisting proxy credentials anywhere."""
    network=network or {}; kind=network.get("transport","auto")
    options=dict(user_agent=user_agent,timeout=timeout,max_retries=max_retries,interval=interval,max_requests=max_requests)
    if kind == "http": return HttpTransport(**options)
    if kind == "proxy_http": return ProxyHttpTransport(proxy_env=network.get("proxy_url_env","WEBSITE_CHECKER_PROXY"),**options)
    if kind == "browser": return BrowserTransport()
    if kind != "auto": raise ValueError("network.transport must be auto, http, proxy_http, or browser")
    items=[ProxyHttpTransport(proxy_env=network.get("proxy_url_env","WEBSITE_CHECKER_PROXY"),**options),HttpTransport(**options)]
    if network.get("browser_fallback",True): items.append(BrowserTransport())
    return AutoTransport(items)
