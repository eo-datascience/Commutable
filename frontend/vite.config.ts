import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

export default defineConfig({
  plugins: [react()],
  build: {
    // The published data sits in public/ and is copied verbatim. 2,895 small
    // files is a lot of files, so they are deliberately kept out of the
    // bundler's graph: they are fetched at run time by name, never imported.
    assetsInlineLimit: 0,
  },
  test: {
    environment: 'node',
    // palette.test.ts imports styles.css with ?raw to check the CSS ramp
    // against the one the map paints with. Vitest stubs CSS imports unless
    // this is on, and a stubbed import reads as a file with no selectors.
    css: true,
    include: ['src/**/*.test.ts'],
  },
})
