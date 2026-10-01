/**
 * PFS Target & Spectrum Viewer - Frontend Application
 * Handles searching, pagination, modals, and Plotly.js interactive spectra.
 */

// Global Spectral Line Reference for Astronomy Verification
const SPECTRAL_LINES = [
  { name: "Lyβ", wave: 102.57, type: "emission" },
  { name: "Lyα", wave: 121.567, type: "emission" },
  { name: "N V", wave: 124.0, type: "emission" },
  { name: "Si IV", wave: 139.7, type: "emission" },
  { name: "C IV", wave: 154.9, type: "emission" },
  { name: "He II", wave: 164.0, type: "emission" },
  { name: "C III]", wave: 190.9, type: "emission" },
  { name: "Mg II", wave: 279.8, type: "emission" },
  { name: "[O II]", wave: 372.7, type: "emission" },
  { name: "Ca II K", wave: 393.4, type: "absorption" },
  { name: "Ca II H", wave: 396.8, type: "absorption" },
  { name: "[Ne III]", wave: 386.9, type: "emission" },
  { name: "Hδ", wave: 410.2, type: "emission" },
  { name: "G-band", wave: 430.5, type: "absorption" },
  { name: "Hγ", wave: 434.0, type: "emission" },
  { name: "Hβ", wave: 486.1, type: "emission" },
  { name: "[O III]", wave: 495.9, type: "emission" },
  { name: "[O III]", wave: 500.7, type: "emission" },
  { name: "Mg I b", wave: 517.5, type: "absorption" },
  { name: "Na I D", wave: 589.0, type: "absorption" },
  { name: "[O I]", wave: 630.0, type: "emission" },
  { name: "[N II]", wave: 654.8, type: "emission" },
  { name: "Hα", wave: 656.3, type: "emission" },
  { name: "[N II]", wave: 658.4, type: "emission" },
  { name: "[S II]", wave: 671.6, type: "emission" },
  { name: "[S II]", wave: 673.1, type: "emission" },
  { name: "Ca II trip", wave: 849.8, type: "absorption" },
  { name: "Ca II trip", wave: 854.2, type: "absorption" },
  { name: "Ca II trip", wave: 866.2, type: "absorption" },
];

const C_KMS = 299792.458;

// Default hidden columns (internal management / large paths)
const DEFAULT_HIDDEN_COLUMNS = new Set([
  "fits_path",
  "png_path",
  "has_fits",
  "has_png"
]);

// Standard columns definitions in display order (Spectrum first, Details second)
const STANDARD_COLUMNS = [
  { key: "thumb", label: "Spectrum Thumbnail" },
  { key: "actions", label: "Details" },
  { key: "target", label: "Target ID & obCode" },
  { key: "coords", label: "Coordinates (RA, Dec)" },
  { key: "class", label: "Classification" },
  { key: "redshift", label: "Best Redshift / Velocity" },
  { key: "subclass", label: "SubClass" },
];

// Application State
const state = {
  q: "",
  classification: "ALL",
  cat_id: null,
  min_z: null,
  max_z: null,
  page: 1,
  limit: 25,
  sort_by: "redshift",
  order: "asc",
  total: 0,
  pages: 1,
  loading: false,

  // Active modal targets
  activeTarget: null,
  rawSpectrumData: null,
  activeZ: null,
  bestZ: null,

  // Sky Map Scope, Cache & Rotation
  skyScope: "all", // "page" or "all"
  skyCentralRa: 180, // Default central meridian: 180 deg (12h)
  spatialFilter: null, // { min_ra, max_ra, min_dec, max_dec } or null
  masterSkyTargets: null, // Unconditional master full-sky coordinate list with all attributes (~217k items)
  allSkyTargets: null, // Plotted coordinates filtered from masterSkyTargets
  allSkyLoading: false,
  targets: [],

  // Image Preview Navigation
  imagePreviewList: null,
  imagePreviewIndex: 0,

  // Custom SQL Query Mode State
  filterMode: "standard", // "standard" or "sql"
  sqlQuery: "",
  activeSqlQuery: "", // The currently applied SQL query
  sqlColumns: [],     // Returned column names from SQL query
  sqlCustomColumns: [], // Columns beyond the standard schema
  sqlLoading: false,
  schemaData: null,   // Cached database schema from /api/sql/schema
  schemaExpandedTables: new Set(["target_summary"]), // Default expanded tables

  // Column Visibility State
  hiddenColumns: new Set(["fits_path", "png_path", "has_fits", "has_png"]),

  // SQL Sorting State
  sqlSortBy: null,
  sqlOrder: "asc",
};

// DOM Element Selectors
const elements = {
  // Mode switch tabs
  tabStandardFilter: document.getElementById("tabStandardFilter"),
  tabSqlQuery: document.getElementById("tabSqlQuery"),
  standardFilterContainer: document.getElementById("standardFilterContainer"),
  sqlFilterContainer: document.getElementById("sqlFilterContainer"),

  // SQL Query Controls
  sqlTemplateSelect: document.getElementById("sqlTemplateSelect"),
  clearSqlBtn: document.getElementById("clearSqlBtn"),
  sqlQueryInput: document.getElementById("sqlQueryInput"),
  runSqlQueryBtn: document.getElementById("runSqlQueryBtn"),
  validateSqlBtn: document.getElementById("validateSqlBtn"),
  toggleSchemaBtn: document.getElementById("toggleSchemaBtn"),
  sqlStatusFeedback: document.getElementById("sqlStatusFeedback"),
  sqlSchemaPane: document.getElementById("sqlSchemaPane"),
  schemaSearchInput: document.getElementById("schemaSearchInput"),
  schemaTree: document.getElementById("schemaTree"),
  schemaTableCountBadge: document.getElementById("schemaTableCountBadge"),
  schemaExpandAllBtn: document.getElementById("schemaExpandAllBtn"),
  schemaCollapseAllBtn: document.getElementById("schemaCollapseAllBtn"),
  sqlFilterBadge: document.getElementById("sqlFilterBadge"),
  sqlFilterText: document.getElementById("sqlFilterText"),
  clearSqlFilterBadgeBtn: document.getElementById("clearSqlFilterBadgeBtn"),

  // Column Visibility Controls
  columnVisibilityDropdown: document.getElementById("columnVisibilityDropdown"),
  columnToggleBtn: document.getElementById("columnToggleBtn"),
  columnCountBadge: document.getElementById("columnCountBadge"),
  columnDropdownMenu: document.getElementById("columnDropdownMenu"),
  columnDropdownList: document.getElementById("columnDropdownList"),
  colSelectAllBtn: document.getElementById("colSelectAllBtn"),
  colResetDefaultBtn: document.getElementById("colResetDefaultBtn"),

  searchInput: document.getElementById("searchInput"),
  clearSearchBtn: document.getElementById("clearSearchBtn"),
  classPills: document.getElementById("classPills"),
  catIdSelect: document.getElementById("catIdSelect"),
  minZInput: document.getElementById("minZInput"),
  maxZInput: document.getElementById("maxZInput"),
  sortBySelect: document.getElementById("sortBySelect"),
  hasSpectraCheckbox: document.getElementById("hasSpectraCheckbox"),
  pageSizeSelect: document.getElementById("pageSizeSelect"),
  resetFiltersBtn: document.getElementById("resetFiltersBtn"),

  resultsCount: document.getElementById("resultsCount"),
  tableScrollWrapper: document.getElementById("tableScrollWrapper"),
  targetsTable: document.getElementById("targetsTable"),
  targetsTbody: document.getElementById("targetsTbody"),
  loadingOverlay: document.getElementById("loadingOverlay"),
  emptyState: document.getElementById("emptyState"),

  prevPageBtn: document.getElementById("prevPageBtn"),
  nextPageBtn: document.getElementById("nextPageBtn"),
  currentPageNum: document.getElementById("currentPageNum"),
  totalPagesNum: document.getElementById("totalPagesNum"),
  pageJumpInput: document.getElementById("pageJumpInput"),
  pageJumpBtn: document.getElementById("pageJumpBtn"),

  // Stats
  statTotal: document.getElementById("statTotal"),
  statGalaxy: document.getElementById("statGalaxy"),
  statQso: document.getElementById("statQso"),
  statStar: document.getElementById("statStar"),

  // Image Modal
  imageModal: document.getElementById("imageModal"),
  imageModalImg: document.getElementById("imageModalImg"),
  imageModalTitle: document.getElementById("imageModalTitle"),
  imageModalSub: document.getElementById("imageModalSub"),
  imageModalDownload: document.getElementById("imageModalDownload"),
  imageModalClose: document.getElementById("imageModalClose"),
  openInteractiveFromImageBtn: document.getElementById("openInteractiveFromImageBtn"),
  imageFloatPrevBtn: document.getElementById("imageFloatPrevBtn"),
  imageFloatNextBtn: document.getElementById("imageFloatNextBtn"),
  imageFooterPrevBtn: document.getElementById("imageFooterPrevBtn"),
  imageFooterNextBtn: document.getElementById("imageFooterNextBtn"),

  // Details Modal
  detailsModal: document.getElementById("detailsModal"),
  detailsModalTitle: document.getElementById("detailsModalTitle"),
  detailsModalSub: document.getElementById("detailsModalSub"),
  detailsModalClose: document.getElementById("detailsModalClose"),
  detailsModalCloseBtn: document.getElementById("detailsModalCloseBtn"),
  openInteractiveFromDetailsBtn: document.getElementById("openInteractiveFromDetailsBtn"),
  candidatesTbody: document.getElementById("candidatesTbody"),
  linesTbody: document.getElementById("linesTbody"),
  solversTbody: document.getElementById("solversTbody"),
  metaGrid: document.getElementById("metaGrid"),

  // HSC / Pan-STARRS Cutout in Details Modal
  hscPreviewBanner: document.getElementById("hscPreviewBanner"),
  hscImgContainer: document.getElementById("hscImgContainer"),
  hscCutoutImg: document.getElementById("hscCutoutImg"),
  hscCutoutSpinner: document.getElementById("hscCutoutSpinner"),
  hscCutoutError: document.getElementById("hscCutoutError"),
  hscFiberCircle: document.getElementById("hscFiberCircle"),
  hscFovIndicator: document.getElementById("hscFovIndicator"),
  hscSurveyTitle: document.getElementById("hscSurveyTitle"),
  hscSurveyBadge: document.getElementById("hscSurveyBadge"),
  hscMapLinkBtn: document.getElementById("hscMapLinkBtn"),
  aladinLinkBtn: document.getElementById("aladinLinkBtn"),
  fullCutoutLinkBtn: document.getElementById("fullCutoutLinkBtn"),
  hscRaVal: document.getElementById("hscRaVal"),
  hscDecVal: document.getElementById("hscDecVal"),
  hscSexagesimalVal: document.getElementById("hscSexagesimalVal"),
  hscFovSelect: document.getElementById("hscFovSelect"),
  hscSurveySelect: document.getElementById("hscSurveySelect"),

  // Expanded Sky Tab
  expandedSkyImg: document.getElementById("expandedSkyImg"),
  expandedSkySpinner: document.getElementById("expandedSkySpinner"),
  expandedSkyError: document.getElementById("expandedSkyError"),
  expandedFiberCircle: document.getElementById("expandedFiberCircle"),
  expandedFovIndicator: document.getElementById("expandedFovIndicator"),
  expandedSurveyName: document.getElementById("expandedSurveyName"),
  expandedCoverageStatus: document.getElementById("expandedCoverageStatus"),
  expandedCoords: document.getElementById("expandedCoords"),
  expandedSexagesimal: document.getElementById("expandedSexagesimal"),
  expandedTargetInfo: document.getElementById("expandedTargetInfo"),
  expandedHscMapBtn: document.getElementById("expandedHscMapBtn"),
  expandedAladinBtn: document.getElementById("expandedAladinBtn"),

  // Interactive Spectrum Modal
  spectrumModal: document.getElementById("spectrumModal"),
  spectrumModalTitle: document.getElementById("spectrumModalTitle"),
  spectrumModalSub: document.getElementById("spectrumModalSub"),
  spectrumModalClose: document.getElementById("spectrumModalClose"),
  specBinningSelect: document.getElementById("specBinningSelect"),
  toggleNoise: document.getElementById("toggleNoise"),
  toggleBadPixels: document.getElementById("toggleBadPixels"),
  toggleEmissionLines: document.getElementById("toggleEmissionLines"),
  toggleAbsorptionLines: document.getElementById("toggleAbsorptionLines"),
  interactiveZInput: document.getElementById("interactiveZInput"),
  interactiveZSlider: document.getElementById("interactiveZSlider"),
  resetZBtn: document.getElementById("resetZBtn"),
  downloadFitsBtn: document.getElementById("downloadFitsBtn"),
  plotlyLoading: document.getElementById("plotlyLoading"),
  plotlyChart: document.getElementById("plotlyChart"),
  obsCount: document.getElementById("obsCount"),
  obsTbody: document.getElementById("obsTbody"),

  // Sky Map
  skyMapCard: document.getElementById("skyMapCard"),
  skyMapBody: document.getElementById("skyMapBody"),
  skyMapCount: document.getElementById("skyMapCount"),
  skyPlotly: document.getElementById("skyPlotly"),
  skyScopePageBtn: document.getElementById("skyScopePageBtn"),
  skyScopeAllBtn: document.getElementById("skyScopeAllBtn"),
  skyPageCount: document.getElementById("skyPageCount"),
  skyAllCount: document.getElementById("skyAllCount"),
  skyMapZoomInBtn: document.getElementById("skyMapZoomInBtn"),
  skyMapZoomOutBtn: document.getElementById("skyMapZoomOutBtn"),
  skyMapResetBtn: document.getElementById("skyMapResetBtn"),
  skyMapToggleBtn: document.getElementById("skyMapToggleBtn"),
  skyFilterByViewBtn: document.getElementById("skyFilterByViewBtn"),
  skyRotationToolbar: document.getElementById("skyRotationToolbar"),
  skyRa0Slider: document.getElementById("skyRa0Slider"),
  skyRa0Value: document.getElementById("skyRa0Value"),
  skyRotStepLeftBtn: document.getElementById("skyRotStepLeftBtn"),
  skyRotStepRightBtn: document.getElementById("skyRotStepRightBtn"),
  skyCenterTargetsBtn: document.getElementById("skyCenterTargetsBtn"),
  spatialFilterBadge: document.getElementById("spatialFilterBadge"),
  spatialFilterText: document.getElementById("spatialFilterText"),
  clearSpatialFilterBtn: document.getElementById("clearSpatialFilterBtn"),
  skySpatialBadge: document.getElementById("skySpatialBadge"),
  skyClearSpatialBtn: document.getElementById("skyClearSpatialBtn"),
};

// ----------------------------------------------------------------------------
// Custom SQL Query Templates & Engine
// ----------------------------------------------------------------------------
const SQL_TEMPLATES = {
  cone_search: `-- Cone Search within 60 arcseconds of RA: 150.0 deg, Dec: 2.0 deg
-- Automatically uses (ra, dec) index bounding box + spherical Haversine distance
SELECT *
FROM target_summary
WHERE CONE_SEARCH(ra, dec, 150.0, 2.0, 60.0)
ORDER BY CONE_DIST_ARCSEC(ra, dec, 150.0, 2.0) ASC`,

  cone_fov: `-- Search within Subaru PFS Field of View (~0.7 degree radius = 2520 arcsec)
-- Automatically optimized with two-stage B-Tree coordinates filter
SELECT *
FROM target_summary
WHERE CONE_SEARCH(ra, dec, 150.0, 2.0, 2520.0)
ORDER BY CONE_DIST_ARCSEC(ra, dec, 150.0, 2.0) ASC`,

  oii_emitters: `-- Measured spectral lines joined for targets in pointing cone (within 0.2 deg)
SELECT 
  ts.catId, ts.objId, ts.ra, ts.dec, ts.bestRedshift,
  lm.lineName, lm.lineWave, lm.lineFlux, lm.lineEW
FROM target_summary ts
JOIN line_measurements lm ON ts.catId = lm.catId AND ts.objId = lm.objId
WHERE CONE_SEARCH(ts.ra, ts.dec, 150.0, 2.0, 720.0)
ORDER BY lm.lineFlux DESC`,

  high_z_qso: `-- High-redshift Quasars (z > 3.0) with reliable redshift solution
SELECT *
FROM target_summary
WHERE classificationName = 'QSO' 
  AND bestRedshift > 3.0 
  AND hasSolution = 1
ORDER BY bestRedshift DESC`,

  boundary_class: `-- Ambiguous classification: Probabilities for Galaxy and Star are both around 0.5
SELECT 
  catId, objId, classificationName, probaGalaxy, probaStar, probaQSO, bestRedshift
FROM target_summary
WHERE probaGalaxy BETWEEN 0.35 AND 0.65 
  AND probaStar BETWEEN 0.35 AND 0.65
ORDER BY ABS(probaGalaxy - probaStar) ASC`,

  solver_warnings: `-- Targets flagged with Redshift Solver Warnings (zWarning or lWarning)
SELECT 
  ts.catId, ts.objId, ts.ra, ts.dec, ts.classificationName, ts.bestRedshift,
  sr.zWarningValue, sr.zWarningName, sr.lWarningValue, sr.lWarningName
FROM target_summary ts
JOIN solver_results sr ON ts.catId = sr.catId AND ts.objId = sr.objId
WHERE sr.zWarningValue > 0 OR sr.lWarningValue > 0
ORDER BY sr.zWarningValue DESC`,

  spectra_only: `-- Science targets with both coadded FITS spectra and PNG cutouts
SELECT *
FROM target_summary
WHERE has_fits = 1 AND has_png = 1
ORDER BY bestRedshift ASC`,
};

