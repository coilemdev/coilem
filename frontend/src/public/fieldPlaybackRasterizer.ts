import { PUBLIC_API_BASE } from './api';
import type { FieldResultRaster } from './FieldResultPlot';
import type {
  PublicFieldPlaybackComposition,
  PublicFieldPlaybackFrame,
} from './model';

export type FieldRasterSource = 'resultant' | 'pm' | 'armature';

interface RasterTask {
  requestId: number;
  artifactId: string;
  source: FieldRasterSource;
  resolve: (raster: FieldResultRaster) => void;
  reject: (error: Error) => void;
}

interface RasterWorkerState {
  worker: Worker;
  busy: boolean;
  task: RasterTask | null;
}

interface RasterWorkerResponse {
  requestId: number;
  ok: boolean;
  raster?: FieldResultRaster;
  error?: string;
}

export class FieldPlaybackRasterizer {
  private readonly workers: RasterWorkerState[];
  private readonly queue: RasterTask[] = [];
  private nextRequestId = 1;
  private disposed = false;

  constructor() {
    const workerCount = Math.max(2, Math.min(4, (navigator.hardwareConcurrency || 4) - 1));
    this.workers = Array.from({ length: workerCount }, () => {
      const worker = new Worker(new URL('./fieldPlaybackWorker.ts', import.meta.url), { type: 'module' });
      const state: RasterWorkerState = { worker, busy: false, task: null };
      worker.onmessage = (event: MessageEvent<RasterWorkerResponse>) => {
        const task = state.task;
        state.busy = false;
        state.task = null;
        if (task && event.data.requestId === task.requestId) {
          if (event.data.ok && event.data.raster) task.resolve(event.data.raster);
          else task.reject(new Error(event.data.error || 'Field frame rasterization failed.'));
        }
        this.pump();
      };
      worker.onerror = () => {
        const task = state.task;
        state.busy = false;
        state.task = null;
        task?.reject(new Error('The field playback worker stopped unexpectedly.'));
        this.pump();
      };
      return state;
    });
  }

  render(
    artifactId: string,
    source: FieldRasterSource,
    playbackFrame?: PublicFieldPlaybackFrame,
  ): Promise<FieldResultRaster> {
    if (this.disposed) return Promise.reject(new Error('The field playback renderer is unavailable.'));
    const composition = playbackFrame?.compositions[source];
    if (playbackFrame && !composition) {
      return Promise.reject(new Error('The requested field composition is unavailable.'));
    }
    if (composition) return this.renderRasterLayers(composition);
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
    return this.renderRasterLayers(composition, true);
  }

  private async renderRasterLayers(
    composition: PublicFieldPlaybackComposition,
    detail = false,
  ): Promise<FieldResultRaster> {
    const bitmaps: ImageBitmap[] = [];
    try {
      const load = async (artifactId: string) => {
        const response = await fetch(
          `${PUBLIC_API_BASE}/solve/playback-frame/${encodeURIComponent(artifactId)}`,
        );
        if (!response.ok) {
          throw new Error(`Playback layer request failed with HTTP ${response.status}.`);
        }
        const bitmap = await createImageBitmap(await response.blob());
        bitmaps.push(bitmap);
        return bitmap;
      };
      const layers = detail ? composition.detail : composition;
      if (!layers) throw new Error('The detailed playback layers are unavailable.');
      const [base, heat, mesh, lines] = await Promise.all([
        load(layers.base.artifact_id),
        load(layers.flux_density.artifact_id),
        layers.mesh ? load(layers.mesh.artifact_id) : Promise.resolve(null),
        load(layers.field_lines.artifact_id),
      ]);
      return {
        base,
        heat,
        mesh,
        lines,
        viewBox: composition.view_box,
        minB: composition.min_b_t,
        maxB: composition.max_b_t,
        triangleCount: composition.triangle_count,
        contourLevelCount: composition.contour_level_count,
        contourSegmentCount: composition.contour_segment_count,
        vectorCues: composition.vector_cues ?? [],
      };
    } catch (error) {
      bitmaps.forEach((bitmap) => bitmap.close());
      throw error;
    }
  }

  dispose(): void {
    this.disposed = true;
    this.queue.splice(0).forEach((task) => task.reject(new Error('Field playback stopped.')));
    this.workers.forEach((state) => {
      state.task?.reject(new Error('Field playback stopped.'));
      state.worker.terminate();
    });
  }

  private pump(): void {
    if (this.disposed) return;
    this.workers.forEach((state) => {
      if (state.busy) return;
      const task = this.queue.shift();
      if (!task) return;
      state.busy = true;
      state.task = task;
      state.worker.postMessage({
        requestId: task.requestId,
        apiBase: PUBLIC_API_BASE,
        artifactId: task.artifactId,
        source: task.source,
      });
    });
  }
}
