/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        surface: 'var(--color-surface)',
        'surface-raised': 'var(--color-surface-raised)',
        'surface-sunken': 'var(--color-surface-sunken)',
        canvas: 'var(--color-canvas)',
        'canvas-alt': 'var(--color-canvas-alt)',
        accent: 'var(--color-accent)',
        flare: 'var(--color-accent-red)',
        'flare-bright': 'var(--color-accent-red-bright)',
        'warm-white': 'var(--color-white-warm)',
        zenaf: 'var(--color-zenaf-accent)',
      },
    },
  },
  plugins: [],
}
