"""Train YOLOv5n v7.0, export static ONNX, verify OpenCV load, package the model."""
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]

def run(command, cwd=None):
    print(" ".join(str(value) for value in command), flush=True)
    subprocess.run([str(value) for value in command], cwd=cwd, check=True)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, default=ROOT/"training/datasets/balloon/data.yaml")
    parser.add_argument("--epochs", type=int, default=60)
    parser.add_argument("--batch", type=int, default=16)
    parser.add_argument("--device", default="0")
    parser.add_argument("--name", default="balloon_yolov5n")
    parser.add_argument("--weights", default="yolov5n.pt")
    parser.add_argument("--optimizer", choices=("SGD", "Adam", "AdamW"), default="Adam")
    args = parser.parse_args()
    # Older YOLO/OpenCV loaders on Windows do not reliably handle Korean paths.
    cache = (Path(os.getenv("LOCALAPPDATA", str(Path.home()/".cache")))/"RCBoatBalloonTraining"/"work").resolve()
    cache.mkdir(parents=True, exist_ok=True)
    vendor = cache/"yolov5"
    if not (vendor/"train.py").exists():
        run(["git", "clone", "--depth", "1", "--branch", "v7.0",
             "https://github.com/ultralytics/yolov5.git", vendor])
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=vendor, text=True).strip()
    if commit != "915bbf294bb74c859f0b41f1c23bc395014ea679":
        raise ValueError("unexpected YOLOv5 vendor revision")
    if not args.data.is_file():
        raise ValueError("prepare or supply labelled balloon dataset first")
    output = cache/"runs"/args.name
    if output.exists():
        raise ValueError("run name already exists; choose a new --name")
    os.environ["WANDB_MODE"] = "disabled"
    os.environ["PYTHONUTF8"] = "1"
    os.environ["PYTHONIOENCODING"] = "utf-8"
    import yaml
    data_config = yaml.safe_load(args.data.read_text(encoding="utf-8"))
    dataset_source = Path(data_config.get("path", args.data.parent))
    if not dataset_source.is_absolute():
        dataset_source = args.data.parent/dataset_source
    local_dataset = cache/"datasets"/args.name
    shutil.copytree(dataset_source, local_dataset, dirs_exist_ok=True)
    data_config["path"] = str(local_dataset)
    local_data_yaml = local_dataset/"train_config.yaml"
    local_data_yaml.write_text(yaml.safe_dump(data_config), encoding="utf-8")
    hyp = yaml.safe_load((vendor/"data/hyps/hyp.scratch-low.yaml").read_text(encoding="utf-8"))
    if args.optimizer != "SGD":
        hyp.update(lr0=.001, warmup_bias_lr=.001)
    local_hyp = local_dataset/"hyperparameters.yaml"
    local_hyp.write_text(yaml.safe_dump(hyp), encoding="utf-8")
    run([sys.executable, ROOT/"training/yolov5_compat.py", vendor/"train.py", "--data", local_data_yaml, "--weights", args.weights,
         "--hyp", local_hyp, "--optimizer", args.optimizer,
         "--img", "320", "--batch", args.batch, "--epochs", args.epochs, "--device", args.device,
         "--workers", "0", "--project", output.parent, "--name", args.name, "--seed", "42",
         "--patience", "20", "--cache", "ram"], cwd=vendor)
    checkpoint = output/"weights/best.pt"
    run([sys.executable, ROOT/"training/yolov5_compat.py", vendor/"export.py", "--weights", checkpoint, "--imgsz", "320", "320",
         "--include", "onnx", "--opset", "12", "--device", "cpu"], cwd=vendor)
    model = checkpoint.with_suffix(".onnx")
    archive_run = ROOT/"training/runs"/args.name
    shutil.copytree(output, archive_run)
    import cv2
    import numpy as np
    net = cv2.dnn.readNetFromONNX(str(model))
    net.setInput(np.zeros((1, 3, 320, 320), dtype=np.float32))
    shape = list(net.forward().shape)
    if len(shape) != 3 or shape[-1] != 6:
        raise ValueError("exported ONNX is not YOLOv5 single-class output: "+str(shape))
    destination = ROOT/"models"
    destination.mkdir(exist_ok=True)
    shutil.copy2(model, destination/"balloon_yolov5n.onnx")
    shutil.copy2(checkpoint, destination/"balloon_yolov5n.pt")
    for name in ("results.csv", "results.png", "confusion_matrix.png", "PR_curve.png"):
        path = output/name
        if path.exists():
            shutil.copy2(path, destination/name)
    source = args.data.parent/"dataset_source.json"
    manifest = {
        "model": "YOLOv5n", "yolov5_commit": commit, "classes": ["balloon"],
        "input_size": 320, "output_format": "yolov5", "opset": 12, "output_shape": shape,
        "sha256": hashlib.sha256(model.read_bytes()).hexdigest(),
        "trained_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "epochs_requested": args.epochs, "data": str(args.data.resolve()),
        "optimizer": args.optimizer, "hyperparameters": hyp,
        "initial_weights": args.weights,
        "initial_weights_sha256": hashlib.sha256(Path(args.weights).read_bytes()).hexdigest()
                                  if Path(args.weights).is_file() else None,
        "dataset": json.loads(source.read_text()) if source.exists() else {"source": "operator supplied"},
        "field_validated": False,
        "deployment_note": "Starter balloon detector. Validate on the selected camera and water scenes before navigation."
    }
    (destination/"model_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    shutil.copy2(vendor/"LICENSE", destination/"YOLOv5_LICENSE.txt")
    print("MODEL_EXPORTED:", destination, flush=True)

if __name__ == "__main__":
    main()