function setFilterMode(mode) {
  state.filterMode = mode;
  if (mode === "sql") {
    if (elements.tabStandardFilter) elements.tabStandardFilter.classList.remove("active");
    if (elements.tabSqlQuery) elements.tabSqlQuery.classList.add("active");
    if (elements.standardFilterContainer) elements.standardFilterContainer.style.display = "none";
    if (elements.sqlFilterContainer) elements.sqlFilterContainer.style.display = "block";
    if (!state.schemaData) {
      loadDatabaseSchema();
    }
  } else {
    if (elements.tabSqlQuery) elements.tabSqlQuery.classList.remove("active");
    if (elements.tabStandardFilter) elements.tabStandardFilter.classList.add("active");
    if (elements.sqlFilterContainer) elements.sqlFilterContainer.style.display = "none";
    if (elements.standardFilterContainer) elements.standardFilterContainer.style.display = "block";
    if (state.activeSqlQuery) {
      clearSqlQueryFilter();
    }
  }
}

async function loadDatabaseSchema() {
  if (!elements.schemaTree) return;
  elements.schemaTree.innerHTML = '<div class="schema-loading">Loading database schema...</div>';
  try {
    const res = await fetch("/api/sql/schema");
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    state.schemaData = data;
    if (elements.schemaTableCountBadge) {
      const count = (data.tables || []).length;
      elements.schemaTableCountBadge.textContent = `${count} tables`;
    }
    renderSchemaTree(elements.schemaSearchInput ? elements.schemaSearchInput.value : "");
  } catch (err) {
    console.error("Failed to load schema:", err);
    elements.schemaTree.innerHTML = `<div class="schema-loading text-danger">Failed to load schema: ${err.message}</div>`;
  }
}

function renderSchemaTree(filterText = "") {
  if (!state.schemaData || !elements.schemaTree) return;
  const q = (filterText || "").trim().toLowerCase();
  const tables = state.schemaData.tables || [];

  if (tables.length === 0) {
    elements.schemaTree.innerHTML = '<div class="schema-loading">No tables found</div>';
    return;
  }

  let html = "";
  tables.forEach((tbl) => {
    const tblName = tbl.name;
    const tblDesc = tbl.description || "";
    const isView = tbl.type === "view";
    const tblMatch = tblName.toLowerCase().includes(q) || tblDesc.toLowerCase().includes(q);
    const columns = tbl.columns || [];
    const matchingCols = columns.filter((c) => {
      if (!q) return true;
      if (tblMatch) return true;
      const cDesc = c.description || "";
      return c.name.toLowerCase().includes(q) || cDesc.toLowerCase().includes(q);
    });

    if (q && !tblMatch && matchingCols.length === 0) return;

    // Auto-expand matching tables on search, otherwise use persistent state
    const isExpanded = q.length > 0 ? true : state.schemaExpandedTables.has(tblName);

    const icon = isView ? "👁️" : "🗂️";
    const arrow = isExpanded ? "▼" : "▶";
    const rowCountStr = tbl.row_count != null ? tbl.row_count.toLocaleString() + " rows" : "";

    html += `
      <div class="schema-table-group ${isExpanded ? 'is-open' : ''}" id="schemaTableGroup_${tblName}" data-table="${tblName}">
        <div class="schema-table-header" title="${tblDesc || tblName} (Click to toggle columns)" onclick="toggleSchemaTable('${tblName}')">
          <span class="schema-table-name">
            <span class="tree-arrow" id="arrow_${tblName}">${arrow}</span>
            <span>${icon}</span>
            <strong>${tblName}</strong>
          </span>
          <div class="schema-table-meta">
            <span class="schema-table-badge badge-cols">${columns.length} cols</span>
            ${rowCountStr ? `<span class="schema-table-badge">${rowCountStr}</span>` : ""}
          </div>
        </div>
        <div class="schema-table-columns" id="schemaCols_${tblName}" style="display: ${isExpanded ? 'flex' : 'none'};">
          ${matchingCols.map((c) => {
            const pkClass = c.primary_key ? "primary-key" : "";
            const tooltip = `${tblName}.${c.name} (${c.type})${c.description ? ' - ' + c.description : ''}`;
            return `
              <div class="schema-col-item ${pkClass}" 
                   title="${tooltip}" 
                   onclick="insertSchemaColumn('${c.name}', event)">
                <div class="schema-col-left">
                  <span class="schema-col-name">${c.name}</span>
                </div>
                <div class="schema-col-right">
                  <span class="schema-col-type">${c.type}</span>
                  <span class="schema-col-insert-hint">＋ Insert</span>
                </div>
              </div>
            `;
          }).join("")}
        </div>
      </div>
    `;
  });

  elements.schemaTree.innerHTML = html || '<div class="schema-loading">No matching tables or columns</div>';
}

function toggleSchemaTable(tableName) {
  const isCurrentlyExpanded = state.schemaExpandedTables.has(tableName);
  if (isCurrentlyExpanded) {
    state.schemaExpandedTables.delete(tableName);
  } else {
    state.schemaExpandedTables.add(tableName);
  }

  const colContainer = document.getElementById(`schemaCols_${tableName}`);
  const arrow = document.getElementById(`arrow_${tableName}`);
  const group = document.getElementById(`schemaTableGroup_${tableName}`);

  const willBeExpanded = !isCurrentlyExpanded;
  if (colContainer) {
    colContainer.style.display = willBeExpanded ? "flex" : "none";
  }
  if (arrow) {
    arrow.textContent = willBeExpanded ? "▼" : "▶";
  }
  if (group) {
    group.classList.toggle("is-open", willBeExpanded);
  }
}

function expandAllSchema() {
  if (!state.schemaData || !state.schemaData.tables) return;
  state.schemaData.tables.forEach((tbl) => state.schemaExpandedTables.add(tbl.name));
  renderSchemaTree(elements.schemaSearchInput ? elements.schemaSearchInput.value : "");
}

function collapseAllSchema() {
  state.schemaExpandedTables.clear();
  renderSchemaTree(elements.schemaSearchInput ? elements.schemaSearchInput.value : "");
}

function insertSchemaColumn(columnName, event) {
  if (event) {
    event.stopPropagation();
  }
  if (!elements.sqlQueryInput) return;
  insertTextAtCursor(elements.sqlQueryInput, columnName);

  // Transient feedback in status bar
  if (elements.sqlStatusFeedback) {
    const originalHtml = elements.sqlStatusFeedback.innerHTML;
    elements.sqlStatusFeedback.innerHTML = `<span class="status-indicator ready" style="color: #38bdf8;">✓ Inserted '${columnName}' at cursor</span>`;
    setTimeout(() => {
      if (elements.sqlStatusFeedback && elements.sqlStatusFeedback.innerHTML.includes(`Inserted '${columnName}'`)) {
        elements.sqlStatusFeedback.innerHTML = originalHtml;
      }
    }, 2000);
  }
}

function insertTextAtCursor(textarea, text) {
  const start = textarea.selectionStart || 0;
  const end = textarea.selectionEnd || 0;
  const before = textarea.value.substring(0, start);
  const after = textarea.value.substring(end);
  textarea.value = before + text + after;
  textarea.selectionStart = textarea.selectionEnd = start + text.length;
  textarea.focus();
}

async function validateSql() {
  const query = elements.sqlQueryInput.value.trim();
  if (!query) {
    setSqlFeedback("error", "Query editor is empty. Please enter an SQL query.");
    return;
  }
  setSqlFeedback("running", "Validating query syntax...");
  try {
    const res = await fetch("/api/sql/validate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query }),
    });
    const data = await res.json();
    if (!res.ok || !data.valid) {
      setSqlFeedback("error", `✗ Syntax Error: ${data.error || "Invalid SQL syntax"}`);
    } else {
      const rowEst = data.estimated_rows != null ? ` (~${data.estimated_rows.toLocaleString()} est. rows)` : "";
      setSqlFeedback("success", `✓ Query syntax is valid${rowEst}`);
    }
  } catch (err) {
    setSqlFeedback("error", `Validation error: ${err.message}`);
  }
}

async function runSqlQuery(page = 1, skipSky = false, forceRefresh = false) {
  const query = elements.sqlQueryInput.value.trim();
  if (!query) {
    setSqlFeedback("error", "Query editor is empty. Please enter an SQL query or select a template.");
    return;
  }

  if (state.sqlLoading) return;
  state.sqlLoading = true;
  state.loading = true;
  elements.loadingOverlay.classList.add("active");
  setSqlFeedback("running", "Executing SQL query...");

  try {
    const res = await fetch("/api/sql/query", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        query: query,
        page: page,
        limit: state.limit,
        sort_by: state.sqlSortBy,
        order: state.sqlOrder,
        skip_sky: skipSky,
        force_refresh: forceRefresh,
      }),
    });

    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.detail || data.error || `HTTP ${res.status}`);
    }

    state.activeSqlQuery = query;
    state.sqlColumns = data.columns || [];
    state.total = data.total;
    state.pages = data.pages;
    state.page = data.page;
    state.targets = data.targets || [];

    // Identify custom columns that are not already covered by the 7 fixed UI table columns
    const standardSet = new Set([
      "catId", "objId", "obCode",
      "ra", "dec",
      "classificationName", "probaGalaxy", "probaQSO", "probaStar",
      "bestRedshift", "bestRedshiftError", "bestVelocity", "bestVelocityError",
      "bestSubClass",
      "has_fits", "has_png", "fits_path", "png_path"
    ]);
    state.sqlCustomColumns = (data.columns || []).filter((c) => !standardSet.has(c));

    // Show SQL Active Badge
    if (elements.sqlFilterBadge) {
      elements.sqlFilterBadge.style.display = "inline-flex";
      if (elements.sqlFilterText) {
        const cacheTag = data.cached ? " ⚡cached" : "";
        elements.sqlFilterText.textContent = `SQL: ${data.total.toLocaleString()} targets (${data.execution_time_ms} ms${cacheTag})`;
      }
    }

    const cacheMsg = data.cached ? " (⚡ cached from server memory)" : "";
    setSqlFeedback("success", `✓ Query completed in ${data.execution_time_ms} ms${cacheMsg} (${data.total.toLocaleString()} rows found)`);

    // Update Sky Map coordinates with returned sky_targets only when new coordinates provided
    if (data.sky_targets && data.sky_targets.length > 0) {
      state.allSkyTargets = data.sky_targets;
    }
    renderSkyMap(state.targets);

    updateTableHeaders();
    renderTargetsTable(data.targets);
    updateTableSortIndicators();
    updatePaginationUI();
  } catch (err) {
    console.error("SQL execution error:", err);
    setSqlFeedback("error", `✗ Execution failed: ${err.message}`);
    elements.targetsTbody.innerHTML = `<tr><td colspan="7" class="text-center text-muted" style="padding: 2rem;">
      <div style="color: #f87171; font-weight: 600; margin-bottom: 0.5rem; font-size: 1rem;">SQL Execution Failed</div>
      <div style="font-family: monospace; font-size: 0.85rem; color: #cbd5e1; white-space: pre-wrap; max-width: 600px; margin: 0 auto; background: rgba(0,0,0,0.3); padding: 0.75rem; border-radius: 4px; border: 1px solid rgba(248,113,113,0.3);">${err.message}</div>
    </td></tr>`;
  } finally {
    state.sqlLoading = false;
    state.loading = false;
    elements.loadingOverlay.classList.remove("active");
  }
}

function clearSqlQueryFilter() {
  state.activeSqlQuery = "";
  state.sqlColumns = [];
  state.sqlCustomColumns = [];
  state.sqlSortBy = null;
  state.sqlOrder = "asc";
  if (elements.sqlFilterBadge) {
    elements.sqlFilterBadge.style.display = "none";
  }
  setSqlFeedback("ready", "Ready (Type query or pick template)");
  updateTableHeaders();
  updateTableSortIndicators();
  state.page = 1;
  updatePlottedSkyTargets();
  fetchTargets();
}

function setSqlFeedback(status, message) {
  if (!elements.sqlStatusFeedback) return;
  let icon = "";
  if (status === "running") {
    icon = `<span style="display:inline-block;width:12px;height:12px;border:2px solid #38bdf8;border-top-color:transparent;border-radius:50%;animation:spin 0.8s linear infinite;vertical-align:middle;margin-right:4px;"></span>`;
  } else if (status === "success") {
    icon = `<span style="color:#4ade80;margin-right:4px;">✓</span>`;
  } else if (status === "error") {
    icon = `<span style="color:#f87171;margin-right:4px;">✗</span>`;
  }
  elements.sqlStatusFeedback.innerHTML = `<span class="status-indicator ${status}">${icon}${message}</span>`;
}

function isColumnVisible(colKey) {
  return !state.hiddenColumns.has(colKey);
}

function setColumnVisible(colKey, visible) {
  if (visible) {
    state.hiddenColumns.delete(colKey);
  } else {
    state.hiddenColumns.add(colKey);
  }
  saveColumnVisibilityPreferences();
  applyColumnVisibility();
  updateColumnCountBadge();
}

function saveColumnVisibilityPreferences() {
  try {
    localStorage.setItem("pfs_hidden_columns", JSON.stringify(Array.from(state.hiddenColumns)));
  } catch (e) {
    // Ignore localStorage error
  }
}

function loadColumnVisibilityPreferences() {
  try {
    const saved = localStorage.getItem("pfs_hidden_columns");
    if (saved) {
      const arr = JSON.parse(saved);
      if (Array.isArray(arr)) {
        state.hiddenColumns = new Set(arr);
        return;
      }
    }
  } catch (e) {
    // Ignore localStorage error
  }
  state.hiddenColumns = new Set(DEFAULT_HIDDEN_COLUMNS);
}

function applyColumnVisibility() {
  if (!elements.targetsTable) return;

  // 1. Update thead headers
  const ths = elements.targetsTable.querySelectorAll("thead th");
  ths.forEach((th) => {
    const colKey = th.dataset.col;
    if (colKey) {
      if (state.hiddenColumns.has(colKey)) {
        th.classList.add("col-hidden");
      } else {
        th.classList.remove("col-hidden");
      }
    }
  });

  // 2. Update tbody cells
  const trs = elements.targetsTable.querySelectorAll("tbody tr");
  trs.forEach((tr) => {
    const tds = tr.querySelectorAll("td");
    tds.forEach((td) => {
      const colKey = td.dataset.col;
      if (colKey) {
        if (state.hiddenColumns.has(colKey)) {
          td.classList.add("col-hidden");
        } else {
          td.classList.remove("col-hidden");
        }
      }
    });
  });
}

function renderColumnVisibilityMenu() {
  if (!elements.columnDropdownList) return;

  let html = `<div class="column-item-group-title">Standard Columns</div>`;
  STANDARD_COLUMNS.forEach((col) => {
    const isChecked = isColumnVisible(col.key);
    html += `
      <label class="column-item-label">
        <input type="checkbox" data-col="${col.key}" ${isChecked ? "checked" : ""}>
        <span>${col.label}</span>
      </label>
    `;
  });

  if (state.sqlCustomColumns && state.sqlCustomColumns.length > 0) {
    html += `<div class="column-item-group-title">Query Columns</div>`;
    state.sqlCustomColumns.forEach((colName) => {
      const isChecked = isColumnVisible(colName);
      html += `
        <label class="column-item-label">
          <input type="checkbox" data-col="${colName}" ${isChecked ? "checked" : ""}>
          <span style="font-family: var(--font-mono); font-size: 0.76rem;">${colName}</span>
        </label>
      `;
    });
  }

  elements.columnDropdownList.innerHTML = html;
  updateColumnCountBadge();

  // Attach change listeners to checkboxes
  elements.columnDropdownList.querySelectorAll("input[type='checkbox']").forEach((cb) => {
    cb.addEventListener("change", (e) => {
      const colKey = e.target.dataset.col;
      setColumnVisible(colKey, e.target.checked);
    });
  });
}

function updateColumnCountBadge() {
  if (!elements.columnCountBadge) return;
  const total = STANDARD_COLUMNS.length + (state.sqlCustomColumns ? state.sqlCustomColumns.length : 0);
  let visible = 0;
  STANDARD_COLUMNS.forEach((c) => {
    if (isColumnVisible(c.key)) visible++;
  });
  if (state.sqlCustomColumns) {
    state.sqlCustomColumns.forEach((c) => {
      if (isColumnVisible(c)) visible++;
    });
  }
  elements.columnCountBadge.textContent = `${visible}/${total}`;
}

function updateTableHeaders() {
  const theadTr = elements.targetsTable ? elements.targetsTable.querySelector("thead tr") : null;
  if (!theadTr) return;

  // Remove existing custom headers
  theadTr.querySelectorAll(".col-custom-header").forEach((th) => th.remove());

  // Append custom SQL columns to the end of the headers
  if (state.sqlCustomColumns && state.sqlCustomColumns.length > 0) {
    state.sqlCustomColumns.forEach((col) => {
      const th = document.createElement("th");
      th.className = "col-custom-header sortable-th";
      th.dataset.col = col;
      th.dataset.sort = col;
      th.title = `Click to sort by ${col}`;
      th.innerHTML = `
        <div class="th-sort-wrapper">
          <span>${col}</span>
          <span class="sort-icon">↕</span>
        </div>
      `;
      if (state.hiddenColumns.has(col)) {
        th.classList.add("col-hidden");
      }
      theadTr.appendChild(th);
    });
  }

  applyColumnVisibility();
  renderColumnVisibilityMenu();
  updateTableSortIndicators();
}

/**
 * In-memory client-side sorting of targets array currently loaded in browser.
 * Executes in <1ms without any database query, network lag, or server roundtrip.
 */
