# Fluxel

PySide6 ベースのデスクトップアプリです。開発は **uv** と **Python 3.14** を想定しています。

## 開発環境の準備

- [uv](https://docs.astral.sh/uv/) をインストールする。
- リポジトリルートで依存関係を同期する。

```powershell
uv sync
```

配布ビルド用の追加依存（任意）:

```powershell
uv sync --extra pack
```

### Docker で共通の開発・テスト環境を使う

Docker Desktop が入っていれば、Windows、macOS、Linux のどこでも同じ Python 3.14 / Qt 環境を作れます。GUI を直接表示する用途ではなく、依存関係の同期とヘッドレステスト向けです。

```sh
docker build -t fluxel-dev .
docker run --rm fluxel-dev
```

コンテナ内で操作する場合:

```sh
docker run --rm -it fluxel-dev bash
```

### macOS / Windows と GitHub Actions

GitHub Actions は macOS と Windows の両方で、ロックファイルどおりに依存関係を同期して全テストを実行します。CI と同じ処理はローカルでも実行できます。

macOS:

```sh
./scripts/ci-macos.sh
```

Windows PowerShell:

```powershell
./scripts/ci-windows.ps1
```

ワークフロー定義は `.github/workflows/ci.yml` にあります。

## ソースから実行

```powershell
uv run python main.py
```

Windows では `python` がストアのスタブだけで失敗することがあります。**このリポジトリでは `uv run python ...` を使ってください。**

### グローバルホットキー（Windows）

アプリにフォーカスがなくても、以下のキーで Fluxel を前面表示して対象ページへ移動できます。

- `Ctrl+Alt+Shift+K` : Kanban
- `Ctrl+Alt+Shift+P` : ShortCut
- `Ctrl+Alt+Shift+O` : OpenFile

### アプリ内ホットキー

- `Ctrl+K` : Kanban
- `Ctrl+P` : ShortCut
- `Ctrl+O` : OpenFile
- `Ctrl+N` : 現在画面に応じて新規追加
  - Kanban 画面: 新規タスク追加ダイアログ
  - ShortCut 画面: ShortCut 新規追加ダイアログ
  - OpenFile 画面: OpenFile 新規追加ダイアログ

### ShortCut / OpenFile（QuickAccess）

`ShortCut` と `OpenFile` は、ページ内の検索UIで「よく使う項目」を蓄積して再利用できます。

- **ShortCut**: タイトル/コマンド/タグを保存し、検索して即実行
  - `nav:kanban` / `nav:shortcut` / `nav:openfile` / `nav:settings` のような内部遷移コマンドに対応
  - `http(s)://...` は既定ブラウザで開く
- **OpenFile**: タイトル/ファイルパス/タグを保存し、検索して即オープン
  - 「ファイル選択から追加」でパスを取り込み可能

保存先DB:

- `%LOCALAPPDATA%\\Fluxel\\QuickAccess.db`

### Settings 画面

上部ナビの `Setting` から `Settings` 画面を開けます。以下を確認・設定できます。

- ユーザ情報（ユーザー名、ユーザーデータ保存先、設定ファイル、Tasks DB）
- ショートカット一覧
- アプリバージョン表示と `更新を確認する`（現状はプレースホルダー）
- Kanban 設定（`Finish -> Archive` に自動移動する日数）
- エクスポート（`ini` / `sql`）

設定は `%LOCALAPPDATA%\\Fluxel\\settings.ini` に保存されます。
`ini` / `sql` エクスポートは Settings 画面のボタンから保存先を指定して出力します。

### デモデータ（大量タスク）を入れる

```powershell
uv run fluxel-seed
```

入れ直す場合（既存の `demo-seed-*` を消してから再投入）:

```powershell
uv run fluxel-seed --force
```

アプリ起動時にまとめて行う場合:

```powershell
uv run python main.py --seed-demo
```

### アーカイブ列について（パフォーマンス）

アーカイブが増えると一覧が重くなるため、**`update_at` が直近 30 日以内**のものだけカンバンに表示します。それより古いタスクは **DB（`Tasks.db`）には残ります**が、アーカイブ列には出ません（既定値は `KanbanBoard._ARCHIVE_VISIBLE_DAYS`）。

---

## 配布用インストーラー（Setup EXE）の作り方

エンドユーザー向けの **配布用 EXE** は、**PyInstaller でアプリ本体を固めたあと**、**Inno Setup でインストーラーをコンパイル**して生成します。リポジトリでは `packaging\build-release.ps1` がこの一連を実行します。

### 必要なもの（ビルドマシン）

| もの | 用途 |
|------|------|
| **uv** | 仮想環境と PyInstaller の実行 |
| **Inno Setup 6**（`ISCC.exe`） | インストーラーのコンパイル |

Inno Setup が未インストールの場合の例（Windows）:

```powershell
winget install --id JRSoftware.InnoSetup -e --source winget
```

インストール後、新しい PowerShell を開くか、`ISCC.exe` が PATH に載る場所を確認してください（スクリプトは一般的なインストール先も自動探索します）。

### ビルド手順（推奨）

リポジトリの**ルート**で次を実行します。

```powershell
Remove-Item Env:FLUXEL_SKIP_INNO -ErrorAction SilentlyContinue
powershell -ExecutionPolicy Bypass -File packaging\build-release.ps1
```

処理の流れは次のとおりです。

1. `uv sync --extra pack` … パッケージング用依存を含めて同期
2. **PyInstaller**（`packaging\fluxel.spec`）… `dist\Fluxel\` に onedir ビルド
3. **Inno Setup**（`packaging\fluxel.iss`）… `dist\installer\Fluxel_Setup_<版表示>.exe` を生成
4. **配布用 ZIP** … 上記 EXE だけを `dist\release\Fluxel_Setup_<版表示>_installer.zip` に格納（メール・ポータル配布向け）

### 成果物の場所

| 配布物 | パス（例・版はリリースに合わせて変わる） |
|--------|------------------------------------------|
| インストーラー本体 | `dist\installer\Fluxel_Setup_v0.2-202605-06.exe` |
| 配布用 ZIP（中身は EXE のみ） | `dist\release\Fluxel_Setup_v0.2-202605-06_installer.zip` |

### 同梱サイズについて

`packaging\fluxel.spec` では **PySide6 を `collect_all` しない**方針です。import された Qt モジュール（Widgets / Gui / Core / Network など）と PyInstaller のフックだけを同梱するため、QtWebEngine や 3D など未使用の巨大 DLL が乗らず、**onedir はおおよそ 100〜150 MB 程度**を目安にできます（PySide6 のバージョンで多少変動します）。

利用者には **ZIP を渡して展開後に EXE を実行**してもらうか、EXE を直接配布しても構いません。インストール先の既定は **Program Files 配下の Fluxel**、ユーザーデータは **`%LOCALAPPDATA%\Fluxel\`** です（初回起動でアプリ側が作成）。

### 環境変数（任意）

| 変数 | 意味 |
|------|------|
| `FLUXEL_SKIP_INNO=1` | Inno を実行しない（PyInstaller まで。配布用としては未完成） |
| `FLUXEL_PORTABLE_ZIP=1` | 追加で `dist\release\Fluxel_portable_<版>.zip`（onedir 一式）も作成 |

**注意:** シェルに `FLUXEL_SKIP_INNO=1` が残っているとインストーラが作られません。配布ビルド前に `Remove-Item Env:FLUXEL_SKIP_INNO` で解除してください。

---

## バージョンを上げるとき（リリース前チェックリスト）

次を**同じリリース内容**になるよう揃えてからビルドすると、表示・ファイル名・インストーラのバージョン情報が一貫します。

1. **`fluxel\__about__.py`** … `APP_VERSION`（例: `v0.2-202605-06`）
2. **`packaging\build-release.ps1`** … 先頭付近の `$ReleaseVersion`（ZIP 名用。`__about__` の表示と揃える）
3. **`packaging\fluxel.iss`** … `#define MyAppVersion` / `MyAppVersionDisplay`、および **`VersionInfoProductVersion`**（Windows の 4 桁 `a.b.c.d` のみ。`MyAppVersion` のような文字列は不可）

`AppId`（`fluxel.iss` の GUID）は、**同じ製品ラインの上書きインストール・アップグレード**を続ける限り**変えない**のが一般的です。

---

## アップデート・今後の開発方針（メモ）

### 配布・アップデートの考え方

- **メイン配布形態**は **Inno インストーラー（Setup EXE）** とする。ポータブル ZIP は必要な場合のみ `FLUXEL_PORTABLE_ZIP=1` で付与する。
- **ユーザーデータ**（DB 等）は `%LOCALAPPDATA%\Fluxel\` に置く方針のため、**アプリ本体を上書きインストール**しても、原則としてデータは別領域で引き続き利用できる設計に寄せる。
- **マイナー／パッチリリース**では `AppId` 固定・`AppVersion` / 表示版の更新・インストーラ再ビルドで対応する。
- **将来、コード署名（Authenticode）**を付与できるなら、SmartScreen 対策としてインストーラ EXE に署名するのを推奨（現状は任意・未設定でよい）。

### 開発プロセスの目安

- **機能開発**は通常どおり `main`（または既定ブランチ）で進め、リリースタイミングで上記チェックリストのあと `build-release.ps1` を回す。
- **破壊的変更**（データ形式の移行、インストール先の変更など）を行う場合は、リリースノートに明記し、必要なら DB 移行ロジックをアプリ側に持たせる（インストーラだけに依存しない）。
- **バージョン表記**は UI のウィンドウタイトルには載せず（アプリ名のみ）、`APP_VERSION` はリリースノート・配布ファイル名・サポート問い合わせ用の識別子として使う方針とする。

### 利用者向けアップデートの流れ（想定）

1. 新しい `Fluxel_Setup_<新版>.exe`（または ZIP 内の同ファイル）を配布する。
2. 利用者が既存版の上から実行し、ウィザードに従ってインストールする。
3. アプリ起動後、 `%LOCALAPPDATA%\Fluxel\` のデータを引き続き読む（移行が必要な場合はアプリが担当）。

---

## ライセンス

（未設定の場合はここにライセンスを追記してください。）

---

## 更新履歴

### v0.2-202605-06

- 検索モードの操作を改善（Enter 検索、Esc で選択モード遷移、`/` で再フォーカス）
- トップメニューに `Setting` を追加
  - ユーザ情報表示
  - ショートカット一覧表示
  - アップデート確認項目（プレースホルダー）
  - INI / SQL エクスポート
- グローバルホットキーを追加
  - `Ctrl+Alt+Shift+K`（Kanban）
  - `Ctrl+Alt+Shift+P`（ShortCut）
  - `Ctrl+Alt+Shift+O`（OpenFile）
- トップメニュー切り替え用ショートカットを追加
  - `Ctrl+K`（Kanban）
  - `Ctrl+P`（ShortCut）
  - `Ctrl+O`（OpenFile）
- 読み込み/反映ロジックを改善し、高速化
  - カード再描画処理を最適化
  - 検索時の描画・選択更新を効率化
- QuickAccess 機能を拡張
  - `QuickAccess.db` による ShortCut / OpenFile 管理
  - ShortCut で選択 Enter 時にクリップボードコピー
  - OpenFile で選択 Enter 時にファイルオープン（失敗時は警告表示）
  - 追加ダイアログで `Ctrl+Enter` 対応
- タグ機能を強化
  - 区切りを `,` に統一
  - タグ候補の入力補完を追加
  - 設定画面にタグ一覧管理（追加/削除）を追加
  - タグ検索・削除周りの不具合を修正
