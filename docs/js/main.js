/**
 * DISHA — Global Site Logic & Interactive Features
 */

document.addEventListener('DOMContentLoaded', () => {
  if (window.DishaComponents && typeof window.DishaComponents.init === 'function') {
    window.DishaComponents.init();
  }
  initTheme();
  initMobileMenu();
  initSimulator();
  initChangelogFilters();
  initBrandStudio();
  initClipboardCopier();
  initDocsSidebar();
});

/* ==========================================================================
   1. Theme Management (Dark / Light)
   ========================================================================== */
function initTheme() {
  const savedTheme = localStorage.getItem('disha-theme') || 'dark';
  document.documentElement.setAttribute('data-theme', savedTheme);
  updateThemeIcon(savedTheme);

  const themeToggleBtns = document.querySelectorAll('.theme-toggle-btn');
  themeToggleBtns.forEach(btn => {
    btn.addEventListener('click', () => {
      const currentTheme = document.documentElement.getAttribute('data-theme') || 'dark';
      const newTheme = currentTheme === 'dark' ? 'light' : 'dark';
      document.documentElement.setAttribute('data-theme', newTheme);
      localStorage.setItem('disha-theme', newTheme);
      updateThemeIcon(newTheme);
      showToast(`Switched to ${newTheme} mode`);
    });
  });
}

function updateThemeIcon(theme) {
  const icons = document.querySelectorAll('.theme-toggle-icon');
  icons.forEach(icon => {
    icon.innerHTML = theme === 'dark' 
      ? `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="5"></circle><line x1="12" y1="1" x2="12" y2="3"></line><line x1="12" y1="21" x2="12" y2="23"></line><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"></line><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"></line><line x1="1" y1="12" x2="3" y2="12"></line><line x1="21" y1="12" x2="23" y2="12"></line><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"></line><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"></line></svg>`
      : `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"></path></svg>`;
  });
}

/* ==========================================================================
   3. Mobile Navigation Drawer
   ========================================================================== */
function initMobileMenu() {
  const toggleBtn = document.querySelector('.mobile-nav-toggle');
  const navMenu = document.querySelector('.nav-menu');
  if (!toggleBtn || !navMenu) return;

  toggleBtn.addEventListener('click', () => {
    const isVisible = navMenu.style.display === 'flex';
    navMenu.style.display = isVisible ? 'none' : 'flex';
    if (!isVisible) {
      navMenu.style.flexDirection = 'column';
      navMenu.style.position = 'absolute';
      navMenu.style.top = '70px';
      navMenu.style.left = '0';
      navMenu.style.right = '0';
      navMenu.style.background = 'var(--bg-panel)';
      navMenu.style.padding = '20px';
      navMenu.style.borderBottom = '1px solid var(--border-strong)';
      navMenu.style.zIndex = '999';
    }
  });
}

/* ==========================================================================
   4. Hero Prompt Simulator
   ========================================================================== */
const PROMPT_PRESETS = {
  buffer: {
    query: "Buffer this flood zone polygon by 500 meters and clip the roads layer to it",
    tool: "gis_buffer → gis_clip",
    response: "Buffered the selected flood risk polygon by 500.0m on WGS84 geodesic ellipsoid and clipped the <code>transportation_roads</code> layer. 41 road segments intersect the hazard perimeter. Created new layer: <span class='mono'>roads_flood_hazard_500m</span>."
  },
  overture: {
    query: "Fetch all medical facilities in Chandigarh from Overture Maps via DuckDB",
    tool: "overture_places_search(theme='places', category='healthcare')",
    response: "Executed DuckDB S3 Parquet spatial query against Overture Maps release. Retrieved 87 verified healthcare facilities with building footprints & classification tags in 412ms."
  },
  traffic: {
    query: "Assign morning peak OD matrix to OSM road network and identify top 5 bottlenecks",
    tool: "assign_traffic_flows → analyze_street_network(metric='betweenness')",
    response: "Assigned 42,000 hourly trips across 3,420 road links. Highest congestion index detected at Madhya Marg & Purv Marg junction (Volume-to-Capacity ratio: 1.42)."
  },
  zoning: {
    query: "Generate a Transit-Oriented Development (TOD) scenario along the Metro corridor",
    tool: "generate_scenario(type='TOD', corridor='Metro_Phase1')",
    response: "Generated TOD Scenario #3: Upzoned 18 parcels to Mixed-Use High Density (FAR 3.5), added 4 modal-split transit hubs, increased projected walkability index by +38%."
  }
};

function initSimulator() {
  const userMsgEl = document.getElementById('sim-user-text');
  const toolBadgeEl = document.getElementById('sim-tool-badge');
  const agentBubbleEl = document.getElementById('sim-agent-text');
  const presetBtns = document.querySelectorAll('.sim-preset-btn');

  if (!userMsgEl || !toolBadgeEl || !agentBubbleEl) return;

  presetBtns.forEach(btn => {
    btn.addEventListener('click', () => {
      presetBtns.forEach(b => b.classList.remove('active'));
      btn.classList.add('active');

      const key = btn.getAttribute('data-preset');
      const data = PROMPT_PRESETS[key];
      if (!data) return;

      // Animate transition
      userMsgEl.style.opacity = '0';
      agentBubbleEl.style.opacity = '0';

      setTimeout(() => {
        userMsgEl.textContent = data.query;
        toolBadgeEl.textContent = data.tool;
        agentBubbleEl.innerHTML = data.response;

        userMsgEl.style.opacity = '1';
        agentBubbleEl.style.opacity = '1';
      }, 150);
    });
  });
}

/* ==========================================================================
   5. Visual Changelog Filters & Search
   ========================================================================== */
