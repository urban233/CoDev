// @ts-check
import { defineConfig } from 'astro/config';
import starlight from '@astrojs/starlight';

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
      sidebar: [
        { label: 'Home', link: '/' },
        { label: 'Getting Started', link: '/getting-started/' },
        {
          label: 'Reference',
          items: [
            { label: 'CLI reference', link: '/cli-reference/' },
            { label: 'Architecture', link: '/architecture/' },
          ],
        },
      ],
    }),
  ],
});
