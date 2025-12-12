import { defineConfig } from 'vitepress'
import { withMermaid } from "vitepress-plugin-mermaid";

// https://vitepress.dev/reference/site-config
export default defineConfig({
  title: "Deadend CLI",
  description: "Agentic security testing",
  themeConfig: {
    // https://vitepress.dev/reference/default-theme-config
    nav: [
      { text: 'Home', link: '/deadend-cli' },
      { text: 'Docs', link: '/deadend-cli/markdown-examples' }
    ],

    sidebar: [
      {
        text: 'Get started',
        collapsed: true,
        items: [
          { text: 'Introduction', link: '/introduction' },
          { text: 'Install', link: '/installation' },
          { text: 'Usage', link: '/usage' },
          { text: 'first target', link: '/first-target' },
          { text: 'Features', link: '/features'}
        ]
      },
            {
        text: 'Run locally',
        collapsed: true,
        items: [
          { text: 'Setup', link: '/introduction' },
          { text: 'Vector database', link: '/installation' },
          { text: 'local model provider', link: '/first-target' },
          { text: 'Sandbox', link: '/usage' },
        ]
      },
      {
        text: 'Eval & Benchmarks',
        collapsed: true,
        items: [
          { text: 'Benchmarks used', link: '/evaluation/benchmarks' },
          { text: 'Web vulnerabilties', link: '/evaluation/complex_vulns' }
        ]
      },
      {
        text: 'Architecture',
        collapsed: true,
        items: [
          { text: 'CLI Architecture', link: '/architecture/cli_architecture' },
          { text: 'Agentic architecture', link: '/architecture/agentic_architecture' },
          { text: 'Web application testing implementation', link: '/architecture/webapp_testing'},
          { text: 'Web resource extractor', link: '/architecture/web_extractor' },
          { text: 'Runtime API Examples', link: '/api-examples' }
        ]
      }, 

      {
        text: 'Research',
        collapsed: true,
        items: [
          { text: 'Web resource extractor', link: '/architecture/web_extractor' },
          { text: 'Runtime API Examples', link: '/api-examples' }
        ]
      }
    ],
    footer: {
      message: 'Hack hack hack',
      copyright: 'Copyright © 2025'
    },
    socialLinks: [
      { icon: 'github', link: 'https://github.com/vuejs/vitepress' }
    ]
  },
  mermaid: {

    },
    mermaidPlugin: {
      class: "mermaid", // set additional css classes for parent container 
    },
})
