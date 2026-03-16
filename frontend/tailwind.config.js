/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      // Design system colors (v3 token names)
      colors: {
        // Elevation levels
        base: '#0c0f0d',
        surface: '#1a1d1b',
        raised: '#252a27',
        elevated: '#323832',

        // Border colors
        subtle: '#2a2f2c',
        'border-default': '#3a3f3c',
        'border-emphasis': '#4a4f4c',

        // Text hierarchy
        primary: '#fafafa',
        secondary: '#a8a8a8',
        tertiary: '#787878',
        muted: '#585858',

        // Accent colors (v3 names — primary/secondary/pop)
        camel: '#d4a574',     // legacy alias — use accent-primary in new code
        terra: '#cd8264',     // legacy alias — use accent-secondary in new code
        'accent-primary': '#d4a574',
        'accent-secondary': '#cd8264',
        'accent-pop': '#50c878',

        // Semantic colors
        'semantic-success': '#7ab07a',
        'semantic-warning': '#e0a458',
        'semantic-error': '#c75050',
        'semantic-info': '#5b8fb9',

        // Highlight colors (for reading annotations)
        highlight: {
          yellow: 'rgba(255, 235, 59, 0.3)',
          blue: 'rgba(66, 165, 245, 0.3)',
          green: 'rgba(102, 187, 106, 0.3)',
          pink: 'rgba(236, 64, 122, 0.3)',
        }
      },

      // Typography
      fontFamily: {
        base: ['Geist', 'Plus Jakarta Sans', 'system-ui', 'sans-serif'],
        display: ['Fraunces', 'Georgia', 'serif'],
        mono: ['JetBrains Mono', 'Fira Code', 'monospace'],
      },

      // Spacing and sizing
      spacing: {
        '18': '4.5rem',
        '88': '22rem',
        '128': '32rem',
      },

      // Motion tokens
      transitionDuration: {
        'fast': '100ms',
        'normal': '200ms',
        'slow': '350ms',
        '250': '250ms',
      },

      transitionTimingFunction: {
        'default': 'cubic-bezier(0.2, 0, 0.2, 1)',
        'ease-out': 'cubic-bezier(0, 0, 0.2, 1)',
        'ease-in': 'cubic-bezier(0.4, 0, 1, 1)',
      },

      // Z-index scale
      zIndex: {
        'raised': '10',
        'dropdown': '20',
        'sticky': '30',
        'tooltip': '40',
        'overlay': '50',
        'modal': '60',
        'toast': '70',
      },
    },
  },
  plugins: [],
}