function sortTargetsInMemory(sortKey, order = "asc") {
  if (!state.targets || state.targets.length === 0 || !sortKey) return;

  const isAsc = (order || "asc").toLowerCase() === "asc";
  const factor = isAsc ? 1 : -1;

  state.targets.sort((a, b) => {
    // 1. Coordinates: RA or Dec
    if (sortKey === "ra" || sortKey === "dec") {
      const valA = a[sortKey] !== null && a[sortKey] !== undefined ? Number(a[sortKey]) : null;
      const valB = b[sortKey] !== null && b[sortKey] !== undefined ? Number(b[sortKey]) : null;
      if (valA === null && valB === null) return 0;
      if (valA === null) return 1; // nulls last
      if (valB === null) return -1;
      return (valA - valB) * factor;
    }

    // 2. Classification
    if (sortKey === "classification" || sortKey === "classificationName") {
      const classOrder = { GALAXY: 1, QSO: 2, STAR: 3, UNKNOWN: 4 };
      const strA = (a.classificationName || "UNKNOWN").toUpperCase();
      const strB = (b.classificationName || "UNKNOWN").toUpperCase();
      const rankA = classOrder[strA] || 99;
      const rankB = classOrder[strB] || 99;
      if (rankA !== rankB) {
        return (rankA - rankB) * factor;
      }
      // Secondary sort: within same class, sort by redshift or velocity so order visibly shifts
      const zA = a.bestRedshift !== null && a.bestRedshift !== undefined ? Number(a.bestRedshift) : (a.bestVelocity !== null && a.bestVelocity !== undefined ? Number(a.bestVelocity) : -99999);
      const zB = b.bestRedshift !== null && b.bestRedshift !== undefined ? Number(b.bestRedshift) : (b.bestVelocity !== null && b.bestVelocity !== undefined ? Number(b.bestVelocity) : -99999);
      return (zA - zB) * factor;
    }

    // 3. Best Redshift / Velocity
    if (sortKey === "redshift" || sortKey === "bestRedshift" || sortKey === "velocity" || sortKey === "bestVelocity") {
      let numA = null;
      let numB = null;

      if (a.bestRedshift !== null && a.bestRedshift !== undefined) {
        numA = Number(a.bestRedshift);
      } else if (a.bestVelocity !== null && a.bestVelocity !== undefined) {
        numA = Number(a.bestVelocity) / C_KMS; // Effective z for stars: v / c
      }

      if (b.bestRedshift !== null && b.bestRedshift !== undefined) {
        numB = Number(b.bestRedshift);
      } else if (b.bestVelocity !== null && b.bestVelocity !== undefined) {
        numB = Number(b.bestVelocity) / C_KMS;
      }

      if (numA === null && numB === null) return 0;
      if (numA === null) return 1; // nulls last
      if (numB === null) return -1;
      return (numA - numB) * factor;
    }

    // 4. Target ID & obCode
    if (sortKey === "objId" || sortKey === "target") {
      try {
        const idA = BigInt(a.objId);
        const idB = BigInt(b.objId);
        if (idA < idB) return -1 * factor;
        if (idA > idB) return 1 * factor;
        return 0;
      } catch (_) {
        return String(a.objId).localeCompare(String(b.objId)) * factor;
      }
    }

    // 5. SubClass
    if (sortKey === "subclass" || sortKey === "bestSubClass") {
      const subA = a.bestSubClass || "";
      const subB = b.bestSubClass || "";
      if (!subA && !subB) return 0;
      if (!subA) return 1;
      if (!subB) return -1;
      return subA.localeCompare(subB) * factor;
    }

    // 6. Generic or Custom column (e.g. lineFlux, probaGalaxy, solverWarnings, etc.)
    const valA = a[sortKey];
    const valB = b[sortKey];
    if (valA === valB) return 0;
    if (valA === null || valA === undefined) return 1;
    if (valB === null || valB === undefined) return -1;

    if (typeof valA === "number" && typeof valB === "number") {
      return (valA - valB) * factor;
    }
    const numCheckA = Number(valA);
    const numCheckB = Number(valB);
    if (!isNaN(numCheckA) && !isNaN(numCheckB)) {
      return (numCheckA - numCheckB) * factor;
    }
    return String(valA).localeCompare(String(valB)) * factor;
  });
}

function handleColumnHeaderSort(sortKey) {
  if (!sortKey) return;

  // Toggle order if clicking same column, else default based on column type
  let newOrder = "asc";
  const currentKey = state.activeSortKey || (state.activeSqlQuery ? state.sqlSortBy : state.sort_by);
  const currentOrder = state.activeSortOrder || (state.activeSqlQuery ? state.sqlOrder : state.order) || "asc";

  if (currentKey === sortKey) {
    newOrder = currentOrder === "asc" ? "desc" : "asc";
  } else {
    // Default to DESC for Redshift so highest z appears first, ASC for other columns
    if (sortKey === "bestRedshift" || sortKey === "redshift") {
      newOrder = "desc";
    } else {
      newOrder = "asc";
    }
  }

  state.activeSortKey = sortKey;
  state.activeSortOrder = newOrder;

  // Keep state sync
  state.sort_by = sortKey;
  state.order = newOrder;
  state.sqlSortBy = sortKey;
  state.sqlOrder = newOrder;

  // Sync sortBySelect dropdown if matching option exists
  if (elements.sortBySelect) {
    const opt = Array.from(elements.sortBySelect.options).find(
      (o) => o.value === sortKey && (o.dataset.order || "asc") === newOrder
    );
    if (opt) {
      elements.sortBySelect.value = opt.value;
    }
  }

  // 1. Update sort indicators and UI state
  state.page = 1;
  updateTableSortIndicators();

  // 2. Fetch full-dataset sorted results from server memory cache
  if (state.filterMode === "sql" && state.activeSqlQuery) {
    runSqlQuery(1, true, false);
  } else {
    fetchTargets();
  }
}

function updateTableSortIndicators() {
  if (!elements.targetsTable) return;
  const isSql = Boolean(state.activeSqlQuery);
  const currentSort = isSql ? state.sqlSortBy : state.sort_by;
  const currentOrder = isSql ? state.sqlOrder : state.order;
  const iconText = (currentOrder || "asc").toLowerCase() === "desc" ? "▼" : "▲";

  // 1. Standard sortable headers
  const ths = elements.targetsTable.querySelectorAll("thead th.sortable-th");
  ths.forEach((th) => {
    const sortKey = th.dataset.sort;
    const icon = th.querySelector(".sort-icon");
    if (sortKey && currentSort && sortKey === currentSort) {
      th.classList.add("sort-active");
      if (icon) icon.textContent = iconText;
    } else {
      th.classList.remove("sort-active");
      if (icon) icon.textContent = "↕";
    }
  });

  // 2. Coordinate buttons (RA / Dec)
  const raBtn = elements.targetsTable.querySelector("[data-sort-coord='ra']");
  const decBtn = elements.targetsTable.querySelector("[data-sort-coord='dec']");
  if (raBtn) {
    const icon = raBtn.querySelector(".sort-icon");
    if (currentSort === "ra") {
      raBtn.classList.add("active");
      if (icon) icon.textContent = iconText;
    } else {
      raBtn.classList.remove("active");
      if (icon) icon.textContent = "↕";
    }
  }
  if (decBtn) {
    const icon = decBtn.querySelector(".sort-icon");
    if (currentSort === "dec") {
      decBtn.classList.add("active");
      if (icon) icon.textContent = iconText;
    } else {
      decBtn.classList.remove("active");
      if (icon) icon.textContent = "↕";
    }
  }
}

// ----------------------------------------------------------------------------
// Initialization
// ----------------------------------------------------------------------------
document.addEventListener("DOMContentLoaded", () => {
  loadColumnVisibilityPreferences();
  renderColumnVisibilityMenu();
  if (elements.sortBySelect && elements.sortBySelect.selectedOptions.length > 0) {
    const opt = elements.sortBySelect.selectedOptions[0];
    state.sort_by = opt.value;
    state.order = opt.dataset.order || "asc";
  }
  initEventListeners();
  updateTableSortIndicators();
  loadStats();
  fetchTargets();
});

function initEventListeners() {
  // Column Visibility Dropdown Controls
  if (elements.columnToggleBtn && elements.columnDropdownMenu) {
    elements.columnToggleBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      const isHidden = elements.columnDropdownMenu.style.display === "none";
      elements.columnDropdownMenu.style.display = isHidden ? "flex" : "none";
      if (isHidden) {
        renderColumnVisibilityMenu();
      }
    });

    elements.columnDropdownMenu.addEventListener("click", (e) => {
      e.stopPropagation();
    });

    document.addEventListener("click", (e) => {
      if (elements.columnVisibilityDropdown && !elements.columnVisibilityDropdown.contains(e.target)) {
        elements.columnDropdownMenu.style.display = "none";
      }
    });
  }

  if (elements.colSelectAllBtn) {
    elements.colSelectAllBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      state.hiddenColumns.clear();
      saveColumnVisibilityPreferences();
      applyColumnVisibility();
      renderColumnVisibilityMenu();
    });
  }

  if (elements.colResetDefaultBtn) {
    elements.colResetDefaultBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      state.hiddenColumns = new Set(DEFAULT_HIDDEN_COLUMNS);
      saveColumnVisibilityPreferences();
      applyColumnVisibility();
      renderColumnVisibilityMenu();
    });
  }

  // Mode Switch Tabs (Standard GUI vs SQL Query)
  if (elements.tabStandardFilter) {
    elements.tabStandardFilter.addEventListener("click", () => setFilterMode("standard"));
  }
  if (elements.tabSqlQuery) {
    elements.tabSqlQuery.addEventListener("click", () => setFilterMode("sql"));
  }

  // SQL Query Controls
  if (elements.sqlTemplateSelect) {
    elements.sqlTemplateSelect.addEventListener("change", (e) => {
      const tmplKey = e.target.value;
      if (tmplKey && SQL_TEMPLATES[tmplKey]) {
        elements.sqlQueryInput.value = SQL_TEMPLATES[tmplKey];
        elements.sqlQueryInput.focus();
        setSqlFeedback("ready", `Loaded template: ${e.target.selectedOptions[0].textContent}`);
      }
    });
  }

  if (elements.clearSqlBtn) {
    elements.clearSqlBtn.addEventListener("click", () => {
      elements.sqlQueryInput.value = "";
      if (elements.sqlTemplateSelect) elements.sqlTemplateSelect.selectedIndex = 0;
      setSqlFeedback("ready", "Query editor cleared. Pick a template or type query.");
      elements.sqlQueryInput.focus();
    });
  }

  if (elements.runSqlQueryBtn) {
    elements.runSqlQueryBtn.addEventListener("click", () => {
      state.page = 1;
      state.sqlSortBy = null;
      state.sqlOrder = "asc";
      runSqlQuery(1, false, true);
    });
  }

  if (elements.validateSqlBtn) {
    elements.validateSqlBtn.addEventListener("click", () => {
      validateSql();
    });
  }

  if (elements.toggleSchemaBtn) {
    elements.toggleSchemaBtn.addEventListener("click", () => {
      if (elements.sqlSchemaPane) {
        elements.sqlSchemaPane.classList.toggle("collapsed");
      }
    });
  }

  if (elements.schemaSearchInput) {
    let schemaSearchTimer;
    elements.schemaSearchInput.addEventListener("input", (e) => {
      clearTimeout(schemaSearchTimer);
      schemaSearchTimer = setTimeout(() => {
        renderSchemaTree(e.target.value);
      }, 200);
    });
  }

  if (elements.schemaExpandAllBtn) {
    elements.schemaExpandAllBtn.addEventListener("click", () => {
      expandAllSchema();
    });
  }

  if (elements.schemaCollapseAllBtn) {
    elements.schemaCollapseAllBtn.addEventListener("click", () => {
      collapseAllSchema();
    });
  }

  if (elements.clearSqlFilterBadgeBtn) {
    elements.clearSqlFilterBadgeBtn.addEventListener("click", () => {
      clearSqlQueryFilter();
    });
  }

  if (elements.sqlQueryInput) {
    elements.sqlQueryInput.addEventListener("keydown", (e) => {
      // Ctrl + Enter or Cmd + Enter to run SQL query
      if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
        e.preventDefault();
        state.page = 1;
        state.sqlSortBy = null;
        state.sqlOrder = "asc";
        runSqlQuery(1, false, true);
      }
      // Tab key support for indentation
      if (e.key === "Tab") {
        e.preventDefault();
        insertTextAtCursor(elements.sqlQueryInput, "  ");
      }
    });
  }

  // Search debouncing
  let searchTimer;
  elements.searchInput.addEventListener("input", (e) => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => {
      state.q = e.target.value.trim();
      state.page = 1;
      updatePlottedSkyTargets();
      fetchTargets();
    }, 300);
  });

  elements.clearSearchBtn.addEventListener("click", () => {
    elements.searchInput.value = "";
    state.q = "";
    state.page = 1;
    updatePlottedSkyTargets();
    fetchTargets();
  });

  // Classification Pills
  elements.classPills.addEventListener("click", (e) => {
    const btn = e.target.closest(".pill-btn");
    if (!btn) return;
    elements.classPills.querySelectorAll(".pill-btn").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    state.classification = btn.dataset.class;
    state.page = 1;
    updatePlottedSkyTargets();
    fetchTargets();
  });

  // catId Select Filter
  if (elements.catIdSelect) {
    elements.catIdSelect.addEventListener("change", (e) => {
      state.cat_id = e.target.value === "ALL" ? null : parseInt(e.target.value, 10);
      state.page = 1;
      updatePlottedSkyTargets();
      fetchTargets();
    });
  }

  // Redshift Inputs
  let zTimer;
  const onZChange = () => {
    clearTimeout(zTimer);
    zTimer = setTimeout(() => {
      state.min_z = elements.minZInput.value ? parseFloat(elements.minZInput.value) : null;
      state.max_z = elements.maxZInput.value ? parseFloat(elements.maxZInput.value) : null;
      state.page = 1;
      updatePlottedSkyTargets();
      fetchTargets();
    }, 400);
  };
  elements.minZInput.addEventListener("input", onZChange);
  elements.maxZInput.addEventListener("input", onZChange);

  // Sorting
  elements.sortBySelect.addEventListener("change", (e) => {
    const opt = e.target.selectedOptions[0];
    state.sort_by = opt.value;
    state.order = opt.dataset.order || "asc";
    state.page = 1;
    updateTableSortIndicators();
    fetchTargets();
  });

  // Table Header Click Sorting (Standard & SQL modes)
  if (elements.targetsTable) {
    const thead = elements.targetsTable.querySelector("thead");
    if (thead) {
      thead.addEventListener("click", (e) => {
        // 1. Check if clicked on RA or Dec sort button in Coordinates header
        const coordBtn = e.target.closest("[data-sort-coord]");
        if (coordBtn) {
          e.stopPropagation();
          const sortKey = coordBtn.dataset.sortCoord;
          handleColumnHeaderSort(sortKey);
          return;
        }

        // 2. Check if clicked on a sortable column header (th.sortable-th)
        const th = e.target.closest("th.sortable-th");
        if (th) {
          const sortKey = th.dataset.sort;
          handleColumnHeaderSort(sortKey);
        }
      });
    }
  }

  // Page Size
  elements.pageSizeSelect.addEventListener("change", (e) => {
    state.limit = parseInt(e.target.value, 10);
    state.page = 1;
    if (state.filterMode === "sql" && state.activeSqlQuery) {
      runSqlQuery(1, true, false);
    } else {
      fetchTargets();
    }
  });

  // With Spectra Only Filter
  if (elements.hasSpectraCheckbox) {
    elements.hasSpectraCheckbox.addEventListener("change", (e) => {
      state.has_png = e.target.checked ? true : null;
      state.has_fits = e.target.checked ? true : null;
      state.page = 1;
      updatePlottedSkyTargets();
      fetchTargets();
    });
  }

  // Reset Filters
  elements.resetFiltersBtn.addEventListener("click", () => {
    elements.searchInput.value = "";
    elements.minZInput.value = "";
    elements.maxZInput.value = "";
    elements.classPills.querySelectorAll(".pill-btn").forEach((b) => b.classList.remove("active"));
    elements.classPills.querySelector('[data-class="ALL"]').classList.add("active");
    if (elements.catIdSelect) elements.catIdSelect.value = "ALL";
    if (elements.sortBySelect) {
      elements.sortBySelect.selectedIndex = 0;
      const opt = elements.sortBySelect.selectedOptions[0];
      state.sort_by = opt ? opt.value : "redshift";
      state.order = opt ? (opt.dataset.order || "asc") : "asc";
    }
    if (elements.hasSpectraCheckbox) elements.hasSpectraCheckbox.checked = false;

    state.q = "";
    state.classification = "ALL";
    state.cat_id = null;
    state.min_z = null;
    state.max_z = null;
    state.has_png = null;
    state.has_fits = null;
    state.spatialFilter = null;
    updateSpatialFilterUI();
    state.skyCentralRa = 180;
    updateSkyRotationUI(180);
    state.page = 1;
    updatePlottedSkyTargets();
    fetchTargets();
  });

  // Pagination
  elements.prevPageBtn.addEventListener("click", () => {
    if (state.page > 1) {
      state.page--;
      if (state.filterMode === "sql" && state.activeSqlQuery) {
        runSqlQuery(state.page, true, false);
      } else {
        fetchTargets();
      }
    }
  });

  elements.nextPageBtn.addEventListener("click", () => {
    if (state.page < state.pages) {
      state.page++;
      if (state.filterMode === "sql" && state.activeSqlQuery) {
        runSqlQuery(state.page, true, false);
      } else {
        fetchTargets();
      }
    }
  });

  elements.pageJumpBtn.addEventListener("click", () => {
    const val = parseInt(elements.pageJumpInput.value, 10);
    if (!isNaN(val) && val >= 1 && val <= state.pages) {
      state.page = val;
      if (state.filterMode === "sql" && state.activeSqlQuery) {
        runSqlQuery(state.page, true, false);
      } else {
        fetchTargets();
      }
      elements.pageJumpInput.value = "";
    }
  });

  // Modals closing
  const setupModalClose = (modal, ...triggers) => {
    triggers.forEach((btn) => {
      if (btn) btn.addEventListener("click", () => (modal.style.display = "none"));
    });
    modal.addEventListener("click", (e) => {
      if (e.target === modal) modal.style.display = "none";
    });
  };

  setupModalClose(elements.imageModal, elements.imageModalClose);
  setupModalClose(elements.detailsModal, elements.detailsModalClose, elements.detailsModalCloseBtn);
  setupModalClose(elements.spectrumModal, elements.spectrumModalClose);

  // Image Modal Navigation (Prev / Next)
  const onImagePrev = () => navigateImagePreview(-1);
  const onImageNext = () => navigateImagePreview(1);

  if (elements.imageFloatPrevBtn) elements.imageFloatPrevBtn.addEventListener("click", onImagePrev);
  if (elements.imageFloatNextBtn) elements.imageFloatNextBtn.addEventListener("click", onImageNext);
  if (elements.imageFooterPrevBtn) elements.imageFooterPrevBtn.addEventListener("click", onImagePrev);
  if (elements.imageFooterNextBtn) elements.imageFooterNextBtn.addEventListener("click", onImageNext);

  // Keyboard navigation for image modal
  document.addEventListener("keydown", (e) => {
    if (elements.imageModal && elements.imageModal.style.display !== "none") {
      if (e.key === "ArrowLeft") {
        e.preventDefault();
        onImagePrev();
      } else if (e.key === "ArrowRight") {
        e.preventDefault();
        onImageNext();
      } else if (e.key === "Escape") {
        elements.imageModal.style.display = "none";
      }
    }
  });

  // Cross modal open buttons
  elements.openInteractiveFromImageBtn.addEventListener("click", () => {
    elements.imageModal.style.display = "none";
    if (state.activeTarget) {
      openInteractiveSpectrumById(state.activeTarget.catId, state.activeTarget.objId);
    }
  });

  elements.openInteractiveFromDetailsBtn.addEventListener("click", () => {
    elements.detailsModal.style.display = "none";
    if (state.activeTarget) openInteractiveSpectrum(state.activeTarget);
  });

  // HSC / Pan-STARRS Cutout interactions
  if (elements.hscFovSelect) {
    elements.hscFovSelect.addEventListener("change", () => {
      if (state.activeTarget && state.activeTarget.ra !== undefined && state.activeTarget.dec !== undefined) {
        loadSkyCutout(state.activeTarget.ra, state.activeTarget.dec);
      }
    });
  }

  if (elements.hscSurveySelect) {
    elements.hscSurveySelect.addEventListener("change", () => {
      if (state.activeTarget && state.activeTarget.ra !== undefined && state.activeTarget.dec !== undefined) {
        loadSkyCutout(state.activeTarget.ra, state.activeTarget.dec);
      }
    });
  }

  if (elements.hscImgContainer) {
    elements.hscImgContainer.addEventListener("click", () => {
      if (elements.fullCutoutLinkBtn && elements.fullCutoutLinkBtn.href) {
        window.open(elements.fullCutoutLinkBtn.href, "_blank");
      }
    });
  }

  // Tab switching in Details modal
  document.querySelectorAll(".modal-tabs .tab-btn").forEach((tabBtn) => {
    tabBtn.addEventListener("click", () => {
      document.querySelectorAll(".modal-tabs .tab-btn").forEach((b) => b.classList.remove("active"));
      document.querySelectorAll(".tab-pane").forEach((p) => p.classList.remove("active"));
      tabBtn.classList.add("active");
      const targetPane = document.getElementById(tabBtn.dataset.tab);
      if (targetPane) targetPane.classList.add("active");
    });
  });

  // Interactive Spectrum Controls
  elements.specBinningSelect.addEventListener("change", () => renderPlotlyChart());
  elements.toggleNoise.addEventListener("change", () => renderPlotlyChart());
  elements.toggleBadPixels.addEventListener("change", () => renderPlotlyChart());
  elements.toggleEmissionLines.addEventListener("change", () => updateSpectralLineShapes());
  elements.toggleAbsorptionLines.addEventListener("change", () => updateSpectralLineShapes());

  // Real-time Redshift Slider
  elements.interactiveZSlider.addEventListener("input", (e) => {
    const z = parseFloat(e.target.value);
    elements.interactiveZInput.value = z.toFixed(4);
    state.activeZ = z;
    updateSpectralLineShapes();
  });

  elements.interactiveZInput.addEventListener("change", (e) => {
    const z = parseFloat(e.target.value);
    if (!isNaN(z)) {
      elements.interactiveZSlider.value = Math.min(Math.max(z, 0), 8);
      state.activeZ = z;
      updateSpectralLineShapes();
    }
  });

  elements.resetZBtn.addEventListener("click", () => {
    if (state.bestZ !== null) {
      state.activeZ = state.bestZ;
      elements.interactiveZInput.value = state.bestZ.toFixed(4);
      elements.interactiveZSlider.value = Math.min(Math.max(state.bestZ, 0), 8);
      updateSpectralLineShapes();
    }
  });

  // Sky Map Controls & Rotation
  if (elements.skyMapResetBtn) {
    elements.skyMapResetBtn.addEventListener("click", () => {
      if (elements.skyPlotly) {
        Plotly.relayout(elements.skyPlotly, {
          "xaxis.range": [3.25, -3.25],
          "yaxis.range": [-1.625, 1.625],
          "xaxis.autorange": false,
          "yaxis.autorange": false,
        });
      }
      setSkyCentralRa(180);
    });
  }

  // Central RA Rotation Slider
  if (elements.skyRa0Slider) {
    let ra0Raf = null;
    elements.skyRa0Slider.addEventListener("input", (e) => {
      const val = parseFloat(e.target.value);
      state.skyCentralRa = val;
      if (elements.skyRa0Value) {
        elements.skyRa0Value.textContent = formatRaDegrees(val);
      }
      document.querySelectorAll(".preset-ra-btn").forEach((btn) => {
        const btnRa = parseFloat(btn.dataset.ra0);
        if (Math.abs(btnRa - val) < 1e-3) {
          btn.classList.add("active");
        } else {
          btn.classList.remove("active");
        }
      });
      if (ra0Raf) cancelAnimationFrame(ra0Raf);
      ra0Raf = requestAnimationFrame(() => {
        renderSkyMap(state.targets);
      });
    });
  }

  // Step Rotate Buttons (15 deg = 1 hour steps)
  if (elements.skyRotStepLeftBtn) {
    elements.skyRotStepLeftBtn.addEventListener("click", () => {
      setSkyCentralRa((state.skyCentralRa - 15 + 360) % 360);
    });
  }

  if (elements.skyRotStepRightBtn) {
    elements.skyRotStepRightBtn.addEventListener("click", () => {
      setSkyCentralRa((state.skyCentralRa + 15) % 360);
    });
  }

  // Preset RA Buttons
  document.querySelectorAll(".preset-ra-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const targetRa = parseFloat(btn.dataset.ra0);
      setSkyCentralRa(targetRa);
    });
  });

  // Center Map on Current Targets (Circular mean of RA)
  if (elements.skyCenterTargetsBtn) {
    elements.skyCenterTargetsBtn.addEventListener("click", () => {
      const isAll = state.skyScope === "all";
      const targets = isAll ? (state.allSkyTargets || state.targets || []) : (state.targets || []);
      const meanRa = calculateMeanRa(targets);
      setSkyCentralRa(meanRa);
    });
  }

  // Filter Table by View Button
  if (elements.skyFilterByViewBtn) {
    elements.skyFilterByViewBtn.addEventListener("click", () => {
      const bounds = getVisibleSkyBounds();
      if (!bounds) {
        alert("No valid sky region visible in current view.");
        return;
      }
      if (bounds.isFullSky) {
        if (state.spatialFilter) {
          clearSpatialFilter();
        } else {
          alert("Currently displaying full sky view. Zoom in or pan to an area of interest first, then click 'Filter Table by View'.");
        }
        return;
      }
      applySpatialFilter(bounds);
    });
  }

  // Clear Spatial Filter Buttons
  if (elements.clearSpatialFilterBtn) {
    elements.clearSpatialFilterBtn.addEventListener("click", () => {
      clearSpatialFilter();
    });
  }
  if (elements.skyClearSpatialBtn) {
    elements.skyClearSpatialBtn.addEventListener("click", () => {
      clearSpatialFilter();
    });
  }

  if (elements.skyMapZoomInBtn) {
    elements.skyMapZoomInBtn.addEventListener("click", () => {
      zoomSkyMap(0.7);
    });
  }

  if (elements.skyMapZoomOutBtn) {
    elements.skyMapZoomOutBtn.addEventListener("click", () => {
      zoomSkyMap(1.4);
    });
  }

  if (elements.skyScopePageBtn) {
    elements.skyScopePageBtn.addEventListener("click", () => {
      if (state.skyScope !== "page") {
        state.skyScope = "page";
        renderSkyMap(state.targets);
      }
    });
  }

  if (elements.skyScopeAllBtn) {
    elements.skyScopeAllBtn.addEventListener("click", () => {
      if (state.skyScope !== "all") {
        state.skyScope = "all";
        updatePlottedSkyTargets();
      }
    });
  }

  if (elements.skyMapToggleBtn) {
    elements.skyMapToggleBtn.addEventListener("click", () => {
      const isHidden = elements.skyMapBody.style.display === "none";
      if (isHidden) {
        elements.skyMapBody.style.display = "flex";
        if (elements.skyRotationToolbar) elements.skyRotationToolbar.style.display = "flex";
        elements.skyMapToggleBtn.textContent = "− Collapse";
        Plotly.Plots.resize(elements.skyPlotly);
      } else {
        elements.skyMapBody.style.display = "none";
        if (elements.skyRotationToolbar) elements.skyRotationToolbar.style.display = "none";
        elements.skyMapToggleBtn.textContent = "+ Expand";
      }
    });
  }
}

