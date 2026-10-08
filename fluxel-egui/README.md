# Fluxel egui

既存のFluxelをRustと`eframe/egui`で再実装する独立プロジェクトです。Python/PySide版はリポジトリ直下に残し、移行完了までは両方を並行して利用できます。

## データ互換

次のファイルは既存版と同じテーブル・列を利用します。

- `Tasks.db`
- `QuickAccess.db`
- `Planning.db`
- `settings.ini`
- `location.ini`

Windowsでは既存版と同じ`%LOCALAPPDATA%\Fluxel`を利用します。`location.ini`で保存先を変更している場合も、その指定を読み取ります。

開発やテストで実データへ触れたくない場合は、`FLUXEL_DATA_DIR`で隔離先を指定できます。

## 実装済みの画面と操作

- Kanban（5列、追加・編集・削除、ステータス移動、自動Archive）
- Dashboard（残件・期限・重要度の集計）
- ShortCut / OpenFile（タグ検索、コピー・URL・ファイル実行）
- Gantt（プロジェクト・期間の編集とタイムライン表示）
- タスク検索、設定保存、`settings.ini` / `Tasks.db`のエクスポート
- アプリ内ショートカットと、macOS / Windows共通のグローバルホットキー

グローバルホットキーは、macOSでは`Cmd+Option+Shift+K/P/O`、Windowsでは`Ctrl+Alt+Shift+K/P/O`です。アプリ内の`Ctrl`系ショートカットも、macOSではすべて`Cmd`へ置き換わります。

クラウドフォルダーの競合マージ機能と自動アップデーターは、移行の次段階です。設定ファイルの互換性を保つため同期フォルダー値は読み書きしますが、egui版からの同期実行はまだ行いません。

## ホストへRustを入れずに開発

必要なのはDocker Desktopだけです。Rust、Cargo、Linux用のGUIビルド依存はコンテナとDockerボリューム内に入ります。

```sh
cd fluxel-egui
docker compose run --rm dev
```

フォーマットと静的チェック:

```sh
docker compose run --rm dev cargo fmt --all -- --check
docker compose run --rm dev cargo clippy --all-targets -- -D warnings
```

ローカルLinux環境でGUIを表示する場合はディスプレイ転送設定が別途必要です。macOS/Windowsのネイティブ実行ファイルはGitHub Actionsで生成し、成功したワークフローのArtifacts（`fluxel-egui-macos` / `fluxel-egui-windows`）から取得できます。普段の開発ではホストへのRust導入は不要です。

GitHub Actionsと同じ確認をホスト上で行うスクリプトも用意しています。この方法だけはホストの`rustup`を利用します。リポジトリルートから実行してください。

macOS:

```sh
./scripts/ci-egui-macos.sh
```

Windows PowerShell:

```powershell
./scripts/ci-egui-windows.ps1
```

## ホストへRustを入れて実行する場合

macOSでは、リポジトリ内だけに最小構成のRustを導入できます。シェルのPATHや`~/.cargo`、`~/.rustup`は変更しません。

```sh
./scripts/bootstrap-egui-macos.sh
./scripts/run-egui-macos.sh
```

初回だけRust 1.95.0と依存ライブラリを取得します。2回目以降は差分だけをビルドして起動します。配布用の最適化ビルドが必要な場合は次のように実行します。

```sh
./scripts/run-egui-macos.sh --release
```

ローカルRust環境を削除する場合は、Fluxelを終了してリポジトリ直下の`.dev-tools`を削除してください。Dockerだけを使う場合はこの手順は不要です。
