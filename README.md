# RTSagents

[English] | [日本語](#日本語)

Visualize your coding flow as an RTS-style simulation. Sync with Codex CLI sessions to see your agent's thoughts and actions as units moving on a vector-scan display.

## Features
- **Vector-Scan Aesthetic**: Retro-style graphics inspired by classic arcade systems.
- **Real-time Sync**: Uses WebSocket to stream events from local CLI logs directly to the browser.
- **RTS-style Visualization**: Actions like `plan`, `read`, `edit`, and `test` correspond to unit movements and effects.
- **Zero Dependencies**: Python scripts use standard libraries only. No `pip install` required.

## Quick Start (WSL / Linux)

1. **Start the WebSocket Server** (Terminal A)
   ```bash
   python3 ws_server.py --tail events.ndjson --verbose
   ```

2. **Start the Bridge** (Terminal B)
   ```bash
   # Automatically follows the latest Codex CLI session
   python3 codex_cli_bridge.py --log events.ndjson --follow-latest --verbose
   ```

3. **Open the Viewer**
   Open `index.html` in your browser. Click **WS: ON** to connect.

## Support

If you find this project useful or entertaining, consider supporting the development:
[☕ Buy Me a Coffee](https://buymeacoffee.com/kgninja)

## License
MIT License.

---

<a name="日本語"></a>
# RTSagents (日本語)

コーディングのフローをRTS（リアルタイムストラテジー）風のシミュレーションとして可視化します。Codex CLI のセッションと同期し、エージェントの思考や行動をベクタースキャン風デフォルメで描画します。

## 特徴
- **ベクタースキャン・デザイン**: クラシックなオシロスコープやアーケードゲームを彷彿とさせるレトロな外観。
- **リアルタイム同期**: WebSocket を使用して、ローカルの CLI ログからイベントをブラウザへ即座に転送。
- **RTS風の可視化**: `plan`, `read`, `edit`, `test` などのアクションがユニットの移動や発光エフェクトに対応。
- **依存ライブラリなし**: Python スクリプトは標準ライブラリのみを使用します。`pip install` は不要です。

## クイックスタート (WSL / Linux)

1. **WebSocketサーバの起動** (Terminal A)
   ```bash
   python3 ws_server.py --tail events.ndjson --verbose
   ```

2. **ブリッジの起動** (Terminal B)
   ```bash
   # 自動的に最新の Codex CLI セッションを追跡します
   python3 codex_cli_bridge.py --log events.ndjson --follow-latest --verbose
   ```

3. **ビューアを開く**
   ブラウザで `index.html` を開きます。**WS: ON** ボタンを押すと接続されます。

## 支援について

このプロジェクトを気に入っていただけましたら、開発の支援をお願いします！
[☕ Buy Me a Coffee (kgninja)](https://buymeacoffee.com/kgninja)

## License
MIT License.
