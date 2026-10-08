"""タスク説明の DB 保存用マーカー（\\url: / \\file|...|）と HTML 表示への変換。"""

from __future__ import annotations

import html
import re
from pathlib import Path

# http(s) URL（貼り付け・本文と同一ルール）
_RAW_URL_RE = re.compile(r"https?://[^\s<>\u201c\u201d\"]+", re.IGNORECASE)

# Windows: UNC とドライブ絶対パス（: の後は \ または /）
_UNC_PATH_RE = re.compile(r"\\\\[^\s\r\n]+(?:\\[^\s\r\n]+)*")
# 末尾セグメントはスペースを含めない（「C:\temp\f.txt only」で only を巻き込まない）。
# ディレクトリ名のスペース（Program Files 等）は中間 (?:...)+[\\/] 側で許容する。
_DRIVE_PATH_RE = re.compile(
    r"(?<![\w/\\])([A-Za-z]:[\\/]"  # C:\ or C:/
    r"(?:[^\\/:*?\"<>|\r\n]+[\\/])*"  # 中間ディレクトリ（スペース可）
    r"[^\s\\/:*?\"<>|\r\n]*)"  # 末尾ファイル名（スペース不可）。ディレクトリのみは末尾空でよい
)


def strip_storage_markers(text: str) -> str:
    """既存の \\url: / \\file| を外し生の URL・パスに戻す（正規化の前処理）。"""
    s = text or ""
    s = re.sub(
        r"\\file\|((?:\\.|[^|])+)\|",
        lambda m: m.group(1).replace("\\|", "|"),
        s,
    )
    s = re.sub(r"\\url:(https?://[^\s<>\u201c\u201d\"]+)", r"\1", s, flags=re.IGNORECASE)
    return s


def _normalize_paths_in_segment(seg: str) -> str:
    """セグメント内のファイルパスを \\file|...| に（重なりは長い一致優先で後ろから置換）。"""
    s = seg
    spans: list[tuple[int, int, str]] = []

    for m in _UNC_PATH_RE.finditer(s):
        p = m.group(0).rstrip("\\")
        if len(p) >= 3:
            spans.append((m.start(), m.end(), p))

    for m in _DRIVE_PATH_RE.finditer(s):
        p = m.group(1).rstrip("\\/")
        if len(p) >= 4 and "://" not in p:
            spans.append((m.start(), m.end(), p))

    spans.sort(key=lambda x: (x[1] - x[0]), reverse=True)
    merged: list[tuple[int, int, str]] = []
    for start, end, p in spans:
        if any(not (end <= es or start >= ee) for es, ee, _ in merged):
            continue
        merged.append((start, end, p))
    merged.sort(key=lambda x: x[0], reverse=True)
    for start, end, p in merged:
        rep = "\\file|" + p.replace("|", "\\|") + "|"
        s = s[:start] + rep + s[end:]
    return s


def normalize_description_for_storage(text: str) -> str:
    """
    保存直前のプレーン文に対し、http(s) URL と Windows パスをマーカー付きで正規化する。
    二重マーカーにならないよう、一度マーカーを外してから再付与する。
    """
    s = strip_storage_markers(text or "")
    if not s:
        return s

    out: list[str] = []
    last = 0
    for m in _RAW_URL_RE.finditer(s):
        chunk = s[last : m.start()]
        out.append(_normalize_paths_in_segment(chunk))
        raw_u = m.group(0)
        out.append("\\url:" + raw_u)
        last = m.end()
    out.append(_normalize_paths_in_segment(s[last:]))
    return "".join(out)


def _file_href(local_path: str) -> str:
    """ローカルパスを file: URI に（存在しなくても組み立て）。"""
    p = local_path.strip().rstrip("\\/")
    if not p:
        return ""
    try:
        return Path(p).resolve().as_uri()
    except (OSError, ValueError):
        try:
            return Path(p).as_uri()
        except ValueError:
            return "file:///" + p.replace("\\", "/")


