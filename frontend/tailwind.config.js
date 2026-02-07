/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      // Design system colors
      colors: {
        // Elevation levels
        base: '#0c0f0d',
        surface: '#1a1d1b',
        raised: '#252a27',
        elevated: '#323832',

        // Border colors
        subtle: '#2a2f2c',

        // Text hierarchy
        primary: '#fafafa',
        secondary: '#a8a8a8',
        tertiary: '#787878',
        muted: '#585858',

        // Accent colors
        camel: '#d4a574',
        terra: '#cd8264',

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

      // Transitions
      transitionDuration: {
        '250': '250ms',
      },
    },
  },
  plugins: [],
}
