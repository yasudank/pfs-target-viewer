[English](README.md) | **日本語**

---

# PFS Target & Spectrum Viewer (Web Application)

Subaru Prime Focus Spectrograph (PFS) のコアッド観測メタデータ（`pfs_metadata.sqlite3`）および生スペクトルデータ（`extracted_targets/` の FITS / PNG）を可視化・検索・分析するためのスタンドアロン Web アプリケーションです。

---

## 主な特徴

- 🚀 **PFS パイプライン非依存 (Pipeline-Free)**
  - `lsst-scipipe` や `pfs_pipe2d` 等の重厚な専用環境を一切必要とせず、標準的な Python 3.10+ 環境（`astropy`, `fastapi`, `uvicorn`, `numpy` のみ）で完全に動作します。
  - 任意のマシン（個人のラップトップ、解析ワークステーション、クラウドサーバー等）へフォルダごとコピーして即座に同じ環境を再現できます。
- 🔍 **柔軟な検索・フィルタリング・ページネーション**
  - `obCode` や `objId` によるキーワード検索（部分一致対応）
  - カタログID (`catId`) によるサンプルの絞り込み（カタログごとの件数も自動集計・表示）
  - 天体分類（GALAXY, QSO, STAR）による絞り込み
  - 赤方偏移範囲（$z_{min} \le z \le z_{max}$）による絞り込み
  - 赤方偏移順、確率順、ID順、`catId` 順などのソート
  - 13,000 件以上の天体をスムーズに閲覧できる高速ページネーション（10 / 25 / 50 / 100 件切替）
- 🌌 **天球上での位置表示 (Sky Distribution: RA / Dec)**
  - 表示範囲の切り替え（`📄 Page`: 現在のテーブルページ内の天体 / `🌐 All Filtered`: フィルター条件に合致する全天体（最大数万件））に対応。
  - 全天体表示時（All Filtered）には WebGL（`scattergl`）による高速レンダリングを行い、さらに現在テーブルに表示されている天体を「Current Page Focus（白枠リング）」としてハイライト重畳。
  - 天文学の慣例に基づき東が左となる軸反転（`autorange: 'reversed'`）対応。
  - 拡大縮小（マウスホイール・ドラッグ・ズームボタン）および視点リセットに対応。
  - マーカーをクリックすると、該当の PNG スペクトル画像プレビューが瞬時に開き、さらにそこから推定赤方偏移を引き継いでインタラクティブビューアーへスムーズに遷移可能。
- 📊 **詳細パラメータの深層閲覧 (Deep Inspection)**
  - ソルバーエラー・警告フラグ (`solver_results`)
  - 赤方偏移候補一覧 (`redshift_candidates`: 各モデルの $z$, 確率, reduced $\chi^2$, 残差等)
  - 輝線・吸収線測定値 (`line_measurements`: 検出波長, フラックス, 等価幅 EW, $\sigma$ 等)
- 📈 **インタラクティブ FITS スペクトルビューア (Plotly.js)**
  - `pfsObject` FITS ファイルの生データをブラウザ上でインタラクティブに可視化（ズーム、パン、正確な波長・フラックスのホバー表示）
  - クライアントサイドでの動的ビン幅調整（Raw, 0.2 nm, 0.5 nm, 1.0 nm, 2.0 nm）
  - 1$\sigma$ ノイズ帯およびバッドピクセルの表示トグル
  - 主要な輝線・吸収線（Lyα, C IV, Mg II, [O II], Ca II H/K, Hβ, [O III], Hα など）のオーバーレイ表示
  - **リアルタイム Redshift スライダー**: スライダーを動かすと輝線/吸収線の位置がリアルタイムに追従し、目視での赤方偏移の確認・検証が可能
  - 個別露出観測リスト（Visit, Arm, Spectrograph, 露出時間）の表示
  - FITS 生ファイルおよび PNG 画像の直接ダウンロード

---

## ディレクトリ構成

```text
pfs_target_viewer/
├── app.py                 # FastAPI バックエンドサーバー
├── requirements.txt       # 依存ライブラリ一覧
├── run_viewer.sh          # ワンクリック起動スクリプト (venv自動構築)
├── README.md              # ビューア詳細マニュアル (English)
├── README_ja.md           # 本ドキュメント (日本語)
├── templates/
│   └── index.html         # ダッシュボード HTML テンプレート
└── static/
    ├── css/
    │   └── style.css      # ダークテーマ・モダンデザイン CSS
    └── js/
        ├── app.js         # クライアントサイド UI & Plotly 制御
        └── plotly.min.js  # オフライン用 Plotly.js ライブラリ
```

---

## セットアップ手順

### 方法 1: 付属の起動スクリプトを使用（推奨・最も簡単）

付属の `run_viewer.sh` は、仮想環境 `.venv_viewer` の作成からライブラリのインストール、サーバー起動まで全自動で行います。

```bash
cd pfs_target_viewer
./run_viewer.sh
```

ポート番号を変更したい場合：
```bash
PORT=8088 ./run_viewer.sh
```

---

### 方法 2: 標準の `venv` と `pip` を使用して手動セットアップ

任意のマシン（Linux / macOS / Windows WSL）で手動で環境を構築する場合：

1. **仮想環境の作成**:
   ```bash
   cd pfs_target_viewer
   python3 -m venv .venv_viewer
   source .venv_viewer/bin/activate
   ```

2. **依存パッケージのインストール**:
   ```bash
   pip install --upgrade pip
   pip install -r requirements.txt
   ```

3. **サーバーの起動**:
   ```bash
   python app.py --port 8090
   ```

---

### 方法 3: `uv` を使用したセットアップ

```bash
cd pfs_target_viewer
uv venv .venv_viewer
uv pip install -r requirements.txt --python .venv_viewer
.venv_viewer/bin/python app.py --port 8090
```

---

## サーバーへのアクセス方法

### 1. ローカルマシンで動かしている場合
ブラウザで以下のアドレスを開きます：
```
http://localhost:8090
```

### 2. リモートサーバーで動かしている場合
お使いのローカル PC から SSH ポートフォワーディングで接続します：
```bash
ssh -L 8090:localhost:8090 user@<remote-host>
```
接続後、ローカル PC のブラウザで `http://localhost:8090` を開いてください。

---

## コマンドライン引数

```bash
python app.py [-h] [--host HOST] [--port PORT] [--db DB] [--data-dir DATA_DIR]
```

- `--host`: バインドするホスト名（デフォルト: `0.0.0.0`）
- `--port`: リッスンするポート番号（デフォルト: `8090`）
- `--db`: SQLite データベースファイルへのパス（デフォルト: `../pfs_metadata.sqlite3`）
- `--data-dir`: FITS / PNG が配置されたディレクトリ（デフォルト: `../extracted_targets`）
