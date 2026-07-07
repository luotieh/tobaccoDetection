"""账户级证据报告：把账户 + 其二次确认批次的多模态识别结果渲染为自包含 HTML。"""
import base64
import html
import json
from pathlib import Path

_IMG_MIME = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
             ".webp": "image/webp", ".gif": "image/gif"}
_MAX_EMBED_BYTES = 3 * 1024 * 1024  # 单个证据文件超过则跳过内嵌，保持报告体积可控


def _img_data_uri(path):
    p = Path(path)
    try:
        if not p.is_file() or p.stat().st_size > _MAX_EMBED_BYTES:
            return ""
        mime = _IMG_MIME.get(p.suffix.lower())
        if not mime:
            return ""
        return f"data:{mime};base64," + base64.b64encode(p.read_bytes()).decode("ascii")
    except OSError:
        return ""


def _esc(value):
    return html.escape(str(value if value is not None else ""))


def _parse_list(value):
    if isinstance(value, list):
        return value
    if isinstance(value, str) and value:
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except json.JSONDecodeError:
            return []
    return []


def _keywords(text_result):
    if not isinstance(text_result, dict):
        return []
    out = []
    for hit in text_result.get("hit_keywords", []) or []:
        if isinstance(hit, dict):
            out.append(hit.get("word", ""))
        else:
            out.append(str(hit))
    return [w for w in out if w]


def _post_card(post):
    content = post.get("content", {}) or {}
    parts = [f'<div class="card"><h3>{_esc(content.get("title") or content.get("id"))}'
             f' <span class="score">{_esc(content.get("risk_level"))} · {_esc(content.get("risk_score"))}</span></h3>']
    url = content.get("content_url")
    if url:
        parts.append(f'<p class="meta">类型：{_esc(content.get("content_type"))}　链接：{_esc(url)}</p>')
    kws = _keywords(post.get("text"))
    if kws:
        parts.append(f'<p><b>文本命中：</b>{_esc("、".join(kws))}</p>')
    image = post.get("image") or {}
    objs = image.get("detected_objects") or []
    if objs:
        parts.append(f'<p><b>检测对象：</b>{_esc("、".join(map(str, objs)))}</p>')
    ocr = image.get("ocr_text") or []
    if ocr:
        parts.append(f'<p><b>OCR：</b>{_esc("、".join(map(str, ocr)))}</p>')
    audio = post.get("audio") or {}
    if audio.get("transcript"):
        parts.append(f'<p><b>语音转写：</b>{_esc(audio.get("transcript"))}</p>')
    imgs = [uri for uri in (_img_data_uri(p) for p in post.get("evidence_images", []) or []) if uri]
    if imgs:
        parts.append('<div class="frames">' +
                     "".join(f'<img alt="证据帧" src="{uri}">' for uri in imgs) + "</div>")
    parts.append("</div>")
    return "".join(parts)


def build_account_report_html(account, posts):
    account = account or {}
    violations = _parse_list(account.get("violation_type"))
    cards = "".join(_post_card(p) for p in (posts or []))
    hit = _esc(account.get("high_post_count"))
    total = _esc(account.get("post_count"))
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>账户证据报告 {_esc(account.get("account_key"))}</title>
<style>
 body{{font-family:-apple-system,"Microsoft YaHei",sans-serif;margin:0;background:#f5f6fa;color:#1f2430}}
 .wrap{{max-width:920px;margin:0 auto;padding:24px}}
 header{{background:#0f2a52;color:#fff;padding:20px;border-radius:8px}}
 header h1{{margin:0 0 6px;font-size:20px}}
 .verdict{{background:#fff;border-left:4px solid #c0392b;padding:16px;margin:16px 0;border-radius:6px}}
 .card{{background:#fff;border:1px solid #e2e6ee;border-radius:6px;padding:14px;margin:12px 0}}
 .card h3{{margin:0 0 8px;font-size:16px}}
 .score{{color:#c0392b;font-size:13px;font-weight:normal}}
 .meta{{color:#6b7280;font-size:13px}}
 .frames img{{max-width:220px;max-height:220px;margin:6px 6px 0 0;border:1px solid #ddd;border-radius:4px}}
 .tag{{display:inline-block;background:#eef;border-radius:4px;padding:2px 8px;margin:2px;font-size:12px}}
</style></head><body><div class="wrap">
<header>
 <h1>烟草违法售卖账户证据报告</h1>
 <div>平台：{_esc(account.get("platform"))}　账号：{_esc(account.get("nickname"))}（{_esc(account.get("user_id"))}）</div>
 <div>{_esc(account.get("description"))}</div>
</header>
<div class="verdict">
 <div><b>账户级判定：</b>近 {total} 条中 <b>{hit}/{total}</b> 条高风险，最高单帖综合分 <b>{_esc(account.get("max_post_score"))}</b></div>
 <div><b>违规类型：</b>{"".join(f'<span class="tag">{_esc(v)}</span>' for v in violations) or "—"}</div>
 <div><b>审核：</b>{_esc(account.get("reviewer"))}　{_esc(account.get("review_time"))}</div>
</div>
<h2>逐帖证据</h2>
{cards or "<p>无帖子证据</p>"}
</div></body></html>"""
