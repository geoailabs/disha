/**
 * DISHA — Shared Layout Components Loader
 * Unifies Header, Navigation, Footer, and SVG Branding across all pages
 * Zero emojis, clean typography, responsive layout.
 */

(function () {
  'use strict';

  const DISHA_BRAND_SVG = `
    <svg viewBox="0 0 64 64" fill="none" width="30" height="30" aria-label="Disha Logo">
      <defs>
        <linearGradient id="nav-grad-shared" x1="0" y1="0" x2="64" y2="64">
          <stop offset="0%" stop-color="#38BDF8"/>
          <stop offset="100%" stop-color="#10B981"/>
        </linearGradient>
      </defs>
      <circle cx="32" cy="32" r="28" stroke="url(#nav-grad-shared)" stroke-width="2.5" stroke-dasharray="6 3" opacity="0.7"/>
      <path d="M32 6L38 26L58 32L38 38L32 58L26 38L6 32L26 26L32 6Z" fill="url(#nav-grad-shared)"/>
      <circle cx="32" cy="32" r="4.5" fill="#38BDF8"/>
      <circle cx="32" cy="32" r="2" fill="#FFFFFF"/>
    </svg>
  `;

  function detectCurrentPage() {
    const path = window.location.pathname.toLowerCase();
    if (path.includes('docs.html')) return 'docs';
    return 'home';
  }

  function renderHeader(activePage) {
    const isIndex = activePage === 'home';
    const downloadHref = isIndex ? '#download' : 'index.html#download';

    return `
      <div class="wrap">
        <div class="header-inner">
          <a href="index.html" class="brand-link" title="Disha Home">
            <div class="brand-logo-icon">
              ${DISHA_BRAND_SVG}
            </div>
            <span>DISHA</span>
          </a>

          <ul class="nav-menu">
            <li class="nav-item">
              <a href="index.html" class="nav-link ${activePage === 'home' ? 'active' : ''}">Home</a>
            </li>
            <li class="nav-item">
              <a href="docs.html" class="nav-link ${activePage === 'docs' ? 'active' : ''}">Documentation</a>
            </li>
            <li class="nav-item">
              <a href="${downloadHref}" class="nav-link">Download</a>
            </li>
          </ul>

          <div class="header-actions">
            <button class="theme-toggle-btn" aria-label="Toggle light/dark theme" title="Toggle theme">
              <span class="theme-toggle-icon">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="5"></circle><line x1="12" y1="1" x2="12" y2="3"></line><line x1="12" y1="21" x2="12" y2="23"></line><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"></line><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"></line><line x1="1" y1="12" x2="3" y2="12"></line><line x1="21" y1="12" x2="23" y2="12"></line><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"></line><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"></line></svg>
              </span>
            </button>

            <a href="https://github.com/geoailabs/disha" target="_blank" rel="noopener" class="github-star-link">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><path d="M12 0C5.37 0 0 5.37 0 12c0 5.31 3.435 9.795 8.205 11.385.6.105.825-.255.825-.57 0-.285-.015-1.23-.015-2.235-3.015.555-3.795-.735-4.035-1.41-.135-.345-.72-1.41-1.23-1.695-.42-.225-1.02-.78-.015-.795.945-.015 1.62.87 1.845 1.23 1.08 1.815 2.805 1.305 3.495.99.105-.78.42-1.305.765-1.605-2.67-.3-5.46-1.335-5.46-5.925 0-1.305.465-2.385 1.23-3.225-.12-.3-.54-1.53.12-3.18 0 0 1.005-.315 3.3 1.23.96-.27 1.98-.405 3-.405s2.04.135 3 .405c2.295-1.56 3.3-1.23 3.3-1.23.66 1.65.24 2.88.12 3.18.765.84 1.23 1.905 1.23 3.225 0 4.605-2.805 5.625-5.475 5.925.435.375.81 1.095.81 2.22 0 1.605-.015 2.895-.015 3.3 0 .315.225.69.825.57A12.02 12.02 0 0 0 24 12c0-6.63-5.37-12-12-12z"/></svg>
              <span>GitHub</span>
              <span class="github-star-badge">Open Source</span>
            </a>

            <button class="mobile-nav-toggle" aria-label="Open mobile navigation">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="3" y1="12" x2="21" y2="12"></line><line x1="3" y1="6" x2="21" y2="6"></line><line x1="3" y1="18" x2="21" y2="18"></line></svg>
            </button>
          </div>
        </div>
      </div>
    `;
  }

  function renderFooter() {
    return `
      <div class="wrap">
        <div class="footer-top">
          <div class="footer-brand">
            <a href="index.html" class="brand-link">
              <div class="brand-logo-icon">
                <svg viewBox="0 0 64 64" fill="none" width="24" height="24">
                  <circle cx="32" cy="32" r="28" stroke="#38BDF8" stroke-width="3" stroke-dasharray="6 3"/>
                  <path d="M32 6L38 26L58 32L38 38L32 58L26 38L6 32L26 26L32 6Z" fill="#38BDF8"/>
                </svg>
              </div>
              <span>DISHA</span>
            </a>
            <p>
              An open-source desktop GIS application empowering urban planners, researchers, and geospatial analysts with an autonomous conversational agent.
            </p>
          </div>

          <div class="footer-col">
            <h4>Product</h4>
            <ul class="footer-links">
              <li><a href="index.html#features">14 Feature Categories</a></li>
              <li><a href="index.html#architecture">Architecture Overview</a></li>
              <li><a href="index.html#download">Download Builds</a></li>
              <li><a href="docs.html">Documentation Hub</a></li>
            </ul>
          </div>

          <div class="footer-col">
            <h4>Documentation</h4>
            <ul class="footer-links">
              <li><a href="docs.html#overview">System Architecture</a></li>
              <li><a href="docs.html#installation">Installation & Setup</a></li>
              <li><a href="docs.html#domain-hubs">7+1 Domain Hubs Reference</a></li>
              <li><a href="docs.html#prompts">Prompt Engineering Handbook</a></li>
              <li><a href="docs.html#registry">Spatial & Polygon Registry</a></li>
              <li><a href="docs.html#connectors">Data Connectors & Engines</a></li>
            </ul>
          </div>

          <div class="footer-col">
            <h4>Project & Code</h4>
            <ul class="footer-links">
              <li><a href="https://github.com/geoailabs/disha" target="_blank" rel="noopener">GitHub Repository</a></li>
              <li><a href="https://github.com/geoailabs/disha/issues" target="_blank" rel="noopener">Report an Issue</a></li>
              <li><a href="https://github.com/geoailabs/disha/releases" target="_blank" rel="noopener">Releases & Binaries</a></li>
              <li><a href="https://github.com/geoailabs/disha/blob/main/LICENSE" target="_blank" rel="noopener">Apache 2.0 License</a></li>
            </ul>
          </div>
        </div>

        <div class="footer-bottom">
          <div>(C) 2026 Disha Geospatial AI Project. Built for open science and urban planning.</div>
          <div style="display:flex; gap:16px;">
            <a href="index.html">Home</a>
            <a href="docs.html">Documentation</a>
            <a href="https://github.com/geoailabs/disha" target="_blank" rel="noopener">GitHub</a>
          </div>
        </div>
      </div>
    `;
  }

  function initSharedComponents() {
    const activePage = document.body.getAttribute('data-page') || detectCurrentPage();

    const headerEl = document.getElementById('site-header');
    if (headerEl) {
      headerEl.className = 'site-header';
      headerEl.innerHTML = renderHeader(activePage);
    }

    const footerEl = document.getElementById('site-footer');
    if (footerEl) {
      footerEl.className = 'site-footer';
      footerEl.innerHTML = renderFooter();
    }
  }

  // Run as early as possible
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initSharedComponents);
  } else {
    initSharedComponents();
  }

  window.DishaComponents = {
    init: initSharedComponents,
    brandSvg: DISHA_BRAND_SVG
  };
})();
