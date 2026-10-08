# Fluxel v0.3.0-20260801 リリースノート

- リリース識別子: `v0.3.0-20260801`
- Windowsインストーラービルド: 2026-09-01

## 概要

本リリースでは、Kanbanを中心としていたFluxelに、Dashboard、Gantt、検索改善、保存先管理、OneDriveを利用した複数端末同期を追加しました。

通常の操作では、引き続き各端末のローカルSQLiteを使用します。OneDrive上のSQLiteを直接共有する方式ではなく、変更内容を追記型の同期イベントとしてOneDriveフォルダーへ保存するローカルファースト構成です。

## 主な新機能

### OneDrive複数端末同期

- Microsoft Entraへのアプリ登録、Microsoft Graph、専用サーバーを必要としないファイルベース同期を追加しました。
- 各端末は独立したローカルSQLiteを保持します。
- `Setting > OneDrive synchronization` から同期フォルダーを設定できます。
- 個人用・職場用OneDriveフォルダーを自動検出します。
- 新規端末向けに `Set up this device` を追加しました。
- 共有データを取り込む前に、同期先、共有項目数、イベント数、既知の端末数を表示して確認します。
- 初期セットアップでは、共有側のデータをローカルDBへ一括で取り込みます。ローカルにしか存在しないデータは保持され、共有側へ追加されます。
- `Ctrl+S` または `Sync now` で手動同期できます。
- Kanbanでタスクを追加すると、同期フォルダー設定済みの場合は自動同期を実行します。
- 次の項目を同期します。
  - Kanbanタスク
  - ShortCut項目
  - OpenFile項目
  - 共通タグ
  - Gantt Project
  - Gantt Term
- 追加・更新・削除は、一意なIDを持つ変更イベントとして保存します。
- 各イベントの内容はSHA-256で検証します。
- 書き込み途中の `.partial` ファイルは同期対象から除外します。
- 端末固有の同期状態は `SyncState.db` に分離し、共有しません。
- 同じ項目が複数端末で変更された場合は競合として検出・記録し、競合内容を黙って破棄しません。

OneDrive上の同期構造:

```text
<同期フォルダー>\
  .fluxel-sync\
    v1\
      info.json
      events\
        task\YYYY\MM\*.json
        shortcut\YYYY\MM\*.json
        openfile\YYYY\MM\*.json
        tag\YYYY\MM\*.json
        gantt_project\YYYY\MM\*.json
        gantt_term\YYYY\MM\*.json
```

### 検索画面の刷新

- 検索ポップアップを横幅の広いシンプルなレイアウトへ変更しました。
- 検索結果を一つのスクロール領域へ統合しました。
- タイトル一致と本文一致は見出しで区別します。
- Wait、Todo、Doing、Finish、ArchiveのStatusフィルターを追加しました。
- High、Medium、LowのImportanceフィルターを追加しました。
- `Include Archive` を追加しました。
- 検索結果件数と空状態の案内を追加しました。
- 選択行、ホバー、期限日、Status、Importanceの表示を改善しました。
- `↑↓` による選択と `Enter` によるタスク表示に対応しました。

### Settingと保存先管理

- Setting画面を次のカードに再構成しました。
  - Storage
  - OneDrive synchronization
  - Kanban
  - Backup & export
  - Tags
  - Application details
  - Danger zone
- 次のSQLiteをまとめて別フォルダーへ移動できるようにしました。
  - `Tasks.db`
  - `QuickAccess.db`
  - `Planning.db`
- SQLite移動時は、移動元とコピー後の両方で整合性を検査してから保存先を切り替えます。
- `settings.ini` の移動機能を追加しました。
- 移動後の保存先は、固定位置の `location.ini` から毎回解決します。
- インストール時にSQLite保存先を設定できるようにしました。
- アンインストール機能を追加しました。
  - SQLiteを残してアンインストール
  - SQLiteを削除してアンインストール
- どちらのアンインストールも二段階確認を行います。
- OneDriveを稼働中SQLiteの保存先として選択した場合は警告を表示します。

### Dashboard

- 残タスクのImportance構成を追加しました。
- 期限日ごとの負荷をImportance別に確認できるグラフを追加しました。
- Finish、Archiveを含むStatusフィルターを追加しました。
- カード、ヘッダー、配色、表示密度を改善しました。
- 上部操作領域を固定し、タイムラインのスクロールと表示範囲拡張に対応しました。

### Gantt

