"""Fine-tune the existing YOLOv8n checkpoint and export a Jetson-compatible candidate."""
import argparse
import csv
import hashlib
import json
import shutil
import time
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--weights', type=Path, required=True)
    parser.add_argument('--dataset', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--epochs', type=int, default=60)
    parser.add_argument('--batch', type=int, default=64)
    args = parser.parse_args()

    import torch
    from ultralytics import YOLO

    torch.set_num_threads(6)
    start = time.monotonic()
    model = YOLO(str(args.weights))
    model.train(data=str(args.dataset/'data.yaml'), epochs=args.epochs, imgsz=320, batch=args.batch,
                device=0, workers=2, cache='ram', project=str(args.output), name='red_balloon',
                seed=2410, optimizer='AdamW', lr0=.00065, cos_lr=True, patience=args.epochs,
                hsv_h=.012, hsv_s=.45, hsv_v=.5, degrees=10, translate=.12, scale=.40,
                fliplr=.5, mosaic=.45, close_mosaic=12, amp=True, plots=True, save_period=10)
    run = Path(model.trainer.save_dir)
    best = run/'weights/best.pt'
    trained = YOLO(str(best))
    evaluations = {}
    for label, weights in (('baseline', args.weights), ('candidate', best)):
        evaluations[label] = {}
        for split in ('val','test'):
            metrics = YOLO(str(weights)).val(data=str(args.dataset/'data.yaml'), split=split,
                imgsz=320, batch=args.batch, device=0, workers=2, plots=False,
                project=str(args.output), name=label+'_'+split)
            evaluations[label][split] = metrics.results_dict
    exported = Path(trained.export(format='onnx', imgsz=320, opset=12, simplify=True,
                                  dynamic=False, batch=1, device='cpu'))
    out = args.output/'candidate'
    out.mkdir(exist_ok=False)
    shutil.copy2(best, out/'balloon_yolov8n.pt')
    shutil.copy2(exported, out/'balloon_yolov8n.onnx')
    source = json.loads((args.dataset/'dataset_source.json').read_text(encoding='utf-8'))
    manifest = dict(model='YOLOv8n red-balloon fine-tune', classes=['balloon'], output_format='yolov8',
                    input_size=320, sha256=hashlib.sha256(exported.read_bytes()).hexdigest(),
                    parent_weights_sha256=hashlib.sha256(args.weights.read_bytes()).hexdigest(),
                    target_colour='red', training_dataset={k:v for k,v in source.items() if k!='red_candidate_records'},
                    range_validation=dict(status='not_field_validated', max_validated_distance_m=None),
                    limitation='Public balloon photos and exposure augmentation; no competition photos',
                    license='Ultralytics YOLOv8 AGPL-3.0; Open Images attribution retained')
    with (run/'results.csv').open() as file:
        epochs_completed = sum(1 for _ in csv.DictReader(file))
    report = dict(epochs_requested=args.epochs, epochs_completed=epochs_completed, input_size=320,
                  training_and_export_seconds=round(time.monotonic()-start,1), evaluations=evaluations,
                  hardware=torch.cuda.get_device_name(0), actual_competition_test=False, jetson_benchmark=False)
    for filename, document in (('model_manifest.json', manifest), ('training_report.json', report)):
        (out/filename).write_text(json.dumps(document, indent=2)+'\n', encoding='utf-8')
    print('RED_CANDIDATE_EXPORTED', json.dumps(report), flush=True)


if __name__ == '__main__':
    main()
