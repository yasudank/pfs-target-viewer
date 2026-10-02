# PFS Target Viewer コードレビュー

- **実施日**: 2026-10-02
- **対象コミット**: `711b327`（作業ツリーはクリーン、`HEAD` == `origin/main`）
- **対象ファイル**: `pfs_target_viewer/app.py`、`pfs_target_viewer/static/js/app.js`、`pfs_target_viewer/templates/index.html`、`build_pfs_database.py`、`export_pfs_targets.py`、`download_data.py`、`run_pfs.py`
- **方法**: 差分が無いためファイル全体のレビュー。各指摘はコードを読んだうえで実際に再現・計測して検証した。

## 指摘一覧

| # | 分類 | 箇所 | 概要 |
| --- | --- | --- | --- |
| 1 | 正しさ | `app.py:1835` | SQL キャッシュのキーが `LIMIT` を無視し、別クエリの結果を返す |
| 2 | 正しさ | `app.py:1880` | `LIMIT` / `OFFSET` が実行時に捨てられ、全件がメモリに載る |
| 3 | データ破壊 | `build_pfs_database.py:523` | DB 再構築でファイルパスが全消去される |
| 4 | データ破壊 | `export_pfs_targets.py:423` | `--skip-fits` / `--skip-png` が既存のパスを消す |
| 5 | データ破壊 | `export_pfs_targets.py:362` | 出力ファイル名と `UPDATE` 条件に `combination` が無い |
| 6 | 表示 | `app.js:3165` | RA / Dec がちょうど 0 のとき「-」と表示される |
| 7 | 表示 | `app.js:606` | ヒット 0 件のクエリで前回のマーカーが残る |
| 8 | 表示 | `app.js:1653` | 読み込み中に変更したフィルタが送信されない |
| 9 | セキュリティ | `app.js:1779` | `obCode` が未エスケープでインライン `onclick` に埋め込まれる |
| 10 | セキュリティ | `app.py:1269` | `survey` パラメータを検証前にキャッシュパスへ連結している |
| 11 | 堅牢性 | `app.py:1402` | SQL キャッシュに件数上限はあるがメモリ上限が無い |
| 12 | 死にコード | `app.js:429` | `c.primary_key` を読むが API は `pk` を返す |
| 13 | 死にコード | `app.js:534` | `data.estimated_rows` を読むが API は返さない |
| 14 | 性能 | `export_pfs_targets.py:84` | `bin_spectrum` が O(nBins×N) |
| 15 | 性能 | `app.py:511` | データセット切り替え時にディスクキャッシュが使われない |
| 16 | 潜在 | `export_pfs_targets.py:200` | `--ob-code` がフォールバック経路で無視される |
| 17 | 軽微 | `app.js:2977` | カットアウトの Object URL が解放されない |

---

## 1. SQL キャッシュのキーが `LIMIT` を無視する（最優先）

