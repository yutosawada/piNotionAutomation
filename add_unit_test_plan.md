# Unit Test Plan (Docker Compose)

## 方針
- 標準ライブラリの `unittest` と `unittest.mock` を使用し、外部依存を追加しない。
- Notion API 呼び出しはすべてモックし、実際のネットワークアクセスを行わない。
- `automation/` 配下の各モジュールを対象にテストを書く。
- テストコードは `tests/` ディレクトリに配置し、`python -m unittest discover -s tests` で一括実行できる形にする。

## テスト対象と観点
- `automation/sync_databases.py`
  - `get_company_name` の抽出ロジック（タイトル/ロールアップ/番号スキップ）。
  - 差分検出と追加処理で失敗があった場合の非ゼロ終了（`SystemExit` 捕捉）。
- `automation/sync_oi_issue_list.py`
  - タイトル抽出とロールアップテキスト化のヘルパー。
  - 既存/欠損判定、追加失敗時の非ゼロ終了。
- `automation/update_business_state.py`
  - Business State 同期時の色付け/リセットのプロパティ生成。
  - リセット日数の設定読み込み（`schedule_config.yml` からの反映とデフォルト）。
  - 例外・失敗時の非ゼロ終了。
- `automation/execution_logger.py`
  - `LogCapture` の start/stop で stdout が戻ること。
  - `log_retention_days` 読み込みのデフォルトと上書き。

## 実行方法（Docker Compose）
- `docker-compose.yml` にテスト用サービスを追加:
  - サービス名: `test`
  - コマンド: `python -m unittest discover -s tests`
  - 既存サービスと同様に `.env` とプロジェクトルートをマウント。
- 実行例:
  ```bash
  docker compose run --rm test
  ```

## 今後の作業ステップ
1) `tests/` ディレクトリを作成し、上記観点に沿ったテストファイルを追加。  
2) `python -m unittest discover -s tests` がローカルとコンテナの両方で通ることを確認。  
3) 必要に応じて `README.md` にテスト手順を追記。
