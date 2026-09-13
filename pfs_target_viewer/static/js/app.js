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
  order: "desc",
  total: 0,
  pages: 1,
  loading: false,

  // Active modal targets
  activeTarget: null,
  rawSpectrumData: null,
  activeZ: null,
  bestZ: null,

  // Sky Map Scope & Cache
  skyScope: "page", // "page" or "all"
  allSkyTargets: null,
  allSkyLoading: false,
  lastFilterKey: null,
  targets: [],
};

// DOM Element Selectors
const elements = {
  searchInput: document.getElementById("searchInput"),
  clearSearchBtn: document.getElementById("clearSearchBtn"),
  classPills: document.getElementById("classPills"),
  catIdSelect: document.getElementById("catIdSelect"),
  minZInput: document.getElementById("minZInput"),
  maxZInput: document.getElementById("maxZInput"),
  sortBySelect: document.getElementById("sortBySelect"),
  pageSizeSelect: document.getElementById("pageSizeSelect"),
  resetFiltersBtn: document.getElementById("resetFiltersBtn"),

  resultsCount: document.getElementById("resultsCount"),
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
  imageModalDownload: document.getElementById("imageModalDownload"),
  imageModalClose: document.getElementById("imageModalClose"),
  openInteractiveFromImageBtn: document.getElementById("openInteractiveFromImageBtn"),

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
};

// ----------------------------------------------------------------------------
// Initialization
// ----------------------------------------------------------------------------
document.addEventListener("DOMContentLoaded", () => {
  initEventListeners();
  loadStats();
  fetchTargets();
});

