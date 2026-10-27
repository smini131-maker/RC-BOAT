"""Evaluate the deployed OpenCV ONNX path on held-out images and save a report."""
import argparse
import csv
import json
from pathlib import Path
import sys
import time
import cv2
import numpy as np
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/"catkin_ws/src/rcboat_ros/src"))
from rcboat_ros.balloon_detector import BalloonDetector
from rcboat_ros.balloon_tracking import validate_config, iou

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, default=ROOT/"training/datasets/balloon/data.yaml")
    args = parser.parse_args()
    config = validate_config({"model_path": str(ROOT/"models/balloon_yolov5n.onnx"),
                              "model_manifest": str(ROOT/"models/model_manifest.json")})
    detector = BalloonDetector(config)
    dataset = yaml.safe_load(args.data.read_text(encoding="utf-8"))
    base = Path(dataset["path"])
    image_dir = base/dataset["val"]
    total, tp, fp, elapsed = 0, 0, 0, []
    samples = []
    preview = ROOT/"artifacts/model_validation"
    preview.mkdir(parents=True, exist_ok=True)
    for index, image_path in enumerate(sorted(image_dir.glob("*"))):
        if image_path.suffix.lower() not in {".jpg", ".jpeg", ".png"}:
            continue
        image = cv2.imdecode(np.frombuffer(image_path.read_bytes(), dtype=np.uint8), cv2.IMREAD_COLOR)
        h, w = image.shape[:2]
        label_path = base/"labels/val"/(image_path.stem+".txt")
        truth = []
        for line in label_path.read_text().splitlines():
            if line.strip():
                cls, x, y, bw, bh = map(float, line.split())
                truth.append([(x-bw/2)*w, (y-bh/2)*h, (x+bw/2)*w, (y+bh/2)*h])
        start = time.perf_counter()
        detections = detector.detect(image)
        elapsed.append((time.perf_counter()-start)*1000)
        matched = set()
        image_tp, image_fp = 0, 0
        for item in sorted(detections, key=lambda detection: -detection["confidence"]):
            overlaps = [iou(item["bbox"], box) if i not in matched else 0 for i, box in enumerate(truth)]
            best = max(range(len(overlaps)), key=overlaps.__getitem__) if overlaps else None
            if best is not None and overlaps[best] >= .5:
                matched.add(best)
                image_tp += 1
            else:
                image_fp += 1
        total += len(truth); tp += image_tp; fp += image_fp
        samples.append({"image": image_path.name, "ground_truth": len(truth), "detections": len(detections),
                        "true_positive": image_tp, "false_positive": image_fp})
        for box in truth:
            x1, y1, x2, y2 = map(int, box)
            cv2.rectangle(image, (x1, y1), (x2, y2), (220, 170, 40), 2)
        for detection in detections:
            x1, y1, x2, y2 = map(int, detection["bbox"])
            cv2.rectangle(image, (x1, y1), (x2, y2), (40, 220, 40), 3)
            cv2.putText(image, "balloon %.2f" % detection["confidence"], (x1, max(20, y1-5)),
                        cv2.FONT_HERSHEY_SIMPLEX, .65, (40, 220, 40), 2)
        if index < 6:
            ok, encoded = cv2.imencode(".jpg", image)
            if ok:
                (preview/("validation_%02d.jpg" % (index+1))).write_bytes(encoded.tobytes())
    rows = list(csv.DictReader((ROOT/"models/results.csv").open(encoding="utf-8")))
    rows = [{key.strip(): value.strip() for key, value in row.items()} for row in rows]
    best = max(rows, key=lambda row: .1*float(row["metrics/mAP_0.5"])+.9*float(row["metrics/mAP_0.5:0.95"]))
    report = {
        "model": "YOLOv5n balloon, 320x320 ONNX",
        "validation_images": len(samples), "validation_balloons": total,
        "training_best_epoch": int(best["epoch"])+1,
        "training_epochs_completed": len(rows),
        "training_validation_mAP50": float(best["metrics/mAP_0.5"]),
        "training_validation_mAP50_95": float(best["metrics/mAP_0.5:0.95"]),
        "deployed_opencv": {"confidence": config["confidence"], "iou_match": .5,
                            "true_positive": tp, "false_positive": fp, "false_negative": total-tp,
                            "precision": tp/max(1, tp+fp), "recall": tp/max(1, total),
                            "pc_cpu_mean_inference_ms": sum(elapsed)/max(1, len(elapsed))},
        "images": samples,
        "field_validated": False,
        "limitations": ["Only 13 public validation images; no independent field test set.",
                        "No water/boat-camera negative scenes; no field false-positive rate established.",
                        "CPU timings are this Windows PC, not Jetson Nano."],
    }
    (ROOT/"models/training_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    manifest_path = ROOT/"models/model_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["epochs_completed"] = len(rows)
    manifest["best_epoch"] = report["training_best_epoch"]
    manifest["validation_mAP50"] = report["training_validation_mAP50"]
    manifest["validation_mAP50_95"] = report["training_validation_mAP50_95"]
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))

if __name__ == "__main__":
    main()
