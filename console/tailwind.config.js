/** @type {import('tailwindcss').Config} */
export default {
  content: [
    './index.html',
    './src/**/*.{ts,tsx}',
  ],
  theme: {
    extend: {
      colors: {
        bg: '#05070B',
        'bg-elevated': '#0B0F15',
        'bg-panel': '#101520',
        'text-primary': '#EEF3FF',
        'text-secondary': '#9AA4B2',
        'text-muted': '#5A6478',
        'elastic-blue': '#0B64DD',
        teal: '#48EFCF',
        profit: '#4ADE80',
        loss: '#FB7185',
        neutral: '#9AA4B2',
        idle: 'rgba(154, 164, 178, 0.7)',
        testing: 'rgba(77, 163, 255, 0.9)',
        promoted: 'rgba(74, 222, 128, 0.9)',
        killed: 'rgba(251, 113, 133, 0.9)',
        incumbent: 'rgba(254, 197, 20, 0.9)',
        warning: 'rgba(251, 191, 36, 0.9)',
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
      },
    },
  },
  plugins: [],
  darkMode: 'class',
}