function initEventListeners() {
  // Search debouncing
  let searchTimer;
  elements.searchInput.addEventListener("input", (e) => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => {
      state.q = e.target.value.trim();
      state.page = 1;
      fetchTargets();
    }, 300);
  });

  elements.clearSearchBtn.addEventListener("click", () => {
    elements.searchInput.value = "";
    state.q = "";
    state.page = 1;
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
    fetchTargets();
  });

  // catId Select Filter
  if (elements.catIdSelect) {
    elements.catIdSelect.addEventListener("change", (e) => {
      state.cat_id = e.target.value === "ALL" ? null : parseInt(e.target.value, 10);
      state.page = 1;
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
    fetchTargets();
  });

  // Page Size
  elements.pageSizeSelect.addEventListener("change", (e) => {
    state.limit = parseInt(e.target.value, 10);
    state.page = 1;
    fetchTargets();
  });

  // Reset Filters
  elements.resetFiltersBtn.addEventListener("click", () => {
    elements.searchInput.value = "";
    elements.minZInput.value = "";
    elements.maxZInput.value = "";
    elements.classPills.querySelectorAll(".pill-btn").forEach((b) => b.classList.remove("active"));
    elements.classPills.querySelector('[data-class="ALL"]').classList.add("active");
    if (elements.catIdSelect) elements.catIdSelect.value = "ALL";
    elements.sortBySelect.value = "redshift";

    state.q = "";
    state.classification = "ALL";
    state.cat_id = null;
    state.min_z = null;
    state.max_z = null;
    state.sort_by = "redshift";
    state.order = "desc";
    state.page = 1;
    fetchTargets();
  });

  // Pagination
  elements.prevPageBtn.addEventListener("click", () => {
    if (state.page > 1) {
      state.page--;
      fetchTargets();
    }
  });

  elements.nextPageBtn.addEventListener("click", () => {
    if (state.page < state.pages) {
      state.page++;
      fetchTargets();
    }
  });

  elements.pageJumpBtn.addEventListener("click", () => {
    const val = parseInt(elements.pageJumpInput.value, 10);
    if (!isNaN(val) && val >= 1 && val <= state.pages) {
      state.page = val;
      fetchTargets();
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

  // Sky Map Controls
  if (elements.skyMapResetBtn) {
    elements.skyMapResetBtn.addEventListener("click", () => {
      if (elements.skyPlotly) {
        Plotly.relayout(elements.skyPlotly, {
          "xaxis.autorange": "reversed",
          "yaxis.autorange": true,
        });
      }
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
        if (!state.allSkyTargets && !state.allSkyLoading) {
          fetchAllSkyPositions();
        } else {
          renderSkyMap(state.targets);
        }
      }
    });
  }

  if (elements.skyMapToggleBtn) {
    elements.skyMapToggleBtn.addEventListener("click", () => {
      const isHidden = elements.skyMapBody.style.display === "none";
      if (isHidden) {
        elements.skyMapBody.style.display = "block";
        elements.skyMapToggleBtn.textContent = "− Collapse";
        Plotly.Plots.resize(elements.skyPlotly);
      } else {
        elements.skyMapBody.style.display = "none";
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

  const filterKey = `${state.q || ""}|${state.classification || ""}|${state.cat_id || ""}|${state.min_z || ""}|${state.max_z || ""}`;
  if (state.lastFilterKey !== filterKey) {
    state.lastFilterKey = filterKey;
    state.allSkyTargets = null;
  }

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

  try {
    const res = await fetch(`/api/targets?${params.toString()}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();

    state.total = data.total;
    state.pages = data.pages;
    state.targets = data.targets || [];
    renderTargetsTable(data.targets);
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
  elements.resultsCount.textContent = `Showing ${startIdx.toLocaleString()}–${endIdx.toLocaleString()} of ${state.total.toLocaleString()} targets`;

  const rowsHtml = targets
    .map((t) => {
      const cls = t.classificationName || "UNKNOWN";
      let badgeClass = "badge-unknown";
      if (cls === "GALAXY") badgeClass = "badge-galaxy";
      else if (cls === "QSO") badgeClass = "badge-qso";
      else if (cls === "STAR") badgeClass = "badge-star";

      // Probabilities
      const pGal = t.probaGalaxy !== null ? (t.probaGalaxy * 100).toFixed(1) + "%" : "-";
      const pQso = t.probaQSO !== null ? (t.probaQSO * 100).toFixed(1) + "%" : "-";
      const pStar = t.probaStar !== null ? (t.probaStar * 100).toFixed(1) + "%" : "-";

      // Redshift / Velocity
      let zDisplay = "-";
      let zErrDisplay = "";
      if (cls === "STAR" && t.bestVelocity !== null) {
        zDisplay = `${t.bestVelocity.toFixed(1)} km/s`;
        if (t.bestVelocityError) zErrDisplay = `&plusmn;${t.bestVelocityError.toFixed(1)}`;
      } else if (t.bestRedshift !== null) {
        zDisplay = `z = ${t.bestRedshift.toFixed(4)}`;
        if (t.bestRedshiftError) zErrDisplay = `&plusmn;${t.bestRedshiftError.toFixed(4)}`;
      }

      // Thumbnail
      const thumbSrc = t.has_png ? `/api/targets/${t.catId}/${t.objId}/image` : null;
      const thumbHtml = thumbSrc
        ? `<div class="thumb-container" onclick="openImagePreview(${t.catId}, '${t.objId}', '${t.obCode || ""}')" title="Click to view full spectrum plot">
             <img src="${thumbSrc}" loading="lazy" alt="Spectrum thumbnail">
           </div>`
        : `<div class="thumb-container thumb-placeholder">No PNG</div>`;

      // Coordinates
      const raStr = t.ra !== null ? `${t.ra.toFixed(4)}°` : "-";
      const decStr = t.dec !== null ? `${t.dec.toFixed(4)}°` : "-";

      return `
      <tr data-catid="${t.catId}" data-objid="${t.objId}">
        <td class="col-thumb">${thumbHtml}</td>
        <td class="col-target">
          <span class="target-id">${t.objId}</span>
          ${t.obCode ? `<span class="obcode-badge">${t.obCode}</span>` : ""}
          <div class="cat-id-muted">catId: ${t.catId} &bull; ${t.combination || ""}</div>
        </td>
        <td class="col-coords">
          <div class="coords-text">RA: ${raStr}</div>
          <div class="coords-text">Dec: ${decStr}</div>
        </td>
        <td class="col-class">
          <span class="badge ${badgeClass}">${cls}</span>
          <div class="proba-bar" title="G: ${pGal} | Q: ${pQso} | S: ${pStar}">
            G:${pGal} Q:${pQso} S:${pStar}
          </div>
        </td>
        <td class="col-z">
          <div class="z-val">${zDisplay}</div>
          ${zErrDisplay ? `<div class="z-err">${zErrDisplay}</div>` : ""}
        </td>
        <td class="col-subclass">
          <span class="subclass-text">${t.bestSubClass || "-"}</span>
        </td>
        <td class="col-actions">
          <div class="action-buttons">
            <button class="btn btn-sm btn-secondary" onclick="openTargetDetails(${t.catId}, '${t.objId}')" title="Inspect solver & line details">
              📋 Details
            </button>
            <button class="btn btn-sm btn-primary" onclick="openInteractiveSpectrumById(${t.catId}, '${t.objId}')" title="Open interactive spectrum viewer">
              📈 Plot
            </button>
            ${t.has_fits ? `<a class="btn btn-sm btn-secondary" href="/api/targets/${t.catId}/${t.objId}/fits" download title="Download raw FITS">💾 FITS</a>` : ""}
          </div>
        </td>
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

// ----------------------------------------------------------------------------
// Sky Map (Celestial Coordinates RA / Dec)
// ----------------------------------------------------------------------------
async function fetchAllSkyPositions() {
  if (state.allSkyLoading) return;
  state.allSkyLoading = true;

  if (elements.skyMapCount) {
    elements.skyMapCount.innerHTML = `<span style="display:inline-block;width:12px;height:12px;border:2px solid #38bdf8;border-top-color:transparent;border-radius:50%;animation:spin 0.8s linear infinite;vertical-align:middle;margin-right:4px;"></span> Loading all ${(state.total || 0).toLocaleString()} coordinates...`;
  }

  const params = new URLSearchParams({ limit: 50000 });
  if (state.q) params.append("q", state.q);
  if (state.classification && state.classification !== "ALL") {
    params.append("classification", state.classification);
  }
  if (state.cat_id !== null && state.cat_id !== "ALL") {
    params.append("cat_id", state.cat_id);
  }
  if (state.min_z !== null) params.append("min_z", state.min_z);
  if (state.max_z !== null) params.append("max_z", state.max_z);

  try {
    const res = await fetch(`/api/targets/sky_positions?${params.toString()}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    state.allSkyTargets = data.targets || [];
    renderSkyMap(state.targets);
  } catch (err) {
    console.error("Failed to load all sky positions:", err);
    if (elements.skyMapCount) elements.skyMapCount.textContent = "Error loading coordinates";
  } finally {
    state.allSkyLoading = false;
  }
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

  // If "all" mode is selected but data not loaded yet, fetch it
  if (isAll && !state.allSkyTargets) {
    if (!state.allSkyLoading) {
      fetchAllSkyPositions();
    }
    return;
  }

  const targetsToPlot = isAll ? (state.allSkyTargets || []) : (pageTargets || []);

  if (!targetsToPlot || targetsToPlot.length === 0) {
    elements.skyMapCount.textContent = "0 targets";
    Plotly.react(
      elements.skyPlotly,
      [],
      {
        plot_bgcolor: "#0b1120",
        paper_bgcolor: "#111827",
        annotations: [
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
        xaxis: { visible: false },
        yaxis: { visible: false },
        margin: { l: 20, r: 20, t: 20, b: 20 },
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
      [],
      {
        plot_bgcolor: "#0b1120",
        paper_bgcolor: "#111827",
        annotations: [
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
        xaxis: { visible: false },
        yaxis: { visible: false },
        margin: { l: 20, r: 20, t: 20, b: 20 },
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
    if (cls === "STAR" && t.bestVelocity !== null) {
      zText = `Velocity: ${t.bestVelocity.toFixed(1)} km/s`;
    } else if (t.bestRedshift !== null) {
      zText = `Redshift: z = ${t.bestRedshift.toFixed(4)}`;
    }

    grp.x.push(t.ra);
    grp.y.push(t.dec);
    grp.customdata.push([t.catId, t.objId, t.obCode || "Target", cls, zText]);
  });

  const traces = [];
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
          size: isAll ? (key === "STAR" ? 7 : 5) : (key === "STAR" ? 11 : 9),
          opacity: isAll ? 0.75 : 0.9,
          line: isAll ? undefined : { color: "#0f172a", width: 1.5 },
        },
        hovertemplate:
          "<b>%{customdata[2]}</b> (objId: %{customdata[1]})<br>" +
          "catId: %{customdata[0]} &bull; %{customdata[3]}<br>" +
          "RA: %{x:.4f}&deg; | Dec: %{y:.4f}&deg;<br>" +
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
      traces.push({
        type: "scatter",
        mode: "markers",
        name: `Current Page Focus (${pageValid.length})`,
        x: pageValid.map((t) => t.ra),
        y: pageValid.map((t) => t.dec),
        customdata: pageValid.map((t) => [t.catId, t.objId, t.obCode || "Target", t.classificationName || "UNKNOWN"]),
        marker: {
          color: "rgba(255, 255, 255, 0.15)",
          symbol: "circle",
          size: 13,
          line: { color: "#ffffff", width: 2 },
        },
        hovertemplate:
          "<b>Page " + state.page + " Focus</b>: %{customdata[2]} (objId: %{customdata[1]})<br>" +
          "catId: %{customdata[0]} &bull; %{customdata[3]}<br>" +
          "RA: %{x:.4f}&deg; | Dec: %{y:.4f}&deg;<br>" +
          "<span style='color:#38bdf8;font-size:11px;'>👆 Click marker to preview spectrum</span>" +
          "<extra></extra>",
      });
    }
  }

  const layout = {
    paper_bgcolor: "#111827",
    plot_bgcolor: "#0b1120",
    margin: { l: 65, r: 25, t: 20, b: 50 },
    hovermode: "closest",
    dragmode: "pan",
    showlegend: true,
    legend: {
      orientation: "h",
      x: 0.01,
      y: 1.15,
      font: { color: "#9ca3af", size: 11 },
      bgcolor: "rgba(17, 24, 39, 0.75)",
      bordercolor: "rgba(255, 255, 255, 0.1)",
      borderwidth: 1,
    },
    xaxis: {
      title: { text: "Right Ascension (RA) [deg]", font: { color: "#9ca3af", size: 12 } },
      tickfont: { color: "#9ca3af", size: 11 },
      gridcolor: "rgba(255, 255, 255, 0.07)",
      zerolinecolor: "rgba(255, 255, 255, 0.12)",
      autorange: "reversed", // Astronomical standard: RA increases to the left
    },
    yaxis: {
      title: { text: "Declination (Dec) [deg]", font: { color: "#9ca3af", size: 12 } },
      tickfont: { color: "#9ca3af", size: 11 },
      gridcolor: "rgba(255, 255, 255, 0.07)",
      zerolinecolor: "rgba(255, 255, 255, 0.12)",
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
// Modal 1: Image Preview
// ----------------------------------------------------------------------------
window.openImagePreview = function (catId, objId, obCode) {
  let existing = state.targets ? state.targets.find((t) => t.catId == catId && String(t.objId) === String(objId)) : null;
  if (!existing && state.allSkyTargets) {
    existing = state.allSkyTargets.find((t) => t.catId == catId && String(t.objId) === String(objId));
  }
  state.activeTarget = existing ? { ...existing } : { catId, objId, obCode };
  elements.imageModalImg.src = `/api/targets/${catId}/${objId}/image`;
  elements.imageModalTitle.textContent = `Coadded Spectrum: ${obCode || ""} (objId: ${objId}, catId: ${catId})`;
  elements.imageModalDownload.href = `/api/targets/${catId}/${objId}/image`;
  elements.imageModal.style.display = "flex";
};

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
}

/**
 * Generate Plotly vertical line shapes and text annotations for spectral lines
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

    shapes.push({
      type: "line",
      x0: obsWave,
      x1: obsWave,
      y0: ymin,
      y1: ymax,
      line: {
        color: color,
        width: 1,
        dash: "dash",
      },
    });

    const yPos = ymax * (0.92 - (stagger % 3) * 0.08);
    stagger++;

    annotations.push({
      x: obsWave,
      y: yPos,
      text: line.name,
      showarrow: false,
      textangle: -90,
      font: { color: color, size: 9, family: "JetBrains Mono" },
      bgcolor: "rgba(11, 15, 25, 0.6)",
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
  const yrange = elements.plotlyChart.layout.yaxis.range;
  const { shapes, annotations } = getSpectralLineShapes(yrange[0], yrange[1]);

  Plotly.relayout(elements.plotlyChart, {
    shapes: shapes,
    annotations: annotations,
  });
}
