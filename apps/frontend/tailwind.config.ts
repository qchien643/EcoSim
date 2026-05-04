import type { Config } from 'tailwindcss'

/**
 * Flat color names (no nested DEFAULT/variant objects) to avoid any
 * Tailwind theme resolution edge case with nested keys.
 *
 * Semantic tokens → hex values. Class `text-fg` produces `color: #09090b`.
 */
const config: Config = {
  content: [
    './app/**/*.{ts,tsx}',
    './components/**/*.{ts,tsx}',
    './lib/**/*.{ts,tsx}',
    './hooks/**/*.{ts,tsx}',
  ],
  theme: {
    extend: {
      colors: {
        // Surface
        surface: '#ffffff',
        'surface-subtle': '#fafafa',
        'surface-muted': '#f4f4f5',
        'surface-inset': '#ededed',

        // Border
        border: '#e4e4e7',
        'border-subtle': '#ededed',
        'border-strong': '#d4d4d8',

        // Foreground
        fg: '#09090b',
        'fg-muted': '#52525b',
        'fg-subtle': '#71717a',
        'fg-faint': '#a1a1aa',

        // Brand (violet)
        'brand-50': '#f5f3ff',
        'brand-100': '#ede9fe',
        'brand-500': '#7c3aed',
        'brand-600': '#6d28d9',
        'brand-700': '#5b21b6',

        // Semantic
        'success-50': '#f0fdf4',
        'success-500': '#10b981',
        'success-600': '#059669',
        'success-700': '#047857',
        'warning-50': '#fffbeb',
        'warning-500': '#f59e0b',
        'warning-600': '#d97706',
        'danger-50': '#fef2f2',
        'danger-500': '#ef4444',
        'danger-600': '#dc2626',
        'info-50': '#eff6ff',
        'info-500': '#3b82f6',
        'info-600': '#2563eb',
      },
      fontFamily: {
        sans: [
          'var(--font-inter)',
          'Inter',
          'ui-sans-serif',
          'system-ui',
          'sans-serif',
        ],
        mono: [
          'var(--font-jetbrains)',
          'JetBrains Mono',
          'ui-monospace',
          'monospace',
        ],
      },
      fontSize: {
        '2xs': ['10px', { lineHeight: '14px' }],
        xs: ['12px', { lineHeight: '16px' }],
        sm: ['13px', { lineHeight: '18px' }],
        base: ['14px', { lineHeight: '20px' }],
        md: ['15px', { lineHeight: '22px' }],
        lg: ['17px', { lineHeight: '24px' }],
        xl: ['20px', { lineHeight: '28px' }],
        '2xl': ['24px', { lineHeight: '30px' }],
        '3xl': ['30px', { lineHeight: '36px' }],
      },
      boxShadow: {
        xs: '0 1px 2px 0 rgba(9, 9, 11, 0.04)',
        sm: '0 1px 3px 0 rgba(9, 9, 11, 0.06), 0 1px 2px -1px rgba(9, 9, 11, 0.06)',
        md: '0 4px 8px -2px rgba(9, 9, 11, 0.08), 0 2px 4px -2px rgba(9, 9, 11, 0.04)',
        lg: '0 10px 20px -5px rgba(9, 9, 11, 0.10), 0 4px 6px -4px rgba(9, 9, 11, 0.06)',
        focus: '0 0 0 3px rgba(124, 58, 237, 0.18)',
      },
      borderRadius: {
        DEFAULT: '6px',
        sm: '4px',
        md: '6px',
        lg: '8px',
        xl: '12px',
      },
      keyframes: {
        in: {
          '0%': { opacity: '0', transform: 'translateY(4px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        shimmer: {
          '0%': { backgroundPosition: '200% 0' },
          '100%': { backgroundPosition: '-200% 0' },
        },
      },
      animation: {
        in: 'in 160ms cubic-bezier(0.16, 1, 0.3, 1)',
        shimmer: 'shimmer 1.6s linear infinite',
      },
    },
  },
  plugins: [],
}

export default config