def storage_to_display_html(text: str) -> str:
    """
    DB の説明文（マーカー付き可）を QTextBrowser 用 HTML にする。
    マーカー以外はエスケープし、従来どおり生の http(s) もリンク化する。
    """
    s = text or ""
    if not s:
        return ""

    low = s.lower()
    if "<a " in low or "<html" in low:
        return s

    pieces: list[str] = []
    pos = 0
    while pos < len(s):
        iu = s.find("\\url:", pos)
        ifu = s.find("\\file|", pos)
        candidates = [(iu, "u") for iu in [iu] if iu >= 0] + [(ifu, "f") for ifu in [ifu] if ifu >= 0]
        if not candidates:
            tail = s[pos:]
            pieces.append(_plain_urls_to_html_fragment(tail))
            break
        nxt, kind = min(candidates)
        if nxt > pos:
            pieces.append(_plain_urls_to_html_fragment(s[pos:nxt]))
        if kind == "u":
            m = re.match(r"\\url:(https?://[^\s<>\u201c\u201d\"]+)", s[nxt:], re.IGNORECASE)
            if not m:
                pieces.append(html.escape(s[nxt : nxt + 5]))
                pos = nxt + 5
                continue
            url = m.group(1)
            pieces.append(
                f'<a href="{html.escape(url, quote=True)}">{html.escape(url)}</a>'
            )
            pos = nxt + m.end()
        else:
            m = re.match(r"\\file\|((?:\\.|[^|])+)\|", s[nxt:])
            if not m:
                pieces.append(html.escape(s[nxt : nxt + 6]))
                pos = nxt + 6
                continue
            raw_path = m.group(1).replace("\\|", "|")
            href = _file_href(raw_path)
            label = raw_path
            pieces.append(
                f'<a href="{html.escape(href, quote=True)}">{html.escape(label)}</a>'
            )
            pos = nxt + m.end()

    return "".join(pieces)


def http_urls_for_title_fetch(text: str) -> list[str]:
    """説明テキスト中の http(s) URL（マーカー外し後）をタイトル取得用に列挙する。"""
    return list(dict.fromkeys(_RAW_URL_RE.findall(strip_storage_markers(text or ""))))


def _plain_urls_to_html_fragment(fragment: str) -> str:
    """フラグメント内の生 http(s) のみ <a> に（改行は <br>）。"""
    parts: list[str] = []
    last = 0
    for m in _RAW_URL_RE.finditer(fragment):
        chunk = fragment[last : m.start()]
        parts.append(html.escape(chunk).replace("\n", "<br>"))
        url = m.group(0)
        parts.append(
            f'<a href="{html.escape(url, quote=True)}">{html.escape(url)}</a>'
        )
        last = m.end()
    parts.append(html.escape(fragment[last:]).replace("\n", "<br>"))
    return "".join(parts)


def description_has_displayable_links(text: str) -> bool:
    t = text or ""
    if "\\url:" in t or "\\file|" in t:
        return True
    if "<a " in t.lower():
        return True
    return bool(_RAW_URL_RE.search(t))


def preview_plain_one_line(text: str, max_len: int = 140) -> str:
    """カード一覧用の軽い1行プレビュー（HTML ウィジェットを使わない）。"""
    s = strip_storage_markers(text or "")
    if not s:
        return ""
    low = s.lower()
    if "<a " in low or "<html" in low:
        fragment = re.sub(r"<[^>]+>", " ", s)
    else:
        fragment = storage_to_display_html(s)
        fragment = re.sub(r"<[^>]+>", " ", fragment)
    fragment = re.sub(r"\s+", " ", fragment).strip()
    if len(fragment) <= max_len:
        return fragment
    return fragment[: max_len - 1] + "…"


def preview_plain_one_line_fast(text: str, max_len: int = 140) -> str:
    """
    カード一覧用のさらに軽いプレビュー。
    storage_to_display_html を呼ばない（大量カード生成時のボトルネック回避）。
    マーカーは strip_storage_markers で外したうえで、改行・連続空白を折りたたむ。
    """
    s = strip_storage_markers(text or "")
    if not s:
        return ""
    low = s.lower()
    if "<a " in low or "<html" in low:
        fragment = re.sub(r"<[^>]+>", " ", s)
    else:
        fragment = re.sub(r"\s+", " ", s).strip()
    if len(fragment) <= max_len:
        return fragment
    return fragment[: max_len - 1] + "…"
