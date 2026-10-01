[English](README.md) | **日本語**

---

# PFS Target & Spectrum Viewer (Web Application)

Subaru Prime Focus Spectrograph (PFS) のコアッド観測メタデータ（`pfs_metadata.sqlite3`）および生スペクトルデータ（`extracted_targets/` の FITS / PNG）を可視化・検索・分析するためのスタンドアロン Web アプリケーションです。

---

## 主な特徴

- 🚀 **PFS パイプライン非依存 (Pipeline-Free) & 大規模データセット完全対応**
  - `lsst-scipipe` や `pfs_pipe2d` 等の重厚な専用環境を一切必要とせず、標準的な Python 3.10+ 環境（`astropy`, `fastapi`, `uvicorn`, `numpy` のみ）で完全に動作します。
  - 20万件規模の大規模カタログやディレクトリシャーディング（`fits/NNN/`, `png/NNN/`）にネイティブ対応。
  - 任意のマシン（個人のラップトップ、解析ワークステーション、クラウドサーバー等）へフォルダごとコピーして即座に同じ環境を再現できます。
- 🔍 **柔軟な検索・フィルタリング・サーバーサイドクエリキャッシュ**
  - **全件対象の即座ソート**: サーバー内インメモリクエリキャッシュ（`SQL_CACHE`）により、フィルター条件に合致する全天体（数万〜20万件）を対象にした赤方偏移（Redshift）、後退速度（Velocity $v=c \cdot z$）、Target ID、`catId`、分類確率などによるソートをサブミリ秒で実行。
  - `obCode` や 64-bit `objId` によるキーワード検索（部分一致対応）。
  - カタログID (`catId`) によるサンプルの絞り込み（カタログ毎の件数バッジ付き）。
  - 天体分類（`ALL`, `GALAXY`, `QSO`, `STAR`）による絞り込み。
  - 赤方偏移範囲（$z_{min} \le z \le z_{max}$）による絞り込み。
  - 「With Spectra」チェックボックス（FITS / PNG 抽出済み天体のみ表示）。
  - 表示カラムカスタマイズ（Column Customizer）。
  - 10 / 25 / 50 / 100 件切替の高速ページネーション。
- 🌌 **モルワイデ全天球プロット & 視野連動絞り込み (Mollweide Sky Map)**
  - モルワイデ楕円図法（2:1 アスペクト比維持）による全天 RA / Dec 投影表示（天文学の東が左慣例）。
  - **中央子午線（RA）回転コントロール**: スライダー（$0^\circ \sim 360^\circ$）またはプリセットボタン（$0^\circ, 60^\circ, 120^\circ, 180^\circ, 240^\circ, 300^\circ$）で瞬時に視野を回転。
  - **「Filter Table by View」視野連動絞り込み**: 天球マップ上で関心のある天域にズーム・パンし、ボタン 1 つで現在の表示視野（バウンディングボックス）内の天体のみにテーブルを空間絞り込み。
  - **デュアル表示スコープ & フォーカスリング**: `📄 Page`（現在テーブル表示中の天体）と `🌐 All Filtered`（全天体・20万件以上を WebGL `scattergl` で高速描画）を切り替え可能。
  - **データセット連動の超高速全天球座標キャッシュ**: 起動時にデータセット側ディレクトリに `.{dbname}_sky_cache.json.gz` を自動生成し、数ミリ秒でのロードおよび HTTP ETag (304) / GZip 配信を実現。
- 💻 **高度な SQL クエリ実行モード & スキーマエクスプローラー**
  - Standard Filters モードに加え、自由な SQL を記述できる SQL モードを搭載。
  - スキーマエクスプローラー（テーブル一覧、カラム型、レコード件数の確認）と連動した編集エリア。
  - **天文学向け拡張 SQL 関数**:
    - `CONE_SEARCH(ra, dec, center_ra, center_dec, radius_arcsec)`: 高速コーンサーチ
    - `BOX_SEARCH(ra, dec, ra_min, ra_max, dec_min, dec_max)`: 矩形領域検索
    - 数学関数: `SQRT`, `POW`, `COS`, `SIN`, `RADIANS`, `DEGREES`, `LOG10`, `LN`, `EXP`
  - プリセット SQL テンプレート（コーンサーチ、高赤方偏移クエーサー、輝線フラックス順、ソルバー警告等）。
  - `ts.combination` や JOIN 先テーブルの任意カラムを結果テーブルに動的展開。
