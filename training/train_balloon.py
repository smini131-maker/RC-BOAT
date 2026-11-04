"""Train a new YOLOv8n balloon head, export a static 320 input for Jetson."""
import argparse,hashlib,json,shutil,time,urllib.request
from pathlib import Path

def main():
    p=argparse.ArgumentParser();p.add_argument('--epochs',type=int,default=120);p.add_argument('--device',default='0');p.add_argument('--data',type=Path);p.add_argument('--runs',type=Path);p.add_argument('--imgsz',type=int,default=320);p.add_argument('--batch',type=int,default=32);p.add_argument('--patience',type=int,default=15);args=p.parse_args()
    from ultralytics import YOLO
    import yaml
    root=Path(__file__).resolve().parents[1];work=root/'training';weights=work/'downloads/yolov8n.pt'
    if not weights.exists():
        weights.parent.mkdir(parents=True,exist_ok=True)
        urllib.request.urlretrieve('https://github.com/ultralytics/assets/releases/download/v8.3.0/yolov8n.pt',weights)
    data=args.data or work/'datasets/balloon/data.yaml';runs=args.runs or work/'runs'
    model=YOLO(str(weights));start=time.time()
    model.train(data=str(data),epochs=args.epochs,imgsz=args.imgsz,batch=args.batch,device=args.device,
        workers=0,project=str(runs),name='pink_balloon_v8n',exist_ok=True,patience=args.patience,
        seed=2300,optimizer='AdamW',lr0=.002,cos_lr=True,hsv_h=.02,hsv_s=.5,hsv_v=.4,
        degrees=12,translate=.15,scale=.5,fliplr=.5,mosaic=.7,close_mosaic=15,plots=True,amp=True)
    best=runs/'pink_balloon_v8n/weights/best.pt';trained=YOLO(str(best))
    metrics=trained.val(data=str(data),imgsz=320,device=args.device,plots=False)
    dataset=yaml.safe_load(data.read_text(encoding='utf-8'))
    test_metrics=trained.val(data=str(data),split='test',imgsz=320,device=args.device,plots=False) if dataset.get('test') else None
    exported=trained.export(format='onnx',imgsz=320,opset=12,simplify=True,dynamic=False,batch=1,device='cpu')
    out=root/'models';out.mkdir(exist_ok=True)
    shutil.copy2(best,out/'balloon_yolov8n.pt');shutil.copy2(exported,out/'balloon_yolov8n.onnx')
    manifest=dict(model='YOLOv8n',classes=['balloon'],output_format='yolov8',input_size=320,
        sha256=hashlib.sha256((out/'balloon_yolov8n.onnx').read_bytes()).hexdigest(),
        pink_selection='neural balloon detection AND HSV pink fraction',
        source_weights_url='https://github.com/ultralytics/assets/releases/download/v8.3.0/yolov8n.pt',
        training_dataset=json.loads((data.parent/'dataset_source.json').read_text()),
        limitation='Starter model, not validated on the competition balloon, water, or Jetson camera.',
        license='Ultralytics YOLOv8 AGPL-3.0; training dataset source attribution retained')
    (out/'model_manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    report=dict(model='YOLOv8n',training_epochs_requested=args.epochs,training_seconds=round(time.time()-start,1),
        input_size=320,validation_images=len(list((Path(dataset['path'])/dataset['val']).glob('*.jpg'))),metrics=metrics.results_dict,
        held_out_test_images=len(list((Path(dataset['path'])/dataset.get('test','__absent__')).glob('*.jpg'))),test_metrics=test_metrics.results_dict if test_metrics else None,hardware='RTX 4060 Laptop GPU; not Jetson',
        actual_competition_test=False,jetson_benchmark=False)
    (out/'training_report.json').write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report))

if __name__=='__main__':main()
