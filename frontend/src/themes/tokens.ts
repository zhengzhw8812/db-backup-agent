import type { GlobalThemeOverrides } from 'naive-ui'

export const lightOverrides: GlobalThemeOverrides = {
  common: {
    primaryColor: '#4f46e5', primaryColorHover: '#6366f1', primaryColorPressed: '#4338ca',
    borderRadius: '8px', borderRadiusSmall: '6px',
    fontFamily: '-apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif',
  },
}

export const darkOverrides: GlobalThemeOverrides = {
  common: {
    primaryColor: '#818cf8', primaryColorHover: '#a5b4fc', primaryColorPressed: '#6366f1',
    borderRadius: '8px',
  },
}
