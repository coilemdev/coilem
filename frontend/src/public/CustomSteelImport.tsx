import { useRef, useState } from 'react';
import { importPublicSteel } from './api';
import { customSteelModel, type CustomSteel, type SteelTarget } from './customSteel';
import { MaterialCurveChart } from './MaterialWorkspace';
import './customSteel.css';

export function CustomSteelImport({ disabled, onImport }: {
  disabled: boolean;
  onImport: (material: CustomSteel, target: SteelTarget) => void;
}) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState('');
  const [source, setSource] = useState('');
  const [thickness, setThickness] = useState('');
  const [csv, setCsv] = useState('');
  const [filename, setFilename] = useState('');
  const [target, setTarget] = useState<SteelTarget>('both');
  const [preview, setPreview] = useState<CustomSteel | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [checking, setChecking] = useState(false);
  const requestId = useRef(0);
  const clearPreview = () => { requestId.current++; setChecking(false); setPreview(null); setError(null); };

  async function readFile(file: File | undefined) {
    clearPreview(); setCsv(''); setFilename('');
    if (!file) return;
    const id = requestId.current;
    if (file.size > 524288) { setError('Use a CSV smaller than 512 KiB, with no more than 4096 points.'); return; }
    try {
      const text = await file.text();
      if (id !== requestId.current) return;
      const metadata = (key: string) => text.match(new RegExp(`^#\\s*${key}:\\s*(.+)$`, 'mi'))?.[1]?.trim();
      setCsv(text); setFilename(file.name);
      setName(metadata('name') ?? file.name.replace(/\.csv$/i, ''));
      setSource(metadata('source') ?? 'User-supplied CSV');
      setThickness(metadata('lamination_thickness_mm') ?? '');
    } catch { setError('Could not read this CSV. Choose a local UTF-8 file.'); }
  }

  async function validate() {
    if (thickness.trim() && (!Number.isFinite(Number(thickness)) || Number(thickness) <= 0 || Number(thickness) > 10)) {
      setError('Lamination thickness must be greater than 0 and no more than 10 mm.');
      return;
    }
    const id = ++requestId.current;
    setChecking(true); setPreview(null); setError(null);
    try {
      const response = await importPublicSteel({ name: name.trim(), source: source.trim(), csv_text: csv,
        lamination_thickness_mm: thickness.trim() ? Number(thickness) : null });
      if (id === requestId.current) setPreview(response.material);
    } catch (reason) {
      if (id === requestId.current) {
        const message = reason && typeof reason === 'object' && 'message' in reason ? String(reason.message) : 'Could not validate the curve.';
        setError(message);
      }
    } finally { if (id === requestId.current) setChecking(false); }
  }

  return <div className="custom-steel-import">
    <button type="button" disabled={disabled} aria-expanded={open} onClick={() => setOpen(!open)}>Import steel material</button>
    {open && <div className="custom-steel-form">
      <p>Import a static magnetization curve. CSV columns: <code>B_T,H_A_per_m</code> (tesla, A/m). Start at 0,0; both columns must increase.</p>
      <a href="/materials/sample-custom-steel.csv" download>Download sample curve</a>
      <small>The sample is synthetic demonstration data, not a measured steel grade.</small>
      <label>B–H curve CSV<input type="file" accept=".csv,text/csv" disabled={disabled || checking}
        onChange={(event) => { void readFile(event.target.files?.[0]); event.target.value = ''; }} /></label>
      {filename && <small>{filename}</small>}
      <label>Material name<input value={name} maxLength={120} disabled={disabled || checking}
        onChange={(event) => { clearPreview(); setName(event.target.value); }} /></label>
      <label>Source / measurement conditions<input value={source} maxLength={500} disabled={disabled || checking}
        onChange={(event) => { clearPreview(); setSource(event.target.value); }} /></label>
      <label>Lamination thickness (mm, optional)<input type="number" min="0.001" max="10" step="any" value={thickness} disabled={disabled || checking}
        onChange={(event) => { clearPreview(); setThickness(event.target.value); }} /></label>
      <button type="button" disabled={disabled || checking || !csv || !name.trim() || !source.trim()}
        onClick={() => void validate()}>{checking ? 'Checking curve…' : 'Validate curve'}</button>
      {error && <p role="alert" className="custom-steel-error">{error}</p>}
      {preview && <div className="custom-steel-preview">
        <strong role="status">Curve valid · {preview.bh_curve.length} points · 0–{preview.bh_curve[preview.bh_curve.length - 1][0]} T</strong>
        <MaterialCurveChart model={customSteelModel(preview)} compact />
        <p>Higher fields use linear extrapolation. Core-loss and temperature data are not included.</p>
        <label>Assign to<select value={target} disabled={disabled} onChange={(event) => setTarget(event.target.value as SteelTarget)}>
          <option value="both">Stator and rotor</option><option value="stator">Stator only</option><option value="rotor">Rotor only</option>
        </select></label>
        <button type="button" disabled={disabled} onClick={() => { onImport(preview, target); setOpen(false); }}>Add and assign material</button>
      </div>}
    </div>}
  </div>;
}