function initChangelogFilters() {
  const filterBtns = document.querySelectorAll('.changelog-filter-btn');
  const searchInput = document.getElementById('changelog-search');
  const releaseCards = document.querySelectorAll('.release-card');

  if (!releaseCards.length) return;

  function filterCards() {
    const activeFilter = document.querySelector('.changelog-filter-btn.active')?.getAttribute('data-tag') || 'all';
    const query = searchInput ? searchInput.value.toLowerCase().trim() : '';

    releaseCards.forEach(card => {
      const cardTags = card.getAttribute('data-tags') || '';
      const cardText = card.textContent.toLowerCase();

      const matchesTag = activeFilter === 'all' || cardTags.includes(activeFilter);
      const matchesSearch = !query || cardText.includes(query);

      card.style.display = (matchesTag && matchesSearch) ? 'flex' : 'none';
    });
  }

  filterBtns.forEach(btn => {
    btn.addEventListener('click', () => {
      filterBtns.forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      filterCards();
    });
  });

  if (searchInput) {
    searchInput.addEventListener('input', filterCards);
  }
}

/* ==========================================================================
   6. Interactive Brand Studio & Logo Exporter
   ========================================================================== */
function initBrandStudio() {
  const candidateBtns = document.querySelectorAll('.studio-candidate-btn');
  const stageEl = document.getElementById('brand-preview-stage');
  const stageBgBtns = document.querySelectorAll('.stage-bg-btn');
  const svgDownloadBtn = document.getElementById('btn-download-svg');
  const copySvgBtn = document.getElementById('btn-copy-svg');
  const candidateTitleEl = document.getElementById('studio-selected-title');
  const candidateDescEl = document.getElementById('studio-selected-desc');

  if (!stageEl || typeof DISHA_LOGOS === 'undefined') return;

  let currentConceptKey = 'compassSpark';

  function renderConcept(key) {
    currentConceptKey = key;
    const data = DISHA_LOGOS[key];
    if (!data) return;

    stageEl.innerHTML = `<div style="width: 280px; height: 80px; display: flex; align-items: center; justify-content: center;">${data.svgFull}</div>`;
    
    if (candidateTitleEl) candidateTitleEl.textContent = data.name;
    if (candidateDescEl) candidateDescEl.textContent = data.tagline;
  }

  candidateBtns.forEach(btn => {
    btn.addEventListener('click', () => {
      candidateBtns.forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      const key = btn.getAttribute('data-concept');
      renderConcept(key);
    });
  });

  stageBgBtns.forEach(btn => {
    btn.addEventListener('click', () => {
      stageBgBtns.forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      const bg = btn.getAttribute('data-bg');
      stageEl.className = `brand-preview-stage brand-stage-${bg}`;
    });
  });

  if (svgDownloadBtn) {
    svgDownloadBtn.addEventListener('click', () => {
      const data = DISHA_LOGOS[currentConceptKey];
      downloadSvgAsset(data.svgFull, `disha-logo-${data.id}.svg`);
      showToast(`Downloaded disha-logo-${data.id}.svg`);
    });
  }

  if (copySvgBtn) {
    copySvgBtn.addEventListener('click', () => {
      const data = DISHA_LOGOS[currentConceptKey];
      navigator.clipboard.writeText(data.svgFull).then(() => {
        showToast('SVG vector code copied to clipboard!');
      });
    });
  }

  // Initial render
  renderConcept('compassSpark');
}

/* ==========================================================================
   7. Clipboard Copy Helper
   ========================================================================== */
function initClipboardCopier() {
  document.querySelectorAll('[data-copy]').forEach(el => {
    el.addEventListener('click', () => {
      const textToCopy = el.getAttribute('data-copy');
      if (!textToCopy) return;

      navigator.clipboard.writeText(textToCopy).then(() => {
        showToast(`Copied: ${textToCopy}`);
      });
    });
  });
}

/* ==========================================================================
   8. Docs Sidebar Navigation & Search
   ========================================================================== */
function initDocsSidebar() {
  const docsLinks = document.querySelectorAll('.docs-nav-link');
  const docsSections = document.querySelectorAll('.doc-section');
  const searchInput = document.getElementById('docs-search-input');

  if (!docsLinks.length) return;

  // Scroll spy
  window.addEventListener('scroll', () => {
    let currentId = '';
    docsSections.forEach(section => {
      const rect = section.getBoundingClientRect();
      if (rect.top <= 120 && rect.bottom >= 120) {
        currentId = section.getAttribute('id');
      }
    });

    if (currentId) {
      docsLinks.forEach(link => {
        if (link.getAttribute('href') === `#${currentId}`) {
          link.classList.add('active');
        } else {
          link.classList.remove('active');
        }
      });
    }
  });

  // Simple Docs search
  if (searchInput) {
    searchInput.addEventListener('input', () => {
      const query = searchInput.value.toLowerCase().trim();
      docsLinks.forEach(link => {
        const text = link.textContent.toLowerCase();
        link.parentElement.style.display = (!query || text.includes(query)) ? 'block' : 'none';
      });
    });
  }
}

/* ==========================================================================
   Toast Notification System
   ========================================================================== */
function showToast(message) {
  let container = document.querySelector('.toast-container');
  if (!container) {
    container = document.createElement('div');
    container.className = 'toast-container';
    document.body.appendChild(container);
  }

  const toast = document.createElement('div');
  toast.className = 'toast';
  toast.innerHTML = `
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#10B981" stroke-width="2.5"><polyline points="20 6 9 17 4 12"></polyline></svg>
    <span>${message}</span>
  `;

  container.appendChild(toast);

  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transform = 'translateY(10px)';
    toast.style.transition = 'all 0.25s ease';
    setTimeout(() => toast.remove(), 250);
  }, 2500);
}
