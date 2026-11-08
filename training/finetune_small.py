"""Fine-tune existing balloon weights; keep the candidate separate until evaluated."""
import argparse
import csv
import hashlib
import json
import shutil
import time
from pathlib import Path


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--weights', type=Path, required=True)
    p.add_argument('--data', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--epochs', type=int, default=30)
    p.add_argument('--batch', type=int, default=32)
    p.add_argument('--workers', type=int, default=2)
    p.add_argument('--cache', choices=('ram','disk','none'), default='ram')
    p.add_argument('--resume', action='store_true')
    p.add_argument('--parent-weights', type=Path)
    args = p.parse_args()
    import torch
    from ultralytics import YOLO
    from ultralytics.models.yolo.detect import DetectionTrainer
    class Trainer(DetectionTrainer):
        def check_resume(self, overrides):
            super().check_resume(overrides)
            # Ultralytics deliberately retains most saved arguments on resume.
            # Worker/cache changes affect throughput only, not labels or optimizer state.
            if self.args.resume:
                self.args.workers=args.workers
                self.args.cache=False if args.cache=='none' else args.cache
    torch.set_num_threads(6)
    start = time.time()
    model = YOLO(str(args.weights))
    model.train(trainer=Trainer, data=str(args.data), epochs=args.epochs, imgsz=320, batch=args.batch, device=0,
                workers=args.workers, cache=False if args.cache=='none' else args.cache,
                resume=str(args.weights) if args.resume else False,
                project=str(args.output), name='small_balloon', exist_ok=False,
                seed=2400, optimizer='AdamW', lr0=.0005, cos_lr=True, patience=8,
                hsv_h=.01, hsv_s=.35, hsv_v=.35, degrees=8, translate=.12, scale=.35,
                fliplr=.5, mosaic=.35, close_mosaic=7, amp=True, plots=True)
    best = Path(model.trainer.save_dir)/'weights/best.pt'
    trained = YOLO(str(best))
    metrics = trained.val(data=str(args.data), imgsz=320, device=0, plots=False)
    test = trained.val(data=str(args.data), split='test', imgsz=320, device=0, plots=False)
    exported = trained.export(format='onnx', imgsz=320, opset=12, simplify=True, dynamic=False, batch=1, device='cpu')
    out = args.output/'candidate'
    out.mkdir(exist_ok=True)
    shutil.copy2(best, out/'balloon_yolov8n.pt')
    shutil.copy2(exported, out/'balloon_yolov8n.onnx')
    manifest = dict(model='YOLOv8n small-object fine-tune', classes=['balloon'], output_format='yolov8', input_size=320,
                    sha256=hashlib.sha256((out/'balloon_yolov8n.onnx').read_bytes()).hexdigest(),
                    parent_weights_sha256=hashlib.sha256((args.parent_weights or args.weights).read_bytes()).hexdigest(),
                    training_dataset=json.loads((args.data.parent/'dataset_source.json').read_text(encoding='utf-8')),
                    range_validation=dict(status='not_field_validated', max_validated_distance_m=None, real_100m_images=0),
                    limitation='Competition balloon diameter/optics unknown; no measured 100m validation',
                    license='Ultralytics YOLOv8 AGPL-3.0; Open Images attribution retained')
    (out/'model_manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    completed=list(csv.DictReader((Path(model.trainer.save_dir)/'results.csv').open()))
    report = dict(epochs_requested=args.epochs,epochs_completed=len(completed),training_seconds=round(time.time()-start,1),
                  training_seconds_scope='this invocation only; excludes earlier stages when resumed',resumed=args.resume,
                  validation_metrics=metrics.results_dict, test_metrics=test.results_dict,
                  hardware=torch.cuda.get_device_name(0), jetson_benchmark=False, actual_competition_test=False)
    (out/'training_report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print('CANDIDATE_EXPORTED '+json.dumps(report), flush=True)


if __name__ == '__main__':
    main()