// ----------------------------------------------------------------------------
// API Calls & Rendering
// ----------------------------------------------------------------------------
async function loadStats() {
  try {
    const res = await fetch("/api/stats");
    if (!res.ok) return;
    const data = await res.json();
    elements.statTotal.textContent = data.total_targets.toLocaleString();
    elements.statGalaxy.textContent = (data.classification_counts.GALAXY || 0).toLocaleString();
    elements.statQso.textContent = (data.classification_counts.QSO || 0).toLocaleString();
    elements.statStar.textContent = (data.classification_counts.STAR || 0).toLocaleString();

    // Populate catId select options if available
    if (data.cat_ids && elements.catIdSelect) {
      const currentVal = elements.catIdSelect.value || "ALL";
      let optionsHtml = `<option value="ALL">All Catalogs (${data.total_targets.toLocaleString()})</option>`;
      for (const [cid, cnt] of Object.entries(data.cat_ids)) {
        optionsHtml += `<option value="${cid}">catId ${cid} (${cnt.toLocaleString()})</option>`;
      }
      elements.catIdSelect.innerHTML = optionsHtml;
      elements.catIdSelect.value = currentVal;
    }
  } catch (err) {
    console.warn("Failed to load stats:", err);
  }
}

async function fetchTargets() {
  if (state.loading) return;
  state.loading = true;
  elements.loadingOverlay.classList.add("active");

  const params = new URLSearchParams({
    page: state.page,
    limit: state.limit,
    sort_by: state.sort_by,
    order: state.order,
  });

  if (state.q) params.append("q", state.q);
  if (state.classification && state.classification !== "ALL") {
    params.append("classification", state.classification);
  }
  if (state.cat_id !== null && state.cat_id !== "ALL") {
    params.append("cat_id", state.cat_id);
  }
  if (state.min_z !== null) params.append("min_z", state.min_z);
  if (state.max_z !== null) params.append("max_z", state.max_z);
  if (state.has_fits !== null && state.has_fits !== undefined) params.append("has_fits", state.has_fits);
  if (state.has_png !== null && state.has_png !== undefined) params.append("has_png", state.has_png);

  if (state.spatialFilter) {
    if (state.spatialFilter.min_ra !== null && state.spatialFilter.min_ra !== undefined) {
      params.append("min_ra", state.spatialFilter.min_ra);
    }
    if (state.spatialFilter.max_ra !== null && state.spatialFilter.max_ra !== undefined) {
      params.append("max_ra", state.spatialFilter.max_ra);
    }
    if (state.spatialFilter.min_dec !== null && state.spatialFilter.min_dec !== undefined) {
      params.append("min_dec", state.spatialFilter.min_dec);
    }
    if (state.spatialFilter.max_dec !== null && state.spatialFilter.max_dec !== undefined) {
      params.append("max_dec", state.spatialFilter.max_dec);
    }
  }

  try {
    const res = await fetch(`/api/targets?${params.toString()}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();

    state.total = data.total;
    state.pages = data.pages;
    state.targets = data.targets || [];
    state.sqlCustomColumns = []; // Reset custom columns in standard mode
    updateTableHeaders();
    renderTargetsTable(data.targets);
    updateTableSortIndicators();
    updatePaginationUI();
  } catch (err) {
    console.error("Error fetching targets:", err);
    elements.targetsTbody.innerHTML = `<tr><td colspan="7" class="text-center text-muted">Error loading targets: ${err.message}</td></tr>`;
  } finally {
    state.loading = false;
    elements.loadingOverlay.classList.remove("active");
  }
}

function renderTargetsTable(targets) {
  if (elements.tableScrollWrapper) {
    elements.tableScrollWrapper.scrollLeft = 0;
  }
  const colSpan = 7 + (state.sqlCustomColumns ? state.sqlCustomColumns.length : 0);
  if (!targets || targets.length === 0) {
    elements.targetsTbody.innerHTML = "";
    elements.emptyState.style.display = "block";
    elements.resultsCount.textContent = "0 targets found";
    renderSkyMap([]);
    return;
  }

  elements.emptyState.style.display = "none";
  const startIdx = (state.page - 1) * state.limit + 1;
  const endIdx = Math.min(startIdx + targets.length - 1, state.total);

  const sortLabels = {
    ra: "RA",
    dec: "Dec",
    objId: "Target ID",
    target: "Target ID",
    classificationName: "Classification",
    classification: "Classification",
    bestRedshift: "Redshift / Velocity",
    redshift: "Redshift / Velocity",
    bestSubClass: "SubClass",
    subclass: "SubClass",
  };
  const activeSort = state.activeSortKey || (state.activeSqlQuery ? state.sqlSortBy : state.sort_by);
  const activeOrder = state.activeSortOrder || (state.activeSqlQuery ? state.sqlOrder : state.order);
  let sortBadge = "";
  if (activeSort) {
    const label = sortLabels[activeSort] || activeSort;
    const orderIcon = (activeOrder || "asc").toLowerCase() === "desc" ? "▼ DESC" : "▲ ASC";
    sortBadge = ` <span class="badge badge-sort-info" title="Full dataset sorted across all pages via server cache">⚡ Sorted: ${label} ${orderIcon}</span>`;
  }
  elements.resultsCount.innerHTML = `Showing ${startIdx.toLocaleString()}–${endIdx.toLocaleString()} of ${state.total.toLocaleString()} targets${sortBadge}`;

  const rowsHtml = targets
    .map((t) => {
      const cls = t.classificationName || "UNKNOWN";
      let badgeClass = "badge-unknown";
      if (cls === "GALAXY") badgeClass = "badge-galaxy";
      else if (cls === "QSO") badgeClass = "badge-qso";
      else if (cls === "STAR") badgeClass = "badge-star";

      // Probabilities
      const pGal = typeof t.probaGalaxy === "number" ? (t.probaGalaxy * 100).toFixed(1) + "%" : "-";
      const pQso = typeof t.probaQSO === "number" ? (t.probaQSO * 100).toFixed(1) + "%" : "-";
      const pStar = typeof t.probaStar === "number" ? (t.probaStar * 100).toFixed(1) + "%" : "-";

      // Redshift / Velocity
      let zDisplay = "-";
      let zErrDisplay = "";
      if (cls === "STAR" && typeof t.bestVelocity === "number") {
        zDisplay = `${t.bestVelocity.toFixed(1)} km/s`;
        if (typeof t.bestVelocityError === "number") zErrDisplay = `&plusmn;${t.bestVelocityError.toFixed(1)}`;
      } else if (typeof t.bestRedshift === "number") {
        zDisplay = `z = ${t.bestRedshift.toFixed(4)}`;
        if (typeof t.bestRedshiftError === "number") zErrDisplay = `&plusmn;${t.bestRedshiftError.toFixed(4)}`;
      }

      // Thumbnail
      const thumbSrc = t.has_png ? `/api/targets/${t.catId}/${t.objId}/image` : null;
      const thumbHtml = thumbSrc
        ? `<div class="thumb-container" onclick="openImagePreview(${t.catId}, '${t.objId}', '${t.obCode || ""}')" title="Click to view full spectrum plot">
             <img src="${thumbSrc}" loading="lazy" alt="Spectrum thumbnail">
           </div>`
        : `<div class="thumb-container thumb-placeholder">No PNG</div>`;

      // Coordinates
      const raStr = typeof t.ra === "number" ? `${t.ra.toFixed(4)}°` : "-";
      const decStr = typeof t.dec === "number" ? `${t.dec.toFixed(4)}°` : "-";

      // Custom SQL columns rendering
      let customCellsHtml = "";
      if (state.sqlCustomColumns && state.sqlCustomColumns.length > 0) {
        customCellsHtml = state.sqlCustomColumns.map((col) => {
          const val = t[col];
          let displayVal = "-";
          if (val !== null && val !== undefined) {
            if (typeof val === "number") {
              if (Number.isInteger(val)) {
                displayVal = val.toLocaleString();
              } else if (val === 0) {
                displayVal = "0";
              } else {
                const absVal = Math.abs(val);
                if (absVal < 1e-4 || absVal >= 1e6) {
                  displayVal = val.toExponential(3);
                } else {
                  displayVal = val.toFixed(4).replace(/\.?0+$/, "");
                }
              }
            } else {
              displayVal = String(val);
            }
          }
          const hiddenClass = state.hiddenColumns.has(col) ? "col-hidden" : "";
          return `<td class="col-custom ${hiddenClass}" data-col="${col}" title="${col}: ${displayVal}"><span class="custom-col-val" style="font-family: var(--font-mono); font-size: 0.8rem; color: #bae6fd;">${displayVal}</span></td>`;
        }).join("");
      }

      const actionsHidden = state.hiddenColumns.has("actions") ? "col-hidden" : "";
      const thumbHidden = state.hiddenColumns.has("thumb") ? "col-hidden" : "";
      const targetHidden = state.hiddenColumns.has("target") ? "col-hidden" : "";
      const coordsHidden = state.hiddenColumns.has("coords") ? "col-hidden" : "";
      const classHidden = state.hiddenColumns.has("class") ? "col-hidden" : "";
      const redshiftHidden = state.hiddenColumns.has("redshift") ? "col-hidden" : "";
      const subclassHidden = state.hiddenColumns.has("subclass") ? "col-hidden" : "";

      return `
      <tr data-catid="${t.catId}" data-objid="${t.objId}">
        <td class="col-thumb ${thumbHidden}" data-col="thumb">${thumbHtml}</td>
        <td class="col-actions ${actionsHidden}" data-col="actions">
          <div class="action-buttons">
            <button class="btn btn-sm btn-secondary" onclick="openTargetDetails(${t.catId}, '${t.objId}')" title="Inspect solver & line details">
              📋 Details
            </button>
          </div>
        </td>
        <td class="col-target ${targetHidden}" data-col="target">
          <span class="target-id">${t.objId}</span>
          ${t.obCode ? `<span class="obcode-badge">${t.obCode}</span>` : ""}
          <div class="cat-id-muted">${(state.filterMode !== "sql" || !(state.sqlCustomColumns && state.sqlCustomColumns.includes("combination"))) && t.combination ? `catId: ${t.catId} &bull; ${t.combination}` : `catId: ${t.catId}`}</div>
        </td>
        <td class="col-coords ${coordsHidden}" data-col="coords">
          <div class="coords-text">RA: ${raStr}</div>
          <div class="coords-text">Dec: ${decStr}</div>
        </td>
        <td class="col-class ${classHidden}" data-col="class">
          <span class="badge ${badgeClass}">${cls}</span>
          <div class="proba-bar" title="G: ${pGal} | Q: ${pQso} | S: ${pStar}">
            G:${pGal} Q:${pQso} S:${pStar}
          </div>
        </td>
        <td class="col-z ${redshiftHidden}" data-col="redshift">
          <div class="z-val">${zDisplay}</div>
          ${zErrDisplay ? `<div class="z-err">${zErrDisplay}</div>` : ""}
        </td>
        <td class="col-subclass ${subclassHidden}" data-col="subclass">
          <span class="subclass-text">${t.bestSubClass || "-"}</span>
        </td>
        ${customCellsHtml}
      </tr>
      `;
    })
    .join("");

  elements.targetsTbody.innerHTML = rowsHtml;
  if (state.skyScope === "all" && !state.allSkyTargets && !state.allSkyLoading) {
    fetchAllSkyPositions();
  } else {
    renderSkyMap(targets);
  }
}

function updatePaginationUI() {
  elements.currentPageNum.textContent = state.page;
  elements.totalPagesNum.textContent = state.pages;
  elements.prevPageBtn.disabled = state.page <= 1;
  elements.nextPageBtn.disabled = state.page >= state.pages;

  if (elements.skyPageCount) {
    elements.skyPageCount.textContent = (state.targets ? state.targets.length : 0).toString();
  }
  if (elements.skyAllCount) {
    elements.skyAllCount.textContent = (state.total || 0).toLocaleString();
  }
}

function isTargetInSpatialFilter(t, filter) {
  if (!filter) return true;
  if (t.ra === null || t.ra === undefined || isNaN(t.ra) ||
      t.dec === null || t.dec === undefined || isNaN(t.dec)) {
    return false;
  }
  if (filter.min_dec !== null && filter.min_dec !== undefined && t.dec < filter.min_dec) {
    return false;
  }
  if (filter.max_dec !== null && filter.max_dec !== undefined && t.dec > filter.max_dec) {
    return false;
  }
  if (filter.min_ra !== null && filter.min_ra !== undefined &&
      filter.max_ra !== null && filter.max_ra !== undefined) {
    if (filter.min_ra <= filter.max_ra) {
      if (t.ra < filter.min_ra || t.ra > filter.max_ra) return false;
    } else {
      // Wraps around RA 0 deg (e.g. min_ra = 350, max_ra = 20)
      if (t.ra < filter.min_ra && t.ra > filter.max_ra) return false;
    }
  }
  return true;
}

function filterMasterSkyTargets() {
  if (!state.masterSkyTargets) return [];

  const q = state.q ? state.q.trim().toLowerCase() : "";
  const isQNum = q ? /^\d+$/.test(q) : false;
  const qNum = isQNum ? parseInt(q, 10) : null;
  const cls = state.classification;
  const catId = state.cat_id;
  const minZ = state.min_z;
  const maxZ = state.max_z;
  const hasFits = state.has_fits;
  const hasPng = state.has_png;
  const sf = state.spatialFilter;

  return state.masterSkyTargets.filter((t) => {
    // 1. Classification
    if (cls && cls !== "ALL") {
      if ((t.classificationName || "UNKNOWN").toUpperCase() !== cls.toUpperCase()) return false;
    }
    // 2. catId
    if (catId !== null && catId !== undefined && catId !== "ALL") {
      if (t.catId !== catId) return false;
    }
    // 3. Redshift
    if (minZ !== null && minZ !== undefined) {
      if (t.bestRedshift === null || t.bestRedshift === undefined || t.bestRedshift < minZ) return false;
    }
    if (maxZ !== null && maxZ !== undefined) {
      if (t.bestRedshift === null || t.bestRedshift === undefined || t.bestRedshift > maxZ) return false;
    }
    // 4. File existence
    if (hasFits === true && !t.has_fits) return false;
    if (hasPng === true && !t.has_png) return false;
    // 5. Search query q
    if (q) {
      if (isQNum) {
        const matchId = t.objId == q || t.catId == qNum;
        const matchCode = t.obCode && t.obCode.toLowerCase().includes(q);
        if (!matchId && !matchCode) return false;
      } else {
        if (!t.obCode || !t.obCode.toLowerCase().includes(q)) return false;
      }
    }
    // 6. Spatial boundary filter (RA / Dec)
    if (sf) {
      if (!isTargetInSpatialFilter(t, sf)) return false;
    }
    return true;
  });
}

function updatePlottedSkyTargets() {
  if (state.filterMode === "sql" && state.activeSqlQuery) {
    if (state.skyScope === "all") {
      renderSkyMap(state.targets);
    }
    return;
  }
  if (state.masterSkyTargets) {
    state.allSkyTargets = filterMasterSkyTargets();
    if (state.skyScope === "all") {
      renderSkyMap(state.targets);
    }
  } else if (!state.allSkyLoading && state.skyScope === "all") {
    fetchAllSkyPositions();
  }
}

// ----------------------------------------------------------------------------
// Sky Map (Celestial Coordinates RA / Dec)
// ----------------------------------------------------------------------------
async function fetchAllSkyPositions() {
  if (state.masterSkyTargets) {
    state.allSkyTargets = filterMasterSkyTargets();
    renderSkyMap(state.targets);
    return;
  }
  if (state.allSkyLoading) return;
  state.allSkyLoading = true;

  if (elements.skyMapCount) {
    elements.skyMapCount.innerHTML = `<span style="display:inline-block;width:12px;height:12px;border:2px solid #38bdf8;border-top-color:transparent;border-radius:50%;animation:spin 0.8s linear infinite;vertical-align:middle;margin-right:4px;"></span> Loading all celestial coordinates...`;
  }

  // Request all celestial coordinates with full attributes once (unconditional)
  const params = new URLSearchParams({ limit: 500000 });

  try {
    const res = await fetch(`/api/targets/sky_positions?${params.toString()}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    state.masterSkyTargets = data.targets || [];
    state.allSkyTargets = filterMasterSkyTargets();
    renderSkyMap(state.targets);
  } catch (err) {
    console.error("Failed to load all sky positions:", err);
    if (elements.skyMapCount) elements.skyMapCount.textContent = "Error loading coordinates";
  } finally {
    state.allSkyLoading = false;
  }
}

// ----------------------------------------------------------------------------
// Mollweide Celestial Projection Math & Graticules
// ----------------------------------------------------------------------------
function solveMollweideTheta(phi) {
  if (Math.abs(phi) >= Math.PI / 2 - 1e-7) return Math.sign(phi) * (Math.PI / 2);
  if (Math.abs(phi) < 1e-7) return 0;
  const piSinPhi = Math.PI * Math.sin(phi);
  let theta = phi;
  for (let iter = 0; iter < 10; iter++) {
    const delta = (2 * theta + Math.sin(2 * theta) - piSinPhi) / (2 + 2 * Math.cos(2 * theta));
    theta -= delta;
    if (Math.abs(delta) < 1e-6) break;
  }
  return theta;
}

function projectMollweide(raDeg, decDeg, ra0Deg = 180) {
  let deltaLambda = (raDeg - ra0Deg) * (Math.PI / 180);
  while (deltaLambda > Math.PI) deltaLambda -= 2 * Math.PI;
  while (deltaLambda < -Math.PI) deltaLambda += 2 * Math.PI;

  const phi = decDeg * (Math.PI / 180);
  const theta = solveMollweideTheta(phi);
  const sqrt2 = Math.SQRT2;
  const x = (2 * sqrt2 / Math.PI) * deltaLambda * Math.cos(theta);
  const y = sqrt2 * Math.sin(theta);
  return { x, y };
}

function unprojectMollweide(x, y, ra0Deg = 180) {
  const sqrt2 = Math.SQRT2;
  const clampedY = Math.max(-sqrt2, Math.min(sqrt2, y));
  const theta = Math.asin(clampedY / sqrt2);
  const cosTheta = Math.cos(theta);

  // Dec: sin(phi) = (2*theta + sin(2*theta)) / PI
  const sinPhi = (2 * theta + Math.sin(2 * theta)) / Math.PI;
  const clampedSinPhi = Math.max(-1, Math.min(1, sinPhi));
  const phi = Math.asin(clampedSinPhi);
  const dec = phi * (180 / Math.PI);

  // RA: x = (2 * sqrt2 / PI) * deltaLambda * cos(theta)
  let deltaLambdaDeg = 0;
  if (Math.abs(cosTheta) > 1e-5) {
    const deltaLambdaRad = (x * Math.PI) / (2 * sqrt2 * cosTheta);
    deltaLambdaDeg = deltaLambdaRad * (180 / Math.PI);
  }
  const ra = ((ra0Deg + deltaLambdaDeg) % 360 + 360) % 360;

  // Check if point is inside or very close to the Mollweide boundary ellipse: x^2 / 8 + y^2 / 2 <= 1
  const insideEllipse = (x * x) / 8 + (y * y) / 2 <= 1.05;

  return { ra, dec, deltaLambdaDeg, insideEllipse };
}

function getVisibleSkyBounds() {
  const el = elements.skyPlotly;
  if (!el || !el._fullLayout) return null;
  const xa = el._fullLayout.xaxis;
  const ya = el._fullLayout.yaxis;
  if (!xa || !ya || !xa.range || !ya.range) return null;

  const x0 = xa.range[0]; // left in screen (positive in Mollweide East=Left)
  const x1 = xa.range[1]; // right in screen (negative)
  const y0 = ya.range[0]; // bottom
  const y1 = ya.range[1]; // top

  const xMin = Math.min(x0, x1);
  const xMax = Math.max(x0, x1);
  const yMin = Math.min(y0, y1);
  const yMax = Math.max(y0, y1);

  const xSpan = xMax - xMin;
  const ySpan = yMax - yMin;

  // Check if view covers practically the entire all-sky ellipse (default span is 6.50 x 3.25)
  if (xSpan >= 6.1 && ySpan >= 3.05) {
    return { isFullSky: true };
  }

  const ra0 = state.skyCentralRa || 180;
  const validPoints = [];

  // Sample the visible viewport on a 20x20 grid
  const nSteps = 20;
  for (let i = 0; i <= nSteps; i++) {
    const x = xMin + (i / nSteps) * xSpan;
    for (let j = 0; j <= nSteps; j++) {
      const y = yMin + (j / nSteps) * ySpan;
      const pt = unprojectMollweide(x, y, ra0);
      if (pt.insideEllipse && Math.abs(pt.deltaLambdaDeg) <= 180.1) {
        validPoints.push(pt);
      }
    }
  }

  if (validPoints.length === 0) {
    return null;
  }

  let minDec = 90, maxDec = -90;
  validPoints.forEach((p) => {
    if (p.dec < minDec) minDec = p.dec;
    if (p.dec > maxDec) maxDec = p.dec;
  });

  let minDelta = 180, maxDelta = -180;
  validPoints.forEach((p) => {
    if (p.deltaLambdaDeg < minDelta) minDelta = p.deltaLambdaDeg;
    if (p.deltaLambdaDeg > maxDelta) maxDelta = p.deltaLambdaDeg;
  });

  minDelta = Math.max(-180, minDelta);
  maxDelta = Math.min(180, maxDelta);

  if (maxDelta - minDelta >= 350) {
    return {
      isFullSky: false,
      min_ra: null,
      max_ra: null,
      min_dec: parseFloat(minDec.toFixed(2)),
      max_dec: parseFloat(maxDec.toFixed(2)),
      ra0,
    };
  }

  const raWest = ((ra0 + minDelta) % 360 + 360) % 360;
  const raEast = ((ra0 + maxDelta) % 360 + 360) % 360;

  return {
    isFullSky: false,
    min_ra: parseFloat(raWest.toFixed(2)),
    max_ra: parseFloat(raEast.toFixed(2)),
    min_dec: parseFloat(minDec.toFixed(2)),
    max_dec: parseFloat(maxDec.toFixed(2)),
    minDelta,
    maxDelta,
    ra0,
  };
}

function getSpatialFilterBoxTrace(filter, ra0Deg) {
  if (!filter || (filter.min_ra === null && filter.min_dec === null)) return null;

  const minDec = filter.min_dec !== null ? filter.min_dec : -90;
  const maxDec = filter.max_dec !== null ? filter.max_dec : 90;

  const boxX = [];
  const boxY = [];
  const nSeg = 24;

  const minRa = filter.min_ra;
  const maxRa = filter.max_ra;

  if (minRa !== null && maxRa !== null) {
    let raSpan = maxRa - minRa;
    if (raSpan < 0) raSpan += 360;

    // 1. Bottom edge: minDec, from minRa to maxRa
    for (let i = 0; i <= nSeg; i++) {
      const ra = (minRa + (i / nSeg) * raSpan) % 360;
      const pt = projectMollweide(ra, minDec, ra0Deg);
      boxX.push(pt.x);
      boxY.push(pt.y);
    }
    // 2. East edge: maxRa, from minDec to maxDec
    for (let i = 0; i <= nSeg; i++) {
      const dec = minDec + (i / nSeg) * (maxDec - minDec);
      const pt = projectMollweide(maxRa, dec, ra0Deg);
      boxX.push(pt.x);
      boxY.push(pt.y);
    }
    // 3. Top edge: maxDec, from maxRa back to minRa
    for (let i = 0; i <= nSeg; i++) {
      const ra = (maxRa - (i / nSeg) * raSpan + 360) % 360;
      const pt = projectMollweide(ra, maxDec, ra0Deg);
      boxX.push(pt.x);
      boxY.push(pt.y);
    }
    // 4. West edge: minRa, from maxDec back to minDec
    for (let i = 0; i <= nSeg; i++) {
      const dec = maxDec - (i / nSeg) * (maxDec - minDec);
      const pt = projectMollweide(minRa, dec, ra0Deg);
      boxX.push(pt.x);
      boxY.push(pt.y);
    }
  } else {
    for (let ra = 0; ra <= 360; ra += 10) {
      const pt = projectMollweide(ra, minDec, ra0Deg);
      boxX.push(pt.x); boxY.push(pt.y);
    }
    for (let ra = 360; ra >= 0; ra -= 10) {
      const pt = projectMollweide(ra, maxDec, ra0Deg);
      boxX.push(pt.x); boxY.push(pt.y);
    }
  }

  return {
    type: "scatter",
    mode: "lines",
    name: "Selected View Region",
    x: boxX,
    y: boxY,
    line: {
      color: "#38bdf8",
      width: 2.2,
      dash: "dash",
    },
    fill: "toself",
    fillcolor: "rgba(56, 189, 248, 0.12)",
    hoverinfo: "none",
    showlegend: true,
  };
}

function updateSpatialFilterUI() {
  const f = state.spatialFilter;
  if (!f) {
    if (elements.spatialFilterBadge) elements.spatialFilterBadge.style.display = "none";
    if (elements.skySpatialBadge) elements.skySpatialBadge.style.display = "none";
    return;
  }

  let text = "";
  if (f.min_ra !== null && f.max_ra !== null) {
    text = `RA: ${f.min_ra.toFixed(1)}°–${f.max_ra.toFixed(1)}°, Dec: ${f.min_dec > 0 ? "+" : ""}${f.min_dec.toFixed(1)}°–${f.max_dec > 0 ? "+" : ""}${f.max_dec.toFixed(1)}°`;
  } else {
    text = `Dec: ${f.min_dec > 0 ? "+" : ""}${f.min_dec.toFixed(1)}°–${f.max_dec > 0 ? "+" : ""}${f.max_dec.toFixed(1)}°`;
  }

  if (elements.spatialFilterText) elements.spatialFilterText.textContent = text;
  if (elements.spatialFilterBadge) elements.spatialFilterBadge.style.display = "inline-flex";
  if (elements.skySpatialBadge) elements.skySpatialBadge.style.display = "inline-flex";
}

function applySpatialFilter(bounds) {
  state.spatialFilter = bounds;
  updateSpatialFilterUI();
  state.page = 1;
  updatePlottedSkyTargets();
  fetchTargets();
}

function clearSpatialFilter() {
  state.spatialFilter = null;
  updateSpatialFilterUI();
  state.page = 1;
  updatePlottedSkyTargets();
  fetchTargets();
}

function degToRaHours(deg) {
  const norm = ((deg % 360) + 360) % 360;
  const totalHours = norm / 15;
  const h = Math.floor(totalHours);
  const m = Math.floor((totalHours - h) * 60);
  const s = (((totalHours - h) * 60 - m) * 60).toFixed(1);
  return `${h}h ${m}m ${s}s`;
}

function formatRaDegrees(deg) {
  const norm = ((deg % 360) + 360) % 360;
  const totalHours = norm / 15;
  const h = Math.floor(totalHours);
  const m = Math.round((totalHours - h) * 60);
  const padM = String(m === 60 ? 0 : m).padStart(2, "0");
  const displayH = m === 60 ? (h + 1) % 24 : h;
  return `${Math.round(norm)}° (${displayH}h ${padM}m)`;
}

function updateSkyRotationUI(ra0) {
  const norm = ((ra0 % 360) + 360) % 360;
  if (elements.skyRa0Slider) {
    elements.skyRa0Slider.value = norm;
  }
  if (elements.skyRa0Value) {
    elements.skyRa0Value.textContent = formatRaDegrees(norm);
  }
  document.querySelectorAll(".preset-ra-btn").forEach((btn) => {
    const btnRa = parseFloat(btn.dataset.ra0);
    if (Math.abs(btnRa - norm) < 1e-3) {
      btn.classList.add("active");
    } else {
      btn.classList.remove("active");
    }
  });
}

function setSkyCentralRa(newRa0) {
  state.skyCentralRa = ((newRa0 % 360) + 360) % 360;
  updateSkyRotationUI(state.skyCentralRa);
  renderSkyMap(state.targets);
}

function calculateMeanRa(targets) {
  const valid = (targets || []).filter((t) => t.ra !== null && t.ra !== undefined && !isNaN(t.ra));
  if (valid.length === 0) return 180;
  let sumSin = 0, sumCos = 0;
  valid.forEach((t) => {
    const rad = t.ra * (Math.PI / 180);
    sumSin += Math.sin(rad);
    sumCos += Math.cos(rad);
  });
  const meanRad = Math.atan2(sumSin, sumCos);
  const meanDeg = (meanRad * (180 / Math.PI) + 360) % 360;
  return Math.round(meanDeg / 5) * 5;
}

let _mollweideStaticBoundaryParallels = null;

function getMollweideStaticGraticules() {
  if (_mollweideStaticBoundaryParallels) return _mollweideStaticBoundaryParallels;

  const traces = [];
  const sqrt2 = Math.SQRT2;

  // 1. Outer Ellipse Boundary
  const bX = [], bY = [];
  const nSteps = 180;
  for (let i = 0; i <= nSteps; i++) {
    const t = (i / nSteps) * 2 * Math.PI;
    bX.push(2 * sqrt2 * Math.cos(t));
    bY.push(sqrt2 * Math.sin(t));
  }
  traces.push({
    type: "scatter",
    mode: "lines",
    x: bX,
    y: bY,
    line: { color: "rgba(56, 189, 248, 0.5)", width: 1.6 },
    hoverinfo: "none",
    showlegend: false,
    name: "Boundary",
  });

  // 2. Parallels of Declination (-60, -30, 0, +30, +60)
  const decs = [-60, -30, 0, 30, 60];
  decs.forEach((dec) => {
    const phi = dec * (Math.PI / 180);
    const theta = solveMollweideTheta(phi);
    const yVal = sqrt2 * Math.sin(theta);
    const xMax = 2 * sqrt2 * Math.cos(theta);
    traces.push({
      type: "scatter",
      mode: "lines",
      x: [-xMax, xMax],
      y: [yVal, yVal],
      line: {
        color: dec === 0 ? "rgba(255, 255, 255, 0.3)" : "rgba(255, 255, 255, 0.12)",
        width: dec === 0 ? 1.2 : 0.8,
        dash: dec === 0 ? "solid" : "dot",
      },
      hoverinfo: "none",
      showlegend: false,
    });
  });

  _mollweideStaticBoundaryParallels = traces;
  return _mollweideStaticBoundaryParallels;
}

function getMollweideGraticules(ra0Deg = 180) {
  const traces = [...getMollweideStaticGraticules()];

  // 3. Dynamic Meridians of Right Ascension (every 30 deg: 0, 30, ..., 330)
  for (let ra = 0; ra < 360; ra += 30) {
    let dRa = (ra - ra0Deg) % 360;
    if (dRa > 180) dRa -= 360;
    if (dRa < -180) dRa += 360;
    if (Math.abs(Math.abs(dRa) - 180) < 1e-4) continue; // Boundary already plotted

    const mX = [], mY = [];
    for (let dec = -90; dec <= 90; dec += 2) {
      const pt = projectMollweide(ra, dec, ra0Deg);
      mX.push(pt.x);
      mY.push(pt.y);
    }
    const isCentral = (Math.abs(dRa) < 1e-4);
    traces.push({
      type: "scatter",
      mode: "lines",
      x: mX,
      y: mY,
      line: {
        color: isCentral ? "rgba(56, 189, 248, 0.45)" : "rgba(255, 255, 255, 0.1)",
        width: isCentral ? 1.4 : 0.8,
        dash: isCentral ? "solid" : "dot",
      },
      hoverinfo: "none",
      showlegend: false,
    });
  }

  return traces;
}

function getMollweideAnnotations(ra0Deg = 180) {
  const annotations = [
    // Dec labels along central meridian
    { x: 0, y: 1.25, text: "+60°", showarrow: false, font: { color: "#64748b", size: 9 }, bgcolor: "rgba(11, 17, 32, 0.75)" },
    { x: 0, y: 0.73, text: "+30°", showarrow: false, font: { color: "#64748b", size: 9 }, bgcolor: "rgba(11, 17, 32, 0.75)" },
    { x: 0, y: -0.73, text: "-30°", showarrow: false, font: { color: "#64748b", size: 9 }, bgcolor: "rgba(11, 17, 32, 0.75)" },
    { x: 0, y: -1.25, text: "-60°", showarrow: false, font: { color: "#64748b", size: 9 }, bgcolor: "rgba(11, 17, 32, 0.75)" },

    // Celestial Poles
    { x: 0, y: 1.50, text: "NCP (+90°)", showarrow: false, font: { color: "#38bdf8", size: 10, weight: 600 } },
    { x: 0, y: -1.50, text: "SCP (-90°)", showarrow: false, font: { color: "#38bdf8", size: 10, weight: 600 } },

    // Celestial East / West labels (Astronomical standard: East is left)
    { x: 2.83, y: 1.25, text: "East (RA &rarr;)", showarrow: false, font: { color: "#38bdf8", size: 10 } },
    { x: -2.83, y: 1.25, text: "(&larr; RA) West", showarrow: false, font: { color: "#38bdf8", size: 10 } },
  ];

  // Dynamic RA labels along Equator (every 30 deg = 2h)
  for (let ra = 0; ra < 360; ra += 30) {
    let dRa = (ra - ra0Deg) % 360;
    if (dRa > 180) dRa -= 360;
    if (dRa < -180) dRa += 360;

    const pt = projectMollweide(ra, 0, ra0Deg);
    const xVal = pt.x;
    if (Math.abs(xVal) > 2.72) continue; // Skip edge boundary overlap

    const isCentral = (Math.abs(dRa) < 1e-4);
    const raH = ra / 15;
    const labelText = isCentral ? `${raH}h (${ra}°)` : `${raH}h`;

    annotations.push({
      x: parseFloat(xVal.toFixed(3)),
      y: -0.16,
      text: labelText,
      showarrow: false,
      font: {
        color: isCentral ? "#38bdf8" : "#64748b",
        size: isCentral ? 10 : 9,
        weight: isCentral ? 700 : 400,
      },
      yanchor: "top",
    });
  }

  return annotations;
}

function renderSkyMap(pageTargets) {
  if (!elements.skyPlotly) return;

  // Update scope button active state
  if (elements.skyScopePageBtn && elements.skyScopeAllBtn) {
    if (state.skyScope === "all") {
      elements.skyScopePageBtn.classList.remove("active");
      elements.skyScopeAllBtn.classList.add("active");
    } else {
      elements.skyScopePageBtn.classList.add("active");
      elements.skyScopeAllBtn.classList.remove("active");
    }
  }

  const isAll = state.skyScope === "all";

  // If "all" mode is selected but data not loaded yet, check master cache or fetch it
  if (isAll && !state.allSkyTargets) {
    if (state.masterSkyTargets) {
      state.allSkyTargets = filterMasterSkyTargets();
    } else {
      if (!state.allSkyLoading) {
        fetchAllSkyPositions();
      }
      return;
    }
  }

  const targetsToPlot = isAll ? (state.allSkyTargets || []) : (pageTargets || []);

  if (!targetsToPlot || targetsToPlot.length === 0) {
    elements.skyMapCount.textContent = "0 targets";
    Plotly.react(
      elements.skyPlotly,
      getMollweideGraticules(state.skyCentralRa),
      {
        plot_bgcolor: "#0b1120",
        paper_bgcolor: "#111827",
        annotations: [
          ...getMollweideAnnotations(state.skyCentralRa),
          {
            text: "No targets to display on sky map",
            xref: "paper",
            yref: "paper",
            x: 0.5,
            y: 0.5,
            showarrow: false,
            font: { color: "#9ca3af", size: 14 },
          },
        ],
        xaxis: { range: [3.25, -3.25], visible: false },
        yaxis: { range: [-1.625, 1.625], scaleanchor: "x", scaleratio: 1, visible: false },
        margin: { l: 15, r: 15, t: 25, b: 15 },
      },
      { responsive: true, displayModeBar: false }
    );
    return;
  }

  const validTargets = targetsToPlot.filter(
    (t) => t.ra !== null && t.ra !== undefined && !isNaN(t.ra) &&
           t.dec !== null && t.dec !== undefined && !isNaN(t.dec)
  );

  const scopeLabel = isAll ? "All Filtered" : `Page ${state.page}`;
  elements.skyMapCount.textContent = `${validTargets.length.toLocaleString()} targets plotted (${scopeLabel})`;

  if (validTargets.length === 0) {
    Plotly.react(
      elements.skyPlotly,
      getMollweideGraticules(state.skyCentralRa),
      {
        plot_bgcolor: "#0b1120",
        paper_bgcolor: "#111827",
        annotations: [
          ...getMollweideAnnotations(state.skyCentralRa),
          {
            text: "No celestial coordinates (RA/Dec) recorded for current targets",
            xref: "paper",
            yref: "paper",
            x: 0.5,
            y: 0.5,
            showarrow: false,
            font: { color: "#9ca3af", size: 14 },
          },
        ],
        xaxis: { range: [3.25, -3.25], visible: false },
        yaxis: { range: [-1.625, 1.625], scaleanchor: "x", scaleratio: 1, visible: false },
        margin: { l: 15, r: 15, t: 25, b: 15 },
      },
      { responsive: true, displayModeBar: false }
    );
    return;
  }

  const groups = {
    GALAXY: { name: "Galaxy", color: "#38bdf8", symbol: "circle", x: [], y: [], customdata: [] },
    QSO: { name: "QSO", color: "#c084fc", symbol: "diamond", x: [], y: [], customdata: [] },
    STAR: { name: "Star", color: "#fbbf24", symbol: "star", x: [], y: [], customdata: [] },
    UNKNOWN: { name: "Other", color: "#94a3b8", symbol: "circle", x: [], y: [], customdata: [] },
  };

  validTargets.forEach((t) => {
    const cls = t.classificationName || "UNKNOWN";
    const grp = groups[cls] || groups["UNKNOWN"];

    let zText = "";
    if (cls === "STAR" && typeof t.bestVelocity === "number") {
      zText = `Velocity: ${t.bestVelocity.toFixed(1)} km/s`;
    } else if (typeof t.bestRedshift === "number") {
      zText = `Redshift: z = ${t.bestRedshift.toFixed(4)}`;
    }

    const pt = projectMollweide(t.ra, t.dec, state.skyCentralRa);
    const raH = degToRaHours(t.ra);

    grp.x.push(pt.x);
    grp.y.push(pt.y);
    grp.customdata.push([t.catId, t.objId, t.obCode || "Target", cls, zText, t.ra, t.dec, raH]);
  });

  // Base graticules and boundary
  const traces = [...getMollweideGraticules(state.skyCentralRa)];
  const plotType = isAll ? "scattergl" : "scatter";

  ["GALAXY", "QSO", "STAR", "UNKNOWN"].forEach((key) => {
    const g = groups[key];
    if (g.x.length > 0) {
      traces.push({
        type: plotType,
        mode: "markers",
        name: `${g.name} (${g.x.length.toLocaleString()})`,
        x: g.x,
        y: g.y,
        customdata: g.customdata,
        marker: {
          color: g.color,
          symbol: g.symbol,
          size: isAll ? (key === "STAR" ? 6 : 4.5) : (key === "STAR" ? 11 : 9),
          opacity: isAll ? 0.75 : 0.9,
          line: isAll ? undefined : { color: "#0f172a", width: 1.5 },
        },
        hovertemplate:
          "<b>%{customdata[2]}</b> (objId: %{customdata[1]})<br>" +
          "catId: %{customdata[0]} &bull; %{customdata[3]}<br>" +
          "RA: %{customdata[5]:.4f}&deg; (%{customdata[7]}) | Dec: %{customdata[6]:.4f}&deg;<br>" +
          "%{customdata[4]}<br>" +
          "<span style='color:#38bdf8;font-size:11px;'>👆 Click marker to preview spectrum</span>" +
          "<extra></extra>",
      });
    }
  });

  // If in "All Filtered" mode, add an overlay trace for current page targets
  if (isAll && pageTargets && pageTargets.length > 0) {
    const pageValid = pageTargets.filter(
      (t) => t.ra !== null && t.ra !== undefined && !isNaN(t.ra) &&
             t.dec !== null && t.dec !== undefined && !isNaN(t.dec)
    );
    if (pageValid.length > 0) {
      const pagePts = pageValid.map((t) => projectMollweide(t.ra, t.dec, state.skyCentralRa));
      traces.push({
        type: "scatter",
        mode: "markers",
        name: `Current Page Focus (${pageValid.length})`,
        x: pagePts.map((p) => p.x),
        y: pagePts.map((p) => p.y),
        customdata: pageValid.map((t) => [
          t.catId,
          t.objId,
          t.obCode || "Target",
          t.classificationName || "UNKNOWN",
          "",
          t.ra,
          t.dec,
          degToRaHours(t.ra),
        ]),
        marker: {
          color: "rgba(255, 255, 255, 0.15)",
          symbol: "circle",
          size: 13,
          line: { color: "#ffffff", width: 2 },
        },
        hovertemplate:
          "<b>Page " + state.page + " Focus</b>: %{customdata[2]} (objId: %{customdata[1]})<br>" +
          "catId: %{customdata[0]} &bull; %{customdata[3]}<br>" +
          "RA: %{customdata[5]:.4f}&deg; (%{customdata[7]}) | Dec: %{customdata[6]:.4f}&deg;<br>" +
          "<span style='color:#38bdf8;font-size:11px;'>👆 Click marker to preview spectrum</span>" +
          "<extra></extra>",
      });
    }
  }

  // If a spatial view filter is active, draw the bounding box region
  if (state.spatialFilter) {
    const boxTrace = getSpatialFilterBoxTrace(state.spatialFilter, state.skyCentralRa);
    if (boxTrace) {
      traces.push(boxTrace);
    }
  }

  const layout = {
    paper_bgcolor: "#111827",
    plot_bgcolor: "#0b1120",
    margin: { l: 15, r: 15, t: 25, b: 15 },
    hovermode: "closest",
    dragmode: "pan",
    showlegend: true,
    legend: {
      orientation: "h",
      x: 0.5,
      y: 1.08,
      xanchor: "center",
      font: { color: "#9ca3af", size: 11 },
      bgcolor: "rgba(17, 24, 39, 0.8)",
      bordercolor: "rgba(255, 255, 255, 0.1)",
      borderwidth: 1,
    },
    annotations: getMollweideAnnotations(state.skyCentralRa),
    xaxis: {
      range: [3.25, -3.25], // Astronomical standard: RA increases to the left
      showgrid: false,
      zeroline: false,
      showticklabels: false,
      fixedrange: false,
    },
    yaxis: {
      range: [-1.625, 1.625],
      scaleanchor: "x",
      scaleratio: 1,
      showgrid: false,
      zeroline: false,
      showticklabels: false,
      fixedrange: false,
    },
  };

  const config = {
    responsive: true,
    displayModeBar: true,
    modeBarButtonsToRemove: ["lasso2d", "select2d"],
    displaylogo: false,
    scrollZoom: true,
  };

  Plotly.react(elements.skyPlotly, traces, layout, config);

  if (!elements.skyPlotly._hasClickHandler) {
    elements.skyPlotly._hasClickHandler = true;
    elements.skyPlotly.on("plotly_click", (data) => {
      if (data.points && data.points.length > 0) {
        const pt = data.points[0];
        const custom = pt.customdata;
        if (custom) {
          const [catId, objId, obCode] = custom;
          highlightTableRow(catId, objId);
          // Show PNG quick-look modal first, as requested
          openImagePreview(catId, objId, obCode);
        }
      }
    });

    elements.skyPlotly.on("plotly_hover", (data) => {
      if (data.points && data.points.length > 0) {
        const custom = data.points[0].customdata;
        if (custom) {
          highlightTableRow(custom[0], custom[1], false);
        }
      }
    });
  }
}

function zoomSkyMap(factor) {
  const el = elements.skyPlotly;
  if (!el || !el._fullLayout) return;
  const xa = el._fullLayout.xaxis;
  const ya = el._fullLayout.yaxis;
  if (!xa || !ya || !xa.range || !ya.range) return;

  const xCenter = (xa.range[0] + xa.range[1]) / 2;
  const xSpan = (xa.range[1] - xa.range[0]) * factor;
  const yCenter = (ya.range[0] + ya.range[1]) / 2;
  const ySpan = (ya.range[1] - ya.range[0]) * factor;

  Plotly.relayout(el, {
    "xaxis.range": [xCenter - xSpan / 2, xCenter + xSpan / 2],
    "yaxis.range": [yCenter - ySpan / 2, yCenter + ySpan / 2],
    "xaxis.autorange": false,
    "yaxis.autorange": false,
  });
}

function highlightTableRow(catId, objId, scrollIntoView = true) {
  document.querySelectorAll("#targetsTbody tr").forEach((row) => {
    row.classList.remove("row-highlighted");
  });
  const targetRow = document.querySelector(`#targetsTbody tr[data-catid="${catId}"][data-objid="${objId}"]`);
  if (targetRow) {
    targetRow.classList.add("row-highlighted");
    if (scrollIntoView) {
      targetRow.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }
  }
}

// ----------------------------------------------------------------------------
// Modal 1: Image Preview & Target Navigation
// ----------------------------------------------------------------------------
window.openImagePreview = function (catId, objId, obCode) {
  let list = state.targets || [];
  let index = list.findIndex((t) => t.catId == catId && String(t.objId) === String(objId));

  if (index === -1 && state.allSkyTargets && state.allSkyTargets.length > 0) {
    const skyIdx = state.allSkyTargets.findIndex((t) => t.catId == catId && String(t.objId) === String(objId));
    if (skyIdx !== -1) {
      list = state.allSkyTargets;
      index = skyIdx;
    }
  }

  if (index !== -1) {
    state.imagePreviewList = list;
    state.imagePreviewIndex = index;
    displayImagePreview(list[index], index, list.length);
  } else {
    state.imagePreviewList = [{ catId, objId, obCode }];
    state.imagePreviewIndex = 0;
    displayImagePreview({ catId, objId, obCode }, 0, 1);
  }

  elements.imageModal.style.display = "flex";
};

function displayImagePreview(target, index, total) {
  state.activeTarget = { ...target };

  elements.imageModalImg.style.opacity = "0.6";
  elements.imageModalImg.src = `/api/targets/${target.catId}/${target.objId}/image`;
  elements.imageModalImg.onload = () => {
    elements.imageModalImg.style.opacity = "1";
  };
  elements.imageModalImg.onerror = () => {
    elements.imageModalImg.style.opacity = "1";
  };

  elements.imageModalTitle.textContent = `Coadded Spectrum: ${target.obCode || ""} (objId: ${target.objId}, catId: ${target.catId})`;
  elements.imageModalDownload.href = `/api/targets/${target.catId}/${target.objId}/image`;

  const isPageList = state.imagePreviewList === state.targets;
  let subText = `Target ${index + 1} of ${total}`;

  if (isPageList && state.pages > 1) {
    const globalIdx = (state.page - 1) * state.limit + index + 1;
    subText = `Target ${globalIdx.toLocaleString()} of ${(state.total || 0).toLocaleString()} (Page ${state.page} • item ${index + 1} of ${total})`;
  } else if (state.imagePreviewList === state.allSkyTargets) {
    subText = `All Filtered • Target ${(index + 1).toLocaleString()} of ${total.toLocaleString()}`;
  }

  if (elements.imageModalSub) elements.imageModalSub.textContent = subText;

  const canPrev = isPageList ? index > 0 || state.page > 1 : index > 0;
  const canNext = isPageList ? index < total - 1 || state.page < state.pages : index < total - 1;

  updateImageNavButtons(canPrev, canNext);
  highlightTableRow(target.catId, target.objId);
}

function updateImageNavButtons(canPrev, canNext) {
  [elements.imageFloatPrevBtn, elements.imageFooterPrevBtn].forEach((btn) => {
    if (btn) btn.disabled = !canPrev;
  });
  [elements.imageFloatNextBtn, elements.imageFooterNextBtn].forEach((btn) => {
    if (btn) btn.disabled = !canNext;
  });
}

async function navigateImagePreview(direction) {
  if (!state.imagePreviewList || state.imagePreviewList.length === 0) return;

  const newIdx = state.imagePreviewIndex + direction;
  const list = state.imagePreviewList;
  const isPageList = list === state.targets;

  if (newIdx >= 0 && newIdx < list.length) {
    state.imagePreviewIndex = newIdx;
    displayImagePreview(list[newIdx], newIdx, list.length);
  } else if (isPageList) {
    if (direction > 0 && state.page < state.pages) {
      state.page++;
      await fetchTargets();
      state.imagePreviewList = state.targets;
      state.imagePreviewIndex = 0;
      if (state.targets && state.targets.length > 0) {
        displayImagePreview(state.targets[0], 0, state.targets.length);
      }
    } else if (direction < 0 && state.page > 1) {
      state.page--;
      await fetchTargets();
      state.imagePreviewList = state.targets;
      state.imagePreviewIndex = state.targets.length - 1;
      if (state.targets && state.targets.length > 0) {
        displayImagePreview(state.targets[state.imagePreviewIndex], state.imagePreviewIndex, state.targets.length);
      }
    }
  }
}

// ----------------------------------------------------------------------------
// Sky Cutout & Coordinate Formatting Utilities
// ----------------------------------------------------------------------------
function formatRaHms(ra) {
  if (ra === null || ra === undefined || isNaN(ra)) return "-";
  let normRa = ((ra % 360) + 360) % 360;
  let totalHours = normRa / 15.0;
  let h = Math.floor(totalHours);
  let remMinutes = (totalHours - h) * 60;
  let m = Math.floor(remMinutes);
  let s = (remMinutes - m) * 60;
  return `${String(h).padStart(2, "0")}h ${String(m).padStart(2, "0")}m ${s.toFixed(2).padStart(5, "0")}s`;
}

function formatDecDms(dec) {
  if (dec === null || dec === undefined || isNaN(dec)) return "-";
  let sign = dec < 0 ? "-" : "+";
  let absDec = Math.abs(dec);
  let d = Math.floor(absDec);
  let remMinutes = (absDec - d) * 60;
  let m = Math.floor(remMinutes);
  let s = (remMinutes - m) * 60;
  return `${sign}${String(d).padStart(2, "0")}° ${String(m).padStart(2, "0")}' ${s.toFixed(1).padStart(4, "0")}"`;
}

let currentCutoutRequestId = 0;

async function loadSkyCutout(ra, dec) {
  const reqId = ++currentCutoutRequestId;

  if (ra === null || dec === null || ra === undefined || dec === undefined || isNaN(ra) || isNaN(dec)) {
    if (elements.hscPreviewBanner) elements.hscPreviewBanner.style.display = "none";
    return;
  }
  if (elements.hscPreviewBanner) elements.hscPreviewBanner.style.display = "flex";

  const fovVal = parseFloat(elements.hscFovSelect ? elements.hscFovSelect.value : 0.008333) || 0.008333;
  const surveyVal = elements.hscSurveySelect ? elements.hscSurveySelect.value : "auto";

  // Coordinates text
  if (elements.hscRaVal) elements.hscRaVal.textContent = `${ra.toFixed(6)}°`;
  if (elements.hscDecVal) elements.hscDecVal.textContent = `${dec.toFixed(6)}°`;
  const hms = formatRaHms(ra);
  const dms = formatDecDms(dec);
  if (elements.hscSexagesimalVal) elements.hscSexagesimalVal.textContent = `${hms}, ${dms}`;

  // External Links
  // Note: hscMap (stellar-globe) requires camera coordinates (a, d, fovy) in RADIANS, not degrees!
  const aRad = (ra * Math.PI) / 180.0;
  const dRad = (dec * Math.PI) / 180.0;
  // Set hscMap FOV to ~3 arcmin (0.00087 rad) for optimal surrounding celestial context
  const fovyRad = Math.max(0.0005, (fovVal * Math.PI / 180.0) * 3);
  const hscState = {
    view: {
      a: aRad,
      d: dRad,
      fovy: fovyRad,
      roll: 0,
    },
    activeReruns: ["pdr3_wide", "pdr3_dud"],
  };
  const hscMapUrl = `https://hscmap.mtk.nao.ac.jp/hscMap4/app/#/?_=${encodeURIComponent(JSON.stringify(hscState))}`;
  if (elements.hscMapLinkBtn) elements.hscMapLinkBtn.href = hscMapUrl;

  const aladinUrl = `https://aladin.cds.unistra.fr/AladinLite/?target=${ra.toFixed(6)}%20${dec.toFixed(6)}&fov=${(fovVal * 2).toFixed(4)}&survey=P%2FPanSTARRS%2FDR1%2Fcolor-z-zg-g`;
  if (elements.aladinLinkBtn) elements.aladinLinkBtn.href = aladinUrl;

  const cutoutApiUrl = `/api/targets/cutout?ra=${ra}&dec=${dec}&fov=${fovVal}&width=300&height=300&survey=${surveyVal}`;
  if (elements.fullCutoutLinkBtn) elements.fullCutoutLinkBtn.href = cutoutApiUrl;

  // FOV indicator
  const fovArcsec = Math.round(fovVal * 3600);
  const fovText = `${fovArcsec}″`;
  if (elements.hscFovIndicator) elements.hscFovIndicator.textContent = fovText;
  if (elements.expandedFovIndicator) elements.expandedFovIndicator.textContent = fovText;

  // Calculate fiber aperture reticle pixel size (PFS fiber core diameter ~1.12 arcsec)
  const thumbnailPx = 140;
  const fiberScalePx = Math.max(4, Math.min(thumbnailPx, (1.12 / fovArcsec) * thumbnailPx));
  if (elements.hscFiberCircle) {
    elements.hscFiberCircle.style.width = `${fiberScalePx.toFixed(1)}px`;
    elements.hscFiberCircle.style.height = `${fiberScalePx.toFixed(1)}px`;
  }

  if (elements.expandedFiberCircle) {
    const expandedPx = 360;
    const expFiberScale = Math.max(6, Math.min(expandedPx, (1.12 / fovArcsec) * expandedPx));
    elements.expandedFiberCircle.style.width = `${expFiberScale.toFixed(1)}px`;
    elements.expandedFiberCircle.style.height = `${expFiberScale.toFixed(1)}px`;
  }

  // Update loading state
  if (elements.hscCutoutSpinner) elements.hscCutoutSpinner.style.display = "flex";
  if (elements.hscCutoutError) elements.hscCutoutError.style.display = "none";
  if (elements.hscCutoutImg) elements.hscCutoutImg.style.display = "none";
  if (elements.expandedSkySpinner) {
    elements.expandedSkySpinner.style.display = "flex";
    elements.expandedSkyError.style.display = "none";
    elements.expandedSkyImg.style.display = "none";
  }

  try {
    const resp = await fetch(cutoutApiUrl);
    if (reqId !== currentCutoutRequestId) return;

    if (!resp.ok) throw new Error("Cutout service unavailable");

    const surveyUsed = resp.headers.get("X-Survey-Used") || "hsc_wide";
    const surveyName = resp.headers.get("X-Survey-Name") || "Subaru HSC DR2";
    const isFallback = resp.headers.get("X-Is-Fallback") === "true";

    const blob = await resp.blob();
    if (reqId !== currentCutoutRequestId) return;

    const imgUrl = URL.createObjectURL(blob);

    if (elements.hscCutoutImg) {
      elements.hscCutoutImg.src = imgUrl;
      elements.hscCutoutImg.style.display = "block";
    }
    if (elements.hscCutoutSpinner) elements.hscCutoutSpinner.style.display = "none";

    if (elements.expandedSkyImg) {
      elements.expandedSkyImg.src = imgUrl;
      elements.expandedSkyImg.style.display = "block";
    }
    if (elements.expandedSkySpinner) elements.expandedSkySpinner.style.display = "none";

    // Update survey badge and title
    if (elements.hscSurveyTitle && elements.hscSurveyBadge) {
      if (isFallback) {
        elements.hscSurveyTitle.innerHTML = `🪐 Pan-STARRS Sky Cutout <small style="font-size:0.74rem; font-weight:400; color:#fbbf24;">(Fallback)</small>`;
        elements.hscSurveyBadge.textContent = surveyName;
        elements.hscSurveyBadge.classList.add("fallback");
      } else {
        elements.hscSurveyTitle.innerHTML = `🌌 Subaru HSC Sky Cutout`;
        elements.hscSurveyBadge.textContent = surveyName;
        elements.hscSurveyBadge.classList.remove("fallback");
      }
    }

    // Update expanded tab metadata
    if (elements.expandedSurveyName) elements.expandedSurveyName.textContent = surveyName;
    if (elements.expandedCoverageStatus) elements.expandedCoverageStatus.textContent = isFallback ? "Outside HSC Coverage (Pan-STARRS Fallback)" : "Within Subaru HSC Coverage";
    if (elements.expandedCoords) elements.expandedCoords.textContent = `RA: ${ra.toFixed(6)}°, Dec: ${dec.toFixed(6)}°`;
    if (elements.expandedSexagesimal) elements.expandedSexagesimal.textContent = `${hms}, ${dms}`;
    if (elements.expandedTargetInfo && state.activeTarget) {
      elements.expandedTargetInfo.textContent = `objId: ${state.activeTarget.objId}, obCode: ${state.activeTarget.obCode || "-"}`;
    }
    if (elements.expandedHscMapBtn) elements.expandedHscMapBtn.href = hscMapUrl;
    if (elements.expandedAladinBtn) elements.expandedAladinBtn.href = aladinUrl;

  } catch (err) {
    if (reqId !== currentCutoutRequestId) return;
    if (elements.hscCutoutSpinner) elements.hscCutoutSpinner.style.display = "none";
    if (elements.hscCutoutError) elements.hscCutoutError.style.display = "flex";
    if (elements.expandedSkySpinner) elements.expandedSkySpinner.style.display = "none";
    if (elements.expandedSkyError) elements.expandedSkyError.style.display = "flex";
  }
}

// ----------------------------------------------------------------------------
// Modal 2: Target Details
// ----------------------------------------------------------------------------
window.openTargetDetails = async function (catId, objId) {
  try {
    const res = await fetch(`/api/targets/${catId}/${objId}/details`);
    if (!res.ok) throw new Error("Target details not found");
    const data = await res.json();
    state.activeTarget = data.target;

    elements.detailsModalTitle.textContent = `Target Details: ${data.target.obCode || ""}`;
    elements.detailsModalSub.textContent = `objId: ${objId} | catId: ${catId} | combination: ${data.target.combination || ""}`;

    // 1. Redshift Candidates Table
    if (data.redshift_candidates && data.redshift_candidates.length > 0) {
      elements.candidatesTbody.innerHTML = data.redshift_candidates
        .map((c) => {
          const zStr = c.redshift !== null ? c.redshift.toFixed(5) : "-";
          const zErr = c.redshiftError !== null ? `&plusmn;${c.redshiftError.toFixed(5)}` : "";
          const probaStr = c.redshiftProba !== null ? (c.redshiftProba * 100).toFixed(1) + "%" : "-";
          const velStr = c.velocity !== null ? c.velocity.toFixed(1) : "-";
          const chiStr = c.reducedLeastSquare !== null ? c.reducedLeastSquare.toFixed(2) : "-";
          const pVal = c.pValue !== null ? c.pValue.toExponential(2) : "-";
          return `
          <tr>
            <td><strong>${c.objectType}</strong></td>
            <td>#${c.cRank}</td>
            <td>${zStr}</td>
            <td>${zErr}</td>
            <td>${probaStr}</td>
            <td>${velStr}</td>
            <td>${c.subClass || "-"}</td>
            <td>${chiStr}</td>
            <td>${pVal}</td>
            <td title="${c.templateFile || ""}">${c.templateFile || "-"}</td>
          </tr>
          `;
        })
        .join("");
    } else {
      elements.candidatesTbody.innerHTML = `<tr><td colspan="10" class="text-center text-muted">No candidate models recorded.</td></tr>`;
    }

    // 2. Line Measurements Table
    if (data.line_measurements && data.line_measurements.length > 0) {
      elements.linesTbody.innerHTML = data.line_measurements
        .map((l) => {
          const waveStr = l.lineWave !== null ? l.lineWave.toFixed(2) : "-";
          const zStr = l.lineZ !== null ? l.lineZ.toFixed(5) : "-";
          const zErr = l.lineZError !== null ? `&plusmn;${l.lineZError.toFixed(5)}` : "";

          // Flux formatting: in 10^-17 erg/s/cm^2 (cgs17), tooltip with SI W/m^2
          let fluxStr = "-";
          let fluxTooltip = "";
          if (l.lineFlux !== null && l.lineFlux !== undefined) {
            if (l.lineFlux === 0 || Math.abs(l.lineFlux) < 1e-32) {
              fluxStr = "0.0";
              fluxTooltip = "0.0 W/m²";
            } else {
              const cgsVal = l.lineFlux * 1e20;
              if (Math.abs(cgsVal) >= 100) {
                fluxStr = cgsVal.toFixed(1);
              } else if (Math.abs(cgsVal) >= 10) {
                fluxStr = cgsVal.toFixed(2);
              } else {
                fluxStr = cgsVal.toFixed(3);
              }
              fluxTooltip = `${l.lineFlux.toExponential(3)} W/m²`;
            }
          }

          let fluxErr = "";
          let fluxErrTooltip = "";
          if (l.lineFluxError !== null && l.lineFluxError !== undefined) {
            if (l.lineFluxError === 0 || Math.abs(l.lineFluxError) < 1e-32) {
              fluxErr = "&plusmn;0.0";
            } else {
              const cgsErr = l.lineFluxError * 1e20;
              let errStr = "";
              if (Math.abs(cgsErr) >= 100) {
                errStr = cgsErr.toFixed(1);
              } else if (Math.abs(cgsErr) >= 10) {
                errStr = cgsErr.toFixed(2);
              } else {
                errStr = cgsErr.toFixed(3);
              }
              fluxErr = `&plusmn;${errStr}`;
              fluxErrTooltip = `&plusmn;${l.lineFluxError.toExponential(3)} W/m²`;
            }
          }

          // Equivalent width: nm, tooltip with Angstroms (1 nm = 10 A)
          const ewStr = l.lineEW !== null ? l.lineEW.toFixed(2) : "-";
          const ewTooltip = l.lineEW !== null ? `${(l.lineEW * 10).toFixed(2)} Å` : "";
          const sigStr = l.lineSigma !== null ? l.lineSigma.toFixed(2) : "-";
          const contStr = l.lineContinuumLevel !== null ? l.lineContinuumLevel.toFixed(1) : "-";

          return `
          <tr>
            <td>${l.objectType}</td>
            <td><strong>${l.lineName || "-"}</strong></td>
            <td>${waveStr}</td>
            <td>${zStr}</td>
            <td>${zErr}</td>
            <td title="${fluxTooltip}">${fluxStr}</td>
            <td title="${fluxErrTooltip}">${fluxErr}</td>
            <td title="${ewTooltip}">${ewStr}</td>
            <td>${sigStr}</td>
            <td>${contStr}</td>
          </tr>
          `;
        })
        .join("");
    } else {
      elements.linesTbody.innerHTML = `<tr><td colspan="10" class="text-center text-muted">No line measurements recorded.</td></tr>`;
    }

    // 3. Solvers Table
    if (data.solver_results && data.solver_results.length > 0) {
      elements.solversTbody.innerHTML = data.solver_results
        .map((s) => `
        <tr>
          <td><strong>${s.objectType}</strong></td>
          <td>${s.nCandidates || 0}</td>
          <td>${s.zWarningName || s.zWarningValue || "-"}</td>
          <td>${s.zErrorCode || "-"}</td>
          <td>${s.lWarningName || s.lWarningValue || "-"}</td>
          <td>${s.lErrorCode || "-"}</td>
        </tr>
        `)
        .join("");
    } else {
      elements.solversTbody.innerHTML = `<tr><td colspan="6" class="text-center text-muted">No solver flags recorded.</td></tr>`;
    }

    // 4. Metadata Grid
    const t = data.target;
    elements.metaGrid.innerHTML = `
      <div class="meta-item"><div class="meta-label">Target ID</div><div class="meta-val">${t.objId}</div></div>
      <div class="meta-item"><div class="meta-label">obCode</div><div class="meta-val">${t.obCode || "-"}</div></div>
      <div class="meta-item"><div class="meta-label">Catalog ID</div><div class="meta-val">${t.catId}</div></div>
      <div class="meta-item"><div class="meta-label">Coordinates (RA, Dec)</div><div class="meta-val">${t.ra ? t.ra.toFixed(6) : "-"}, ${t.dec ? t.dec.toFixed(6) : "-"}</div></div>
      <div class="meta-item"><div class="meta-label">Target Type</div><div class="meta-val">${t.targetTypeName || "-"}</div></div>
      <div class="meta-item"><div class="meta-label">Fiber Status</div><div class="meta-val">${t.fiberStatusName || "-"}</div></div>
      <div class="meta-item"><div class="meta-label">Classification</div><div class="meta-val">${t.classificationName || "-"}</div></div>
      <div class="meta-item"><div class="meta-label">Best Redshift / Velocity</div><div class="meta-val">${t.bestRedshift !== null ? "z=" + t.bestRedshift.toFixed(5) : t.bestVelocity !== null ? t.bestVelocity.toFixed(1) + " km/s" : "-"}</div></div>
      <div class="meta-item"><div class="meta-label">Has Solution</div><div class="meta-val">${t.hasSolution ? "Yes" : "No"}</div></div>
      <div class="meta-item"><div class="meta-label">FITS File</div><div class="meta-val">${data.files.fits_filename || "Not found"}</div></div>
      <div class="meta-item"><div class="meta-label">PNG Image</div><div class="meta-val">${data.files.png_filename || "Not found"}</div></div>
    `;

    // 5. Load Subaru HSC / Pan-STARRS Cutout Preview
    if (t.ra !== null && t.dec !== null && t.ra !== undefined && t.dec !== undefined && !isNaN(t.ra) && !isNaN(t.dec)) {
      loadSkyCutout(t.ra, t.dec);
    } else {
      if (elements.hscPreviewBanner) elements.hscPreviewBanner.style.display = "none";
    }

    elements.detailsModal.style.display = "flex";
  } catch (err) {
    alert("Error loading details: " + err.message);
  }
};

// ----------------------------------------------------------------------------
// Modal 3: Interactive FITS Spectrum (Plotly.js)
// ----------------------------------------------------------------------------
window.openInteractiveSpectrumById = async function (catId, objId) {
  try {
    const res = await fetch(`/api/targets/${catId}/${objId}/details`);
    if (res.ok) {
      const data = await res.json();
      openInteractiveSpectrum(data.target);
    } else {
      openInteractiveSpectrum({ catId, objId });
    }
  } catch (e) {
    openInteractiveSpectrum({ catId, objId });
  }
};

window.openInteractiveSpectrum = async function (target) {
  if (!target) return;
  const catId = target.catId;
  const objId = target.objId;

  // If target lacks bestRedshift or classificationName (e.g., opened from minimal context), fetch full details
  if (target.bestRedshift === undefined && target.bestVelocity === undefined) {
    try {
      const res = await fetch(`/api/targets/${catId}/${objId}/details`);
      if (res.ok) {
        const data = await res.json();
        target = { ...target, ...data.target };
      }
    } catch (e) {
      console.warn("Could not fetch target details for spectrum:", e);
    }
  }

  state.activeTarget = target;

  elements.spectrumModalTitle.textContent = `Interactive Spectrum: ${target.obCode || ""} (objId: ${objId})`;
  elements.spectrumModalSub.textContent = `catId: ${catId} | Class: ${target.classificationName || "UNKNOWN"}`;
  elements.downloadFitsBtn.href = `/api/targets/${catId}/${objId}/fits`;

  // Determine initial redshift
  let initZ = 0.0;
  if (target.classificationName === "STAR" && target.bestVelocity !== null && target.bestVelocity !== undefined) {
    initZ = target.bestVelocity / C_KMS;
  } else if (target.bestRedshift !== null && target.bestRedshift !== undefined && !isNaN(target.bestRedshift)) {
    initZ = target.bestRedshift;
  }
  state.bestZ = initZ;
  state.activeZ = initZ;

  // Adjust slider max if z > 8
  const sliderMax = Math.max(8, Math.ceil(initZ + 0.5));
  elements.interactiveZSlider.max = sliderMax;

  elements.interactiveZInput.value = initZ.toFixed(4);
  elements.interactiveZSlider.value = Math.min(Math.max(initZ, 0), sliderMax);

  elements.spectrumModal.style.display = "flex";
  elements.plotlyLoading.style.display = "flex";

  try {
    const res = await fetch(`/api/targets/${catId}/${objId}/spectrum`);
    if (!res.ok) throw new Error("FITS spectrum file could not be loaded.");
    const data = await res.json();
    state.rawSpectrumData = data;

    // Render observation table
    if (data.observations && data.observations.length > 0) {
      elements.obsCount.textContent = data.observations.length;
      elements.obsTbody.innerHTML = data.observations
        .map((o) => `
        <tr>
          <td>${o.visit || "-"}</td>
          <td><strong>${o.arm || "-"}</strong></td>
          <td>${o.spectrograph || "-"}</td>
          <td>${o.fiberId || "-"}</td>
          <td>${o.expTime ? o.expTime.toFixed(1) : "-"}</td>
          <td>${o.obsTime || "-"}</td>
        </tr>
        `)
        .join("");
    } else {
      elements.obsCount.textContent = "0";
      elements.obsTbody.innerHTML = `<tr><td colspan="6" class="text-center text-muted">No individual exposure records found.</td></tr>`;
    }

    renderPlotlyChart();
  } catch (err) {
    elements.plotlyLoading.style.display = "none";
    elements.plotlyChart.innerHTML = `<div class="empty-state"><h3>⚠️ ${err.message}</h3><p>Ensure the FITS file exists in extracted_targets/fits/.</p></div>`;
  }
};

/**
 * Inverse-variance binning for spectrum
 */
function binSpectrum(wave, flux, variance, binWidth) {
  if (!binWidth || binWidth <= 0) {
    return { wave, flux, variance };
  }
  const minW = wave[0];
  const maxW = wave[wave.length - 1];
  const nBins = Math.floor((maxW - minW) / binWidth);

  const bWave = [];
  const bFlux = [];
  const bVar = [];

  let idx = 0;
  for (let i = 0; i < nBins; i++) {
    const edgeStart = minW + i * binWidth;
    const edgeEnd = edgeStart + binWidth;

    let wSum = 0;
    let wfSum = 0;
    let count = 0;

    while (idx < wave.length && wave[idx] < edgeEnd) {
      const w = wave[idx];
      const f = flux[idx];
      const v = variance ? variance[idx] : null;

      if (f !== null && !isNaN(f) && v !== null && v > 0) {
        const weight = 1.0 / v;
        wSum += weight;
        wfSum += f * weight;
        count++;
      }
      idx++;
    }

    if (count > 0 && wSum > 0) {
      bWave.push(0.5 * (edgeStart + edgeEnd));
      bFlux.push(wfSum / wSum);
      bVar.push(1.0 / wSum);
    }
  }

  return { wave: bWave, flux: bFlux, variance: bVar };
}

function renderPlotlyChart() {
  if (!state.rawSpectrumData) return;
  elements.plotlyLoading.style.display = "none";

  const raw = state.rawSpectrumData;
  const binWidth = parseFloat(elements.specBinningSelect.value);

  // Filter valid points
  const rawW = [];
  const rawF = [];
  const rawV = [];
  const badW = [];
  const badF = [];

  for (let i = 0; i < raw.wavelength.length; i++) {
    const w = raw.wavelength[i];
    const f = raw.flux[i];
    const v = raw.variance ? raw.variance[i] : 1;
    const m = raw.mask ? raw.mask[i] : 0;

    // Mask check (typical PFS bad mask bits: BAD(0), CR(1), NO_DATA(3), SAT(4))
    const isBad = m && (m & ((1 << 0) | (1 << 1) | (1 << 3) | (1 << 4))) !== 0;

    if (isBad) {
      badW.push(w);
      badF.push(f);
    } else if (f !== null && !isNaN(f)) {
      rawW.push(w);
      rawF.push(f);
      rawV.push(v);
    }
  }

  // Binning
  const binned = binSpectrum(rawW, rawF, rawV, binWidth);

  const traces = [];

  // 1. Noise envelope (1-sigma upper & lower)
  if (elements.toggleNoise.checked && binned.variance && binned.variance.length > 0) {
    const upperY = [];
    const lowerY = [];
    for (let i = 0; i < binned.flux.length; i++) {
      const sig = Math.sqrt(binned.variance[i]);
      upperY.push(binned.flux[i] + sig);
      lowerY.push(binned.flux[i] - sig);
    }

    traces.push({
      x: binned.wave.concat(binned.wave.slice().reverse()),
      y: upperY.concat(lowerY.slice().reverse()),
      fill: "toself",
      fillcolor: "rgba(148, 163, 184, 0.15)",
      line: { color: "transparent" },
      name: "1σ Noise Envelope",
      hoverinfo: "skip",
      type: "scatter",
    });
  }

  // 2. Coadded Flux Line
  traces.push({
    x: binned.wave,
    y: binned.flux,
    mode: "lines",
    line: { color: "#38bdf8", width: 1.2 },
    name: binWidth > 0 ? `Flux (${binWidth} nm bin)` : "Flux (Raw)",
    hovertemplate: "<b>λ:</b> %{x:.2f} nm<br><b>Flux:</b> %{y:.2f} nJy<extra></extra>",
    type: "scatter",
  });

  // 3. Bad Pixels
  if (elements.toggleBadPixels.checked && badW.length > 0) {
    traces.push({
      x: badW,
      y: badF,
      mode: "markers",
      marker: { color: "#f43f5e", size: 3, opacity: 0.5 },
      name: "Bad Pixels",
      hovertemplate: "<b>Bad λ:</b> %{x:.2f} nm<extra></extra>",
      type: "scatter",
    });
  }

  // Calculate robust Y range
  const sortedF = binned.flux.filter((v) => v !== null && !isNaN(v)).sort((a, b) => a - b);
  let ymin = -10;
  let ymax = 100;
  if (sortedF.length > 10) {
    const p05 = sortedF[Math.floor(sortedF.length * 0.05)];
    const p95 = sortedF[Math.floor(sortedF.length * 0.95)];
    ymax = Math.max(p95 * 1.5, 10);
    ymin = Math.min(p05 * 1.1, -ymax * 0.1);
  }

  const { shapes, annotations } = getSpectralLineShapes(ymin, ymax);

  const layout = {
    paper_bgcolor: "#111827",
    plot_bgcolor: "#0b0f19",
    margin: { l: 60, r: 30, t: 30, b: 50 },
    xaxis: {
      title: { text: "Wavelength [nm]", font: { color: "#94a3b8", size: 12 } },
      gridcolor: "rgba(255, 255, 255, 0.06)",
      tickfont: { color: "#cbd5e1", family: "JetBrains Mono" },
      zerolinecolor: "rgba(255, 255, 255, 0.15)",
    },
    yaxis: {
      title: { text: "Flux [nJy]", font: { color: "#94a3b8", size: 12 } },
      gridcolor: "rgba(255, 255, 255, 0.06)",
      tickfont: { color: "#cbd5e1", family: "JetBrains Mono" },
      range: [ymin, ymax],
      zerolinecolor: "rgba(255, 255, 255, 0.15)",
    },
    showlegend: true,
    legend: {
      x: 0.01,
      y: 0.99,
      bgcolor: "rgba(17, 24, 39, 0.7)",
      bordercolor: "rgba(255, 255, 255, 0.1)",
      borderwidth: 1,
      font: { color: "#cbd5e1", size: 10 },
    },
    shapes: shapes,
    annotations: annotations,
    hovermode: "closest",
  };

  const config = {
    responsive: true,
    displayModeBar: true,
    modeBarButtonsToRemove: ["lasso2d", "select2d"],
    displaylogo: false,
  };

  Plotly.react(elements.plotlyChart, traces, layout, config);

  if (!elements.plotlyChart._hasRelayoutListener) {
    elements.plotlyChart.on("plotly_relayout", (eventData) => {
      // Ensure shapes and annotations remain anchored and synchronized during user zoom / pan / reset
      if (eventData && (eventData["xaxis.range[0]"] || eventData["yaxis.range[0]"] || eventData["xaxis.autorange"] || eventData["yaxis.autorange"])) {
        // yref: "paper" ensures Plotly natively keeps annotations at the top of the viewport
      }
    });
    elements.plotlyChart._hasRelayoutListener = true;
  }
}

/**
 * Generate Plotly vertical line shapes and text annotations for spectral lines.
 * Uses yref: "paper" (0 to 1) so lines span the full visible height and text labels
 * remain permanently pinned at the top of the viewport, regardless of any Y-axis zooming,
 * scaling, or panning.
 */
function getSpectralLineShapes(ymin, ymax) {
  const shapes = [];
  const annotations = [];

  const z = state.activeZ;
  if (z === null || isNaN(z)) return { shapes, annotations };

  const showEmission = elements.toggleEmissionLines.checked;
  const showAbsorption = elements.toggleAbsorptionLines.checked;

  let stagger = 0;
  SPECTRAL_LINES.forEach((line) => {
    if (line.type === "emission" && !showEmission) return;
    if (line.type === "absorption" && !showAbsorption) return;

    const obsWave = line.wave * (1.0 + z);
    if (obsWave < 350 || obsWave > 1300) return; // Outside PFS optical/NIR range

    const isEmission = line.type === "emission";
    const color = isEmission ? "#38bdf8" : "#f43f5e";

    // 1. Vertical dashed line spanning full visible viewport
    shapes.push({
      type: "line",
      xref: "x",
      x0: obsWave,
      x1: obsWave,
      yref: "paper",
      y0: 0,
      y1: 1,
      line: {
        color: color,
        width: 1,
        dash: "dash",
      },
    });

    // 2. Line label pinned near the top of the visible viewport
    const yPaperPos = 0.95 - (stagger % 3) * 0.08;
    stagger++;

    annotations.push({
      x: obsWave,
      xref: "x",
      y: yPaperPos,
      yref: "paper",
      text: line.name,
      showarrow: false,
      textangle: -90,
      font: { color: color, size: 9, family: "JetBrains Mono" },
      bgcolor: "rgba(11, 15, 25, 0.75)",
      bordercolor: color,
      borderwidth: 0.5,
      borderpad: 2,
    });
  });

  return { shapes, annotations };
}

/**
 * High-performance layout relayout for real-time redshift slider
 */
function updateSpectralLineShapes() {
  if (!elements.plotlyChart || !elements.plotlyChart.layout) return;
  const { shapes, annotations } = getSpectralLineShapes();

  Plotly.relayout(elements.plotlyChart, {
    shapes: shapes,
    annotations: annotations,
  });
}
