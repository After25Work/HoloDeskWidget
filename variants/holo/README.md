# HoloDeskWidget

[English](README.en.md) | 日本語

hololive所属タレントの配信状況を常時表示するWindowsデスクトップウィジェット。

> **注意**: 本プロジェクトは個人が制作した非公式のファンメイドツールです。hololive、hololive production、カバー株式会社とは一切関係がなく、公式の許諾を受けたものでもありません。

## 機能

- **配信状況の一覧表示**: 登録タレントの状態(配信中/待機中/取得エラー)を色分けカードで表示。カードをクリックすると配信ページ(YouTube)が開きます。右クリックすると、名前や配信タイトルをクリップボードにコピーするメニューが表示されます。
- **常時前面表示できる半透明ウィジェット**: デスクトップに常駐する透過ウィンドウ。背景部分のドラッグで移動、端・角のドラッグでサイズ変更ができます。
- **LIVEフィルタ**: 配信中のタレントだけに絞り込んで表示し、配信タイトルをティッカー(横スクロール)表示します。
- **番組タイトル検索(インクリメンタルサーチ)**: スライダーの下の検索ボックスに文字を入れると、入力するたびに配信タイトルで絞り込まれます(大文字小文字は区別しません)。絞り込み中は該当タレントの配信タイトルが名前の横に表示され、ステータスバーの件数も「該当◯件」に切り替わります。`Ctrl+F`で検索ボックスへ移動、`Esc`または右側の×ボタンで解除できます。
- **世界時計**: JST/WIB/UTC/EST/PSTの現在時刻をあわせて表示します。
- **表示のカスタマイズ**: 最前面固定・ダークモード/ライトモード切替・テーマカラー(配色パレット)選択・表示言語(日本語/英語)切替を右上のボタンまたは右クリックメニューから操作できます。背景の透過度と文字サイズはスライダーで調整できます。文字幅(タレント名の列幅、LIVE表示時は名前と配信タイトルの分割位置)は「幅」スライダーで調整でき、広げると省略されていた長い名前が最後まで表示されます。
- **設定の自動保存**: ウィンドウ位置・サイズ・言語・テーマなどの個人設定は`settings.json`に自動保存され、次回起動時に復元されます。
- **チャンネル自動解決**: 起動時にhololive公式サイトのタレントページからYouTubeチャンネルを自動解決し、失敗した場合のみ`productions/hololive.json`の`channel_url`にフォールバックします。
- **システムトレイ常駐**: 右クリックメニューの「トレイに格納」でウィンドウを非表示にしたまま常駐を継続します。タスクトレイアイコンを左クリックすると表示に戻り、右クリックすると「表示」「終了」を選べます。
- **配信履歴**: 各タレントの配信開始・終了を自動記録し、右クリックメニューの「配信履歴」から直近の履歴一覧と本日の配信回数を確認できます。

## スクリーンショット

<p align="center">
  <img src="docs/screenshots/main.png" width="320" alt="メイン画面">
  <img src="docs/screenshots/context_menu.png" width="320" alt="右クリックメニュー">
</p>

左: タレントごとに配信状況を色分け表示するメイン画面。右: 右クリックメニューから最前面固定・LIVEフィルタ・ダークモード・言語・テーマカラー切り替えなどを操作できます(右上のボタン列からも同じ操作が可能です)。

<p align="center">
  <img src="docs/screenshots/buttons.png" alt="右上のボタン">
</p>

LIVEフィルタ使用時は、配信中のタレントに絞り込んだ上で配信タイトルがティッカー表示されます。

<p align="center">
  <img src="docs/screenshots/live_ticker.gif" width="320" alt="LIVEフィルタのティッカー表示">
</p>

## 動作環境

- **OS**: Windows専用(Win32レイヤードウィンドウ・`ctypes`/`windll`・Win32ミューテックスに依存しており、Windows以外では動作しません)。Windows 10 / 11での動作を想定しています。
- **インターネット接続**: 必須(hololive公式サイトからのチャンネル自動解決、YouTube innertube APIからの配信状況取得に使用します)。
- **配布版(exe)を使う場合**: 追加の準備は不要です。PyInstallerでビルドされた単体exeとして動作します。
- **開発環境から起動する場合**: Python 3.10以降と`requirements.txt`記載の依存パッケージ(`Pillow>=10.1,<12`)に加え、標準ライブラリの`tkinter`(Tcl/Tk)が必要です(python.org配布のインストーラには同梱されています)。
- **フォント**: 日本語表示にはYu Gothic(なければMeiryo→MS Gothicの順にフォールバック)、絵文字表示にはSegoe UI Emojiを使用します。いずれもWindows標準搭載フォントですが、East Asian言語サポートを追加していない環境などで欠けている場合はフォントが正しく描画されないことがあります。

## 構成

このリポジトリはHoloDeskWidgetと、複数プロダクション対応の姉妹アプリ「VTDeskWidget」を、共通のエンジンパッケージから2種類のexeとしてビルドする構成になっています。HoloDeskWidget固有のファイルは`variants/holo/`以下にあります(VTDeskWidgetは`variants/vt/`)。

