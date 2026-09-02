# HoloDeskWidget

[English](README.en.md) | 日本語

hololive所属タレントの配信状況を常時表示するWindowsデスクトップウィジェット。

## 構成

- `start_widget_native.py` — 起動エントリポイント(多重起動チェック→`holowidget`のウィジェットをmainloop実行)
- `holowidget/` — 本体パッケージ(常駐・透過表示・ドラッグ移動対応のWin32レイヤードウィンドウ実装)
  - `widget.py` — ウィンドウ本体(描画・イベント処理)
  - `config.py` — ウィンドウ既定値・`settings.json`の読み書き
  - `talents.py` — `talents.json`の読み込み
  - `youtube.py` — チャンネル解決・配信状況スクレイピング
  - `theme.py` / `strings.py` / `fonts.py` — 配色・多言語文字列・フォント
  - `layout.py` — 右上ボタン列の配置テーブル
  - `paths.py` — パス解決とログ出力(サイズ上限付きローテーション)
  - `single_instance.py` — 多重起動防止(Win32ミューテックス)
  - `version.py` — バージョン番号(右クリックメニューに表示)
- `talents.json` — 表示対象タレントの一覧（名前・ユニット・スラッグ・既知のチャンネルURL）
- `start_widget.bat` — ネイティブ版の起動ランチャー
- `build_widget.bat` — PyInstallerで`dist/HoloDesk Widget.exe`をビルド
- `find_python.bat` — `start_widget.bat`/`build_widget.bat`共通のPython検出スクリプト
- `release_widget.bat` — ビルド＋配布用zip(`release/HoloDeskWidget-v<version>.zip`)の作成
- `docs/Readme.html` / `docs/Readme.en.html` — エンドユーザー向け使い方ガイド(リリースzipに同梱)

## セットアップ

Python 3.10+ と以下の依存パッケージが必要です。

```bash
pip install -r requirements.txt
```

## 起動

```bash
start_widget.bat
```

`start_widget.bat` はPythonインストール先の自動検出、`pythonw.exe`の存在確認、Pillowの導入チェックを行った上でウィジェットを起動します。エラー発生時は `start_widget.log` を確認してください。

## バージョン

現在のバージョン: **1.0.0**

`holowidget/version.py` の `__version__` が唯一の管理箇所です(ウィジェットの右クリックメニューにも表示されます)。リリース時はこの値を手動で更新してください。`release_widget.bat` はこの値を読み取り、`build_widget.bat`(PyInstaller)でexeをビルドした上で、exe・`talents.json`・`docs/Readme*.html` をまとめた `release/HoloDeskWidget-v<version>.zip` を作成します。

## リリース手順

1. バージョンを上げる場合は `holowidget/version.py` の `__version__` を更新し、`README.md` の `現在のバージョン: **x.y.z**`、`README.en.md` の `Current version: **x.y.z**`、`docs/Readme.html` / `docs/Readme.en.html` に埋め込まれた同じバージョン文字列も合わせて更新します。5箇所まとめて更新するには以下を使用します。
   ```bash
   python .claude/skills/release/scripts/bump_version.py <old_version> <new_version>
   ```
2. `release_widget.bat` を実行します。内部で `build_widget.bat`(PyInstaller、要インストール)を呼び出して `dist/HoloDesk Widget.exe` をビルドし、exe・`talents.json`・`docs/Readme.html`・`docs/Readme.en.html` の4点を `release/HoloDeskWidget-v<version>.zip` にまとめます(`settings.json`やログなどの実行時生成ファイルは含まれません)。
3. 生成された `release/HoloDeskWidget-v<version>.zip` を配布します。`build/`・`dist/`・`release/` はgit管理対象外です。

## タレント一覧の更新

`talents.json` に `{"name": "...", "unit": "...", "slug": "...", "channel_url": "..."}` の形式でエントリを追加/編集します。`channel_url` は既知のチャンネルURLが分かっている場合のみ指定し、未指定の場合は起動時にhololive公式サイトのタレントページからチャンネルを自動解決します。

## 注意

配信中判定はYouTubeの `/live` ページをポーリングして行っており、非公式なスクレイピングです。YouTube側のページ構造変更で動作しなくなる可能性があります。
