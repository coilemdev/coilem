/** Independent CSV reader used to check downloads, including quoted commas and newlines. */
export function parseCsv(text) {
  const data = text.replace(/^\uFEFF/, '');
  const rows = [];
  let row = [], cell = '', quoted = false;
  for (let index = 0; index < data.length; index++) {
    const char = data[index];
    if (quoted) {
      if (char === '"' && data[index + 1] === '"') { cell += '"'; index++; }
      else if (char === '"') quoted = false;
      else cell += char;
    } else if (char === '"') quoted = true;
    else if (char === ',') { row.push(cell); cell = ''; }
    else if (char === '\r' || char === '\n') {
      if (char === '\r' && data[index + 1] === '\n') index++;
      row.push(cell); rows.push(row); row = []; cell = '';
    } else cell += char;
  }
  if (quoted) throw new Error('Unterminated CSV quote.');
  if (cell || row.length) { row.push(cell); rows.push(row); }
  return rows;
}
