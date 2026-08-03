/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        'cih-orange': '#F26522',
        'cih-orange-dark': '#D9530F',
        'cih-orange-light': '#FDECE2',
        'cih-blue': '#005CA9',
        'cih-blue-dark': '#00427A',
        'cih-blue-light': '#E6F0F9',
        'cih-bg-dark-from': '#0B1E33',
        'cih-bg-dark-to': '#142A45',
        'cih-surface': '#F8FAFC',
        // Degrade de l'ecran de connexion - voir DocsContext/05_interface_frontend.md §6
        'auth-gradient-orange': '#F26522',
        'auth-gradient-red': '#D9434B',
        'auth-gradient-blue': '#1E3A6E',
        'auth-gradient-violet': '#2E1A47',
      },
    },
  },
  plugins: [],
}
