import { PUBLIC_API_BASE } from './api';
import type { FieldResultRaster } from './FieldResultPlot';
import type {
  PublicFieldPlaybackComposition,
  PublicFieldPlaybackFrame,
} from './model';

export type FieldRasterSource = 'resultant' | 'pm' | 'armature';

export enum FieldRasterLayer {
  Base = 1,
  Heat = 2,
  Mesh = 4,
  Lines = 8,
  All = Base | Heat | Mesh | Lines,
}

interface FrameTask {
  requestId: number;
  artifactId: string;
  source: FieldRasterSource;
  resolve: (raster: FieldResultRaster) => void;
  reject: (error: Error) => void;
}

interface PmArrowTask {
  requestId: number;
  pmArrowBlob: Blob;
  resolve: (lines: ImageBitmap) => void;
  reject: (error: Error) => void;
}

type RasterTask = FrameTask | PmArrowTask;

interface RasterWorkerState {
  worker: Worker;
  busy: boolean;
  task: RasterTask | null;
}

interface RasterWorkerResponse {
  requestId: number;
  ok: boolean;
  raster?: FieldResultRaster;
  lines?: ImageBitmap;
  error?: string;
}

export class FieldPlaybackRasterizer {
  private readonly workers: RasterWorkerState[] = [];
  private readonly queue: RasterTask[] = [];
  private readonly requests = new AbortController();
  private tintPmInWorker = typeof OffscreenCanvas !== 'undefined';
  private nextRequestId = 1;
  private disposed = false;

  constructor() {
    const workerCount = Math.max(2, Math.min(4, (navigator.hardwareConcurrency || 4) - 1));
    for (let index = 0; index < workerCount; index += 1) {
      let worker: Worker;
      try {
        worker = new Worker(new URL('./fieldPlaybackWorker.ts', import.meta.url), { type: 'module' });
      } catch {
        // Saved images can still be decoded and coloured on the main thread.
        break;
      }
      const state: RasterWorkerState = { worker, busy: false, task: null };
      worker.onmessage = (event: MessageEvent<RasterWorkerResponse>) => {
        const task = state.task;
        state.busy = false;
        state.task = null;
        if (task && event.data.requestId === task.requestId) {
          if (event.data.ok && 'pmArrowBlob' in task && event.data.lines) task.resolve(event.data.lines);
          else if (event.data.ok && 'artifactId' in task && event.data.raster) task.resolve(event.data.raster);
          else task.reject(new Error(event.data.error || 'Field frame rasterization failed.'));
        }
        this.pump();
      };
      worker.onerror = (event) => {
        event.preventDefault();
        this.dropWorker(state);
      };
      worker.onmessageerror = () => this.dropWorker(state);
      this.workers.push(state);
    }
  }

  /** Each saved layer is a full bitmap, so decode only the ones this view draws. */
  render(
    artifactId: string,
    source: FieldRasterSource,
    playbackFrame?: PublicFieldPlaybackFrame,
    requestedLayers: number = FieldRasterLayer.All,
  ): Promise<FieldResultRaster> {
    if (this.disposed) return Promise.reject(new Error('The field playback renderer is unavailable.'));
    const composition = playbackFrame?.compositions[source];
    if (playbackFrame && !composition) {
      return Promise.reject(new Error('The requested field composition is unavailable.'));
    }
    if (composition) return this.renderRasterLayers(composition, source, false, requestedLayers);
    return new Promise((resolve, reject) => {
      this.queue.push({
        requestId: this.nextRequestId++,
        artifactId,
        source,
        resolve,
        reject,
      });
      this.pump();
    });
  }

  renderDetail(
    source: FieldRasterSource,
    playbackFrame?: PublicFieldPlaybackFrame,
  ): Promise<FieldResultRaster | null> {
    const composition = playbackFrame?.compositions[source];
    if (!composition?.detail) return Promise.resolve(null);
    return this.renderRasterLayers(composition, source, true);
  }

