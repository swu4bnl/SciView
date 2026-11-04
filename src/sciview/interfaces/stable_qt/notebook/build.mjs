import { build } from 'esbuild';
import { copyFile, mkdir, readFile, readdir, writeFile } from 'node:fs/promises';
import path from 'node:path';

await mkdir('dist', { recursive: true });
const result = await build({
  entryPoints: ['editor.js'],
  outfile: 'dist/editor.js',
  bundle: true,
  format: 'iife',
  target: ['chrome87'],
  legalComments: 'eof',
  minify: true,
  metafile: true,
  loader: { '.woff2': 'dataurl', '.woff': 'dataurl', '.ttf': 'dataurl' },
});
await copyFile('index.html', 'dist/index.html');
const packages = new Set();
for (const input of Object.keys(result.metafile.inputs)) {
  const match = input.replaceAll('\\', '/').match(/^(.*node_modules\/(?:@[^/]+\/)?[^/]+)/);
  if (match) packages.add(match[1]);
}
const notices = [];
for (const directory of [...packages].sort()) {
  const metadata = JSON.parse(await readFile(path.join(directory, 'package.json'), 'utf8'));
  const files = await readdir(directory);
  const license = files.find(name => /^licen[sc]e(?:\.md|\.txt)?$/i.test(name));
  const notice = license ? path.join(directory, license)
    : path.join('licenses', `${metadata.name.replaceAll('/', '-')}.txt`);
  notices.push(`${metadata.name} ${metadata.version}\n${await readFile(notice, 'utf8')}`);
}
await writeFile('dist/THIRD_PARTY_LICENSES.txt', notices.join('\n\n--------------------\n\n'));