[app.py:1835](pfs_target_viewer/app.py#L1835) の `cache_key_source = strip_trailing_order_by(optimized_sql)` は、先頭レベルの `ORDER BY` が見つかるとそこから文字列の末尾までを切り落とす。末尾の `LIMIT` / `OFFSET` も一緒に消える。

実際に関数を抽出して実行した結果:

```
'SELECT * FROM target_summary ORDER BY bestRedshift DESC LIMIT 10'
  -> 'SELECT * FROM target_summary'

'SELECT * FROM target_summary ORDER BY catId ASC LIMIT 5000'
  -> 'SELECT * FROM target_summary'

'SELECT * FROM target_summary LIMIT 10'
  -> 'SELECT * FROM target_summary LIMIT 10'

'SELECT * FROM target_summary WHERE catId=10094 ORDER BY objId LIMIT 25 OFFSET 50'
  -> 'SELECT * FROM target_summary WHERE catId=10094'
```

上の 2 つは同じキャッシュキーに衝突する。後から実行したクエリが、先に実行したクエリの結果セットをそのまま受け取る。

ソート順をキーから除くこと自体は、全件をメモリ上で並べ替える設計なので意図どおり。問題は `LIMIT` が行集合そのものを変えるのに一緒に除かれている点にある。

## 2. 同じ関数のせいで `LIMIT` が実行時にも捨てられる

[app.py:1880](pfs_target_viewer/app.py#L1880) は `unordered_sql = strip_trailing_order_by(executable_sql)` をそのまま `cur.execute()` に渡す。ユーザが `ORDER BY ... LIMIT 100` と書いても全件スキャンになり、レスポンスの `total` も実際の行数ではなく全件数になる。`ORDER BY` が無い場合は `LIMIT` が保持されるため、挙動が非一貫である。

指摘 1 と合成すると影響が大きい。`SELECT * FROM redshift_candidates ORDER BY redshift LIMIT 100` のつもりのクエリが 238 万行を Python の dict として展開する。

### 推奨する修正

`strip_trailing_order_by` を「`ORDER BY` 句だけを除去し、後続の `LIMIT` / `OFFSET` は保持して連結し直す」実装に変更する。これで指摘 1 と 2 の両方が同時に解消する。

## 3. DB 再構築でファイルパスが全消去される

[build_pfs_database.py:523](build_pfs_database.py#L523) の `populate_target_summary()` は `DELETE FROM target_summary` の後、`has_fits, fits_path, has_png, png_path` に `0, NULL, 0, NULL` をハードコードで入れ直す。

```sql
    t.bestSubClass, t.hasSolution,
    0, NULL, 0, NULL
FROM targets t
```

`export_pfs_targets.py` が記録したパスは DB を再構築するたびに失われる。現状 `--skip-target-summary` フラグが唯一の回避策になっている。

再構築後もファイル情報を保つには、再投入後に既存のパスを戻すか、ファイル情報を別テーブルに分離して `target_summary` の再構築対象から外すのが素直である。

## 4. `--skip-fits` / `--skip-png` が既存のパスを消す

[export_pfs_targets.py:423](export_pfs_targets.py#L423) 付近で、`--skip-fits` を指定すると `saved_fits_rel` が `None` のままになり、そのまま `db_updates` に積まれる。

```python
db_updates.append((
    1 if saved_fits_rel else 0,
    saved_fits_rel,
    ...
```

この `UPDATE` は `has_fits = 0, fits_path = NULL` を書き込むので、PNG だけ再生成するつもりの実行が、処理対象行の FITS パスを消す。スカイポジション API にはファイルシステムへのフォールバックが無いため、「FITS あり」フィルタが空になる。

スキップされた種別はタプルから外し、`UPDATE` 文を動的に組み立てるべきである。

## 5. 出力ファイル名と `UPDATE` 条件に `combination` が無い

[export_pfs_targets.py:362](export_pfs_targets.py#L362):

```python
base_name = f"{obCode}_{catId}_{objId}" if obCode else f"{catId}_{objId}"
```

DB 更新側も同様:

```sql
UPDATE target_summary
SET has_fits = ?, fits_path = ?, has_png = ?, png_path = ?
WHERE catId = ? AND objId = ?;
```

`targets` の主キーは `(catId, objId, combination)` である。実測では 217,176 行に対して distinct `(catId, objId)` は 200,724 で、**16,452 行**が別の行と `(catId, objId)` を共有する。これらは同じファイル名に書き出されて一方が他方を上書きし、DB 上は両方の行が同じファイルを指す。

ファイル名と `WHERE` 句の双方に `combination` を含める必要がある。

## 6. RA / Dec がちょうど 0 のとき「-」と表示される

[app.js:3165](pfs_target_viewer/static/js/app.js#L3165):

```javascript
${t.ra ? t.ra.toFixed(6) : "-"}, ${t.dec ? t.dec.toFixed(6) : "-"}
```

`0` は falsy なので、赤道付近のフィールドで座標が消える。同じファイルの [app.js:1785](pfs_target_viewer/static/js/app.js#L1785) では `typeof t.ra === "number"` と正しく判定しており、非一貫である。

## 7. ヒット 0 件のクエリで前回のマーカーが残る

[app.js:606](pfs_target_viewer/static/js/app.js#L606):

```javascript
if (data.sky_targets && data.sky_targets.length > 0) {
  state.allSkyTargets = data.sky_targets;
}
```

この条件は「帯域節約のため送らなかった」（`skip_sky` によるページ送り・ソート時）と「本当に 0 件だった」を区別できない。結果として、プロット対象が 0 件のクエリでも前のクエリのマーカーが「All Filtered」のラベルのまま地図に残る。

レスポンス側で「送っていない」ことを明示するフラグ（例: `sky_targets: null` と `[]` の区別）を設けるのが確実である。

## 8. 読み込み中に変更したフィルタが送信されない

[app.js:1653](pfs_target_viewer/static/js/app.js#L1653):

```javascript
async function fetchTargets() {
  if (state.loading) return;
```

早期復帰するだけで再キューしない。遅いフェッチの最中にクリックしたフィルタは、UI 上は適用済みに見えて実際には送信されない。保留フラグを立てて `finally` で再実行するか、`AbortController` で進行中のリクエストを中断して投げ直すのが妥当である。

## 9. `obCode` が未エスケープでインライン `onclick` に埋め込まれる

[app.js:1779](pfs_target_viewer/static/js/app.js#L1779):

```javascript
onclick="openImagePreview(${t.catId}, '${t.objId}', '${t.obCode || ""}')"
```

この文字列は `innerHTML` に渡される。`obCode` にアポストロフィが 1 つ含まれるだけでハンドラが壊れ、注入点にもなる。`obCode` はパイプライン由来で完全に信頼できる値ではない。

インライン `onclick` をやめて `addEventListener` と `dataset` 属性に移すか、少なくとも HTML 属性とし JavaScript 文字列の両方をエスケープする。

## 10. `survey` パラメータを検証前にキャッシュパスへ連結している

[app.py:1269](pfs_target_viewer/app.py#L1269):

```python
survey_key = survey.lower().strip()
cache_prefix = f"cutout_{survey_key}_{ra:.5f}_{dec:+.5f}_{fov:.5f}_{width}x{height}"
cache_img = os.path.join(CUTOUT_CACHE_DIR, f"{cache_prefix}.jpg")
```

`SURVEY_HIPS_MAP` による検証は [app.py:1337](pfs_target_viewer/app.py#L1337) まで行われない。書き込みは検証後なので実害は限定的で、必須のサフィックスのせいで任意ファイルの読み出しも実質困難だが、パスを組む前に検証する順序へ直すべきである。

## 11. SQL キャッシュにメモリ上限が無い

[app.py:1402](pfs_target_viewer/app.py#L1402) の `SqlQueryCache` は `max_entries=8`、TTL 1800 秒で件数は制限されるが、1 エントリあたりのサイズは制限されない。指摘 2 と組み合わさると、数エントリでプロセスのメモリを使い切り得る。15 秒のクエリタイムアウト（[app.py:303](pfs_target_viewer/app.py#L303)）が事実上唯一の歯止めになっている。

行数または概算バイト数に基づく上限を設け、超えた場合はキャッシュせずストリーミングで返すのが安全である。

## 12 / 13. 動いていないコード

- [app.js:429](pfs_target_viewer/static/js/app.js#L429) が `c.primary_key` を読むが、API は [app.py:1770](pfs_target_viewer/app.py#L1770) で `"pk"` を返す。主キーのハイライトは一度も発火しない。
- [app.js:534](pfs_target_viewer/static/js/app.js#L534) が `data.estimated_rows` を読むが、`/api/sql/validate` はこれを返さない。計算済みの `query_plan` は使われずに捨てられている。

## 14. `bin_spectrum` が O(nBins×N)

[export_pfs_targets.py:84](export_pfs_targets.py#L84):

```python
for i in range(nBins):
    sel = finite & (binIndex == i)
```

ビンごとに全長の真偽マスクを作り直している。PFS のスペクトルは 13,293 点、`bin_width=0.5` でビン数は約 1,760 なので、1 スペクトルあたり約 2,300 万回の論理演算になる。`np.bincount` を重み付きで 3 回呼べば 1 パスで同じ結果が得られる。20 万件規模のエクスポートでは時間と分の差になる。

## 15. データセット切り替え時にディスクキャッシュが使われない

[app.py:511](pfs_target_viewer/app.py#L511) のディスクキャッシュ読み出しは `if not force and ...` で守られているが、データセット切り替え時の呼び出しは [app.py:228](pfs_target_viewer/app.py#L228) で常に `force=True` である。そのため DB ごとのディスクキャッシュ（コミット `a8bca3c` で追加）が切り替え時に一度も使われず、毎回 DB から再構築される。

`force` の意味を「メモリキャッシュを破棄する」に限定し、ディスクキャッシュの有効性は `mtime` 比較のみで判定すればよい。

## 16. `--ob-code` がフォールバック経路で無視される

[export_pfs_targets.py:200](export_pfs_targets.py#L200) で `--ob-code` は `has_view` 分岐の中でのみ `WHERE` に追加される。フォールバック側では引数が受理されて黙って無視され、カタログ全体が処理対象になる。

さらにフォールバック側は次のように書いている:

```sql
NULL AS bestRedshift, NULL AS bestRedshiftError, NULL AS bestVelocity, ...
FROM targets t
```

`bestRedshift`、`bestVelocity`、`bestSubClass` は `targets` テーブルに実在する列であり、`NULL` で潰す理由が無い。`fiber_configs` 由来で本当に取得できないのは `obCode`、`targetTypeName`、`fiberStatusName`、`ra`、`dec` だけである。

現在は `build_pfs_database.py:249` が `CREATE VIEW IF NOT EXISTS v_target_summary AS SELECT * FROM target_summary` で互換ビューを残しているため、このフォールバック経路には到達しない。潜在的な欠陥として記録する。

## 17. Object URL が解放されない

[app.js:2977](pfs_target_viewer/static/js/app.js#L2977) でカットアウト画像の `URL.createObjectURL(blob)` を作るが `revokeObjectURL` を呼んでいない。長時間の閲覧でリークする。

---

## 問題なしと確認した箇所

- `export_pfs_targets.py` の `mask & bad_mask != 0` の演算子優先順位。Python では `&` が `!=` より強く結合するため意図どおり。
- `build_spatial_clauses`（サーバ側）と `isTargetInSpatialFilter`（クライアント側）双方の RA ラップアラウンド処理。
- スカイキャッシュの高速経路と `GZipMiddleware` の二重 gzip。Starlette は `Content-Encoding` が設定済みならスキップする。
- SQL エディタの安全性。キーワードのブロックリストに加えて `mode=ro` 接続が実質的な防御になっており、複文チェックも引用符除去後に行っている。
- `index.html` に対する全 `getElementById` 参照とインライン `onclick` ハンドラの整合性。欠落した ID やグローバルでないハンドラは無い。
- `load_or_build_master_sky_cache` の二重チェックロックと `mtime` ベースの無効化（指摘 15 の `force` の扱いを除く）。

---

## 推奨する修正順序

| 順序 | 対象 | 理由 |
| --- | --- | --- |
| 1 | 指摘 1・2（`strip_trailing_order_by`） | 同一関数が原因で、誤った結果とメモリ枯渇の両方を引き起こす |
| 2 | 指摘 3・4・5（データ破壊系） | 既存の DB とエクスポート済みファイルに影響が残っている可能性がある |
| 3 | 指摘 9・10・11（セキュリティ・堅牢性） | 外部公開するなら着手前に必須 |
| 4 | 指摘 6・7・8（表示の不具合） | 利用者が誤ったデータを読む恐れがある |
| 5 | 指摘 12〜17（死にコード・性能・軽微） | 影響は限定的 |

指摘 5 については、既存の `extracted_targets` 以下に `combination` 違いで取りこぼされたターゲットが無いか、修正前に棚卸しすることを推奨する。
