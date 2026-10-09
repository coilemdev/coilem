import { readFile } from 'node:fs/promises';
import typescript from 'typescript';

/**
 * Transpile a TypeScript module (plus its relative imports, recursively) into
 * nested data: URLs so node can import it without a build step. data: modules
 * cannot resolve relative specifiers, so each `./dep` is transpiled first and
 * its specifier rewritten to the child's data: URL. Import cycles are not
 * supported — keep test-imported modules acyclic.
 */
export async function importTypeScriptModule(moduleUrl) {
  return import(await transpileToDataUrl(moduleUrl, new Map()));
}

async function transpileToDataUrl(moduleUrl, cache) {
  const cached = cache.get(moduleUrl.href);
  if (cached) return cached;

  const source = await readFile(moduleUrl, 'utf8');
  let output = typescript.transpileModule(source, {
    compilerOptions: {
      module: typescript.ModuleKind.ESNext,
      target: typescript.ScriptTarget.ES2022,
    },
    fileName: moduleUrl.pathname,
  }).outputText;

  const relativeSpecifiers = new Set(
    [...output.matchAll(/from\s+["'](\.{1,2}\/[^"']+)["']/g)].map((match) => match[1]),
  );
  for (const specifier of relativeSpecifiers) {
    const withExtension = /\.[cm]?[jt]sx?$/.test(specifier) ? specifier : `${specifier}.ts`;
    const childUrl = await transpileToDataUrl(new URL(withExtension, moduleUrl), cache);
    output = output
      .split(`"${specifier}"`).join(`"${childUrl}"`)
      .split(`'${specifier}'`).join(`'${childUrl}'`);
  }

  const dataUrl = `data:text/javascript;base64,${Buffer.from(output, 'utf8').toString('base64')}`;
  cache.set(moduleUrl.href, dataUrl);
  return dataUrl;
}