- 🌌 **光学画像カットアウト連携 (HSC & Pan-STARRS)**
  - 詳細モーダル内で Hyper Suprime-Cam (HSC) SSP の光学 3 色合成カラー画像を自動取得・表示。
  - HSC 未撮影領域やダミー白色フレームを自動判定し、Pan-STARRS1 (PS1) カラーカットアウトへ自動フォールバック。
- 🖼️ **PNG スペクトル画像クイックルック & 連続閲覧 (Sequential Browsing)**
  - サムネイルまたは天球マップから瞬時に高解像度 PNG スペクトル画像モーダルを起動。
  - キーボードの矢印キー（`←` / `→`）または左右のフローティング矢印ボタンで、モーダルを開いたまま次々と前後の天体を連続プレビュー。
  - ページ末尾到達時に自動で次ページを取得し、シームレスな連続閲覧を維持。
  - モーダル内の「Open Interactive Spectrum」から推定赤方偏移を引き継いでインタラクティブビューアへシームレスに遷移可能。
- 📊 **詳細パラメータの深層閲覧 (Deep Inspection)**
  - ソルバーエラー・警告フラグ (`solver_results`)
  - 赤方偏移候補一覧 (`redshift_candidates`: 各モデルの $z$, 誤差, 確率, reduced $\chi^2$, $p$-value 等)
  - 輝線・吸収線測定値 (`line_measurements`: 検出波長, フラックス, 等価幅 EW, $\sigma$ 等)
- 📈 **インタラクティブ FITS スペクトルビューア (Plotly.js)**
  - `pfsObject` FITS ファイルの生データをブラウザ上でインタラクティブに可視化（ズーム、パン、正確な波長・フラックスのホバー表示）。
  - クライアントサイドでの動的逆分散ビン幅調整（Raw, 0.2 nm, 0.5 nm, 1.0 nm, 2.0 nm）。
  - $1\sigma$ ノイズ帯およびバッドピクセルマスクのシェーディング表示。
  - 主要な輝線・吸収線のオーバーレイ（グラフのズーム時も波長位置に固定表示）：
    - **輝線**: Lyα, C IV, C III], Mg II, [O II], Hβ, [O III], Hα, [N II], [S II]
    - **吸収線**: Ca II H/K, G-band, Mg b, Na D
  - **リアルタイム Redshift スライダー**: スライダーをドラッグすると輝線・吸収線の位置がリアルタイムに追従し、目視での赤方偏移の同定・確認が可能。
  - 個別露出観測リスト（Visit, Arm, Spectrograph, 露出時間）の表示。
  - FITS 生ファイルおよび PNG 画像の直接ダウンロード。

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

## コマンドライン引数 / データディレクトリの指定

`pfs_metadata.sqlite3` と `extracted_targets/` が存在するディレクトリを直接指定して起動できます。

```bash
# 方法 1: 位置引数でディレクトリを指定（推奨・最もシンプル）
./run_viewer.sh /path/to/dataset
python app.py /path/to/dataset

# 方法 2: --dir (-d) オプションで指定
./run_viewer.sh --dir /path/to/dataset
python app.py -d /path/to/dataset

# 方法 3: 環境変数で指定
export PFS_DIR=/path/to/dataset
./run_viewer.sh
```

### 引数一覧

```bash
python app.py [-h] [-d OPT_DIR] [--host HOST] [--port PORT] [--db DB] [--data-dir DATA_DIR] [target_dir]
```

- `target_dir` (位置引数): `pfs_metadata.sqlite3` と `extracted_targets/` が存在するディレクトリパス（省略時はデフォルトで `..`）
- `-d, --dir, --dataset-dir`: `pfs_metadata.sqlite3` と `extracted_targets/` が存在するディレクトリパス
- `--host`: バインドするホスト名（デフォルト: `0.0.0.0`）
- `--port`: リッスンするポート番号（デフォルト: `8090`）
- `--db`: SQLite データベースファイルへの個別明示パス（個別指定時に `--dir` より優先）
- `--data-dir`: `extracted_targets` ディレクトリへの個別明示パス（個別指定時に `--dir` より優先）
