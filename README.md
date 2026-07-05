# local-coding-agent

`local-coding-agent` は、llama.cpp server で提供される `LFM2.5-8B-A1B` を使い、Python の安全なエージェントハーネス経由で開発タスクを進めるローカルコーディングエージェントです。

LLM は「判断・提案」のみを行います。ファイル操作、コマンド実行、検索、git 操作は Python 側の harness が JSON action を検証したうえで実行します。これにより、LLM を直接信頼せず、許可された操作だけを Docker sandbox 内で行えます。

## 主な機能

- llama.cpp の OpenAI 互換 API 経由で `LFM2.5-8B-A1B` を呼び出し
- LLM 出力を JSON action として schema 検証
- workspace 内での `read_file` / `write_file` / `append_file` / `list_files`
- Docker sandbox 内での `run_command`
- SearXNG 経由の `search_web`
- `git diff` 確認と `commit_changes` による細かい監査可能な commit
- JSON Lines 形式の action / observation / command / search / git ログ
- 最大ステップ数、timeout、最大実行時間、検索回数、失敗回数による暴走防止
- `-1` による運用上限の無効化と unsafe mode 警告
- 制限なし設定でも無効化されない安全ポリシー

## 必要要件

- Python 3.10 以上
- Docker
- Git
- llama.cpp server
- SearXNG（検索 action を使う場合）

## セットアップ

```bash
git clone <this-repository-url>
cd local-coding-agent
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
cp .env.example .env
```

## llama.cpp server の起動

`llama.cpp` を server モードで起動し、OpenAI 互換 API を有効にします。

```bash
./llama-server \
  -m /path/to/LFM2.5-8B-A1B.gguf \
  --host 127.0.0.1 \
  --port 8080
```

`.env` の想定値:

```text
LLM_BASE_URL=http://localhost:8080/v1
LLM_MODEL=LFM2.5-8B-A1B
LLM_TEMPERATURE=0.2
LLM_MAX_TOKENS=2048
```

llama.cpp server が起動していない場合、エージェントは接続先を含むわかりやすいエラーメッセージを表示して終了します。

## SearXNG の起動

検索 action を使う場合は SearXNG を起動し、URL を設定します。

```bash
docker run --rm -p 8888:8080 searxng/searxng
```

```text
SEARXNG_URL=http://localhost:8888
```

検索結果は LLM に全文では渡さず、上位 5 件の `title`、`url`、`summary` に整形されます。

## 実行方法

```bash
python -m agent.main "FastAPI の hello world アプリを作ってテストも追加してください"
```

インストール後は console script でも実行できます。

```bash
local-agent "pytest が通る Python パッケージを作ってください"
```

オプション例:

```bash
local-agent \
  --workspace ./sandbox_workspace \
  --max-steps 30 \
  --command-timeout 30 \
  --max-runtime 600 \
  "CLI TODO アプリを作ってください"
```

## 制限値の変更

`.env` で以下を変更できます。

```text
AGENT_MAX_STEPS=30
AGENT_COMMAND_TIMEOUT=30
AGENT_MAX_RUNTIME_SECONDS=600
AGENT_MAX_SEARCHES=5
AGENT_MAX_REPEATED_ERRORS=3
AGENT_MAX_CONSECUTIVE_FAILURES=5
```

各値に `-1` を指定すると、その運用上限だけを無効化します。

```bash
local-agent \
  --workspace ./sandbox_workspace \
  --max-steps -1 \
  --command-timeout -1 \
  --max-runtime -1 \
  --max-searches -1 \
  "大きめのアプリを作ってください"
```

## unsafe mode の注意点

いずれかの運用上限を `-1` にすると unsafe mode として扱われ、起動時に以下の警告が表示され、ログにも記録されます。

```text
WARNING: unsafe mode is enabled.
Some agent operational limits are disabled.
This may cause infinite loops, excessive resource usage, or unintended long-running execution.
```

unsafe mode で無効化できるのは、反復回数、実行時間、検索回数、Docker の一部リソース上限などの運用上限だけです。

次の安全機能は `-1` でも無効化されません。

- workspace 外アクセス禁止
- 絶対パス禁止
- `..` による path traversal 禁止
- 危険コマンド拒否
- 秘密情報ファイル読み取り禁止
- Docker sandbox 内での実行
- non-root 実行
- ホスト任意ディレクトリのマウント禁止
- commit 前 diff 確認
- JSONL ログ記録

## Docker sandbox

コマンドは Docker コンテナ内で実行されます。

推奨デフォルト:

```text
memory: 1GB
cpu: 1 core
timeout: 30 seconds per command
pids_limit: 128
network: disabled
user: 1000:1000
```

`.env` で調整できます。

```text
SANDBOX_MEMORY_LIMIT=1g
SANDBOX_CPU_LIMIT=1
SANDBOX_PIDS_LIMIT=128
SANDBOX_DOCKER_IMAGE=python:3.11-slim
```

`SANDBOX_MEMORY_LIMIT=-1`、`SANDBOX_CPU_LIMIT=-1`、`SANDBOX_PIDS_LIMIT=-1` により、それぞれのリソース上限を無効化できます。ただし Docker sandbox、non-root 実行、workspace のみマウント、危険コマンド拒否は無効化できません。

## 利用可能な action

LLM は必ず次のような JSON action を出力します。

```json
{
  "thought_summary": "次にテストを実行して失敗原因を確認する",
  "action": "run_command",
  "args": {
    "command": "pytest -q"
  }
}
```

対応 action:

- `read_file`
- `write_file`
- `append_file`
- `list_files`
- `run_command`
- `search_web`
- `git_diff`
- `commit_changes`
- `finish`
- `ask_user`

## git diff / commit 管理

workspace 初期化時に git repository を作成します。

```bash
git init
git add .
git commit -m "Initial workspace"
```

変更内容が確定したタイミングで `commit_changes` を使います。commit 前には必ず `git diff HEAD --` を取得し、diff が空なら commit しません。

ログには以下を保存します。

- git status
- git diff
- commit hash
- commit message
- changed files
- commit 成功または失敗

finish 時には未コミット変更を確認し、残っている場合は warning を含めます。

## ログ

ログは JSON Lines 形式で保存されます。

```text
logs/run-YYYYMMDD-HHMMSS.jsonl
```

記録対象:

- ユーザー入力タスク
- LLM request / response
- action 出力
- action 実行結果
- command stdout / stderr / exit code
- search query / result URL
- git status / diff / commit
- unsafe mode 状態
- 停止理由

## テスト

```bash
pytest
```

テストは Docker や外部 API に依存しないよう、主な外部呼び出しを mock しています。

## 制限事項

初期実装では以下は対象外です。

- vLLM / SGLang / MLX への対応
- GUI
- ブラウザ操作
- 複数エージェント
- 長期記憶
- 自動 pull request 作成
- ホスト環境での直接コマンド実行
- sandbox 外ファイルの編集
- 安全ポリシーを無効化する機能
- commit 前 diff 確認を無効化する機能

## 受け入れ確認例

```bash
python -m agent.main "簡単な Python スクリプトを作って実行してください"
```

このコマンドにより、エージェントは LLM の JSON action を処理し、workspace 内にファイルを作成し、Docker sandbox 内でコマンドを実行し、結果を observation として LLM に戻します。
