/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    './src/renderer/index.html',
    './src/renderer/**/*.{vue,js,ts,jsx,tsx}',
  ],
  theme: {
    extend: {
      colors: {
        pet: {
          primary: '#4CAF50',
          bg: '#f8f9fa',
          border: '#e4e7ed',
        },
      },
      boxShadow: {
        'pet-panel': '0 20px 40px -15px rgba(0, 0, 0, 0.1)',
      },
    },
  },
  corePlugins: {
    preflight: false,
  },
  plugins: [],
}
