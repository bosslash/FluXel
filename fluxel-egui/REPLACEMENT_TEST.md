# 置き換え判定

Rust/egui版は、画面のピクセル一致ではなく、データと操作の互換性を置き換え条件とする。

## 自動確認

- Python版と同じ`Tasks.db`、`QuickAccess.db`、`Planning.db`のテーブルと値を読み書きする。
- URLとファイルマーカーを含む説明の保存形式を維持する。
- 検索のタイトル優先順、Archive、ステータス、重要度フィルターを維持する。
- ShortCutは保存値をそのままコピーし、OpenFileは存在する対象を開けた場合だけ利用回数を更新する。
- Ganttの並べ替え、日付移動、プロジェク間移動で本文と期間を保持する。
- Python版と同じ正規JSONとSHA-256で同期イベントを作成し、2つの独立した保存先間で送受信できる。

`cargo test --all-targets --locked`、`cargo clippy --all-targets --locked -- -D warnings`、macOS / WindowsのGitHub Actionsビルドをすべて通過したコミットを置き換え可能と判定する。

## 手動スモーク確認

1. 既存の各DBをバックアップし、egui版で起動する。
2. 看板の空列を含む左右移動、カード選択、`Cmd/Ctrl+↑↓`の並べ替えを確認する。
3. 検索、ShortCutコピー、OpenFile、Ganttのドラッグとキー操作を確認する。
4. 再起動後に保存値を確認し、Python版でも同じDBを開けることを確認する。
