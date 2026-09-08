# Disha Official Website & Documentation Portal

Official website and comprehensive technical documentation hub for [Disha](https://github.com/geoailabs/disha) — the open-source desktop GIS application with an autonomous conversational AI agent.

Hosted live on GitHub Pages from the root `/docs` folder.

## Portal Structure

- **`index.html`**: Flagship homepage with hero prompt simulator, 14-feature catalog, architecture comparison, and multi-platform download hub.
- **`docs.html`**: Comprehensive documentation hub, system architecture, 7+1 Domain Hubs reference, AI prompt handbook, spatial registry, and live data connectors.
- **`404.html`**: Custom themed 404 page for missing routes on GitHub Pages.
- **`js/components.js`**: Shared component loader unifying Header, Navigation, Footer, and SVG branding across all pages.
- **`.nojekyll`**: Bypasses Jekyll processing on GitHub Pages to serve all assets directly.

## Enabling GitHub Pages

To host this website on GitHub Pages:

1. Navigate to the GitHub repository **Settings**.
2. Under the **Code and automation** section in the left sidebar, click **Pages**.
3. Under **Build and deployment**:
   - **Source**: Select `Deploy from a branch`.
   - **Branch**: Select `main`.
   - **Folder**: Select `/docs`.
4. Click **Save**.
5. Within 1-2 minutes, the website will be live at `https://<org>.github.io/disha/` (or your custom domain).

## Running Locally

From the repository root:

```bash
# Using the monorepo pnpm command (auto-syncs docs and starts preview server)
pnpm run preview:docs

# Or compiling docs and serving with Python
pnpm run build:docs
cd docs && python3 -m http.server 8000
```

Open `http://localhost:8000` in your browser.
