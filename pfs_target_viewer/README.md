# PFS Target & Spectrum Viewer

Subaru Prime Focus Spectrograph (PFS) のコアッド観測メタデータ（`pfs_metadata.sqlite3`）および生スペクトルデータ（`extracted_targets/` の FITS / PNG）を可視化・検索・分析するためのスタンドアロン Web アプリケーションです。

---

## 主な特徴

- 🚀 **PFS パイプライン非依存 (Pipeline-Free)**
  - `lsst-scipipe` や `pfs_pipe2d` 等の重厚な専用環境を一切必要とせず、標準的な Python 3.10+ 環境（`astropy`, `fastapi`, `uvicorn`, `numpy` のみ）で完全に動作します。
  - 任意のマシン（個人のラップトップ、解析ワークステーション、クラウドサーバー等）へフォルダごとコピーして即座に同じ環境を再現できます。
- 🔍 **Search, Filter & High-Performance Pagination**
  - Instant search by `obCode` (substring) or `objId` (64-bit ID exact match).
  - Catalog ID (`catId`) dropdown filtering with dynamic target count badges.
  - Target classification filter pills (`GALAXY`, `QSO`, `STAR`).
  - Redshift range filtering ($z_{min} \le z \le z_{max}$, e.g. $z \ge 6.0$).
  - Multi-column sorting by Redshift, Target ID, `catId`, or classification probabilities.
  - 13,000 件以上の天体をスムーズに閲覧できる高速ページネーション（10 / 25 / 50 / 100 件切替）
- 🌌 **Celestial Sky Distribution (RA / Dec)**
  - Dual-scope celestial map toggle: `📄 Page` (current table page targets) vs. `🌐 All Filtered` (all matching targets across survey, up to tens of thousands).
  - High-performance WebGL rendering (`scattergl`) for full survey distribution, with prominent "Current Page Focus" overlay rings highlighting the active table page.
  - Astronomical coordinate convention with reversed RA axis (`autorange: 'reversed'`).
  - Interactive zooming, panning, reset controls, and collapsible card toggle.
  - Clicking any target marker instantly launches the PNG spectrum quick-look, with seamless one-click transition to the interactive viewer with preserved estimated redshift.
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
├── README.md              # 本ドキュメント
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
cd /mnt/ugnas/work/LSST/PFS/pfs_target_viewer
./run_viewer.sh
```

ポート番号やホストを変更したい場合：
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

### 方法 3: `uv` を使用した超高速セットアップ

`uv` がインストールされている環境では、わずか数秒でセットアップできます：

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

### 2. リモートサーバー（例: `pgx` などの計算機）で動かしている場合
お使いのローカル PC から SSH ポートフォワーディングで接続します：

```bash
# ローカル PC のターミナルで実行
ssh -L 8090:localhost:8090 yasuda@<remote-host>
```
接続後、ローカル PC のブラウザで `http://localhost:8090` を開いてください。

---

## コマンドライン引数

`app.py` は以下の起動オプションに対応しています：

```bash
python app.py [-h] [--host HOST] [--port PORT] [--db DB] [--data-dir DATA_DIR]
```

- `--host`: バインドするホスト名（デフォルト: `0.0.0.0`）
- `--port`: リッスンするポート番号（デフォルト: `8090`）
- `--db`: SQLite データベースファイルへのパス（デフォルト: `../pfs_metadata.sqlite3`）
- `--data-dir`: FITS / PNG が配置されたディレクトリ（デフォルト: `../extracted_targets`）

---

## 画面の主な使い方

1. **クイック統計バッジ（画面最上部）**
   - リポジトリ内の総天体数、および Galaxy / QSO / Star の内訳を表示します。
2. **検索 & フィルターバー**
   - **Search**: `rubin_0001` や `313875415099768848` などの obCode または Target ID で即座に検索できます。
   - **Class**: `All`, `Galaxy`, `QSO`, `Star` のピルボタンで分類別にワンクリック抽出。
   - **Redshift**: 最小 $z$ と最大 $z$ を入力して赤方偏移の範囲指定検索（例: $z \ge 6.0$）。
   - **Sort**: 赤方偏移の高い順、低い順、Target ID 順、各分類確率順等でソート。
3. **ターゲット一覧テーブル**
   - サムネイル画像をクリックすると、高解像度の PNG プロットがモーダルで拡大表示されます。
   - 各行の **「📋 Details」** ボタンをクリックすると、ソルバー結果、全候補解、輝線・吸収線の測定パラメータがタブ形式で表示されます。
   - **「📈 Plot」** ボタンをクリックすると、FITS 生データを読み込んでインタラクティブなスペクトルビューアが起動します。
   - **「💾 FITS」** ボタンから生 FITS ファイルを直接ダウンロード可能です。
4. **インタラクティブ・スペクトルビューア**
   - **ズーム / パン**: グラフ上をドラッグして任意の波長領域を拡大・観察できます（ダブルクリックでリセット）。
   - **Binning**: プルダウンでビン幅（Raw, 0.2 nm, 0.5 nm, 1.0 nm, 2.0 nm）を動的に切り替えます。
   - **Lines**: チェックボックスで輝線（青）や吸収線（赤）の表示をオン/オフできます。
   - **Adjust $z$**: スライダーまたは数値入力で赤方偏移を変更すると、輝線・吸収線の縦線がリアルタイムで追従します。
