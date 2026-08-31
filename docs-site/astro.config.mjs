// @ts-check
import { defineConfig } from 'astro/config';
import starlight from '@astrojs/starlight';
import starlightLlmsTxt from 'starlight-llms-txt';

// CoDev's installed-package version, kept as one constant so the sidebar
// badge below never drifts from pyproject.toml/CHANGELOG.md by hand.
const CODEV_VERSION = '0.5.0';

// Deployed as a GitHub Pages *project* site (github.com/urban233/CoDev ->
// urban233.github.io/CoDev/), so `base` must carry the repo name. If a
// custom domain is ever attached instead, drop `base` and point `site` at
// the domain.
export default defineConfig({
  site: 'https://urban233.github.io',
  base: '/CoDev',
  integrations: [
    starlight({
      title: 'CoDev',
      description: 'Human-guided AI software delivery.',
      logo: {
        src: './src/assets/codev-mark.svg',
        replacesTitle: false,
      },
      favicon: '/favicon.svg',
      customCss: ['./src/styles/custom.css'],
      social: [
        { icon: 'github', label: 'GitHub', href: 'https://github.com/urban233/CoDev' },
        { icon: 'npm', label: 'PyPI', href: 'https://pypi.org/project/open-codev-workflow/' },
      ],
      editLink: {
        baseUrl: 'https://github.com/urban233/CoDev/edit/main/docs-site/',
      },
      // Onest: SIL Open Font License, served from Google Fonts -- see
      // docs/brand.md ("Do not bundle proprietary fonts").
      head: [
        { tag: 'link', attrs: { rel: 'preconnect', href: 'https://fonts.googleapis.com' } },
        {
          tag: 'link',
          attrs: { rel: 'preconnect', href: 'https://fonts.gstatic.com', crossorigin: true },
        },
        {
          tag: 'link',
          attrs: {
            rel: 'stylesheet',
            href: 'https://fonts.googleapis.com/css2?family=Onest:wght@400;500;600;700&display=swap',
          },
        },
      ],
      components: {
        PageTitle: './src/components/PageTitle.astro',
      },
      plugins: [starlightLlmsTxt()],
      sidebar: [
        { label: 'Home', link: '/' },
        { label: 'Getting Started', link: '/getting-started/' },
        {
          label: 'Working With Your Agent',
          items: [
            { label: 'Talking to Your Agent', link: '/working-with-your-agent/' },
            { label: 'Starting Prompts', link: '/starting-prompts/' },
            { label: 'Examples', link: '/examples/' },
          ],
        },
        { label: 'Concepts', link: '/concepts/' },
        {
          label: 'Tutorials',
          items: [
            { label: '1. Your First Fix', link: '/tutorials/your-first-fix/' },
            { label: '2. A Design-Worthy Change', link: '/tutorials/a-design-worthy-change/' },
            { label: '3. Outer-Loop Review', link: '/tutorials/outer-loop-review/' },
            { label: '4. Multi-Developer Coordination', link: '/tutorials/multi-developer-coordination/' },
          ],
        },
        { label: 'Agent Platforms', link: '/agent-platforms/' },
        {
          label: 'Reference',
          badge: { text: `v${CODEV_VERSION}`, variant: 'default' },
          items: [
            { label: 'CLI Reference', link: '/cli-reference/' },
            { label: 'Manual CLI Walkthrough', link: '/workflow-checklist/' },
            { label: 'Architecture', link: '/architecture/' },
          ],
        },
        { label: 'FAQ', link: '/faq/' },
      ],
    }),
  ],
});
