/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        elastic: {
          blue: '#0B64DD',
          teal: '#48EFCF',
          developer: '#101C3F',
          midnight: '#153385',
          yellow: '#FEC514',
          pink: '#F04E98',
        },
        brand: {
          body: '#343741',
          'light-bg': '#F5F7FA',
          'medium-gray': '#98A2B3',
          'border-gray': '#D0D5DD',
          ice: '#CADCFC',
        },
      },
      fontFamily: {
        inter: ['Inter', 'system-ui', 'sans-serif'],
      },
    },
  },
  plugins: [],
}
