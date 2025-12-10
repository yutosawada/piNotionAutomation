# Notion Automation

FIL SU Long List と Status Report など、複数の Notion データベース間での差分管理を自動化する Python ユーティリティ群です。Notion API を直接呼び出すため、書き込み権限付きのインテグレーショントークンと対象データベースの ID を `.env` に設定するだけで動作します。

## 主な機能
- `automation/sync_databases.py`  
  SU Long List (`FIL_SU_LONG_LIST`) の Active 企業を Status Report (`FIL_STATUS_REPORT`) と突合し、足りない企業を Status Report に作成して元レコードと関連付けます。
- `automation/sync_oi_issue_list.py`  
  OI Issue List (`OI_ISSUE_LIST_ID`) の Active 企業を抽出し、OI List Share (`OI_LIST_SHARE_RS_ID`) の reference リレーションおよびタイトルへ同期します（既存のタイトルや relation があるデータは自動スキップし、同期完了後に *_ref カラムの内容を表示用カラムへコピー）。
- `automation/update_business_state.py`  
  Business State／status_buffer／Last State／business_state_log を同期し、スタイルのリセット、更新履歴の追記、実行ログ（任意）を行います。
- `docker-compose.yml`  
  2 つのジョブをローカルコードをマウントしたコンテナで実行できるように定義しています。

## リポジトリ構成
- `automation/` – 各 Python スクリプト（モジュール実行）。
- `scripts/` – docker compose 実行用スクリプトと cron 管理スクリプト。
- `docker-compose.yml` – `sync-databases` / `sync-oi-issue-list` / `update-business-state` サービスを定義。
- `schedule_config.yml` – 実行ログ保持日数や Business State リセット日数、cron 生成用の各ジョブ間隔を設定。
- `active_companies.json` – `update_business_state` 実行時に最新の SU Long List データを保存するファイル。

## 必要条件
- ローカル実行時: Python 3.11 以上（Docker イメージは Python 3.12 を使用）
- Notion インテグレーショントークン（対象 DB に読み書き可能なもの）
- プロジェクト直下の `.env` に以下の変数を設定

```
NOTION_API_KEY=secret_xxx
FIL_SU_LONG_LIST_DB_ID=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
FIL_STATUS_REPORT_DB_ID=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx  # sync_databases.py で使用
EXE_LOG_DB_ID=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx            # 任意、実行ログ保存用
OI_ISSUE_LIST_ID=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx         # sync_oi_issue_list.py で使用
OI_LIST_SHARE_RS_ID=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx      # sync_oi_issue_list.py で使用
```

> 秘密情報を含むため `.env` は必ずバージョン管理から除外してください。

ローカルで依存関係をインストールするには次のコマンドを実行します。

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

## 実行方法

### ホスト環境で直接実行
仮想環境を有効化したら、以下のどちらかを実行します（`automation/` 配下に配置）。

```bash
python -m automation.sync_databases
python -m automation.sync_oi_issue_list
python -m automation.update_business_state
```

どちらのスクリプトも実行結果を詳細に出力します。`automation/update_business_state.py` 実行後は `active_companies.json` に処理対象の SU Long List が保存され、`EXE_LOG_DB_ID` が設定されている場合は同じログを実行ログ用データベースにアップロードします。

### Docker Compose 経由
`docker-compose.yml` はローカルのコードを `/app` にマウントしたままコンテナを起動します。サービス名を指定して任意のジョブを実行します。

```bash
docker compose run --rm sync-databases
docker compose run --rm sync-oi-issue-list
docker compose run --rm update-business-state
```

コンテナには `.env` の内容が自動で読み込まれるため、トークンをイメージ内にコピーする必要はありません。

## 開発メモ
- どちらのスクリプトも `fetch_all_pages` を用いてページネーションを処理するため、データベースが大きい場合は取得に多少時間がかかります。
- `update_business_state.py` は Business State を更新直後 2 週間だけオレンジ＆太字で強調し、その後は自動で元のスタイルに戻します。
- コンソール出力に ✗ が出た場合は、Notion 側のスキーマ変更や権限不足の可能性が高いので確認してください。
- 新しい自動化を追加する際は、ページネーションや企業名抽出などの共通ロジックを揃えておくとスキーマ差異による不具合を防げます。
- `schedule_config.yml` でログ保持日数 (`log_retention_days`)、Business State 強調リセット日数 (`business_state_reset_days`)、各ジョブの cron 間隔を調整できます。