- Kanbanとは独立したProjectとTermを `Planning.db` で管理します。
- ドラッグ＆ドロップによる期間移動を追加しました。
- Project単位のフィルターと、完了Projectの非表示に対応しました。
- ProjectとTermにDescriptionを追加しました。
- 次のキーボード操作に対応しました。
  - 矢印キー: 選択移動
  - `Alt+↑/↓`: Project間の選択移動
  - `Ctrl+↑/↓`: 並べ替え
  - `Ctrl+Alt+↑/↓`: Termを別Projectへ移動
  - Gantt表示中の `Ctrl+N`: Term追加
- `Ctrl++`、`Ctrl+-`、Ctrl+マウスホイールで拡大縮小できます。
- Day、Month、Quarter、Yearの表示粒度に対応しました。
- 月・四半期・年の境界線と追従ヘッダーを追加しました。
- 過去・未来方向への表示範囲拡張に対応しました。

### Kanban、OpenFile、タグ

- Kanban表示中の `Ctrl+W` でWaitタスクを作成できます。
- `Ctrl+N` を表示画面に応じた新規作成へ統一しました。
- OpenFileの矢印キー選択を改善しました。
- タグの追加、候補表示、選択、削除処理を改善しました。
- 複数語検索と検索順位を改善しました。

### DBマイグレーションと配布

- 起動時にDBバージョンを確認し、古いスキーマを非破壊でマイグレーションします。
- 主要な画面タイトルと操作名を英語表記へ統一しました。
- 更新対象画面のQtスタイルシート警告を解消しました。
- PyInstallerとInno SetupでWindows配布パッケージを再生成しました。
- インストーラーにDB保存先選択と、データ保持を考慮したアンインストール処理を追加しました。

## ショートカット

| ショートカット | 操作 |
|---|---|
| `Ctrl+S` | 設定済みOneDriveフォルダーとの同期 |
| `Ctrl+K` | Kanbanを表示 |
| `Ctrl+P` | ShortCutを表示 |
| `Ctrl+O` | OpenFileを表示 |
| `Ctrl+F` | タスク検索を表示 |
| `Ctrl+N` | 現在の画面に応じた新規作成 |
| `Ctrl+W` | KanbanでWaitタスクを作成 |
| `Ctrl+X` | Fluxelを終了 |

## 新しい端末のセットアップ

1. Fluxelをインストールし、ローカルDBを作成します。
2. OneDriveデスクトップアプリで、既存端末と同じアカウントへサインインします。
3. `Setting > OneDrive synchronization` を開きます。
4. `Set up this device` を選択します。
5. 自動検出されたOneDriveとFluxel Syncフォルダーを確認します。
6. 共有項目数、イベント数、既知の端末数を確認します。
7. `Import / merge remote data` を承認します。
8. 初期マージ完了後にデータ編集を開始します。

初期マージではローカル固有の項目を維持します。同じIDで内容が異なる項目は競合として扱い、黙って削除しません。

## アップグレード時の注意

- ユーザーが明示的に保存先を変更しない限り、既存SQLiteは現在の場所に残ります。
- 古いDBスキーマは起動時に自動マイグレーションされます。
- 同期フォルダー保存時に `settings.ini` へ `[sync]` セクションが追加されます。
- `SyncState.db` は端末固有です。別端末へコピーしないでください。
- 複数端末同期を本格運用する前に、既存SQLiteのバックアップを推奨します。

## 既知の制約

- 今回UIから選択できる同期先はOneDriveのみです。
- Microsoft Graphへ直接アップロードせず、インストール済みのOneDriveデスクトップアプリに同期を委ねます。
- OneDriveが共有イベントをダウンロードするまで、Fluxelはその変更を取り込めません。
- オフライン利用する場合はFluxel Syncフォルダーを `このデバイス上で常に保持する` に設定してください。
- タスク追加時は自動同期します。それ以外の変更は `Ctrl+S` で確実に収集されます。すべての変更操作を起点にした自動同期は今後の対象です。
- 競合は検出・記録されますが、左右比較による専用競合解決画面は未実装です。
- イベント圧縮とスナップショット生成は未実装です。本リリースではイベントを追記したまま保持します。

## 検証結果

- 自動試験20件が成功しました。
- 2端末を模した環境で、追加・更新・削除の往復同期を確認しました。
- 新規端末への共有データとローカルデータのマージを確認しました。
- 検索のStatus／Importanceフィルターを確認しました。
- Qt Setting／Search画面の生成と描画を確認しました。
- PyInstaller版アプリの起動を確認しました。
- Inno Setupインストーラーのコンパイルに成功しました。

## 配布物

```text
dist\installer\Fluxel_Setup_v0.3.0-20260801.exe
dist\release\Fluxel_Setup_v0.3.0-20260801_installer.zip
```

インストーラーSHA-256:

```text
8AF63BD70E728EB52FFFCD6FC8EF55683A7750BDB53802E8DAF3F794B23C2A5D
```
