# HoloDeskWidget / VTDeskWidget

[English](README.en.md) | 日本語

VTuberタレントの配信状況を常時表示するWindowsデスクトップウィジェットを、共通のエンジン(`deskwidget_core/`)から2種類のexeとしてビルドするモノレポです。

| Variant | ディレクトリ | 内容 |
|---|---|---|
| **HoloDeskWidget** | [`variants/holo/`](variants/holo/README.md) | hololive所属タレントのみを表示する単一プロダクション版 |
| **VTDeskWidget** | [`variants/vt/`](variants/vt/README.md) | hololive・にじさんじ・あおぎり高校など複数プロダクションをタブ切替で表示する版 |

機能・スクリーンショット・セットアップ手順・リリース手順など、アプリとしての詳細はそれぞれのREADME(上表のリンク先)を参照してください。このファイルはリポジトリ全体の構成のみを説明します。

## 構成

- `deskwidget_core/` — 両アプリ共通のエンジンパッケージ。プロダクションが1つしかないvariant(Holo)では、複数プロダクション向けのタブ切替UI(タブ列・プロダクション選択ボタン)は自動的に現れません。
- `variants/holo/` / `variants/vt/` — 各アプリ固有のデータ(タレント一覧JSON・バージョン・アクセントカラーなどの`profile.py`)とエンドユーザー向けドキュメント。
- `start_widget_holo.py` / `start_widget_vt.py` — 各アプリの起動エントリポイント。`start_widget_holo.bat` / `start_widget_vt.bat` は開発環境からの起動ランチャーです。
- `build_widget.bat holo|vt` / `release_widget.bat holo|vt` — ビルド・リリースzip作成スクリプト(variant名を引数に取ります)。詳細は`.claude/skills/release/SKILL.md`を参照。
- `tools/` — 開発者向けツール(現状Holo variant向けのスクリーンショット撮影スクリプトのみ)。
- `tests/` — `deskwidget_core`のロジック部分(設定の読み書き・配信履歴・talents/production一覧・YouTube応答のパース・レイアウト計算・世界時計のDST計算・多言語文字列の整合性)に対するpytestユニットテスト。Tkinter描画やWin32連携部分(`widget.py`本体・`rendering.py`・`tray.py`等)はGUI依存のため対象外です。

両アプリは独立にバージョン管理・リリースされます(`variants/holo/version.py` / `variants/vt/version.py`)。

## テスト

```bash
pip install -r requirements-dev.txt
pytest
```

## ライセンス

[MIT License](LICENSE)。ただし本ライセンスはソースコードにのみ適用され、本アプリが参照する各タレント・プロダクションの商標・名称の権利を許諾するものではありません。
