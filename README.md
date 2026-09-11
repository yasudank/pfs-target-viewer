**English** | [日本語](README_ja.md)

---

# PFS Target & Spectrum Viewer

An integrated toolkit for aggregating Subaru Prime Focus Spectrograph (PFS) coadd observation metadata into an SQLite database, extracting target raw spectra (`pfsObject` FITS) and diagnostic plots (PNG), and interactively exploring targets via a standalone web application.

---

## 📁 Repository Structure

```text
pfs-target-viewer/
├── .gitignore
├── README.md                      # Project Guide (English)
├── README_ja.md                   # Project Guide (Japanese)
├── download_data.sh               # Hugging Face dataset download script (Bash)
├── download_data.py               # Hugging Face dataset download script (Python)
├── build_pfs_database.py          # [Step 1] Build SQLite DB from pfsConfig & pfsCoZCandidates
├── export_pfs_targets.py          # [Step 2] Extract per-target pfsObject FITS and PNG plots
├── run_pfs.py                     # PFS pipeline execution wrapper
└── pfs_target_viewer/             # [Step 3] Standalone Web Application
    ├── README.md                  # Viewer Manual (English)
    ├── README_ja.md               # Viewer Manual (Japanese)
    ├── app.py                     # FastAPI backend server & FITS/SQLite parser
    ├── requirements.txt           # Viewer dependencies (Pipeline-independent)
    ├── run_viewer.sh              # One-click launcher (auto-creates venv)
    ├── templates/
    │   └── index.html             # Dashboard UI template
    └── static/
        ├── css/
        │   └── style.css          # Dark-themed astronomical UI styling
        └── js/
            ├── app.js             # Client-side state, dynamic binning & Plotly logic
            └── plotly.min.js      # Offline standalone Plotly.js bundle
```

---

## 🚀 Workflow Overview

This toolkit provides an end-to-end data pipeline and interactive inspection workflow:

```text
[PFS Butler Repository]
       │
       ▼  (python run_pfs.py build_pfs_database.py)
[pfs_metadata.sqlite3]  ─── Aggregated metadata for 13,000+ targets
       │
       ▼  (python run_pfs.py export_pfs_targets.py)
[extracted_targets/]    ─── fits/ (pfsObject raw data) & png/ (spectrum plots)
       │
       ▼  (cd pfs_target_viewer && ./run_viewer.sh)
[Web Dashboard (http://localhost:8090)] ─── Search, deep inspection & interactive Plotly plots
```

---

### Step 1: Metadata Database Ingestion (`build_pfs_database.py`)

Reads `pfsConfig` and `pfsCoZCandidates` from the PFS Gen3 Butler repository and ingests target summaries, solver results, candidate models, and line measurements into SQLite (`pfs_metadata.sqlite3`).

```bash
# Execute within PFS pipeline environment
python run_pfs.py build_pfs_database.py
```

- **Output**: `pfs_metadata.sqlite3`
- **Primary Tables**:
  - `v_target_summary`: Target representative parameters (redshift, classification probabilities, coordinates, obCode, etc.)
  - `solver_results`: Solver status, warning flags (`zWarning`), and error codes
  - `redshift_candidates`: Candidate model rankings, redshifts, $\chi^2$, and templates
  - `line_measurements`: Detected emission and absorption lines (wavelength, flux, EW, $\sigma$)

---

### Step 2: Target FITS & PNG Plot Extraction (`export_pfs_targets.py`)

Extracts raw spectra (`pfsObject` FITS) and generates quick-look spectrum plots (PNG) with rest-frame emission/absorption line overlays for all targets registered in the database.

```bash
# Execute within PFS pipeline environment
python run_pfs.py export_pfs_targets.py
```

- **Output**: `extracted_targets/`
  - `fits/pfsObject_{obCode}_{catId}_{objId}.fits` (Raw spectrum FITS files)
  - `png/spec_{obCode}_{catId}_{objId}.png` (Quick-look spectrum plots)

---

### 📥 For Collaborators: Download Pre-built Datasets (`download_data.sh`)

If you are a collaborator or running on a machine **without the PFS pipeline installed**, you do **not** need to run Step 1 and Step 2. You can download the pre-generated dataset (`pfs_metadata.sqlite3` and `extracted_targets.tar.gz`) directly from the Hugging Face private repository.

```bash
# Set your Hugging Face Access Token (Read permission) and run:
export HF_TOKEN="hf_xxxxxxxxxxxx"
./download_data.sh

# Or using Python:
python download_data.py
```

---

### Step 3: Launch Web Viewer (`pfs_target_viewer/`)

The web application is **completely independent of the PFS pipeline (`pfs_pipe2d`, `lsst-scipipe`)**. It runs on a standard Python 3.10+ environment (FastAPI, Astropy, NumPy, Jinja2) and can be easily reproduced on any machine (laptop, workstation, or server).

```bash
cd pfs_target_viewer
./run_viewer.sh
```

Then open `http://localhost:8090` in your web browser.

#### Key Features:
1. **Search, Filter & High-Performance Pagination**:
   - Real-time search by `obCode` (partial match) or 64-bit `objId` (exact match)
   - Classification filter pills (`ALL`, `GALAXY`, `QSO`, `STAR`)
   - Redshift range filtering ($z_{min} \le z \le z_{max}$, e.g. $z \ge 6.0$ or $z \ge 7.9$)
   - Multi-column sorting (Redshift, Target ID, Classification probabilities)
   - Fast pagination handling 13,000+ targets smoothly (10, 25, 50, 100 per page)
2. **Deep Parameter Inspection (`📋 Details`)**:
   - Model candidates table (`redshift_candidates`: Rank, $z$, error, proba, reduced $\chi^2$, $p$-value, template)
   - Line measurements table (`line_measurements`: Line name, rest wavelength, $z$, flux, EW, $\sigma$)
   - Solver execution flags and warnings (`solver_results`)
3. **Interactive FITS Spectrum Viewer (`📈 Plot`)**:
   - Pure Astropy FITS reader parsing `WAVELENGTH`, `FLUX`, `COVAR`, and `MASK` directly
   - Client-side dynamic inverse-variance binning (Raw, 0.2 nm, 0.5 nm, 1.0 nm, 2.0 nm)
   - $1\sigma$ noise band and bad pixel mask shading
   - Rest-frame line overlays:
     - **Emission lines**: Lyα, C IV, C III], Mg II, [O II], Hβ, [O III], Hα, [N II], [S II]
     - **Absorption lines**: Ca II H/K, G-band, Mg b, Na D
   - **Real-time Redshift Slider**: Smooth 60fps line shifting for visual redshift confirmation
   - Observations list (Visits, arms, spectrographs, exposure times)
   - One-click raw FITS and PNG plot downloads

---

## 🛠️ Requirements

- **Step 1 & 2 (Data Ingestion & Extraction)**:
  - PFS 2D Pipeline environment (`pfs_pipe2d`, `lsst-scipipe`)
- **Step 3 (Web Viewer)**:
  - Python 3.10+
  - Dependencies: `fastapi`, `uvicorn`, `astropy`, `numpy`, `jinja2`, `python-multipart`
  - *Note: Running `./run_viewer.sh` automatically sets up the dedicated `.venv_viewer` virtual environment.*

---

## 📄 License

This software is developed for research and academic purposes within the Subaru Prime Focus Spectrograph collaboration.