  private async renderRasterLayers(
    composition: PublicFieldPlaybackComposition,
    source: FieldRasterSource,
    detail = false,
    requestedLayers: number = FieldRasterLayer.All,
  ): Promise<FieldResultRaster> {
    const bitmaps: ImageBitmap[] = [];
    let failed = false;
    let pmArrowsTinted = false;
    try {
      const load = async (artifactId: string, tintPm = false) => {
        const response = await fetch(
          `${PUBLIC_API_BASE}/solve/playback-frame/${encodeURIComponent(artifactId)}`,
          { signal: this.requests.signal },
        );
        if (!response.ok) {
          throw new Error(`Playback layer request failed with HTTP ${response.status}.`);
        }
        const blob = await response.blob();
        let bitmap: ImageBitmap;
        if (tintPm && this.tintPmInWorker && this.workers.length > 0 && !this.disposed) {
          try {
            bitmap = await new Promise<ImageBitmap>((resolve, reject) => {
              this.queue.push({ requestId: this.nextRequestId++, pmArrowBlob: blob, resolve, reject });
              this.pump();
            });
            pmArrowsTinted = true;
          } catch (error) {
            if (this.disposed) throw error;
            // Some browsers can decode images but cannot transfer a worker's
            // 2D drawing surface. The viewer can still tint the original image.
            bitmap = await createImageBitmap(blob);
            this.tintPmInWorker = false;
          }
        } else {
          bitmap = await createImageBitmap(blob);
        }
        if (failed || this.disposed) {
          bitmap.close();
          throw new Error('Field playback stopped.');
        }
        bitmaps.push(bitmap);
        return bitmap;
      };
      const layers = detail ? composition.detail : composition;
      if (!layers) throw new Error('The detailed playback layers are unavailable.');
      const [base, heat, mesh, lines] = await Promise.all([
        requestedLayers & FieldRasterLayer.Base ? load(layers.base.artifact_id) : null,
        requestedLayers & FieldRasterLayer.Heat ? load(layers.flux_density.artifact_id) : null,
        layers.mesh && (requestedLayers & FieldRasterLayer.Mesh) ? load(layers.mesh.artifact_id) : null,
        requestedLayers & FieldRasterLayer.Lines ? load(layers.field_lines.artifact_id, source === 'pm') : null,
      ]);
      return {
        base,
        heat,
        mesh,
        lines,
        pmArrowsTinted,
        viewBox: composition.view_box,
        minB: composition.min_b_t,
        maxB: composition.max_b_t,
        colorScale: composition.color_scale?.kind === 'fixed'
          ? {
            minB: composition.color_scale.min,
            maxB: composition.color_scale.max,
            overAboveT: composition.color_scale.max,
            fixed: true,
          }
          : null,
        triangleCount: composition.triangle_count,
        contourLevelCount: composition.contour_level_count,
        contourSegmentCount: composition.contour_segment_count,
        vectorCues: composition.vector_cues ?? [],
      };
    } catch (error) {
      failed = true;
      bitmaps.forEach((bitmap) => bitmap.close());
      throw error;
    }
  }

  dispose(): void {
    this.disposed = true;
    this.requests.abort();
    this.queue.splice(0).forEach((task) => task.reject(new Error('Field playback stopped.')));
    this.workers.forEach((state) => {
      state.task?.reject(new Error('Field playback stopped.'));
      state.worker.terminate();
    });
  }

  private dropWorker(state: RasterWorkerState): void {
    const index = this.workers.indexOf(state);
    if (index < 0) return;
    this.workers.splice(index, 1);
    state.worker.terminate();
    state.task?.reject(new Error('The field playback worker stopped unexpectedly.'));
    this.pump();
  }

  private pump(): void {
    if (this.disposed) return;
    if (this.workers.length === 0) {
      this.queue.splice(0).forEach((task) => task.reject(new Error('Field playback workers are unavailable.')));
      return;
    }
    this.workers.forEach((state) => {
      if (state.busy) return;
      const task = this.queue.shift();
      if (!task) return;
      state.busy = true;
      state.task = task;
      try {
        state.worker.postMessage('pmArrowBlob' in task ? {
          requestId: task.requestId,
          pmArrowBlob: task.pmArrowBlob,
        } : {
          requestId: task.requestId,
          apiBase: PUBLIC_API_BASE,
          artifactId: task.artifactId,
          source: task.source,
        });
      } catch {
        this.dropWorker(state);
      }
    });
  }
}
