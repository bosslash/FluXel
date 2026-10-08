import html
import re
from pathlib import Path

from PySide6.QtCore import QMimeData, Qt, QUrl
from PySide6.QtGui import (
    QDesktopServices,
    QKeyEvent,
    QMouseEvent,
    QPalette,
    QTextBlock,
    QTextCharFormat,
    QTextCursor,
)
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import QTextEdit, QWidget

# HTML タイトル抽出に使う正規表現と通信設定。
_TITLE_IN_HTML_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_USER_AGENT = (
    b"Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    b"AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def _redirect_policy_prefer_same_or_safer() -> QNetworkRequest.RedirectPolicy:
    """Qt 6.9 以降は NoLessSecure が NoLessSafe に改名されたため両対応する。"""
    e = QNetworkRequest.RedirectPolicy
    v = getattr(e, "NoLessSecureRedirectPolicy", None) or getattr(
        e, "NoLessSafeRedirectPolicy", None
    )
    if v is not None:
        return v
    return e.ManualRedirectPolicy


def _extract_page_title(body: bytes, max_scan: int = 524288) -> str | None:
    """HTML 文字列から <title> を取り出し、表示用に整形して返す。"""
    try:
        text = body[:max_scan].decode("utf-8", errors="replace")
    except Exception:
        return None
    m = _TITLE_IN_HTML_RE.search(text)
    if not m:
        return None
    inner = m.group(1)
    inner = _HTML_TAG_RE.sub("", inner)
    inner = html.unescape(inner)
    inner = re.sub(r"\s+", " ", inner).strip()
    if not inner:
        return None
    return inner[:240]


class LinkFriendlyTextEdit(QTextEdit):
    """リッチ編集、URL 貼り付けのリンク化、リンクの左クリックでブラウザを開く。改行後は挿入書式を既定に戻す。"""

    # URL とみなす文字列パターン。
    _URL_RE = re.compile(r"https?://[^\s<>\u201c\u201d\"]+", re.IGNORECASE)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        # URL 先ページのタイトル取得に使う非同期 HTTP クライアント。
        self._nam = QNetworkAccessManager(self)
        # Qt / PySide の版によっては QNetworkRequest に setRedirectPolicy が無く、
        # QNetworkAccessManager 側でのみ指定できる。
        _rp = _redirect_policy_prefer_same_or_safer()
        if hasattr(self._nam, "setRedirectPolicy"):
            self._nam.setRedirectPolicy(_rp)

    def _plain_text_to_linked_html(self, text: str) -> str:
        """プレーンテキスト中の URL を <a> に変換して HTML 化する。"""
        parts: list[str] = []
        pos = 0
        for m in self._URL_RE.finditer(text):
            chunk = text[pos : m.start()]
            parts.append(html.escape(chunk).replace("\n", "<br>"))
            url = m.group(0)
            parts.append(
                f'<a href="{html.escape(url, quote=True)}">{html.escape(url)}</a>'
            )
            pos = m.end()
        parts.append(html.escape(text[pos:]).replace("\n", "<br>"))
        return "".join(parts)

    def insertFromMimeData(self, source: QMimeData) -> None:
        """貼り付け時に URL を検知してリンク化し、タイトル取得を予約する。"""
        if source is None:
            return
        if source.hasText():
            text = source.text()
            if self._URL_RE.search(text):
                html_clip = source.html() if source.hasHtml() else ""
                if "<a" not in html_clip.lower():
                    self.insertHtml(self._plain_text_to_linked_html(text))
                    for u in dict.fromkeys(self._URL_RE.findall(text)):
                        self._enqueue_page_title(u)
                    return
        QTextEdit.insertFromMimeData(self, source)

    def _enqueue_page_title(self, url: str) -> None:
        """URL のページタイトル取得リクエストを非同期で発行する。"""
        qurl = QUrl(url)
        if qurl.scheme() not in ("http", "https"):
            return
        req = QNetworkRequest(qurl)
        req.setRawHeader(b"User-Agent", _USER_AGENT)
        req.setTransferTimeout(12_000)
        if hasattr(req, "setRedirectPolicy"):
            req.setRedirectPolicy(_redirect_policy_prefer_same_or_safer())
        rep = self._nam.get(req)
        rep.finished.connect(lambda r=rep, u=url: self._on_title_reply(r, u))

    def _on_title_reply(self, reply: QNetworkReply, url: str) -> None:
        """HTTP 応答からタイトルを取り出し、リンク表示テキストを更新する。"""
        reply.deleteLater()
        if reply.error() != QNetworkReply.NetworkError.NoError:
            return
        title = _extract_page_title(bytes(reply.readAll()))
        if not title:
            return
        self._replace_anchor_label(url, title)

    def _replace_anchor_label(self, href: str, label: str) -> None:
        """href が一致するリンクの表示文字列を URL -> タイトルに置換する。"""
        doc = self.document()
        hits: list[tuple[int, int]] = []
        block = doc.begin()
        while block.isValid():
            it = block.begin()
            while not it.atEnd():
                frag = it.fragment()
                fmt = frag.charFormat()
                if (
                    fmt.isAnchor()
                    and fmt.anchorHref() == href
                    and frag.text() == href
                ):
                    hits.append((frag.position(), frag.length()))
                it += 1
            block = block.next()
        for pos, length in sorted(hits, reverse=True):
            cur = QTextCursor(doc)
            cur.setPosition(pos)
            cur.setPosition(pos + length, QTextCursor.MoveMode.KeepAnchor)
            link_fmt = QTextCharFormat()
            link_fmt.setAnchor(True)
            link_fmt.setAnchorHref(href)
            link_fmt.setFontUnderline(True)
            cur.insertText(label, link_fmt)

    def _serialize_block_for_storage(self, block: QTextBlock) -> str:
        """1 ブロック分を、リンクは href から \\url: / \\file| に戻したプレーン相当文字列にする。"""
        parts: list[str] = []
        it = block.begin()
        while not it.atEnd():
            frag = it.fragment()
            fmt = frag.charFormat()
            text = frag.text()
            if fmt.isAnchor():
                href = (fmt.anchorHref() or "").strip()
                if href:
                    q = QUrl(href)
                    sch = (q.scheme() or "").lower()
                    if sch in ("http", "https"):
                        parts.append("\\url:" + href)
                    elif sch == "file":
                        local = q.toLocalFile()
                        if local:
                            p = str(Path(local))
                            parts.append("\\file|" + p.replace("|", "\\|") + "|")
                        else:
                            parts.append(text)
                    else:
                        parts.append(text)
                else:
                    parts.append(text)
            else:
                parts.append(text)
            it += 1
        joined = "".join(parts)
        return joined if parts else block.text()

    def plain_text_for_storage(self) -> str:
        """
        DB 保存用のプレーン文字列。
        toPlainText() ではアンカーの表示がタイトルに差し替わった後に URL が失われるため、
        ドキュメントを走査して http(s) / file の href を \\url: / \\file| に復元する。
        """
        doc = self.document()
        lines: list[str] = []
        block = doc.begin()
        while block.isValid():
            lines.append(self._serialize_block_for_storage(block))
            block = block.next()
        return "\n".join(lines)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        """改行後にリンク書式が次行へ引き継がれないよう挿入書式をリセットする。"""
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            QTextEdit.keyPressEvent(self, event)
            plain = QTextCharFormat()
            plain.setAnchor(False)
            plain.setFontUnderline(False)
            plain.setForeground(self.palette().brush(QPalette.ColorRole.Text))
            self.setCurrentCharFormat(plain)
            return
        super().keyPressEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """http(s) のアンカーを左クリックで外部ブラウザで開く（Ctrl 不要）。"""
        if event.button() == Qt.MouseButton.LeftButton:
            anchor = self.anchorAt(event.position().toPoint())
            if anchor:
                qurl = QUrl(anchor)
                if qurl.scheme() in ("http", "https", "file"):
                    QDesktopServices.openUrl(qurl)
                    return
        super().mousePressEvent(event)
