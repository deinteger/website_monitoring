"""TimelyGPT-backed, evidence-only assistant for local inspection results."""
from __future__ import annotations
import json, os, re, time
from pathlib import Path
from typing import Any
import requests

TIMELY_BASE="https://hello.timelygpt.co.kr/api/v2/chat/bridge"
ALLOWED_ENDPOINTS={f"{TIMELY_BASE}/openai",f"{TIMELY_BASE}/info/models"}
SAFE_ERRORS={401:"인증에 실패했습니다.",402:"사용 가능한 크레딧이 없습니다.",429:"요청이 제한되었습니다."}

class AIConfigError(ValueError): pass

class TimelyGPTClient:
    def __init__(self, *, api_key=None, base_url=TIMELY_BASE, model="", timeout=60, session=None):
        self.api_key=api_key or os.environ.get("TIMELYGPT_API_KEY",""); self.base_url=base_url.rstrip("/"); self.model=model; self.timeout=timeout; self.session=session or requests.Session()
        if self.base_url not in {TIMELY_BASE}: raise AIConfigError("허용되지 않은 AI API 주소입니다.")
    def _headers(self): return {"Authorization":f"Bearer {self.api_key}","Content-Type":"application/json"}
    def models(self):
        if not self.api_key: raise AIConfigError("TIMELYGPT_API_KEY가 설정되지 않았습니다.")
        try:
            r=self.session.get(f"{self.base_url}/info/models",headers=self._headers(),timeout=self.timeout); r.raise_for_status(); data=r.json()
            values=data.get("data",data.get("models",data)) if isinstance(data,(dict,list)) else []
            return [x.get("id",x.get("name")) for x in values if isinstance(x,dict) and x.get("id",x.get("name")) and str(x.get("type","text")).lower() in {"text","chat",""}] if isinstance(values,list) else []
        except requests.Timeout as exc: raise RuntimeError("모델 목록 조회 시간이 초과되었습니다.") from exc
        except requests.RequestException as exc: raise RuntimeError(SAFE_ERRORS.get(getattr(exc.response,"status_code",0),"모델 목록을 조회할 수 없습니다.")) from exc
    def chat(self, messages, *, model=None):
        if not self.api_key: raise AIConfigError("TIMELYGPT_API_KEY가 설정되지 않았습니다.")
        try:
            r=self.session.post(f"{self.base_url}/openai",headers=self._headers(),json={"model":model or self.model,"messages":messages},timeout=self.timeout); r.raise_for_status(); data=r.json()
            answer=((data.get("choices") or [{}])[0].get("message") or {}).get("content")
            if not isinstance(answer,str): raise RuntimeError("AI 응답 형식을 해석할 수 없습니다.")
            return answer
        except requests.Timeout as exc: raise RuntimeError("AI 응답 시간이 초과되었습니다.") from exc
        except requests.RequestException as exc: raise RuntimeError(SAFE_ERRORS.get(getattr(exc.response,"status_code",0),"TimelyGPT 서버 오류가 발생했습니다.")) from exc

class ResultContext:
    def __init__(self,state_dir="state",*,max_items=30,max_chars=30000): self.root=Path(state_dir); self.max_items=max_items; self.max_chars=max_chars
    def _json(self,name):
        p=self.root/name
        try: return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
        except (OSError,ValueError): return {}
    def select(self, question, filters=None):
        filters=filters or {}; issues=self._json("issues.json"); inventory=self._json("inventory.json")
        pages=issues.get("page_results",[]) if isinstance(issues,dict) else []
        text=question.lower(); terms=[str(filters.get(k,"")) for k in ("target_id","url","menu_path","verdict","issue_type","lifecycle") if filters.get(k)]
        pages=[p for p in pages if all(t.lower() in json.dumps(p,ensure_ascii=False).lower() for t in terms)]
        if not terms and any(x in text for x in ("오류","문제","신규","재발")):
            pages=[p for p in pages if any(x in json.dumps(p,ensure_ascii=False) for x in ("오류","신규","재발"))]
        pages=pages[:self.max_items]; payload={"pages":pages,"run_metadata":issues.get("run_metadata",{}) if isinstance(issues,dict) else {},"inventory_summary":list(inventory) if isinstance(inventory,dict) else []}
        raw=json.dumps(payload,ensure_ascii=False); return raw[:self.max_chars],pages

class AIAssistant:
    def __init__(self,state_dir="state",config=None,client=None):
        cfg=config or {}; self.enabled=bool(cfg.get("enabled",False)); self.model=cfg.get("model",""); self.max_history=int(cfg.get("max_history_messages",10)); self.context=ResultContext(state_dir,max_items=int(cfg.get("max_context_items",30)),max_chars=int(cfg.get("max_context_chars",30000))); self.client=client or TimelyGPTClient(model=self.model,timeout=int(cfg.get("request_timeout_seconds",60))); self.last_result="disabled"; self._models=[]; self._models_at=0
    def status(self): return {"enabled":self.enabled,"api_key_configured":bool(os.environ.get("TIMELYGPT_API_KEY")),"model":self.model,"last_result":self.last_result}
    def models(self):
        if time.time()-self._models_at<300: return self._models
        try: self._models=self.client.models(); self._models_at=time.time(); self.last_result="ok"; return self._models
        except Exception as exc: self.last_result=str(exc); return self._models
    def chat(self,question,history=None,filters=None):
        if not self.enabled: return {"answer":"AI 점검 도우미가 비활성화되어 있습니다.","evidence":[],"available":False}
        if not isinstance(question,str) or not 1<=len(question)<=2000: raise ValueError("질문은 1~2000자로 입력해 주세요.")
        context,pages=self.context.select(question,filters); system="점검결과 근거만 사용하세요. 근거가 없으면 확인할 수 없음이라고 답하세요. 오류와 점검 불가를 구분하고, 부분실패에서 해결을 단정하지 마세요. 답변에 점검일·사이트·URL·issue key를 포함하세요."
        messages=[{"role":"system","content":system},{"role":"user","content":f"점검결과 컨텍스트:\n{context}\n\n질문: {question}"}]
        for item in (history or [])[-self.max_history:]:
            if isinstance(item,dict) and item.get("role") in {"user","assistant"} and isinstance(item.get("content"),str): messages.insert(-1,{"role":item["role"],"content":item["content"][:4000]})
        answer=self.client.chat(messages,model=self.model); self.last_result="ok"; return {"answer":answer,"evidence":[{"url":p.get("url"),"issue_key":p.get("issue_key"),"checked_at":p.get("checked_at")} for p in pages],"available":True}
