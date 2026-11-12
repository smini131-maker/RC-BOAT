"""Rank saved checkpoints on the red validation split without reading test labels."""
import argparse
import hashlib
import json
import shutil
import statistics
from pathlib import Path

from evaluate_red_balloon import evaluate, BalloonDetector, validate_config


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('dataset','baseline','baseline-manifest','run','output'):
        parser.add_argument('--'+name, required=True, type=Path)
    args = parser.parse_args()
    from ultralytics import YOLO
    import torch
    torch.set_num_threads(4)

    records = json.loads((args.dataset/'dataset_source.json').read_text(encoding='utf-8'))['red_candidate_records']
    args.output.mkdir(exist_ok=False)
    weights = args.run/'weights'
    paths = [weights/name for name in ('best.pt','epoch10.pt','epoch20.pt','epoch30.pt','epoch40.pt','epoch50.pt','last.pt')]
    pairs = {'baseline': (args.baseline, args.baseline_manifest)}
    for weight in paths:
        if weight.exists():
            saved = args.output/weight.name
            shutil.copy2(weight, saved)
            net = Path(YOLO(str(saved)).export(format='onnx',imgsz=320,opset=12,simplify=True,dynamic=False,batch=1,device='cpu'))
            manifest = saved.with_suffix('.json')
            document = dict(classes=['balloon'],output_format='yolov8',input_size=320,
                            sha256=hashlib.sha256(net.read_bytes()).hexdigest(),target_colour='red')
            manifest.write_text(json.dumps(document),encoding='utf-8')
            pairs[saved.stem] = (net, manifest)
    result = {}
    for name, (net, manifest) in pairs.items():
        metadata = json.loads(manifest.read_text(encoding='utf-8'))
        metadata['target_colour']='red'
        check_manifest=args.output/'validation_profile.json'
        check_manifest.write_text(json.dumps(metadata),encoding='utf-8')
        config=validate_config(dict(model_path=str(net),model_manifest=str(check_manifest),
                                   backend='onnxruntime',long_range_enabled=False))
        detector=BalloonDetector(config)
        try:
            metrics=evaluate(detector,args.dataset,records,None,split='val',max_background=0)
        finally:
            detector.close()
        conditions=('original','bright','dim')
        average_f1=statistics.mean(
            2*metrics[key]['matched_boxes']/(metrics[key]['confirmed_boxes']+metrics[key]['expected_boxes'])
            for key in conditions)
        result[name]=dict(mean_red_f1=average_f1,conditions={key:metrics[key] for key in conditions})
        print('RED_VALIDATION',name,json.dumps(result[name]),flush=True)
    best=max((name for name in result if name!='baseline'),key=lambda name:result[name]['mean_red_f1'])
    (args.output/'checkpoint_selection.json').write_text(json.dumps(dict(
        checkpoint=best, criterion='mean red box F1 across original/bright/dim validation photos',
        validation=result),indent=2)+'\n',encoding='utf-8')
    print('RED_CHECKPOINT_SELECTED',best,flush=True)


if __name__ == '__main__':
    main()
