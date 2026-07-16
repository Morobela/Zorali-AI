// Import-integrity guard: every httpClient-style `apiXxx(...)` identifier used
// anywhere in frontend/src must be imported (or defined) in that file, and must
// actually be exported by httpClient.js. This is the class of bug where
// `apiPatch` was called without being imported — a runtime ReferenceError that
// `vite build` does not catch.
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

const srcDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../frontend/src')

function walk(dir) {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = path.join(dir, entry.name)
    if (entry.isDirectory()) return walk(full)
    return /\.(js|jsx)$/.test(entry.name) ? [full] : []
  })
}

function importedNames(source) {
  const names = new Set()
  for (const m of source.matchAll(/import\s+(?:[\w$]+\s*,\s*)?\{([^}]+)\}\s*from/g)) {
    for (const part of m[1].split(',')) {
      const name = part.trim().split(/\s+as\s+/).pop().trim()
      if (name) names.add(name)
    }
  }
  for (const m of source.matchAll(/import\s+([\w$]+)\s+from/g)) names.add(m[1])
  return names
}

const httpClientSource = fs.readFileSync(path.join(srcDir, 'api/httpClient.js'), 'utf8')
const httpClientExports = new Set(
  [...httpClientSource.matchAll(/export\s+(?:const|async\s+function|function)\s+([\w$]+)/g)].map((m) => m[1])
)

describe('frontend import integrity', () => {
  const files = walk(srcDir)

  it('finds source files', () => {
    expect(files.length).toBeGreaterThan(0)
  })

  for (const file of files) {
    const rel = path.relative(srcDir, file)
    it(`every api* call in ${rel} resolves to an import or local definition`, () => {
      const source = fs.readFileSync(file, 'utf8')
      const imports = importedNames(source)
      const used = new Set([...source.matchAll(/\b(api[A-Z][\w$]*)\s*\(/g)].map((m) => m[1]))
      for (const name of used) {
        const definedLocally = new RegExp(`(?:function|const|let|var)\\s+${name}\\b`).test(source)
        expect(
          imports.has(name) || definedLocally,
          `${rel} calls ${name}() but neither imports nor defines it`
        ).toBe(true)
        if (imports.has(name) && source.includes('httpClient')) {
          expect(
            httpClientExports.has(name),
            `${rel} imports ${name} but httpClient.js does not export it`
          ).toBe(true)
        }
      }
    })
  }
})
