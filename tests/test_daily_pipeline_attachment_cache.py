import json
from datetime import date
from src.daily_pipeline import DailyPipeline
from src.resources.cache import AttachmentCache
BASE="https://fixture.test"
def fixture():
    xml="<urlset xmlns='http://www.sitemaps.org/schemas/sitemap/0.9'><url><loc>%s/a</loc></url><url><loc>%s/b</loc></url></urlset>"%(BASE,BASE)
    html="<html><body><a href='/files/guide.pdf'>Guide</a></body></html>"
    return {"menu":{"main_selectors":["a"],"all_menu_selectors":["a"],"sitemap_path":"/sitemap.xml"},"responses":{BASE+"/":{"status_code":200,"html":"<body><a href='/a'>A</a><a href='/b'>B</a></body>"},BASE+"/sitemap.xml":{"status_code":200,"text":xml},BASE+"/a":{"status_code":200,"html":html},BASE+"/b":{"status_code":200,"html":html},BASE+"/files/guide.pdf":{"status_code":200,"headers":{"Content-Type":"application/pdf","Content-Length":"12","ETag":"\"pdf-v1\"","Last-Modified":"Tue, 25 Aug 2026 00:00:00 GMT"},"body":b"%PDF-1.7 demo"}}}
def test_first_run_pdf_head_range_signature_and_dedup(tmp_path):
    p=DailyPipeline(state_dir=tmp_path/"s",output_root=tmp_path/"o"); p.run_raw_fixture(fixture(),date="2026-08-25"); m=p.last_metrics; assert any(x[0]=="HEAD" and "guide.pdf" in x[1] for x in m["resource_calls"]); assert m["signature_checks"]==1 and m["download_bytes"]>0
def test_same_attachment_two_pages_one_signature(tmp_path):
    p=DailyPipeline(state_dir=tmp_path/"s",output_root=tmp_path/"o"); p.run_raw_fixture(fixture(),date="2026-08-25"); assert p.last_metrics["signature_checks"]==1
def test_second_run_reuses_cache_without_signature(tmp_path):
    p=DailyPipeline(state_dir=tmp_path/"s",output_root=tmp_path/"o"); p.run_raw_fixture(fixture(),date="2026-08-25"); p.run_raw_fixture(fixture(),date="2026-08-26"); assert p.last_metrics["signature_checks"]==0 and p.last_metrics["attachment_reuses"]>=1
def test_third_run_reuses_cache(tmp_path):
    p=DailyPipeline(state_dir=tmp_path/"s",output_root=tmp_path/"o");
    for d in ("2026-08-25","2026-08-26","2026-08-27"): p.run_raw_fixture(fixture(),date=d)
    assert p.last_metrics["signature_checks"]==0 and p.last_metrics["attachment_reuses"]>=1
def test_cache_state_relations_and_dates(tmp_path):
    p=DailyPipeline(state_dir=tmp_path/"s",output_root=tmp_path/"o"); p.run_raw_fixture(fixture(),date="2026-08-25"); data=json.loads((tmp_path/"s"/"attachment_cache.json").read_text(encoding="utf-8")); e=next(iter(data["entries"].values())); assert set(e["original_pages"])=={BASE+"/a",BASE+"/b"} and e["next_recheck_date"]
def test_expiry_rechecks(tmp_path):
    p=DailyPipeline(state_dir=tmp_path/"s",output_root=tmp_path/"o"); p.run_raw_fixture(fixture(),date="2026-08-25"); p.run_raw_fixture(fixture(),date="2026-09-25"); assert p.last_metrics["signature_checks"]==1
def test_cache_json_is_created_atomically_and_reported(tmp_path):
    p=DailyPipeline(state_dir=tmp_path/"s",output_root=tmp_path/"o"); r=p.run_raw_fixture(fixture(),date="2026-08-25"); assert (tmp_path/"s"/"attachment_cache.json").exists() and r["report_path"]

def seeded():
    c=AttachmentCache(policy_version="p",recheck_days=30); c.update("https://e/f.pdf",content_hash="h",original_url="https://e/f.pdf",page_url="https://e/p",filename="f.pdf",link_text="Guide",result={"verdict":"정상","etag":"v1","last_modified":"d1","content_length":12},checked_date=date(2026,8,25),policy_version="p"); return c
def assert_recheck(**kw):
    ok, reason=seeded().reusable("https://e/f.pdf",content_hash=kw.get("content_hash","h"),original_url=kw.get("original_url","https://e/f.pdf"),filename=kw.get("filename","f.pdf"),link_text=kw.get("link_text","Guide"),today=kw.get("today",date(2026,8,26)),policy_version=kw.get("policy_version","p"),force=kw.get("force",False)); assert ok is False and reason
def test_force_resource_check_rechecks(): assert_recheck(force=True)
def test_url_change_rechecks(): assert_recheck(original_url="https://e/new.pdf")
def test_filename_or_link_change_rechecks(): assert_recheck(filename="new.pdf"); assert_recheck(link_text="New guide")
def test_content_hash_change_rechecks(): assert_recheck(content_hash="changed")
def test_policy_version_change_rechecks(): assert_recheck(policy_version="p2")
def test_expired_cache_rechecks(): assert_recheck(today=date(2026,9,25))
def test_previous_non_normal_result_rechecks():
    c=seeded(); c.entries["https://e/f.pdf"]["verdict"]="오류"; ok,reason=c.reusable("https://e/f.pdf",content_hash="h",original_url="https://e/f.pdf",filename="f.pdf",link_text="Guide",today=date(2026,8,26),policy_version="p"); assert not ok and reason
def test_metadata_change_is_recorded_for_recheck():
    c=seeded(); c.entries["https://e/f.pdf"].update({"etag":"v2","last_modified":"d2","content_length":13}); assert c.get("https://e/f.pdf")["etag"]=="v2" and c.get("https://e/f.pdf")["content_length"]==13
def test_cache_recheck_result_and_reason_are_serializable():
    c=seeded(); ok,reason=c.reusable("https://e/f.pdf",content_hash="changed",original_url="https://e/f.pdf",filename="f.pdf",link_text="Guide",today=date(2026,8,26),policy_version="p"); payload=c.to_dict(); assert not ok and reason and payload["entries"]["https://e/f.pdf"]["verdict"]=="정상"