- `start_widget_holo.py` — HoloDeskWidgetの起動エントリポイント(多重起動チェック→`deskwidget_core`のウィジェットをmainloop実行)
- `deskwidget_core/` — 両アプリ共通のエンジンパッケージ(常駐・透過表示・ドラッグ移動対応のWin32レイヤードウィンドウ実装)
  - `widget.py` — ウィンドウ本体(描画・イベント処理)
  - `config.py` — ウィンドウ既定値・`settings.json`の読み書き
  - `talents.py` — `productions/index.json`とプロダクションごとのタレント一覧JSONの読み込み
  - `youtube.py` — チャンネル解決・配信状況の取得(YouTube内部API/innertube経由)
  - `theme.py` / `strings.py` / `fonts.py` — 配色・多言語文字列・フォント
  - `layout.py` / `grid_layout.py` — ボタン列・タブ・タレントグリッドの配置計算
  - `paths.py` — パス解決とログ出力(サイズ上限付きローテーション)
  - `single_instance.py` — 多重起動防止(Win32ミューテックス)
  - `appconfig.py` — アプリ名・配色・バージョンなど、variantごとに異なる値の受け皿
  - `tray.py` — システムトレイアイコン(Shell_NotifyIcon、ctypesで直接実装)
  - `stream_log.py` — 配信開始・終了イベントの記録・読み込み(`stream_history.jsonl`)
- `variants/holo/` — HoloDeskWidget固有のデータ・ドキュメント
  - `profile.py` — アプリ名・アクセントカラー・バージョンなど`appconfig`に渡す設定値
  - `version.py` — バージョン番号(右クリックメニューに表示)
  - `productions/index.json` / `productions/hololive.json` — 表示対象タレントの一覧(hololive単独プロダクション)
  - `docs/Readme.html` / `docs/Readme.en.html` — エンドユーザー向け使い方ガイド(リリースzipに同梱)
  - `docs/screenshots/` — 上記ガイドに埋め込むスクリーンショット・GIF
- `start_widget_holo.bat` — ネイティブ版(Holo)の起動ランチャー
- `build_widget.bat holo|vt` — PyInstallerで指定したvariantのexeをビルド
- `find_python.bat` — `start_widget_holo.bat`/`build_widget.bat`共通のPython検出スクリプト
- `release_widget.bat holo|vt` — ビルド＋配布用zip(`release/<AppName>-v<version>.zip`)の作成
- `tools/capture_screenshots.py` / `capture_screenshots.bat` — `variants/holo/docs/screenshots/`内の画像・GIFを実際のウィジェットを操作して再撮影する開発者向けツール

## セットアップ

Python 3.10+ と以下の依存パッケージが必要です。

```bash
pip install -r requirements.txt
```

## 起動

### 開発環境から起動

```bash
start_widget_holo.bat
```

`start_widget_holo.bat` はPythonインストール先の自動検出、`pythonw.exe`の存在確認、Pillowの導入チェックを行った上でウィジェットを起動します。エラー発生時は `variants/holo/start_widget.log` を確認してください。

### 配布版(リリースzip)から起動

`release/HoloDeskWidget-v<version>.zip` を展開し、`HoloDesk Widget.exe` をダブルクリックするだけで起動します。Pythonのインストールなど事前準備は不要です。初回起動時にWindows SmartScreenの警告が出る場合は「詳細情報」→「実行」を選んでください(署名されていない実行ファイルのための一般的な警告です)。

## バージョン

現在のバージョン: **1.0.2**

`variants/holo/version.py` の `__version__` が唯一の管理箇所です(ウィジェットの右クリックメニューにも表示されます)。リリース時はこの値を手動で更新してください。`release_widget.bat holo` はこの値を読み取り、`build_widget.bat holo`(PyInstaller)でexeをビルドした上で、exe・`productions/`・`docs/Readme*.html` をまとめた `release/HoloDeskWidget-v<version>.zip` を作成します。

## リリース手順

1. バージョンを上げる場合は `variants/holo/version.py` の `__version__` を更新し、`variants/holo/README.md` の `現在のバージョン: **x.y.z**`、`variants/holo/README.en.md` の `Current version: **x.y.z**`、`variants/holo/docs/Readme.html` / `docs/Readme.en.html` に埋め込まれた同じバージョン文字列も合わせて更新します。5箇所まとめて更新するには以下を使用します。
   ```bash
   python .claude/skills/release/scripts/bump_version.py holo <old_version> <new_version>
   ```
2. `release_widget.bat holo` を実行します。内部で `build_widget.bat holo`(PyInstaller、要インストール)を呼び出して `dist/HoloDesk Widget.exe` をビルドし、exe・`productions/`・`docs/Readme.html`・`docs/Readme.en.html` を `release/HoloDeskWidget-v<version>.zip` にまとめます(`settings.json`やログなどの実行時生成ファイルは含まれません)。VTDeskWidget側は同じ手順を `vt` 引数で実行します(`.claude/skills/release/SKILL.md`参照)。
3. 生成された `release/HoloDeskWidget-v<version>.zip` を配布します。`build/`・`dist/`・`release/` はgit管理対象外です。

## タレント一覧の更新

`variants/holo/productions/hololive.json` に `{"name": "...", "unit": "...", "slug": "...", "channel_url": "..."}` の形式でエントリを追加/編集します。起動時は常にhololive公式サイトのタレントページからチャンネルの自動解決を試み、失敗したときだけ`channel_url`(未指定なら`https://www.youtube.com/@<slug>`)にフォールバックします。自動解決が失敗しやすいタレント(卒業済みなど)では`channel_url`を指定しておくと安定します。

## 注意

配信中判定はYouTubeの内部API(innertube)経由でチャンネルの「Live」タブを取得して行っており、非公式な方法です。YouTube側の仕様変更で動作しなくなる可能性があります。

## ライセンス

[MIT License](../../LICENSE)。ただし本ライセンスはソースコードにのみ適用され、「hololive」「hololive production」および各タレント名などの第三者の商標・名称の権利を許諾するものではありません。
